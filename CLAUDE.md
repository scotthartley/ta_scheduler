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
├── pyproject.toml     ← dependency declarations (managed with uv)
├── uv.lock             ← locked dependency versions
└── CourseExport.csv   ← sample department course export used for CSV import
```

## Dependencies

Declared in `pyproject.toml`:

```
flask>=3.0.0
python-docx>=1.1.0
pywebview>=5.0.0
```

Install: `uv sync`

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
                      outside_proctoring[], other_commitments[], date_conflicts[]}]
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
- `other_commitments[]`: `[{label, day, start_min, end_min}]` — recurring weekly blocks
- `date_conflicts[]`: `[{label, date, start_min, end_min}]` — one-off blocks on a specific date; read by the proctoring solver
- `tbd`: if true, the exam has no date/time yet. It is skipped by the proctoring solver *and* by its diagnostics, so a TBD exam never reports the schedule as partial.

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

Only `random.random()` in `score()` varies between iterations, so everything else is
hoisted out of `_greedy_pass()` and computed once: the `static_conflicts` frozenset of
`(ta_id, lab_id)` pairs, the `lab_meetings` map, and `sorted_slots`. `initial_state()`
returns a fresh mutable state per pass. Changing what `eligible_tas()` reads means
re-checking whether it still belongs in the precomputed set.

## Solver (greedy — proctoring)

Endpoint: `/api/schedule-proctoring`

Hard constraints:
1. PE cap: total PE assigned to a TA ≤ their max_pe (including outside_proctoring)
2. No double-booking: a TA cannot proctor two exams with overlapping times on the same date
3. No conflict with assigned lab meetings (exam weekday vs. lab weekday)
4. No conflict with grad course regular meetings (weekday) or grad course exams (date-specific)
5. No conflict with other_commitments (weekday)
6. No conflict with the TA's `date_conflicts[]` (date-specific)
7. TBD exams (no date/time) are skipped

Scoring (higher is better): base 1000, then

- +300 lab familiarity — TA is assigned a lab for the same course
- +150 lab section — TA is assigned the lab for that same course *and* section
- +200 same-course proctoring — TA already proctors another exam for that course
- +100 same-section proctoring — …for that same course and section
- − load-balancing penalty (current PE × 500)
- + random tiebreak

Also runs up to 50 iterations, keeping the best result. It gets the same
hoisting treatment as the lab solver: `exam_wd`, the `static_conflicts` frozenset of
`(ta_id, exam_id)` pairs, and `sorted_slots` are all computed once.

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
`load_data()` returns a `copy.deepcopy` of it, so callers can never mutate the module-level default.

Manual TA assignments default to `locked: true`.

## Frontend utilities

**Extend these rather than writing a parallel copy** — the lab and proctoring sides
of every feature go through the same primitive.

Data accessors:
- `getMeetings(item)` — the only way to read an item's meeting times. Returns `[{day, start_min, end_min}]`, preferring `meetings[]` and falling back to the legacy top-level fields. Mirrors the backend's `_get_meetings()`.
- `fmtMeetings(item, dayNames = DAYS)` — every meeting formatted and joined (`"M 9:00 AM–10:15 AM, W 9:00 AM–10:15 AM"`), or `"—"`. Pass `DAY_SHORT` / `DAY_LONG` for longer forms. Backend twin: `fmt_meetings(item, day_names)`.
- `displayName(item)` — `"CHM 111 001"` from `{name, section}`.
- `examLabel(exam, fallback='—')` — `displayName` for exams (course + section).
- `examFullLabel(exam)` — `"CHM 111 001 — Midterm 1"`, degrading to whichever half exists.

Rendering primitives:
- `buildTable(headers, rows, totalRows)` — the one table builder; emits `.data-table` inside a `.data-table-wrap`. A cell may be a string, a DOM node, or an array of nodes, so tables with live inputs and chips go through it too. The last `totalRows` rows get `.summary-total`.
- `renderAssignGrid(container, cfg)` — the TA × slot matrix behind both Grid views. `cfg` supplies `columns`, `conflictFn`, `findAssignment`, `onAdd`, `onRemove`, `onToggleLock`.
- `renderTASummaryTable(container, headers, rowFn)` — the "TA Summary" table under both schedule tabs.
- `renderLoadSection(which)` / `openAddLoadModal(which)` — Outside Duties (SE) and Outside Proctoring (PE), driven by the `LOAD_SECTIONS` config.
- `openAssignPicker(cfg)` — the assign-a-TA modal for both lab roles and exam proctoring.
- `lockBadge(locked, onToggle?)` — the only 🔒/🔓 renderer. Interactive when given `onToggle`, static otherwise (for cells whose parent already handles the click).
- `xBtn(onClick, title, extraCls?)` — the only delete affordance (`.btn-x`).
- `showWarnBox(div, html)` — shows/hides a `.warn-box` diagnostics panel.
- `gmailCopyBtn(tas)` — "Copy e-mail addresses" button (or `null` if no TA has an email) that copies `Name <email>, ...`; used in Summary headings and Meeting Finder.
- `escHtml(s)` — required for anything user-named that reaches `innerHTML`.

Conflict detection (single source of truth, used by both the grids and the modals):
- `taLabConflictReasons(ta, lab, maps?)` and `taExamConflictReasons(ta, exam, maps?)` return human-readable reason strings. They deliberately **exclude** the SE/PE cap check, which the caller adds because only it knows the role. Pass `conflictMaps()` when calling in a loop.

## Styling

- All type goes through five tokens in `:root`: `--fs-xs` 11, `--fs-sm` 13, `--fs-base` 15, `--fs-lg` 17, `--fs-xl` 19. No literal `font-size` outside the print block.
- Colors go through the `:root` palette (`--blue-lt`/`--blue-dk`, `--green-lt`/`--green-dk`, `--amber-lt`/`--amber-dk`, `--purple-lt`/`--purple-dk`) and the warning set (`--warn-bg`, `--warn-border`, `--warn-text`, `--warn-text2`).
- One table system: `.data-table` inside `.data-table-wrap`, with `.lab-header` / `.ta-header` / `.summary-total` as row modifiers. The wrap uses `overflow-x: auto; overflow-y: hidden` — do not collapse those into the `overflow` shorthand, which resets the x-axis and kills horizontal scrolling.
- Workspace tabs are shown/hidden purely with the `.active` class (see `TAB_WORKSPACE`), never inline `style.display`.
- The Meeting Finder legend and heatmap are both driven by `HEAT_STOPS` / `heatColor()` so they cannot drift apart.

## Key conventions

- IDs are generated client-side with `uid()` (random hex string)
- `EMPTY_DATA` in `ta_scheduler.py` defines the schema for a blank schedule
- Native file dialogs use `_file_dialog()` via pywebview (`webview.FileDialog`)
- `_get_meetings(item)` in the solver returns all `(day, start_min, end_min)` tuples for an item, falling back to the top-level fields for legacy entries without a `meetings` array
- `POST /api/data` returns 400 when no file is open; the frontend falls back to Save As
