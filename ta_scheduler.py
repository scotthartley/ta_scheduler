import csv
import io
import json
import os
import random
import re
import socket
import threading
import traceback

from flask import Flask, jsonify, make_response, request, send_file

# When frozen by PyInstaller, data files live under sys._MEIPASS.
_BASE_DIR = getattr(__import__("sys"), "_MEIPASS",
                    os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__, static_folder=os.path.join(_BASE_DIR, "static"))

# None until the user opens or saves a file.
_data_file = None

# Set to the pywebview window once it's created, or None if running headless.
_window = None

EMPTY_DATA = {
    "roles": [{"id": "role-primary-ta", "label": "Primary TA", "se_value": 1.0}],
    "grad_courses": [], "labs": [], "tas": [], "assignments": [],
}


def get_data_file():
    return _data_file


def set_data_file(path):
    global _data_file
    _data_file = path


# ── helpers ──────────────────────────────────────────────────────────────────

def load_data():
    p = get_data_file()
    if not p or not os.path.exists(p):
        return EMPTY_DATA
    with open(p) as f:
        return json.load(f)


def save_data_to_file(data):
    with open(get_data_file(), "w") as f:
        json.dump(data, f, indent=2)


def _file_dialog(dialog_type, directory=None, save_filename="", file_types=()):
    """Show a native file dialog via pywebview and return the chosen path, or None."""
    if _window is None:
        return None
    from webview import FileDialog
    kwargs = dict(directory=directory or _default_dir(), file_types=file_types)
    if dialog_type == FileDialog.SAVE:
        kwargs["save_filename"] = save_filename
    result = _window.create_file_dialog(dialog_type, **kwargs)
    if not result:
        return None
    # SAVE dialog returns a plain string; OPEN/FOLDER returns a tuple
    if isinstance(result, str):
        return result or None
    return result[0] if len(result) > 0 else None


def times_overlap(s1, e1, s2, e2):
    return s1 < e2 and e1 > s2


def _get_meetings(item):
    """Return list of (day, start_min, end_min) for all meetings of an item."""
    if item.get("meetings"):
        return [(m["day"], m["start_min"], m["end_min"]) for m in item["meetings"]]
    day = item.get("day")
    if day is not None:
        return [(day, item.get("start_min", 0), item.get("end_min", 0))]
    return []


def fmt_time(minutes):
    h, m = divmod(int(minutes), 60)
    ampm = "PM" if h >= 12 else "AM"
    h12 = h - 12 if h > 12 else (12 if h == 0 else h)
    return f"{h12}:{m:02d} {ampm}"


# ── CSV import helpers ────────────────────────────────────────────────────────

def _parse_days(s):
    """'MWF' → [0,2,4], 'TR' → [1,3]"""
    DAY_MAP = {'M': 0, 'T': 1, 'W': 2, 'R': 3, 'F': 4}
    return [DAY_MAP[c] for c in s if c in DAY_MAP]


def _parse_time(t):
    """'8:30am' → 510"""
    m = re.match(r'(\d+):(\d+)\s*(am|pm)', t.strip(), re.IGNORECASE)
    if not m:
        return None
    h, mn, p = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if p == 'pm' and h != 12:
        h += 12
    elif p == 'am' and h == 12:
        h = 0
    return h * 60 + mn


def _parse_time_range(t):
    """'8:30am-9:25am' → (510, 565)"""
    parts = t.split('-')
    if len(parts) != 2:
        return None, None
    return _parse_time(parts[0].strip()), _parse_time(parts[1].strip())


def _is_regular(date_str):
    """True if date range spans multiple days (not a single exam date)."""
    parts = date_str.strip().split('-')
    return len(parts) == 2 and parts[0].strip() != parts[1].strip()


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(os.path.join(_BASE_DIR, "static", "index.html"))


@app.route("/api/data", methods=["GET"])
def get_data():
    return jsonify(load_data())


@app.route("/api/data", methods=["POST"])
def post_data():
    data = request.get_json()
    save_data_to_file(data)
    return jsonify({"status": "ok"})


