import csv
import io
import json
import os
import re
import subprocess
import traceback

from flask import Flask, jsonify, make_response, request, send_file

app = Flask(__name__, static_folder="static")

# None until the user opens or saves a file.
_data_file = None

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


def _osascript_dialog(script):
    """Run an AppleScript file-dialog and return the chosen path, or None."""
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


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
    return send_file("static/index.html")


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
    data = request.get_json()
    current = get_data_file()
    default_name = os.path.basename(current) if current else "schedule.json"
    script = (
        f'set f to choose file name '
        f'with prompt "Save Schedule As" '
        f'default name "{default_name}" '
        f'default location POSIX file "{_default_dir()}"\n'
        f'return POSIX path of f'
    )
    path = _osascript_dialog(script)
    if path is None:
        return jsonify({"cancelled": True})
    if not path.endswith(".json"):
        path += ".json"
    set_data_file(path)
    save_data_to_file(data)
    return jsonify({"path": path})


@app.route("/api/open-dialog", methods=["POST"])
def open_dialog():
    script = (
        f'set f to choose file '
        f'with prompt "Open Schedule" '
        f'default location POSIX file "{_default_dir()}"\n'
        f'return POSIX path of f'
    )
    path = _osascript_dialog(script)
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
    script = (
        f'set f to choose file '
        f'with prompt "Import Course CSV" '
        f'default location POSIX file "{_default_dir()}"\n'
        f'return POSIX path of f'
    )
    path = _osascript_dialog(script)
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
    data = request.get_json()
    try:
        doc = generate_docx(data)
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        response = make_response(buf.read())
        response.headers["Content-Type"] = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        response.headers["Content-Disposition"] = "attachment; filename=ta_schedule.docx"
        return response
    except Exception:
        traceback.print_exc()
        return jsonify({"error": traceback.format_exc()}), 500


# ── solver ───────────────────────────────────────────────────────────────────

