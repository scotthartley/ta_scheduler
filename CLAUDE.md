# TA Scheduler — Claude Instructions

## Project overview

A single-user desktop web app (macOS) for scheduling graduate teaching assistants across lab sections. The backend serves the frontend and runs the solver; there is no separate database or build step.

## Running the app

```bash
cd /Users/hartlecs/git_repos/ta_scheduler
python ta_scheduler.py
# Opens at http://localhost:5050
```

Port 5050 is used because macOS AirPlay Receiver occupies 5000.

## File structure

```
ta_scheduler/          ← repo root (flat, no subdirectories)
├── ta_scheduler.py             ← Flask backend + OR-Tools CP-SAT solver + python-docx export + CSV import
├── static/
│   └── index.html     ← entire frontend (vanilla JS, no build tools, no dependencies)
├── requirements.txt
└── CourseExport.csv   ← sample department course export used for CSV import
```

## Dependencies

```
flask>=3.0.0
ortools>=9.9.0
python-docx>=1.1.0
```

Install: `pip install -r requirements.txt`

## Architecture

**Backend (`ta_scheduler.py`):**
- Flask serves `static/index.html` and a JSON REST API
- All persistent data lives in a single `.json` file chosen by the user via macOS file dialogs (`osascript`)
- No data file is required to start; the app begins with empty in-memory state
- The CP-SAT solver runs synchronously on `/api/schedule`

**Frontend (`static/index.html`):**
- Single HTML file — all CSS, JS, and HTML in one file
- All runtime state lives in the `S` object; changes call `markDirty()` and are saved via Ctrl+S or the Save button
- No framework, no npm, no bundler

## Data model (JSON schema)

```
roles:        [{id, label, se_value}]
grad_courses: [{id, name, day, start_min, end_min, meetings?, exams?}]
labs:         [{id, name, day, start_min, end_min, meetings?, exams?, roles[]}]
              roles[]: [{role_id, count, preferred_experienced}]
tas:          [{id, name, experience, max_se, grad_course_ids[], outside_duties[], other_commitments[]}]
assignments:  [{lab_id, role_id, ta_id, locked}]
```

- `day`: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
- `start_min` / `end_min`: minutes since midnight (e.g. 540 = 9:00 AM)
- `meetings`: optional array of `{day, start_min, end_min}` — present on multi-day entries (e.g. MWF); `day`/`start_min`/`end_min` at the top level always hold the first meeting for backward compatibility
- `experience`: `"experienced"` | `"inexperienced"`
- `se_value`: SE (service equivalent) units as a float (e.g. 1.0, 0.5)

## Grid

- Hours displayed: 7:00 AM – 7:00 PM (`GRID_START = 420`, `GRID_END = 1140`)
- `HOUR_H = 80` px per hour; `PX_PER_MIN = HOUR_H / 60`
- Time snaps to 5-minute increments

## Tab order (left to right)

Lab Sections | Graduate Courses | TAs | Schedule | Meeting Finder

## Solver (CP-SAT)

Hard constraints:
1. Role count: assignments per role ≤ configured count
2. SE cap: total SE assigned to a TA ≤ their max_se (including outside duties)
3. No double-booking: a TA cannot be assigned to two labs whose meetings overlap on the same day (checks all meetings in `meetings[]`)
4. Availability: a TA cannot be assigned to a lab that conflicts with any of their grad course meetings or other commitments

Objective: maximize filled slots (weight 1000) + experience preference soft goal.

Locked assignments are always preserved; the solver fills remaining slots.

## CSV import

The "Import CSV" button (visible on Lab Sections and Graduate Courses tabs) opens a macOS file picker and parses a department course export CSV with these columns:

`Course Level, Subject, Number, Section, Title, Meeting Days, Meeting Times, Meeting Dates`

- Multi-day sections (e.g. `MWF`) are stored as a single entry with a `meetings[]` array
- Exam sessions (Meeting Dates start == end) are stored in `exams[]` and ignored by the solver
- Rows with empty Meeting Days or Meeting Times are skipped (online-only)
- Graduate courses → imported into the Graduate Courses list
- Undergraduate courses → grouped by course number, imported into Lab Sections via a checkbox modal

## Default data

New/empty schedules start with one default role: `{id: "role-primary-ta", label: "Primary TA", se_value: 1.0}`.

Manual TA assignments default to `locked: true`.

## Key conventions

- IDs are generated client-side with `uid()` (random hex string)
- `EMPTY_DATA` in `ta_scheduler.py` defines the schema for a blank schedule
- The `_osascript_dialog()` helper wraps all macOS file dialogs
- `_get_meetings(item)` in the solver returns all `(day, start_min, end_min)` tuples for an item, falling back to the top-level fields for legacy entries without a `meetings` array