@app.route("/api/file-path", methods=["GET"])
def file_path():
    return jsonify({"path": get_data_file()})


def _default_dir():
    """Best guess for the initial directory in file dialogs."""
    current = get_data_file()
    if current:
        return os.path.dirname(current)
    return os.path.expanduser("~")


@app.route("/api/saveas", methods=["POST"])
def save_as():
    from webview import FileDialog
    data = request.get_json()
    current = get_data_file()
    default_name = os.path.basename(current) if current else "schedule.json"
    path = _file_dialog(FileDialog.SAVE,
                        save_filename=default_name,
                        file_types=("JSON files (*.json)", "All files (*.*)"))
    if path is None:
        return jsonify({"cancelled": True})
    if not path.endswith(".json"):
        path += ".json"
    set_data_file(path)
    save_data_to_file(data)
    return jsonify({"path": path})


@app.route("/api/open-dialog", methods=["POST"])
def open_dialog():
    from webview import FileDialog
    path = _file_dialog(FileDialog.OPEN,
                        file_types=("JSON files (*.json)", "All files (*.*)"))
    if path is None:
        return jsonify({"cancelled": True})
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    set_data_file(path)
    return jsonify({"path": path, "data": data})


@app.route("/api/import-csv", methods=["POST"])
def import_csv_route():
    from webview import FileDialog
    path = _file_dialog(FileDialog.OPEN,
                        file_types=("CSV files (*.csv)", "All files (*.*)"))
    if path is None:
        return jsonify({"cancelled": True})

    DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    grad_courses = []
    undergrad = {}  # key: "SUBJ NUMBER" → {subject, number, title, sections:[]}

    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                level = row.get("Course Level", "").strip()
                subject = row.get("Subject", "").strip()
                number = row.get("Number", "").strip()
                section = row.get("Section", "").strip()
                title = row.get("Title", "").strip()
                days_raw = row.get("Meeting Days", "").strip()
                times_raw = row.get("Meeting Times", "").strip()
                dates_raw = row.get("Meeting Dates", "").strip()

                if not days_raw or not times_raw:
                    continue

                slots_days = days_raw.split("|")
                slots_times = times_raw.split("|")
                slots_dates = dates_raw.split("|") if dates_raw else []

                regular, exams = [], []
                for i, d in enumerate(slots_days):
                    t_str = slots_times[i].strip() if i < len(slots_times) else ""
                    dt_str = slots_dates[i].strip() if i < len(slots_dates) else ""
                    days = _parse_days(d.strip())
                    s_min, e_min = _parse_time_range(t_str)
                    if not days or s_min is None:
                        continue
                    target = regular if _is_regular(dt_str) else exams
                    for day in days:
                        target.append({"day": day, "start_min": s_min, "end_min": e_min})

                course_name = f"{subject} {number}"
                section_label = section.strip()

                if level == "Graduate":
                    if regular:
                        grad_courses.append({
                            "name": course_name,
                            "section": section_label,
                            "day": regular[0]["day"],
                            "start_min": regular[0]["start_min"],
                            "end_min": regular[0]["end_min"],
                            "meetings": regular,
                            "exams": exams,
                        })
                elif level == "Undergraduate":
                    key = course_name
                    if key not in undergrad:
                        undergrad[key] = {"subject": subject, "number": number,
                                          "title": title, "sections": []}
                    if regular:
                        undergrad[key]["sections"].append({
                            "name": course_name,
                            "section": section_label,
                            "day": regular[0]["day"],
                            "start_min": regular[0]["start_min"],
                            "end_min": regular[0]["end_min"],
                            "meetings": regular,
                            "exams": exams,
                        })

        return jsonify({
            "grad_courses": grad_courses,
            "undergrad_courses": sorted(undergrad.values(),
                                        key=lambda c: (c["subject"], c["number"])),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/schedule", methods=["POST"])
def run_schedule():
    data = request.get_json()
    try:
        result = solve(data)
        return jsonify(result)
    except Exception:
        traceback.print_exc()
        return jsonify({"status": "error", "message": traceback.format_exc()}), 500


@app.route("/api/export/docx", methods=["POST"])
def export_docx():
    from webview import FileDialog
    data = request.get_json()
    path = _file_dialog(FileDialog.SAVE,
                        save_filename="ta_schedule.docx",
                        file_types=("Word documents (*.docx)", "All files (*.*)"))
    if not path or path in ("/", ""):
        return jsonify({"cancelled": True})
    if not path.endswith(".docx"):
        path += ".docx"
    try:
        doc = generate_docx(data)
        doc.save(path)
        return jsonify({"path": path})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": traceback.format_exc()}), 500


# ── solver ───────────────────────────────────────────────────────────────────

def solve(data):
    roles_map = {r["id"]: r for r in data.get("roles", [])}
    labs      = data.get("labs", [])
    tas       = data.get("tas", [])
    assignments_in = data.get("assignments", [])
    gc_map    = {gc["id"]: gc for gc in data.get("grad_courses", [])}

    if not labs or not tas:
        return {"status": "feasible", "assignments": assignments_in, "diagnostics": {}}

    # ── initialise per-TA state from locked assignments ──────────────────────
    labs_by_id = {lab["id"]: lab for lab in labs}

    ta_used_se        = {}   # ta_id -> float  (outside duties + assigned roles)
    ta_booked_labs    = {}   # ta_id -> {lab_id, ...}  (for double-booking check)
    ta_courses        = {}   # ta_id -> {course_name, ...}  (for split penalty)
    ta_per_slot       = {}   # (lab_id, role_id) -> {ta_id, ...}

    for ta in tas:
        outside_se = sum(d.get("se_value", 0) for d in ta.get("outside_duties", []))
        ta_used_se[ta["id"]]     = outside_se
        ta_booked_labs[ta["id"]] = set()
        ta_courses[ta["id"]]     = set()

    locked_assignments = [a for a in assignments_in if a.get("locked")]
    for a in locked_assignments:
        tid, lid, rid = a["ta_id"], a["lab_id"], a["role_id"]
        lab  = labs_by_id.get(lid)
        role = roles_map.get(rid, {})
        if lab and tid in ta_used_se:
            ta_used_se[tid]     += role.get("se_value", 1.0)
            ta_booked_labs[tid].add(lid)
            ta_courses[tid].add(lab.get("name", ""))
        key = (lid, rid)
        ta_per_slot.setdefault(key, set()).add(tid)

    # ── helpers ───────────────────────────────────────────────────────────────

    def static_conflict(ta, lab):
        """True if ta has a fixed time conflict with lab (courses or commitments)."""
        lab_mtgs = _get_meetings(lab)
        for gc_id in ta.get("grad_course_ids", []):
            gc = gc_map.get(gc_id)
            if not gc:
                continue
            for gd, gs, ge in _get_meetings(gc):
                for ld, ls, le in lab_mtgs:
                    if ld == gd and times_overlap(ls, le, gs, ge):
                        return True
        for oc in ta.get("other_commitments", []):
            for ld, ls, le in lab_mtgs:
                if oc["day"] == ld and times_overlap(ls, le, oc["start_min"], oc["end_min"]):
                    return True
        return False

    def double_booked(ta_id, lab):
        """True if assigning ta to lab would clash with an already-assigned lab."""
        lab_mtgs = _get_meetings(lab)
        for booked_id in ta_booked_labs[ta_id]:
            booked = labs_by_id.get(booked_id)
            if not booked:
                continue
            for bd, bs, be in _get_meetings(booked):
                for ld, ls, le in lab_mtgs:
                    if ld == bd and times_overlap(ls, le, bs, be):
                        return True
        return False

    def eligible_tas(lab, rr):
        """TAs that can fill one more seat for this (lab, role) slot right now."""
        role    = roles_map.get(rr["role_id"], {})
        se_val  = role.get("se_value", 1.0)
        already = ta_per_slot.get((lab["id"], rr["role_id"]), set())
        result  = []
        for ta in tas:
            tid = ta["id"]
            if tid in already:
                continue
            if static_conflict(ta, lab):
                continue
            if ta_used_se[tid] + se_val > ta.get("max_se", 2.0) + 0.001:
                continue
            if double_booked(tid, lab):
                continue
            result.append(ta)
        return result

    def score(ta, lab, rr):
        """Higher is better."""
        s = 1000   # filling the slot at all
        if rr.get("preferred_experienced", 0) > 0 and ta.get("experience") == "experienced":
            s += 1
        # split penalty: ta already assigned to a *different* course name
        courses = ta_courses[ta["id"]]
        cn = lab.get("name", "")
        if courses and cn not in courses:
            s -= 200
        # load-balancing: prefer TAs with less SE already assigned
        s -= ta_used_se[ta["id"]] * 500
        # random tiebreak
        s += random.random()
        return s

    # ── build work list: one entry per unfilled seat ──────────────────────────
    slots = []
    for lab in labs:
        for rr in lab.get("roles", []):
            count        = rr.get("count", 1)
            locked_count = len(ta_per_slot.get((lab["id"], rr["role_id"]), set()))
            for _ in range(count - locked_count):
                slots.append((lab, rr))

    # Sort by number of currently eligible TAs ascending (fail-first heuristic).
    slots.sort(key=lambda s: len(eligible_tas(s[0], s[1])))

    # ── greedy assignment ─────────────────────────────────────────────────────
    result_assignments = list(locked_assignments)

    for lab, rr in slots:
        candidates = eligible_tas(lab, rr)
        if not candidates:
            continue
        best = max(candidates, key=lambda ta: score(ta, lab, rr))
        role = roles_map.get(rr["role_id"], {})

        result_assignments.append({
            "lab_id":  lab["id"],
            "role_id": rr["role_id"],
            "ta_id":   best["id"],
            "locked":  False,
        })

        # update running state
        ta_used_se[best["id"]]     += role.get("se_value", 1.0)
        ta_booked_labs[best["id"]].add(lab["id"])
        ta_courses[best["id"]].add(lab.get("name", ""))
        ta_per_slot.setdefault((lab["id"], rr["role_id"]), set()).add(best["id"])

    # ── diagnostics ──────────────────────────────────────────────────────────
    tas_map = {ta["id"]: ta for ta in tas}
    unfilled, unfulfilled_exp = [], []
    for lab in labs:
        for rr in lab.get("roles", []):
            role_id    = rr["role_id"]
            count      = rr.get("count", 1)
            pref_exp   = rr.get("preferred_experienced", 0)
            role_label = roles_map.get(role_id, {}).get("label", role_id)
            role_asgn  = [a for a in result_assignments
                          if a["lab_id"] == lab["id"] and a["role_id"] == role_id]
            if len(role_asgn) < count:
                unfilled.append({
                    "lab_name":   lab["name"],
                    "role_label": role_label,
                    "assigned":   len(role_asgn),
                    "required":   count,
                })
            if pref_exp > 0:
                exp_n = sum(1 for a in role_asgn
                            if tas_map.get(a["ta_id"], {}).get("experience") == "experienced")
                if exp_n < pref_exp:
                    unfulfilled_exp.append({
                        "lab_name":      lab["name"],
                        "role_label":    role_label,
                        "exp_assigned":  exp_n,
                        "exp_preferred": pref_exp,
                    })

    status = "partial" if (unfilled or unfulfilled_exp) else "feasible"
    return {
        "status":      status,
        "assignments": result_assignments,
        "diagnostics": {"unfilled_roles": unfilled, "unfulfilled_experience": unfulfilled_exp},
    }


# ── DOCX export ──────────────────────────────────────────────────────────────

def generate_docx(data):
    from docx import Document

    doc = Document()
    doc.add_heading("TA Schedule", 0)

    roles_map = {r["id"]: r for r in data.get("roles", [])}
    tas_map = {t["id"]: t for t in data.get("tas", [])}
    labs_map = {l["id"]: l for l in data.get("labs", [])}
    assignments = data.get("assignments", [])
    day_long = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    day_short = ["Mon", "Tue", "Wed", "Thu", "Fri"]

    # Lab-centric
    doc.add_heading("Lab Assignments", 1)
    for lab in data.get("labs", []):
        doc.add_heading(lab["name"], 2)
        day = lab.get("day", 0)
        doc.add_paragraph(
            f"{day_long[day]}, {fmt_time(lab.get('start_min', 480))} – {fmt_time(lab.get('end_min', 540))}"
        )
        lab_asgn = [a for a in assignments if a["lab_id"] == lab["id"]]
        if lab_asgn:
            tbl = doc.add_table(rows=1, cols=3)
            tbl.style = "Table Grid"
            hdr = tbl.rows[0].cells
            hdr[0].text, hdr[1].text, hdr[2].text = "Role", "TA", "Status"
            for a in lab_asgn:
                row = tbl.add_row().cells
                row[0].text = roles_map.get(a["role_id"], {}).get("label", a.get("role_id", ""))
                row[1].text = tas_map.get(a["ta_id"], {}).get("name", a.get("ta_id", ""))
                row[2].text = "Locked" if a.get("locked") else "Assigned"
        else:
            doc.add_paragraph("No assignments")
        doc.add_paragraph()

    # TA-centric
    doc.add_heading("TA Assignments", 1)
    for ta in data.get("tas", []):
        doc.add_heading(ta["name"], 2)
        doc.add_paragraph(
            f"{ta.get('experience','').capitalize()}, Max SE: {ta.get('max_se', 2.0):.1f}"
        )
        ta_asgn = [a for a in assignments if a["ta_id"] == ta["id"]]
        outside = ta.get("outside_duties", [])
        if ta_asgn or outside:
            tbl = doc.add_table(rows=1, cols=4)
            tbl.style = "Table Grid"
            hdr = tbl.rows[0].cells
            hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = "Lab", "Role", "Time", "SE"
            total_se = 0.0
            for a in sorted(
                ta_asgn,
                key=lambda a: (
                    labs_map.get(a["lab_id"], {}).get("day", 0),
                    labs_map.get(a["lab_id"], {}).get("start_min", 0),
                ),
            ):
                lab = labs_map.get(a["lab_id"], {})
                role = roles_map.get(a["role_id"], {})
                se = role.get("se_value", 0)
                total_se += se
                row = tbl.add_row().cells
                row[0].text = lab.get("name", "")
                row[1].text = role.get("label", "")
                if lab:
                    d = lab.get("day", 0)
                    row[2].text = (
                        f"{day_short[d]} {fmt_time(lab['start_min'])}–{fmt_time(lab['end_min'])}"
                    )
                row[3].text = f"{se:.1f}"
            for od in outside:
                se = od.get("se_value", 0)
                total_se += se
                row = tbl.add_row().cells
                row[0].text = od.get("label", "Outside Duty")
                row[1].text = "Outside Duty"
                row[2].text = "—"
                row[3].text = f"{se:.1f}"
            tot = tbl.add_row().cells
            tot[0].text = "Total SE"
            tot[3].text = f"{total_se:.1f} / {ta.get('max_se', 2.0):.1f}"
        else:
            doc.add_paragraph("No assignments")
        doc.add_paragraph()

    return doc


def _find_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_flask(port, timeout=10):
    import time
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/", timeout=1)
            return True
        except Exception:
            time.sleep(0.05)
    return False


if __name__ == "__main__":

    try:
        import webview
    except ImportError:
        # pywebview not installed — fall back to plain Flask + browser
        import webbrowser
        webbrowser.open("http://localhost:5050")
        app.run(debug=False, port=5050)
    else:
        port = _find_free_port()

        flask_thread = threading.Thread(
            target=lambda: app.run(host="127.0.0.1", port=port, debug=False),
            daemon=True,
        )
        flask_thread.start()
        _wait_for_flask(port)

        _window = webview.create_window(
            "TA Scheduler",
            f"http://127.0.0.1:{port}/",
            width=1500,
            height=960,
            min_size=(900, 600),
        )
        webview.start()
