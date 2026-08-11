import copy
import csv
import json
import os
import random
import re
import socket
import threading
import traceback

from flask import Flask, jsonify, request, send_file

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
    "exams": [], "proctor_assignments": [],
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
        return copy.deepcopy(EMPTY_DATA)
    with open(p) as f:
        data = json.load(f)
    # Backward compat: fill missing keys
    for key in EMPTY_DATA:
        if key not in data:
            data[key] = copy.deepcopy(EMPTY_DATA[key]) if key == "roles" else []
    return data


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


DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri"]
DAY_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def fmt_meetings(item, day_names=None):
    """Every meeting of an item: 'Mon 9:00 AM–10:15 AM, Wed 9:00 AM–10:15 AM'."""
    names = day_names or DAY_SHORT
    parts = [f"{names[d]} {fmt_time(s)}–{fmt_time(e)}"
             for d, s, e in _get_meetings(item) if 0 <= d < len(names)]
    return ", ".join(parts) if parts else "—"


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


def _parse_exam_date(date_str):
    """'05/12-05/12' → '05/12' (the single date portion)."""
    parts = date_str.strip().split('-')
    return parts[0].strip() if parts else None


def _exam_date_to_iso(date_part, year):
    """'05/12' + 2026 → '2026-05-12'."""
    m = re.match(r'(\d{2})/(\d{2})', date_part)
    if not m:
        return None
    return f"{year}-{m.group(1)}-{m.group(2)}"


def _parse_regular_date_range(date_str, year):
    """'01/26-05/08' + 2026 → ('2026-01-26', '2026-05-08'), or (None, None)."""
    parts = date_str.strip().split('-')
    if len(parts) != 2:
        return None, None
    start = _exam_date_to_iso(parts[0].strip(), year)
    end   = _exam_date_to_iso(parts[1].strip(), year)
    return start, end


def _extract_year_from_term(term_str):
    """Extract 4-digit year from term code like '202620'."""
    m = re.match(r'(\d{4})', str(term_str).strip())
    return int(m.group(1)) if m else None


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(os.path.join(_BASE_DIR, "static", "index.html"))


@app.route("/api/data", methods=["GET"])
def get_data():
    return jsonify(load_data())


