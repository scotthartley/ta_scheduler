# TA Scheduler

A single-user desktop web app for scheduling graduate teaching assistants (TAs) across lab sections. Runs entirely locally — no cloud, no database, no build step.

> **Note:** This README was written by [Claude Code](https://claude.ai/claude-code), Anthropic's AI coding assistant, which also contributed substantially to the codebase.

## Features

- **Visual weekly grid** — drag to draw, resize, and move time blocks for courses, labs, and TA commitments (7 AM – 7 PM, Mon–Fri)
- **Automatic solver** — assigns TAs to lab roles while respecting section equivalent (SE) caps, availability, and scheduling conflicts; locked manual assignments are always preserved
- **CSV import** — paste in a department course export to bulk-import graduate courses and lab sections, including multi-day meetings (MWF, TR, etc.)
- **Conflict-override assignment** — manually force-assign a TA despite a conflict, with the reason clearly shown
- **DOCX export** — generate a formatted schedule document
- **Roles system** — define custom TA role types (e.g. Primary TA, Grader) with configurable SE values and experience preferences
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

Opens at [http://localhost:5050](http://localhost:5050). (Port 5050 is used because macOS AirPlay Receiver occupies 5000.)

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
| **Graduate Courses** | Define grad courses that TAs may be enrolled in |
| **TAs** | Define TAs, their experience level, SE cap, grad courses, and other commitments |
| **Schedule** | Run the solver, view/edit assignments, export DOCX |
| **Meeting Finder** | Find times when most TAs are free |

### Typical workflow

1. **Import CSV** (Lab Sections or Graduate Courses tab) — import your department's course export to populate labs and grad courses automatically
2. **Add TAs** — enter each TA's name, experience, max SE, enrolled grad courses, and any other time commitments
3. **Configure roles** — use the **Roles** button to define role types and set counts/experience preferences on each lab
4. **Run solver** — go to the Schedule tab and click **Assign TAs**
5. **Adjust manually** — lock, override, or tweak assignments as needed
6. **Export** — download a formatted DOCX

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
├── ta_scheduler.py             # Flask backend, greedy solver, DOCX export, CSV import
├── static/
│   └── index.html     # Entire frontend (vanilla JS/CSS/HTML, no build tools)
├── requirements.txt
└── CourseExport.csv   # Sample department course export for CSV import testing
```

## Data format

Schedules are stored as plain JSON. The schema:

```
roles:        [{id, label, se_value}]
grad_courses: [{id, name, day, start_min, end_min, meetings?, exams?}]
labs:         [{id, name, day, start_min, end_min, meetings?, exams?, roles[]}]
tas:          [{id, name, experience, max_se, grad_course_ids[], outside_duties[], other_commitments[]}]
assignments:  [{lab_id, role_id, ta_id, locked}]
```

- `day`: 0 = Mon … 4 = Fri
- `start_min` / `end_min`: minutes since midnight (e.g. 540 = 9:00 AM)
- `experience`: `"experienced"` or `"inexperienced"`
- `se_value`: section equivalent (SE) units — a float representing workload (e.g. 1.0 = one full lab section)

## Solver details

The solver is a greedy algorithm with a fail-first heuristic (no external dependencies). It enforces these hard constraints:

1. **Role count** — assignments per role ≤ configured count
2. **SE cap** — total SE assigned to a TA ≤ their `max_se` (including outside duties)
3. **No double-booking** — a TA cannot be assigned to two labs with overlapping meeting times
4. **Availability** — a TA cannot be assigned to a lab that conflicts with their grad courses or other commitments

Slots with the fewest eligible TAs are filled first. The scoring function maximizes filled slots (weight 1000), prefers experience-matched TAs (+1), penalizes split assignments across courses (-200), penalizes already-loaded TAs (current SE × -500) to spread load evenly, and breaks ties randomly.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
