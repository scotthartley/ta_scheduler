# TA Scheduler — Claude Instructions

## Project overview

A single-user desktop web app (macOS) for scheduling graduate teaching assistants across lab sections. The backend serves the frontend and runs the solver; there is no separate database or build step.

## Running the app

```bash
cd /Users/hartlecs/git_repos/ta_scheduler
python ta_scheduler.py
# Opens as a native pywebview window; falls back to browser at http://localhost:5050
```

Port 5050 is used for the browser fallback. When pywebview is available, a free port is chosen dynamically.

## File structure

```
ta_scheduler/          ← repo root (flat, no subdirectories)
├── ta_scheduler.py             ← Flask backend + greedy solver + python-docx export + CSV import
├── static/
│   └── index.html     ← entire frontend (vanilla JS, no build tools, no dependencies)
├── requirements.txt
└── CourseExport.csv   ← sample department course export used for CSV import
```

## Dependencies

```
flask>=3.0.0
python-docx>=1.1.0
pywebview>=5.0.0
```

Install: `pip install -r requirements.txt`

## Architecture

**Backend (`ta_scheduler.py`):**
- Flask serves `static/index.html` and a JSON REST API
- All persistent data lives in a single `.json` file chosen by the user via pywebview native file dialogs
- No data file is required to start; the app begins with empty in-memory state
- The greedy lab solver runs synchronously on `/api/schedule`
- The greedy proctoring solver runs synchronously on `/api/schedule-proctoring`
- When pywebview is unavailable, falls back to plain Flask + browser on port 5050
- `text_select=True` is set on `create_window` to enable text selection in the native window (not the pywebview default)

**Frontend (`static/index.html`):**
- Single HTML file — all CSS, JS, and HTML in one file
- All runtime state lives in the `S` object; changes call `markDirty()` and are saved via Ctrl+S or the Save button
- No framework, no npm, no bundler

## Data model (JSON schema)

```
roles:              [{id, label, se_value}]
grad_courses:       [{id, name, section, day, start_min, end_min, meetings?, exams?, date_start?, date_end?}]
labs:               [{id, name, section, day, start_min, end_min, meetings?, exams?, date_start?, date_end?, roles[]}]
                    roles[]: [{role_id, count, preferred_experienced}]
tas:                [{id, name, email?, experience, max_se, max_pe, grad_course_ids[], outside_duties[],
                      outside_proctoring[], other_commitments[]}]
assignments:        [{lab_id, role_id, ta_id, locked}]
exams:              [{id, name, course_name, section, date, start_min, end_min, tbd, proctor_count, pe_value}]
proctor_assignments: [{exam_id, ta_id, locked}]
```

- `day`: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
- `start_min` / `end_min`: minutes since midnight (e.g. 540 = 9:00 AM)
- `meetings`: optional array of `{day, start_min, end_min}` — present on multi-day entries (e.g. MWF); `day`/`start_min`/`end_min` at the top level always hold the first meeting for backward compatibility
- `experience`: `"experienced"` | `"inexperienced"`
- `se_value`: SE (service equivalent) units as a float (e.g. 1.0, 0.5)
- `pe_value`: PE (proctoring equivalent) units as a float
- `max_pe`: maximum PE a TA can be assigned (default 2.0)
- `outside_proctoring[]`: `[{label, pe_value}]` — external proctoring duties counted toward max_pe
- `tbd`: if true, the exam has no date/time yet and is skipped by the proctoring solver

## Grid

- Hours displayed: 7:00 AM – 7:00 PM (`GRID_START = 420`, `GRID_END = 1140`)
- `HOUR_H = 75` px per hour; `PX_PER_MIN = GRID_H / GRID_MINS` (= 1.25 px/min)
- Time snaps to 5-minute increments
- The **main schedule grid** (Lab Sections, Graduate Courses, TAs tabs) uses pixel-based positioning via `minToY()` / `yToMin()`
- The **Meeting Finder grid** uses percentage-based positioning so it scales to fill the available panel height without scrolling; cells and hour lines are positioned as `(offset / GRID_MINS) * 100 + '%'`