@app.route("/api/data", methods=["POST"])
def post_data():
    if not get_data_file():
        return jsonify({"error": "No file is open — use Save As to choose one."}), 400
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
    exam_courses = {}  # key: course_name → set of (date_iso, start_min, end_min)
    term_year = None

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

                # Try to extract year from Term column
                if term_year is None:
                    term_val = row.get("Term", "").strip()
                    if term_val:
                        term_year = _extract_year_from_term(term_val)

                if not days_raw or not times_raw:
                    continue

                slots_days = days_raw.split("|")
                slots_times = times_raw.split("|")
                slots_dates = dates_raw.split("|") if dates_raw else []

                regular, exams = [], []
                date_start, date_end = None, None
                for i, d in enumerate(slots_days):
                    t_str = slots_times[i].strip() if i < len(slots_times) else ""
                    dt_str = slots_dates[i].strip() if i < len(slots_dates) else ""
                    days = _parse_days(d.strip())
                    s_min, e_min = _parse_time_range(t_str)
                    if not days or s_min is None:
                        continue
                    if _is_regular(dt_str):
                        for day in days:
                            regular.append({"day": day, "start_min": s_min, "end_min": e_min})
                        if date_start is None and term_year:
                            date_start, date_end = _parse_regular_date_range(dt_str, term_year)
                    else:
                        # Exam: capture the actual date
                        date_part = _parse_exam_date(dt_str)
                        date_iso = _exam_date_to_iso(date_part, term_year) if date_part and term_year else None
                        for day in days:
                            exam_entry = {"day": day, "start_min": s_min, "end_min": e_min}
                            if date_iso:
                                exam_entry["date"] = date_iso
                            elif date_part:
                                exam_entry["date_raw"] = date_part
                            exams.append(exam_entry)

                course_name = f"{subject} {number}"
                section_label = section.strip()

                # Collect exam info for exam_courses (dedup by date+time)
                if level == "Undergraduate":
                    for ex in exams:
                        iso = ex.get("date") or (
                            _exam_date_to_iso(ex["date_raw"], term_year)
                            if ex.get("date_raw") and term_year else None)
                        if iso:
                            exam_courses.setdefault(course_name, set()).add(
                                (iso, ex["start_min"], ex["end_min"]))

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
                            "date_start": date_start,
                            "date_end":   date_end,
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
                            "date_start": date_start,
                            "date_end":   date_end,
                        })

        # Build exam_courses response: list of {name, exams: [{date, start_min, end_min}]}
        exam_courses_list = []
        for cname in sorted(exam_courses.keys()):
            unique_exams = sorted(exam_courses[cname])
            exam_courses_list.append({
                "name": cname,
                "exams": [{"date": e[0], "start_min": e[1], "end_min": e[2]}
                          for e in unique_exams],
            })

        return jsonify({
            "grad_courses": grad_courses,
            "undergrad_courses": sorted(undergrad.values(),
                                        key=lambda c: (c["subject"], c["number"])),
            "exam_courses": exam_courses_list,
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


@app.route("/api/schedule-proctoring", methods=["POST"])
def run_proctoring():
    data = request.get_json()
    try:
        result = solve_proctoring(data)
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

_SOLVER_ITERATIONS = 50


def solve(data):
    roles_map = {r["id"]: r for r in data.get("roles", [])}
    labs      = data.get("labs", [])
    tas       = data.get("tas", [])
    assignments_in = data.get("assignments", [])
    gc_map    = {gc["id"]: gc for gc in data.get("grad_courses", [])}

    if not labs or not tas:
        return {"status": "feasible", "assignments": assignments_in, "diagnostics": {}}

    labs_by_id = {lab["id"]: lab for lab in labs}
    locked_assignments = [a for a in assignments_in if a.get("locked")]

    # ── precomputed, input-only data (constant across all iterations) ──────

    lab_meetings = {lab["id"]: _get_meetings(lab) for lab in labs}

    # Every fixed time block a TA already owns: grad courses + other commitments.
    ta_fixed_times = {}
    for ta in tas:
        fixed = []
        for gc_id in ta.get("grad_course_ids", []):
            gc = gc_map.get(gc_id)
            if gc:
                fixed.extend(_get_meetings(gc))
        for oc in ta.get("other_commitments", []):
            fixed.append((oc["day"], oc["start_min"], oc["end_min"]))
        ta_fixed_times[ta["id"]] = fixed

    # (ta_id, lab_id) pairs blocked by a fixed conflict. Depends only on the
    # input, so it is built once rather than re-derived on every eligibility test.
    static_conflicts = frozenset(
        (ta["id"], lab["id"])
        for ta in tas
        for lab in labs
        if any(ld == fd and times_overlap(ls, le, fs, fe)
               for ld, ls, le in lab_meetings[lab["id"]]
               for fd, fs, fe in ta_fixed_times[ta["id"]])
    )

    # ── build work list (same every iteration) ─────────────────────────────

    # Initialise locked state to compute the slot list and initial eligibility
    init_ta_per_slot = {}
    for a in locked_assignments:
        key = (a["lab_id"], a["role_id"])
        init_ta_per_slot.setdefault(key, set()).add(a["ta_id"])

    slots = []
    for lab in labs:
        for rr in lab.get("roles", []):
            count        = rr.get("count", 1)
            locked_count = len(init_ta_per_slot.get((lab["id"], rr["role_id"]), set()))
            for _ in range(count - locked_count):
                slots.append((lab, rr))

    if not slots:
        # Nothing to assign — return locked assignments as-is
        return {"status": "feasible", "assignments": locked_assignments, "diagnostics": {}}

    # ── mutable per-pass state ─────────────────────────────────────────────

    def initial_state():
        """Fresh solver state seeded from the locked assignments."""
        st = {"used_se": {}, "booked_labs": {}, "courses": {}, "per_slot": {}}
        for ta in tas:
            tid = ta["id"]
            st["used_se"][tid]     = sum(d.get("se_value", 0)
                                         for d in ta.get("outside_duties", []))
            st["booked_labs"][tid] = set()
            st["courses"][tid]     = set()
        for a in locked_assignments:
            tid, lid, rid = a["ta_id"], a["lab_id"], a["role_id"]
            lab  = labs_by_id.get(lid)
            role = roles_map.get(rid, {})
            if lab and tid in st["used_se"]:
                st["used_se"][tid] += role.get("se_value", 1.0)
                st["booked_labs"][tid].add(lid)
                st["courses"][tid].add(lab.get("name", ""))
            st["per_slot"].setdefault((lid, rid), set()).add(tid)
        return st

    def double_booked(st, ta_id, lab_mtgs):
        for booked_id in st["booked_labs"][ta_id]:
            for bd, bs, be in lab_meetings.get(booked_id, ()):
                for ld, ls, le in lab_mtgs:
                    if ld == bd and times_overlap(ls, le, bs, be):
                        return True
        return False

    def eligible_tas(st, lab, rr):
        role     = roles_map.get(rr["role_id"], {})
        se_val   = role.get("se_value", 1.0)
        lab_id   = lab["id"]
        lab_mtgs = lab_meetings[lab_id]
        already  = st["per_slot"].get((lab_id, rr["role_id"]), set())
        result   = []
        for ta in tas:
            tid = ta["id"]
            if tid in already:
                continue
            if (tid, lab_id) in static_conflicts:
                continue
            if st["used_se"][tid] + se_val > ta.get("max_se", 2.0) + 0.001:
                continue
            if double_booked(st, tid, lab_mtgs):
                continue
            result.append(ta)
        return result

    def score(st, ta, lab, rr):
        s = 1000
        if rr.get("preferred_experienced", 0) > 0 and ta.get("experience") == "experienced":
            s += 200
        courses = st["courses"][ta["id"]]
        cn = lab.get("name", "")
        if courses and cn not in courses:
            s -= 200
        s -= st["used_se"][ta["id"]] * 500
        s += random.random()
        return s

    # Slot order is derived from locked-only state, so it is identical on every
    # iteration — compute it once.
    init_st = initial_state()
    sorted_slots = sorted(slots,
        key=lambda s: (len(eligible_tas(init_st, s[0], s[1])),
                       -roles_map.get(s[1]["role_id"], {}).get("se_value", 1.0)))

    # ── single greedy pass ─────────────────────────────────────────────────

    def _greedy_pass():
        st = initial_state()
        result_assignments = list(locked_assignments)

        for lab, rr in sorted_slots:
            candidates = eligible_tas(st, lab, rr)
            if not candidates:
                continue
            best = max(candidates, key=lambda ta: score(st, ta, lab, rr))
            role = roles_map.get(rr["role_id"], {})

            result_assignments.append({
                "lab_id":  lab["id"],
                "role_id": rr["role_id"],
                "ta_id":   best["id"],
                "locked":  False,
            })

            st["used_se"][best["id"]] += role.get("se_value", 1.0)
            st["booked_labs"][best["id"]].add(lab["id"])
            st["courses"][best["id"]].add(lab.get("name", ""))
            st["per_slot"].setdefault((lab["id"], rr["role_id"]), set()).add(best["id"])

        return result_assignments

    # ── run multiple iterations, keep the best ─────────────────────────────

    best_result = None
    best_unfilled = float("inf")

    for _ in range(_SOLVER_ITERATIONS):
        result_assignments = _greedy_pass()

        # Count unfilled seats for this attempt
        unfilled_count = len(slots) - sum(
            1 for a in result_assignments if not a.get("locked"))
        if unfilled_count <= 0:
            best_result = result_assignments
            break
        if unfilled_count < best_unfilled:
            best_unfilled = unfilled_count
            best_result = result_assignments

    result_assignments = best_result

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


# ── proctoring solver ────────────────────────────────────────────────────────

def solve_proctoring(data):
    import datetime

    exams = data.get("exams", [])
    tas = data.get("tas", [])
    proctor_in = data.get("proctor_assignments", [])
    labs = data.get("labs", [])
    gc_map = {gc["id"]: gc for gc in data.get("grad_courses", [])}
    assignments = data.get("assignments", [])

    if not exams or not tas:
        return {"status": "feasible", "proctor_assignments": proctor_in, "diagnostics": {}}

    exams_by_id = {ex["id"]: ex for ex in exams}
    locked = [a for a in proctor_in if a.get("locked")]

    # Build lab assignments per TA: ta_id → [(weekday, start_min, end_min)]
    labs_by_id = {l["id"]: l for l in labs}
    ta_lab_times = {}
    for a in assignments:
        lab = labs_by_id.get(a["lab_id"])
        if not lab:
            continue
        for d, s, e in _get_meetings(lab):
            ta_lab_times.setdefault(a["ta_id"], []).append((d, s, e))

    # TA → set of lab course names and sections (for familiarity bonus)
    ta_lab_courses = {}
    ta_lab_sections = {}
    for a in assignments:
        lab = labs_by_id.get(a["lab_id"])
        if lab:
            ta_lab_courses.setdefault(a["ta_id"], set()).add(lab.get("name", ""))
            sect = lab.get("section", "")
            if sect:
                ta_lab_sections.setdefault(a["ta_id"], set()).add((lab.get("name", ""), sect))

    def exam_weekday(exam):
        """Get weekday (0=Mon) from exam date string."""
        try:
            d = datetime.date.fromisoformat(exam["date"])
            return d.weekday()  # 0=Mon
        except (KeyError, ValueError):
            return None

    # Build slots
    init_per_exam = {}
    for a in locked:
        init_per_exam.setdefault(a["exam_id"], set()).add(a["ta_id"])

    slots = []
    for exam in exams:
        if exam.get("tbd"):
            continue  # Skip TBD exams — no date/time to schedule against
        count = exam.get("proctor_count", 1)
        locked_count = len(init_per_exam.get(exam["id"], set()))
        for _ in range(count - locked_count):
            slots.append(exam)

    if not slots:
        return {"status": "feasible", "proctor_assignments": locked, "diagnostics": {}}

    # ── precomputed, input-only data (constant across all iterations) ──────

    slot_exams = {ex["id"]: ex for ex in slots}
    exam_wd = {eid: exam_weekday(ex) for eid, ex in slot_exams.items()}

    def _fixed_conflict(ta, exam):
        """True if a TA has an input-derived conflict with this exam: an assigned
        lab, a grad course meeting or exam, a commitment, or a date conflict."""
        wd = exam_wd.get(exam["id"])
        es, ee = exam.get("start_min", 0), exam.get("end_min", 0)
        if wd is not None:
            for ld, ls, le in ta_lab_times.get(ta["id"], []):
                if ld == wd and times_overlap(es, ee, ls, le):
                    return True
            for gc_id in ta.get("grad_course_ids", []):
                gc = gc_map.get(gc_id)
                if not gc:
                    continue
                for gd, gs, ge in _get_meetings(gc):
                    if gd == wd and times_overlap(es, ee, gs, ge):
                        return True
                exam_date = exam.get("date")
                if exam_date:
                    for gc_ex in gc.get("exams", []):
                        if gc_ex.get("date") == exam_date and times_overlap(
                                es, ee, gc_ex.get("start_min", 0), gc_ex.get("end_min", 0)):
                            return True
            for oc in ta.get("other_commitments", []):
                if oc["day"] == wd and times_overlap(
                        es, ee, oc["start_min"], oc["end_min"]):
                    return True
        dc_date = exam.get("date")
        if dc_date:
            for dc in ta.get("date_conflicts", []):
                if dc.get("date") == dc_date and times_overlap(
                        es, ee, dc.get("start_min", 0), dc.get("end_min", 0)):
                    return True
        return False

    static_conflicts = frozenset(
        (ta["id"], eid)
        for ta in tas
        for eid, exam in slot_exams.items()
        if _fixed_conflict(ta, exam)
    )

    # ── mutable per-pass state ─────────────────────────────────────────────

    def initial_state():
        """Fresh solver state seeded from the locked proctor assignments."""
        st = {"used_pe": {}, "assigned_exams": {}, "times": {},
              "courses": {}, "sections": {}}
        for ta in tas:
            tid = ta["id"]
            st["used_pe"][tid]        = sum(op.get("pe_value", 0)
                                            for op in ta.get("outside_proctoring", []))
            st["assigned_exams"][tid] = set()
            st["times"][tid]          = []
            st["courses"][tid]        = set()
            st["sections"][tid]       = set()
        for a in locked:
            tid, eid = a["ta_id"], a["exam_id"]
            exam = exams_by_id.get(eid)
            if not exam or tid not in st["used_pe"]:
                continue
            st["used_pe"][tid] += exam.get("pe_value", 1.0)
            st["assigned_exams"][tid].add(eid)
            st["times"][tid].append(
                (exam.get("date", ""), exam.get("start_min", 0), exam.get("end_min", 0)))
            course_name = exam.get("course_name", "")
            sect = exam.get("section", "")
            if course_name:
                st["courses"][tid].add(course_name)
            if course_name and sect:
                st["sections"][tid].add((course_name, sect))
        return st

    def eligible_tas(st, exam):
        pe_val = exam.get("pe_value", 1.0)
        eid    = exam["id"]
        edate  = exam.get("date")
        es, ee = exam.get("start_min", 0), exam.get("end_min", 0)
        result = []
        for ta in tas:
            tid = ta["id"]
            if st["used_pe"][tid] + pe_val > ta.get("max_pe", 2.0) + 0.001:
                continue
            if eid in st["assigned_exams"][tid]:
                continue
            # Same-date time conflicts with exams already being proctored
            if any(pdate == edate and times_overlap(es, ee, ps, pe)
                   for pdate, ps, pe in st["times"][tid]):
                continue
            if (tid, eid) in static_conflicts:
                continue
            result.append(ta)
        return result

    def score(st, ta, exam):
        s = 1000
        tid = ta["id"]
        course_name = exam.get("course_name", "")
        section = exam.get("section", "")
        key = (course_name, section)
        # Lab familiarity bonus (same course)
        if course_name and course_name in ta_lab_courses.get(tid, set()):
            s += 300
        # Lab section bonus (same course + section)
        if course_name and section and key in ta_lab_sections.get(tid, set()):
            s += 150
        # Same-course proctoring bonus
        if course_name and course_name in st["courses"][tid]:
            s += 200
        # Same-section proctoring bonus
        if course_name and section and key in st["sections"][tid]:
            s += 100
        # Load balancing
        s -= st["used_pe"][tid] * 500
        s += random.random()
        return s

    # Slot order is derived from locked-only state, so it is identical on every
    # iteration — compute it once.
    init_st = initial_state()
    sorted_slots = sorted(slots, key=lambda ex: len(eligible_tas(init_st, ex)))

    def _greedy_pass():
        st = initial_state()
        result = list(locked)
        for exam in sorted_slots:
            candidates = eligible_tas(st, exam)
            if not candidates:
                continue
            best = max(candidates, key=lambda ta: score(st, ta, exam))
            tid = best["id"]
            result.append({
                "exam_id": exam["id"],
                "ta_id": tid,
                "locked": False,
            })
            st["used_pe"][tid] += exam.get("pe_value", 1.0)
            st["assigned_exams"][tid].add(exam["id"])
            st["times"][tid].append(
                (exam.get("date", ""), exam.get("start_min", 0), exam.get("end_min", 0)))
            cname = exam.get("course_name", "")
            sect = exam.get("section", "")
            if cname:
                st["courses"][tid].add(cname)
            if cname and sect:
                st["sections"][tid].add((cname, sect))

        return result

    best_result = None
    best_unfilled = float("inf")

    for _ in range(_SOLVER_ITERATIONS):
        result = _greedy_pass()
        unfilled_count = len(slots) - sum(1 for a in result if not a.get("locked"))
        if unfilled_count <= 0:
            best_result = result
            break
        if unfilled_count < best_unfilled:
            best_unfilled = unfilled_count
            best_result = result

    result = best_result

    # Diagnostics
    unfilled = []
    for exam in exams:
        if exam.get("tbd"):
            continue  # Never scheduled, so never "unfilled"
        count = exam.get("proctor_count", 1)
        assigned = [a for a in result if a["exam_id"] == exam["id"]]
        if len(assigned) < count:
            unfilled.append({
                "exam_name": exam.get("name", ""),
                "assigned": len(assigned),
                "required": count,
            })

    status = "partial" if unfilled else "feasible"
    return {
        "status": status,
        "proctor_assignments": result,
        "diagnostics": {"unfilled_proctors": unfilled},
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
    exams_map = {e["id"]: e for e in data.get("exams", [])}
    proctor_assignments = data.get("proctor_assignments", [])

    def lab_disp(lab):
        s = lab.get("section", "")
        return f"{lab['name']} {s}".strip() if s else lab["name"]

    # Lab-centric
    doc.add_heading("Lab Assignments", 1)
    for lab in sorted(data.get("labs", []), key=lambda l: (l.get("name", ""), l.get("section", ""))):
        doc.add_heading(lab_disp(lab), 2)
        doc.add_paragraph(fmt_meetings(lab, DAY_LONG))
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

    # Exam proctoring
    exams = data.get("exams", [])
    if exams and proctor_assignments:
        doc.add_heading("Exam Proctoring", 1)
        sorted_exams = sorted(exams, key=lambda e: (e.get("course_name", ""), e.get("section", ""), e.get("date", "")))
        for exam in sorted_exams:
            exam_asgn = [a for a in proctor_assignments if a["exam_id"] == exam["id"]]
            if not exam_asgn:
                continue
            cname = exam.get("course_name", "")
            sect = exam.get("section", "")
            label = f"{cname} {sect}".strip() if cname else exam.get("name", "Exam")
            sub = exam.get("name", "")
            doc.add_heading(f"{label} — {sub}" if sub and label != sub else label or sub, 2)
            doc.add_paragraph(
                f"{exam.get('date', '—')}, {fmt_time(exam.get('start_min', 0))} – "
                f"{fmt_time(exam.get('end_min', 0))}"
            )
            for a in exam_asgn:
                ta = tas_map.get(a["ta_id"])
                status = "Locked" if a.get("locked") else "Assigned"
                doc.add_paragraph(f"  {ta.get('name', a['ta_id']) if ta else a['ta_id']} ({status})")
        doc.add_paragraph()

    # TA-centric
    doc.add_heading("TA Assignments", 1)
    for ta in data.get("tas", []):
        doc.add_heading(ta["name"], 2)
        email_str = f", Email: {ta['email']}" if ta.get('email') else ''
        doc.add_paragraph(
            f"{ta.get('experience','').capitalize()}, Max SE: {ta.get('max_se', 2.0):.1f}{email_str}"
        )
        ta_asgn = [a for a in assignments if a["ta_id"] == ta["id"]]
        outside = ta.get("outside_duties", [])
        ta_proctor = sorted(
            [a for a in proctor_assignments if a["ta_id"] == ta["id"]],
            key=lambda a: (
                exams_map.get(a["exam_id"], {}).get("course_name", ""),
                exams_map.get(a["exam_id"], {}).get("section", ""),
                exams_map.get(a["exam_id"], {}).get("date", ""),
            ),
        )
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
                row[0].text = lab_disp(lab)
                row[1].text = role.get("label", "")
                if lab:
                    row[2].text = fmt_meetings(lab)
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
        outside_proctor = ta.get("outside_proctoring", [])
        if ta_proctor or outside_proctor:
            doc.add_paragraph("Proctoring")
            ptbl = doc.add_table(rows=1, cols=4)
            ptbl.style = "Table Grid"
            phdr = ptbl.rows[0].cells
            phdr[0].text, phdr[1].text, phdr[2].text, phdr[3].text = "Exam", "Date", "Time", "PE"
            total_pe = 0.0
            for pa in ta_proctor:
                exam = exams_map.get(pa["exam_id"], {})
                pe = exam.get("pe_value", 0)
                total_pe += pe
                cname = exam.get("course_name", "")
                sect = exam.get("section", "")
                label = f"{cname} {sect}".strip() if cname else exam.get("name", "Exam")
                sub = exam.get("name", "")
                exam_label = f"{label} — {sub}" if sub and label != sub else label or sub
                prow = ptbl.add_row().cells
                prow[0].text = exam_label
                prow[1].text = exam.get("date", "—")
                prow[2].text = (
                    f"{fmt_time(exam.get('start_min', 0))}–{fmt_time(exam.get('end_min', 0))}"
                    if exam.get("date") else "—"
                )
                prow[3].text = f"{pe:.1f}"
            for op in outside_proctor:
                pe = op.get("pe_value", 0)
                total_pe += pe
                orow = ptbl.add_row().cells
                orow[0].text = op.get("label", "Outside Proctoring")
                orow[1].text = "—"
                orow[2].text = "—"
                orow[3].text = f"{pe:.1f}"
            ptot = ptbl.add_row().cells
            ptot[0].text = "Total PE"
            ptot[3].text = f"{total_pe:.1f}"
        if not ta_asgn and not outside and not ta_proctor and not outside_proctor:
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
            text_select=True,
        )
        webview.start()