def solve(data):
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return {"status": "error", "message": "ortools not installed. Run: pip install ortools"}

    model = cp_model.CpModel()

    roles_map = {r["id"]: r for r in data.get("roles", [])}
    labs = data.get("labs", [])
    tas = data.get("tas", [])
    assignments_in = data.get("assignments", [])
    gc_map = {gc["id"]: gc for gc in data.get("grad_courses", [])}

    if not labs or not tas:
        return {"status": "feasible", "assignments": assignments_in, "diagnostics": {}}

    locked_set = {
        (a["lab_id"], a["role_id"], a["ta_id"])
        for a in assignments_in
        if a.get("locked")
    }

    # ── decision variables ──
    x = {}
    real_vars = []
    for lab in labs:
        for rr in lab.get("roles", []):
            role_id = rr["role_id"]
            for ta in tas:
                key = (lab["id"], role_id, ta["id"])

                # availability hard-exclude
                unavail = False
                lab_meetings = _get_meetings(lab)
                for gc_id in ta.get("grad_course_ids", []):
                    gc = gc_map.get(gc_id)
                    if not gc:
                        continue
                    for gc_day, gc_start, gc_end in _get_meetings(gc):
                        for lab_day, lab_start, lab_end in lab_meetings:
                            if gc_day == lab_day and times_overlap(lab_start, lab_end, gc_start, gc_end):
                                unavail = True
                                break
                        if unavail:
                            break
                    if unavail:
                        break
                if not unavail:
                    for oc in ta.get("other_commitments", []):
                        for lab_day, lab_start, lab_end in lab_meetings:
                            if oc["day"] == lab_day and times_overlap(lab_start, lab_end, oc["start_min"], oc["end_min"]):
                                unavail = True
                                break
                        if unavail:
                            break
                if unavail:
                    x[key] = model.NewConstant(0)
                    continue

                var = model.NewBoolVar(f"x_{lab['id']}_{role_id}_{ta['id']}")
                if key in locked_set:
                    model.Add(var == 1)
                else:
                    real_vars.append(var)
                x[key] = var

    # ── constraint 1: role count (soft upper bound, maximize fill) ──
    for lab in labs:
        for rr in lab.get("roles", []):
            role_id = rr["role_id"]
            count = rr.get("count", 1)
            ta_vars = [x[(lab["id"], role_id, ta["id"])]
                       for ta in tas if (lab["id"], role_id, ta["id"]) in x]
            model.Add(sum(ta_vars) <= count)

    # ── objective: fill slots (high weight) + experience preference (low weight) ──
    FILL_W = 1000
    obj_terms = [v * FILL_W for v in real_vars]
    for lab in labs:
        for rr in lab.get("roles", []):
            role_id = rr["role_id"]
            pref_exp = rr.get("preferred_experienced", 0)
            if pref_exp <= 0:
                continue
            exp_vars = [
                x[(lab["id"], role_id, ta["id"])]
                for ta in tas
                if ta.get("experience") == "experienced"
                and (lab["id"], role_id, ta["id"]) in x
            ]
            if not exp_vars:
                continue
            exp_count = model.NewIntVar(0, pref_exp, f"exp_{lab['id']}_{role_id}")
            model.Add(exp_count <= sum(exp_vars))
            obj_terms.append(exp_count)
    # ── soft penalty: minimize split assignments ──
    # A "split" is a TA assigned to labs from more than one distinct course name.
    # For each TA, count distinct course names assigned; penalize each name beyond the first.
    SPLIT_W = 200
    from collections import defaultdict
    course_lab_roles = defaultdict(list)  # course_name -> [(lab_id, role_id)]
    for lab in labs:
        cn = lab.get("name", "")
        for rr in lab.get("roles", []):
            course_lab_roles[cn].append((lab["id"], rr["role_id"]))

    if len(course_lab_roles) > 1:
        for ta in tas:
            ta_course_bools = []
            for cn, lab_roles in course_lab_roles.items():
                cb = model.NewBoolVar(f"tc_{ta['id']}_{cn}")
                for lab_id, role_id in lab_roles:
                    key = (lab_id, role_id, ta["id"])
                    if key in x:
                        model.Add(cb >= x[key])
                ta_course_bools.append(cb)
            if len(ta_course_bools) > 1:
                excess = model.NewIntVar(0, len(ta_course_bools) - 1, f"exc_{ta['id']}")
                model.Add(excess >= sum(ta_course_bools) - 1)
                obj_terms.append(excess * -SPLIT_W)

    if obj_terms:
        model.Maximize(sum(obj_terms))

    # ── constraint 2: SE cap ──
    SE_SCALE = 100
    for ta in tas:
        max_se = int(ta.get("max_se", 2.0) * SE_SCALE)
        outside_se = sum(int(d.get("se_value", 0) * SE_SCALE)
                         for d in ta.get("outside_duties", []))
        se_terms = []
        for lab in labs:
            for rr in lab.get("roles", []):
                key = (lab["id"], rr["role_id"], ta["id"])
                if key in x:
                    se_val = int(roles_map.get(rr["role_id"], {}).get("se_value", 1.0) * SE_SCALE)
                    se_terms.append(x[key] * se_val)
        if se_terms:
            model.Add(sum(se_terms) + outside_se <= max_se)

    # ── constraint 3: no double-booking ──
    for ta in tas:
        for i, lab1 in enumerate(labs):
            for lab2 in labs[i + 1:]:
                overlap = any(
                    d1 == d2 and times_overlap(s1, e1, s2, e2)
                    for d1, s1, e1 in _get_meetings(lab1)
                    for d2, s2, e2 in _get_meetings(lab2)
                )
                if not overlap:
                    continue
                v1 = [x[(lab1["id"], rr["role_id"], ta["id"])]
                      for rr in lab1.get("roles", [])
                      if (lab1["id"], rr["role_id"], ta["id"]) in x]
                v2 = [x[(lab2["id"], rr["role_id"], ta["id"])]
                      for rr in lab2.get("roles", [])
                      if (lab2["id"], rr["role_id"], ta["id"]) in x]
                if v1 and v2:
                    model.Add(sum(v1) + sum(v2) <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        new_assignments = [a for a in assignments_in if a.get("locked")]
        for lab in labs:
            for rr in lab.get("roles", []):
                role_id = rr["role_id"]
                for ta in tas:
                    key = (lab["id"], role_id, ta["id"])
                    if key in locked_set:
                        continue
                    if key in x and solver.Value(x[key]) == 1:
                        new_assignments.append({
                            "lab_id": lab["id"],
                            "role_id": role_id,
                            "ta_id": ta["id"],
                            "locked": False,
                        })

        # compute unfilled roles and unmet experience preferences
        tas_map = {ta["id"]: ta for ta in tas}
        unfilled = []
        unfulfilled_exp = []
        for lab in labs:
            for rr in lab.get("roles", []):
                role_id = rr["role_id"]
                count = rr.get("count", 1)
                pref_exp = rr.get("preferred_experienced", 0)
                role_label = roles_map.get(role_id, {}).get("label", role_id)
                role_assigns = [
                    a for a in new_assignments
                    if a["lab_id"] == lab["id"] and a["role_id"] == role_id
                ]
                assigned = len(role_assigns)
                if assigned < count:
                    unfilled.append({
                        "lab_name": lab["name"],
                        "role_label": role_label,
                        "assigned": assigned,
                        "required": count,
                    })
                if pref_exp > 0:
                    exp_assigned = sum(
                        1 for a in role_assigns
                        if tas_map.get(a["ta_id"], {}).get("experience") == "experienced"
                    )
                    if exp_assigned < pref_exp:
                        unfulfilled_exp.append({
                            "lab_name": lab["name"],
                            "role_label": role_label,
                            "exp_assigned": exp_assigned,
                            "exp_preferred": pref_exp,
                        })

        solve_status = "partial" if (unfilled or unfulfilled_exp) else (
            "optimal" if status == cp_model.OPTIMAL else "feasible"
        )
        return {
            "status": solve_status,
            "assignments": new_assignments,
            "diagnostics": {"unfilled_roles": unfilled, "unfulfilled_experience": unfulfilled_exp},
        }
    else:
        return {
            "status": "infeasible",
            "assignments": [a for a in assignments_in if a.get("locked")],
            "diagnostics": {"unfilled_roles": [], "error": "Locked assignments conflict with constraints."},
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
            f"{ta.get('experience','').capitalize()}, Max SE: {ta.get('max_se', 2.0)}"
        )
        ta_asgn = [a for a in assignments if a["ta_id"] == ta["id"]]
        if ta_asgn:
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
                row[3].text = str(se)
            tot = tbl.add_row().cells
            tot[0].text = "Total SE"
            tot[3].text = f"{total_se} / {ta.get('max_se', 2.0)}"
        else:
            doc.add_paragraph("No assignments")
        doc.add_paragraph()

    return doc


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=True, port=5050)