## Tab order (left to right)

Lab Sections | Exams | Graduate Courses | TAs | Schedule Labs | Schedule Proctoring | Summary | Meeting Finder

## Solver (greedy — lab scheduling)

Hard constraints (eligibility filters):
1. Role count: assignments per role ≤ configured count
2. SE cap: total SE assigned to a TA ≤ their max_se (including outside duties)
3. No double-booking: a TA cannot be assigned to two labs whose meetings overlap on the same day (checks all meetings in `meetings[]`)
4. Availability: a TA cannot be assigned to a lab that conflicts with any of their grad course meetings or other commitments

Scoring (higher is better): base 1000 + experience preference (+200 if preferred_experienced and TA is experienced) − split penalty for assigning to a different course name (−200) − load-balancing penalty (current SE × 500) + random tiebreak.

Slots are processed in ascending order of eligible TA count (fail-first). The highest-scoring eligible TA is assigned to each slot.

The solver runs up to 50 random-tiebreak iterations and keeps the result with the fewest unfilled slots.

Locked assignments are always preserved; the solver fills remaining slots.

## Solver (greedy — proctoring)

Endpoint: `/api/schedule-proctoring`

Hard constraints:
1. PE cap: total PE assigned to a TA ≤ their max_pe (including outside_proctoring)
2. No double-booking: a TA cannot proctor two exams with overlapping times on the same date
3. No conflict with assigned lab meetings (exam weekday vs. lab weekday)
4. No conflict with grad course regular meetings (weekday) or grad course exams (date-specific)
5. No conflict with other_commitments (weekday)
6. TBD exams (no date/time) are skipped

Scoring: base 1000 + course familiarity bonus (+300 if TA is assigned a lab for the same course) − load-balancing penalty (current PE × 500) + random tiebreak.

Also runs up to 50 iterations, keeping the best result.

## CSV import

The "Import Class Info" button (visible on Lab Sections and Exams tabs) opens a file picker and parses a department course export CSV with these columns:

`Course Level, Subject, Number, Section, Title, Meeting Days, Meeting Times, Meeting Dates, Term`

- Multi-day sections (e.g. `MWF`) are stored as a single entry with a `meetings[]` array
- Each entry also includes `section`, `date_start`, and `date_end` from the Term/Meeting Dates columns
- Exam sessions (Meeting Dates start == end) are stored in `exams[]` on the course entry and also returned as `exam_courses` for import into the Exams tab
- Rows with empty Meeting Days or Meeting Times are skipped (online-only)
- Graduate courses → imported into the Graduate Courses list
- Undergraduate courses → grouped by course number, imported into Lab Sections via a checkbox modal
- `exam_courses` → deduplicated list of exams per undergrad course, importable into the Exams tab

## Default data

New/empty schedules start with one default role: `{id: "role-primary-ta", label: "Primary TA", se_value: 1.0}`.

`EMPTY_DATA` also initializes `exams: []` and `proctor_assignments: []`.

Manual TA assignments default to `locked: true`.

## Frontend utilities

- `gmailCopyBtn(tas)` — takes an array of TA objects, returns a "Copy e-mail addresses" button (or `null` if none have emails) that copies `Name <email>, ...` to the clipboard; used in Summary tab headings and Meeting Finder

## Key conventions

- IDs are generated client-side with `uid()` (random hex string)
- `EMPTY_DATA` in `ta_scheduler.py` defines the schema for a blank schedule
- Native file dialogs use `_file_dialog()` via pywebview (`webview.FileDialog`)
- `_get_meetings(item)` in the solver returns all `(day, start_min, end_min)` tuples for an item, falling back to the top-level fields for legacy entries without a `meetings` array
