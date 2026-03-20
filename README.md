# TA Scheduler

A single-user desktop web app for scheduling graduate teaching assistants (TAs) across lab sections and exam proctoring. Runs entirely locally — no cloud, no database, no build step.

> **Note:** This README was written by [Claude Code](https://claude.ai/claude-code), Anthropic's AI coding assistant, which also contributed substantially to the codebase.

## Features

- **Visual weekly grid** — drag to draw, resize, and move time blocks for courses, labs, and TA commitments (7 AM – 7 PM, Mon–Fri)
- **Automatic lab solver** — assigns TAs to lab roles while respecting section equivalent (SE) caps, availability, and scheduling conflicts; locked manual assignments are always preserved
- **Automatic proctoring solver** — assigns TAs to exam proctoring slots while respecting PE caps and avoiding conflicts with labs, grad courses, and other commitments
- **CSV import** — paste in a department course export to bulk-import graduate courses, lab sections, and exam sessions, including multi-day meetings (MWF, TR, etc.)
- **Conflict-override assignment** — manually force-assign a TA despite a conflict, with the reason clearly shown
- **DOCX export** — generate a formatted schedule document
- **Roles system** — define custom TA role types (e.g. Primary TA, Grader) with configurable SE values and experience preferences
- **Summary tab** — read-only overview organized by lab, by exam, and by TA, with SE/PE totals and one-click email copying
- **Meeting Finder** — visualize collective TA availability across the week
- **Single JSON file** persistence — open and save schedule files via native file dialogs

## Requirements

- Python 3.9+
- macOS, Windows, or Linux (pywebview provides native file dialogs on all platforms)

## Installation

```bash
pip install -r requirements.txt
```

Dependencies:

| Package | Version |
|---|---|
| flask | ≥ 3.0.0 |
| python-docx | ≥ 1.1.0 |
| pywebview | ≥ 5.0.0 |

## Running

```bash
python ta_scheduler.py
```

Opens as a native desktop window via pywebview. If pywebview is unavailable, falls back to a browser at [http://localhost:5050](http://localhost:5050).

No data file is required to start — the app begins with empty in-memory state. Use **Open…** to load an existing schedule or **Save** / **Save As…** to persist your work.

## macOS app bundle

To build a self-contained `TA Scheduler.dmg` (no Python installation required):

```bash
pip install pyinstaller
brew install create-dmg
bash build.sh
```

The DMG is written to `dist/`. Drag **TA Scheduler.app** to `/Applications` to install.

> **Note:** The app is not code-signed. After installing, macOS may block it from launching. To remove the quarantine flag, run:
> ```bash
> xattr -cr "/Applications/TA Scheduler.app"
> ```

## Usage overview

### Tabs

| Tab | Purpose |
|---|---|
| **Lab Sections** | Define lab sections, their meeting times, and role requirements |
| **Exams** | Define exam sessions for proctoring, with date, time, PE value, and proctor count |
| **Graduate Courses** | Define grad courses that TAs may be enrolled in |
| **TAs** | Define TAs, their experience level, SE/PE caps, grad courses, and other commitments |
| **Schedule Labs** | Run the lab solver, view/edit assignments, export DOCX |
| **Schedule Proctoring** | Run the proctoring solver, view/edit proctor assignments |
| **Summary** | Read-only overview by lab, by exam, and by TA with SE/PE totals |
| **Meeting Finder** | Find times when most TAs are free |

### Typical workflow

1. **Import CSV** (Lab Sections or Exams tab) — import your department's course export to populate labs, grad courses, and exam sessions automatically
2. **Add TAs** — enter each TA's name, experience, max SE, max PE, enrolled grad courses, and any other time commitments
3. **Configure roles** — use the **Roles** button to define role types and set counts/experience preferences on each lab
4. **Run lab solver** — go to the Schedule Labs tab and click **Assign TAs**
5. **Run proctoring solver** — go to the Schedule Proctoring tab and click **Assign Proctors**
6. **Adjust manually** — lock, override, or tweak assignments as needed
7. **Review** — check the Summary tab for a consolidated view; export DOCX from Schedule Labs

### Grid interaction

- **Draw** — click and drag on an empty column to create a time block
- **Move** — drag an existing block to a new time or day
- **Resize** — drag the top or bottom handle of a block
- **Delete** — click the × on a block

### Conflict overrides

When assigning a TA manually, the assignment modal shows eligible TAs at the top and conflicted TAs (SE over cap, grad course overlap, or commitment overlap) below a divider with the reason listed. Clicking a conflicted TA force-assigns them with a locked assignment.

## File structure

```
ta_scheduler/
├── ta_scheduler.py             # Flask backend, greedy solvers, DOCX export, CSV import
├── static/
│   └── index.html     # Entire frontend (vanilla JS/CSS/HTML, no build tools)
├── requirements.txt
└── CourseExport.csv   # Sample department course export for CSV import testing
```

## Data format

Schedules are stored as plain JSON. The schema:

```
roles:               [{id, label, se_value}]
grad_courses:        [{id, name, section, day, start_min, end_min, meetings?, exams?, date_start?, date_end?}]
labs:                [{id, name, section, day, start_min, end_min, meetings?, exams?, date_start?, date_end?, roles[]}]
                     roles[]: [{role_id, count, preferred_experienced}]
tas:                 [{id, name, email?, experience, max_se, max_pe, grad_course_ids[],
                       outside_duties[], outside_proctoring[], other_commitments[]}]
assignments:         [{lab_id, role_id, ta_id, locked}]
exams:               [{id, name, course_name, section, date, start_min, end_min, tbd, proctor_count, pe_value}]
proctor_assignments: [{exam_id, ta_id, locked}]
```

- `day`: 0 = Mon … 4 = Fri
- `start_min` / `end_min`: minutes since midnight (e.g. 540 = 9:00 AM)
- `experience`: `"experienced"` or `"inexperienced"`
- `se_value`: section equivalent (SE) units — a float representing workload (e.g. 1.0 = one full lab section)
- `pe_value`: proctoring equivalent (PE) units
- `outside_proctoring`: `[{label, pe_value}]` — external proctoring duties counted toward `max_pe`
- `tbd`: if true, the exam has no date/time yet and is skipped by the proctoring solver

## Solver details

### Lab solver

The solver is a greedy algorithm with a fail-first heuristic (no external dependencies). It enforces these hard constraints:

1. **Role count** — assignments per role ≤ configured count
2. **SE cap** — total SE assigned to a TA ≤ their `max_se` (including outside duties)
3. **No double-booking** — a TA cannot be assigned to two labs with overlapping meeting times
4. **Availability** — a TA cannot be assigned to a lab that conflicts with their grad courses or other commitments

Slots with the fewest eligible TAs are filled first. The scoring function prefers experience-matched TAs (+200), penalizes split assignments across courses (−200), and penalizes already-loaded TAs (current SE × −500) to spread load evenly. The solver runs up to 50 random-tiebreak iterations and keeps the result with the fewest unfilled slots.

### Proctoring solver

Enforces these hard constraints:

1. **PE cap** — total PE assigned to a TA ≤ their `max_pe` (including outside proctoring)
2. **No double-booking** — a TA cannot proctor two exams with overlapping times on the same date
3. **No conflict with labs** — exam weekday must not conflict with any assigned lab meeting
4. **No conflict with grad courses** — neither regular meetings nor course-specific exams
5. **No conflict with other commitments**
6. **TBD exams are skipped**

Scoring gives a +300 bonus when the TA is assigned to a lab for the same course as the exam. Also runs up to 50 iterations.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
