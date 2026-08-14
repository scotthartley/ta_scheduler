# TA Scheduler — Claude Instructions

## Project overview

A single-user desktop web app (macOS) for scheduling graduate teaching assistants across lab sections. The backend serves the frontend and runs the solver; there is no separate database or build step.

## Running the app

```bash
cd /Users/hartlecs/Coding/productivity/ta_scheduler
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
labs:               [{id, name, section, day, start_min, end_min, meetings?, date_meetings?, exams?, date_start?, date_end?, roles[]}]
                    date_meetings[]: [{date, start_min, end_min, label?}]
                    roles[]: [{role_id, count, preferred_experienced}]
tas:                [{id, name, email?, experience, max_se, max_pe, grad_course_ids[], outside_duties[],
                      outside_proctoring[], other_commitments[], date_conflicts[], schedule_complete?}]
assignments:        [{lab_id, role_id, ta_id, locked}]
exams:              [{id, name, course_name, section, date, start_min, end_min, tbd, time_tbd, proctor_count, pe_value}]
proctor_assignments: [{exam_id, ta_id, locked}]
```

- `day`: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
- `start_min` / `end_min`: minutes since midnight (e.g. 540 = 9:00 AM)
- `meetings`: optional array of `{day, start_min, end_min}` — present on multi-day entries (e.g. MWF); `day`/`start_min`/`end_min` at the top level always hold the first meeting for backward compatibility
- `date_meetings`: optional array of `{date, start_min, end_min, label?}` on a `labs[]` entry — one-off, date-specific sessions, for work that happens only in certain weeks rather than every week (`date` is ISO `YYYY-MM-DD`, matching `exams[].date`). Absent on every pre-existing record; there is no migration pass, so every reader goes through `_get_date_meetings()` / `getDateMeetings()` at point of use, matching the `date_conflicts[]` convention. An entry may have weekly `meetings[]`, `date_meetings[]`, or both; a **date-only assignment** has `meetings: []` and `day: null` (the state `syncTopLevel()` already produces once the last weekly meeting is deleted). `label` is an optional per-session name ("IR training"); it is **display-only** — the solvers never read it. Blank/absent means "use the assignment's own name", which is what the grid block and the lists fall back to. Not to be confused with `labs[].exams[]`, which CSV import populates with exam *sittings* that also feed the Exams tab as proctoring targets — that array is inert as far as lab meetings are concerned, and treating it as one would double-count.
- `experience`: `"experienced"` | `"inexperienced"`
- `se_value`: SE (service equivalent) units as a float (e.g. 1.0, 0.5)
- `pe_value`: PE (proctoring equivalent) units as a float
- `max_pe`: maximum PE a TA can be assigned (default 2.0)
- `outside_proctoring[]`: `[{label, pe_value}]` — external proctoring duties counted toward max_pe
- `other_commitments[]`: `[{label, day, start_min, end_min}]` — recurring weekly blocks
- `date_conflicts[]`: `[{label, start_date, end_date, start_min, end_min, ignore_for_labs}]` — a block spanning `start_date`/`start_min` to `end_date`/`end_min` (equal dates for the common single-day case). Always a hard constraint for the proctoring solver; also a hard constraint for the lab solver unless `ignore_for_labs` is set on that entry (see "Solver (greedy — lab scheduling)"). Legacy entries may still use the old singular `date` field instead of `start_date`/`end_date` — there is no migration pass, so every reader falls back to `date` at point of use (`start_date = dc.get('start_date') or dc.get('date')`, etc.), matching the rest of this codebase's convention of defensive per-field reads rather than upfront normalization.
- `tbd`: if true, the exam has no date/time yet. It is still built into the proctoring solver's slot list and diagnostics, exactly like any other exam — only the PE cap applies to it; with no date at all, it's exempt from every other check, in both directions (it is never blocked by another assignment, and its own assignment never blocks anything else).
- `time_tbd`: if true, the exam has a confirmed `date` but no fixed `start_min`/`end_min` yet. Like `tbd`, it's scheduled and diagnosed like any other exam with only the PE cap enforced — it's exempt from double-booking and every weekday/lab/grad-course/commitment check — but because its date *is* known, it's still checked against a TA's `date_conflicts[]` for whole-day blocks (a multi-day conflict's interior days, never a boundary day's partial-time window, since the exam might still land outside that window once its time is set).

## Grid

- Hours displayed: 7:00 AM – 7:00 PM (`GRID_START = 420`, `GRID_END = 1140`)
- `HOUR_H = 75` px per hour; `PX_PER_MIN = GRID_H / GRID_MINS` (= 1.25 px/min)
- Time snaps to 5-minute increments
- The **main schedule grid** (Assignments, Graduate Courses, TAs tabs) uses pixel-based positioning via `minToY()` / `yToMin()`
- On the Assignments tab the grid also paints `date_meetings[]` as `.block-labdate` (dashed green), on the weekday of each date, **deduplicated by `(weekday, start, end, label)`** so a four-week series is one block labelled `"… · 4 dates"` rather than four identical blocks fanned into lanes by `layoutOverlaps()`, while two differently-named sessions in the same slot stay separate blocks. The block shows the session's own `label` when it has one, falling back to `displayName(item)`; its `title` is the name plus the full date list. These blocks are `editable: false` and carry **no `eraseType`/`commitIndex`** — those are positional indices into `meetings[]` consumed by `applyBlockChange()` / `eraseBlock()`, and leaving them off keeps that coupling untouched. Deletion happens in the Specific Dates list's Edit form. Weekdays outside 0–4 simply don't render.
- **Meeting Finder is deliberately weekday-only** (`markAll`) — it searches for a recurring weekly slot, and projecting a one-off date onto every week of the term would over-block the heatmap.
- The **Meeting Finder grid** uses percentage-based positioning so it scales to fill the available panel height without scrolling; cells and hour lines are positioned as `(offset / GRID_MINS) * 100 + '%'`

## Tab order (left to right)

Assignments | Exams | TAs | Graduate Courses | Schedule Labs | Schedule Proctoring | Summary | Meeting Finder

"Assignments" is UI text only — the JSON key is still `labs`, and so are every function name (`renderLabForm`, `duplicateLab`, …) and the docx export's "Lab Assignments" heading. An entry there is a lab section or any other duty a TA is assigned to.

## Solver (greedy — lab scheduling)

Hard constraints (eligibility filters):
1. Role count: assignments per role ≤ configured count
2. SE cap: total SE assigned to a TA ≤ their max_se (including outside duties)
3. No double-booking: a TA cannot hold two labs that clash. Precomputed once into `lab_conflicts` (`lab_id → frozenset` of clashing lab ids), so `double_booked()` is a set-membership test rather than a nested scan. Pairwise rule:
   - **weekly × weekly** — same weekday + time overlap. Deliberately does *not* consult date ranges, preserving the conservative behavior that predates `date_meetings[]`.
   - **weekly × dated** — the dated meeting's weekday matches the weekly meeting's day, times overlap, and the dated meeting's date falls inside the weekly lab's `date_start`/`date_end` (an absent bound never excludes).
   - **dated × dated** — same *date* + time overlap. This exactness is what stops two one-off sessions on the same weekday but different dates from being falsely reported as double-booked.
4. Availability: a TA cannot be assigned to a lab that conflicts with any of their grad course meetings or other commitments. `ta_fixed_times` entries are `(day, start, end, date_start, date_end)` — the trailing range is the grad course's own (`None, None` for `other_commitments`, which recur all term). Weekly lab meetings are matched by weekday and ignore the range; a `date_meetings[]` session additionally requires its date to fall inside it.
5. `date_conflicts[]`: evaluated per (TA, lab) pair, not folded into the flat, lab-agnostic fixed-times list — a conflict's effect on a given lab depends on that lab's own `date_start`/`date_end`. The conflict's date span is clamped to the lab's `date_start`/`date_end` (when present) before being expanded into weekday+time windows checked against that lab's meetings; if the lab has no date range set, the check falls back to the conflict's own unclamped span. Entries with `ignore_for_labs` are skipped entirely for this check. Because the app has no per-occurrence lab-assignment model, a lab that's actively meeting on the conflicting weekday within the (clamped) window is blocked entirely, not just for the specific date(s) within the conflict — the residual imprecision the `ignore_for_labs` toggle exists to work around. A `date_meetings[]` session *has* a real date, so it skips all of that and goes straight through `_date_conflict_overlaps(dc, date_obj, s, e)` — the exact-date test, no weekday collapsing and no clamping. That path is strictly more precise and is the one case where `ignore_for_labs` should not be needed.

Scoring (higher is better), with all magnitudes as **user-configurable
weights** — defaults live in `_DEFAULT_SETTINGS` in `ta_scheduler.py`, the
single source of truth (mirrored in `DEFAULT_SETTINGS` in
`static/index.html`), and are overridden per-schedule by `data["settings"]`,
edited via the Preferences (⚙) modal. `_SOLVER_ITERATIONS` and `_BASE_SCORE`
are the exceptions: iteration count is a performance/quality tradeoff, not a
scoring weight, and the base score is a constant offset added identically to
every candidate for a slot, so it never affects ranking — neither is
user-configurable.

- `_BASE_SCORE` 1000 (fixed, not configurable)
- `+ experience_bonus` (default 200) — role has `preferred_experienced` and the TA is experienced
- `− new_role_penalty × (1 + roles already held)` — default 800 per new (TA, role) pairing.
  Charged whenever the role is not already in `st["roles"][ta_id]`, **including a
  TA's first role**: that is what lets a TA already in a role outrank an idle one.
  Scaling by roles already held makes the objective "minimize the total number of
  distinct (TA, role) pairings" rather than a binary one-vs-many flag.
- `− load_balance_weight × current SE` — default 500
- `+ random tiebreak`

The rest of this section describes the relationship between the *default*
values; it changes if the user edits their weights via Preferences.

800 is deliberately above one load unit (500) so continuing a role beats an idle
rival, and below two so a TA near their cap still yields. Concentration therefore
outranks load balancing: loads come out lumpier (slack pools in one or two TAs)
in exchange for near-zero split TAs. `new_role_penalty = 400` is the moderate
setting if that ever feels too aggressive.

The break-even between the two is `new_role_penalty / load_balance_weight` =
**1.6 SE** at the defaults: past that load, an idle TA outscores a TA who already
holds the role, so a role's last seats can land on a fresh person even when an
existing holder is still under their cap. That is the intended "near-cap TAs
yield" behavior, but it is also the first thing to check when a role looks more
scattered than expected.

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
3. No conflict with assigned lab meetings. Weekly meetings are matched exam-weekday vs. lab-weekday, gated on `_date_in_range(exam.date, lab.date_start, lab.date_end)` — an exam outside the lab's active term does not block. One-off `date_meetings[]` sessions are matched on the exact date instead (`ta_lab_dates`, checked next to the `date_conflicts` block since it needs the parsed exam date rather than the weekday, which also puts it below the `time_tbd`/`tbd` early returns that must exempt it).
4. No conflict with grad course regular meetings (weekday) or grad course exams (date-specific)
5. No conflict with other_commitments (weekday)
6. No conflict with the TA's `date_conflicts[]` (date-specific) — an interval-overlap test against the exam's exact date: the conflict's first day contributes from `start_min`, its last day up to `end_min`, and any days between are treated as full days. Always enforced regardless of `ignore_for_labs` (that flag only ever narrows the lab-side check)

`tbd` exams (no date at all) and `time_tbd` exams (date known, time flexible) are both scheduled and diagnosed like any other exam — the PE cap (1) always applies — but are exempt from constraints 2–6, since none of them can be evaluated without a fixed time. The one exception: a `time_tbd` exam's known date is still checked against constraint 6, but only for a `date_conflicts[]` entry that blocks the TA's *entire* day (a multi-day conflict's interior days) — never a boundary day, whose partial-time window the exam might still fall outside once its actual time is set. A `tbd` exam has no date to check against constraint 6 at all.

Scoring (higher is better): base 1000 (fixed, not configurable), then — again as
**user-configurable weights**, defaulted from `_DEFAULT_SETTINGS` and overridden
by `data["settings"]`:

- + lab_familiarity_bonus (default 300) — TA is assigned a lab for the same course
- + lab_section_bonus (default 150) — TA is assigned the lab for that same course *and* section
- − `new_course_penalty × (1 + courses already proctored)` — default 1600 per new
  (TA, course) pairing, charged whenever the exam's course is not already in
  `st["courses"][ta_id]`, **including a TA's first course**. The exact twin of
  the lab solver's `new_role_penalty`, and adopted for the same reason: it
  replaced a flat `same_course_proctor_bonus` (200) that could never actually
  concentrate anything, because it paid the incumbent a fixed amount while
  `proc_load_balance_weight` charged that same incumbent 500 for *every* PE they
  already carried. Break-even against an idle rival was one third of a PE unit;
  a TA one 1.0-PE exam ahead already lost. Charging the newcomer instead — and
  scaling by courses already held — makes the objective "minimize the total
  number of distinct (TA, course) pairings", exactly as on the lab side.
- + same_section_proctor_bonus (default 100) — …for that same course and section
- − spread penalty — this TA already proctors another (non-`tbd`, non-`time_tbd`) exam within
  `spread_window_days` (default 7) days; scales linearly with closeness up to
  `spread_window_days × spread_penalty_per_day` (default 280 at same-day), capped
  below one load-balance PE unit (default 500) so it nudges rather than overrides,
  at the default values
- − load-balancing penalty (current PE × proc_load_balance_weight, default 500)
- + random tiebreak

`new_course_penalty / proc_load_balance_weight` = **3.2 PE** at the defaults, so
a TA already proctoring a course keeps winning its remaining exams until they are
3.2 PE ahead of an idle rival (6.4 for a rival already holding one course, which
is the usual case once a run is under way). 800 is the gentler setting. Note
`lab_familiarity_bonus` (300) is now far smaller than the opening cost, so it no
longer decides *whether* a course gets opened — only who opens it, among TAs the
load term has left level.

**Scoring cannot beat the slot ordering, and on a capacity-tight file the
ordering wins.** A course processed after the PE budget is spent cannot be
concentrated by any weight, because greedy has no lookahead and nothing reserves
capacity. On a file at ~92% of total PE capacity this is the dominant effect:
raising `new_course_penalty` from 1600 to 10000 changed the outcome for a
late-processed course not at all — it was the course-block ordering below that
moved it. Reach for capacity or ordering there, not weights.

Also runs up to 50 iterations, keeping the best result. It gets similar hoisting
treatment to the lab solver: `exam_wd`, the `static_conflicts` frozenset of
`(ta_id, exam_id)` pairs, and each exam's `eligible_count` (from locked-only
state) are all computed once. `exam_date_obj` (each exam's parsed
`datetime.date`, or `None`) is hoisted the same way and covers every exam — not
just slot exams — since locked assignments seed `st["times"]` from exams that
may be fully locked and absent from the slot list. Slot *order* is deliberately
not hoisted — `_greedy_pass()` re-sorts `slots` on each call, in **course
blocks, fail-first within each block**:

```
(course_order[course_name],           # drawn fresh per pass
 eligible_count - proctor_count, -pe_value, random.random())
```

Blocking by course is what lets `new_course_penalty` concentrate at all: once a
TA opens a course they are the cheap candidate for the rest of it, and keeping
those slots consecutive puts them in front of the solver while that TA's PE
headroom is still free. Interleaved, the penalty just watches capacity drain
into whichever course happened to be processed first.

The block order is **drawn per pass, not sorted**. Any fail-first rule ranks a
course by how constrained its exams are, which sends the loosest course —
single-proctor sittings with few conflicts, typically the make-ups — dead last,
every pass. Redrawing lets some of the 50 iterations hand that course an early
block, and best-of-50 keeps a draw that worked out. (Sorting blocks fail-first
was measured and behaves like no blocking at all, for exactly this reason.)

Within a block, fail-first is measured in **slack, not pool size**. An exam
needing `proctor_count` *distinct* TAs (a TA can't take two seats at the same
exam) consumes that many of its own candidates, so `eligible_count -
proctor_count` is what's left over once it is fully staffed: a 13-candidate/
8-seat exam (slack 5) is harder than an 11-candidate/3-seat one (slack 8) and
must be placed first. This is what keeps `tbd`/`time_tbd` exams from starving —
their conflict exemptions give them the *largest* candidate pool (often every
TA), so a sort on raw `eligible_count` puts them last, past the point where
`proc_load_balance_weight` has fragmented everyone's remaining headroom into
sub-`pe_value` crumbs. A per-iteration `random.random()` alone cannot fix that:
it only shuffles *within* a tie group, and such an exam usually sits alone above
the pack rather than in one. `-pe_value` places the expensive seats while
headroom is still unfragmented.

The 50 iterations select on **unfilled count only**, stopping at the first
feasible pass — they buy feasibility, never quality. Selecting the
highest-*scoring* feasible pass instead was measured: it improves the global
objective (distinct (TA, course) pairings 23.0 → 21.1) but costs ~8× the
runtime and consistently overrides a user's locked assignment as a seed for
concentration, since the global optimum concentrates somewhere else. Left as-is
deliberately.

When the best of the 50 passes still leaves slots unfilled, each `unfilled`
diagnostics entry carries a `reason` string ("9 of 13 TAs at PE cap (needs 1.5
PE free), 1 proctoring an overlapping exam") tallied from the winning pass's
final state, which `_greedy_pass()` returns alongside its result.
`_rejection_reason()` re-uses `eligible_tas()`'s predicates in the same order —
each TA is counted under the first one that applies — so the explanation cannot
drift from the constraint that produced it.

## CSV import

The "Import Class Info" button (visible on the Assignments and Exams tabs) opens a file picker and parses a department course export CSV with these columns:

`Course Level, Subject, Number, Section, Title, Meeting Days, Meeting Times, Meeting Dates, Term`

- Multi-day sections (e.g. `MWF`) are stored as a single entry with a `meetings[]` array
- Each entry also includes `section`, `date_start`, and `date_end` from the Term/Meeting Dates columns
- Exam sessions (Meeting Dates start == end) are stored in `exams[]` on the course entry and also returned as `exam_courses` for import into the Exams tab
- Rows with empty Meeting Days or Meeting Times are skipped (online-only)
- Graduate courses → imported into the Graduate Courses list
- Undergraduate courses → grouped by course number, imported into Assignments via a checkbox modal
- `exam_courses` → deduplicated list of exams per undergrad course, importable into the Exams tab

## Default data

New/empty schedules start with no roles (`roles: []`) — per-course roles are
auto-created the first time a lab's name is set (see "Roles" below).

`EMPTY_DATA` also initializes `exams: []` and `proctor_assignments: []`.
`load_data()` returns a `copy.deepcopy` of it, so callers can never mutate the module-level default.

Manual TA assignments default to `locked: true`.

## Roles

Role objects optionally carry a `course_name` field:

- **Present** — an auto-managed default role for that course (exact match on
  `lab.name`). Created/attached via `ensureCourseRole()` / `attachCourseRole()`
  when a lab's name field loses focus, on CSV import, and by the one-time
  `migrateCourseRoles()` migration that runs on file load for files created
  before this system existed. A lab's Role Requirements picker only shows a
  course role when it matches that lab's `name` exactly.
- **Absent** — a free-form "shared" role (e.g. "Instrumentation TA"), created
  via "+ Add Role" in the Roles modal, attachable to labs across multiple
  courses, and always shown in every lab's Role Requirements picker.

The lab solver's split penalty (`score()` in `solve()`) operates on `role_id`,
not course name: a TA is penalized for picking up a role they do not already
hold, not for spanning multiple courses in the *same* role. The charge applies
to a TA's **first** role as well, which is what makes concentration possible —
otherwise an idle TA is free to pull into a role, and every role fans out across
as many people as capacity allows. This is why every course needs its own default
role — without one, a "shared" Primary TA role reused everywhere would make the
penalty a no-op.

A shared role spanning multiple courses costs a TA nothing extra: `score()` reads
only `role_id`, never the lab's course name. When a shared role still comes out
split across course lines, the cause is a hard constraint (overlapping lab times
between the courses, or the SE cap), not the scoring.

## Frontend utilities

**Extend these rather than writing a parallel copy** — the lab and proctoring sides
of every feature go through the same primitive.

Data accessors:
- `getMeetings(item)` — the only way to read an item's **weekly** meeting times. Returns `[{day, start_min, end_min}]`, preferring `meetings[]` and falling back to the legacy top-level fields. Mirrors the backend's `_get_meetings()`. It stays weekday-only on purpose — all nine call sites assume that shape.
- `getDateMeetings(item)` — the twin for one-off `date_meetings[]`, returning the raw entry objects in **raw order** so `inlineList()` removal indices stay valid. `sortedDateMeetings(item)` is the date-sorted copy every display path uses. Backend: `_date_meeting_rows()` yields `(date, start, end, label)`, and `_get_date_meetings()` is the solver's projection of it down to `(date, start, end)` — labels are display-only and are deliberately not threaded through the conflict checks.
- `dateMeetingWeekday(dm)` — the app's 0=Mon..4=Fri weekday for a dated meeting, or `null` if unparseable. Uses the established `new Date(iso + 'T00:00:00')` idiom; never `Date.parse()` of a bare ISO date, which parses as UTC.
- `dateInRange(dateStr, ds, de)` — true unless `dateStr` falls outside `[ds, de]`; an absent bound never excludes. ISO strings compared directly, exactly as the backend's `_date_in_range()` does, so the two cannot drift.
- `fmtMeetings(item, dayNames = DAYS)` — every weekly meeting formatted and joined (`"M 9:00 AM–10:15 AM, W 9:00 AM–10:15 AM"`), or `"—"`. Pass `DAY_SHORT` / `DAY_LONG` for longer forms. Backend twin: `fmt_meetings(item, day_names)`.
- `fmtDateMeetings(item, dayNames = DAY_SHORT)` — every dated meeting, date-sorted (`"Tue 9/15/2026 1:00 PM–5:00 PM (Setup), …"`), or `"—"`; the trailing `(label)` appears only for named sessions. Backend twin: `fmt_date_meetings(item)`. Because its output can now carry a user-typed name, `renderLabView`'s Day/Time cell runs it through `escHtml()` — the one `innerHTML` consumer of it.
- `fmtMeetingsAll(item, dayNames)` — weekly and dated joined with `·`, `"—"` if neither. **This is what every display call site uses** (`renderLabView`'s Day/Time column, `taAssignmentSummary()`, the Summary tab subtitle), so a date-only assignment never renders as a blank row. Twin of the combined string the docx export builds.
- `displayName(item)` — `"CHM 111 001"` from `{name, section}`.
- `examLabel(exam, fallback='—')` — `displayName` for exams (course + section).
- `examFullLabel(exam)` — `"CHM 111 001 — Midterm 1"`, degrading to whichever half exists.
- `examDateTimeLabel(exam)` — `"2026-03-05 9:00 AM–10:15 AM"`, `"2026-03-05 — Time TBD"` for `time_tbd`, or `"TBD"`.
- `dateConflictSpan(dc)` / `expandDateConflictWeekdays(dc, clampStart?, clampEnd?)` / `dateConflictOverlapsDate(dc, dateStr, startMin, endMin)` / `dateConflictLabel(dc)` — the frontend twins of the backend's `_date_conflict_days()` / `_expand_date_conflict_weekdays()` / `_date_conflict_overlaps()` helpers, operating on `date_conflicts[]` entries. `dateConflictLabel(dc)` renders `"2026-03-05 3:00 PM–5:00 PM"` (single day) or `"2026-03-05 3:00 PM – 2026-03-07 9:00 PM"` (multi-day).

Rendering primitives:
- `buildTable(headers, rows, totalRows)` — the one table builder; emits `.data-table` inside a `.data-table-wrap`. A cell may be a string, a DOM node, or an array of nodes, so tables with live inputs and chips go through it too. The last `totalRows` rows get `.summary-total`.
- `inlineList(items, {empty, footer})` — the one row-list builder; emits an `.ilist` grouped inset list. `items` is `[{cells, onRemove, removeTitle}]`, where a cell is a string (wrapped in `.il-label`) or a DOM node, so lists with live inputs go through it too. `footer` is a node or array of nodes rendered as the group's last row — every add-action lives there rather than in a card of its own. Used by Meeting Times, course exams, Other Commitments, Date-Specific Conflicts, Role Requirements and both Roles-panel groups.
- `renderAssignGrid(container, cfg)` — the TA × slot matrix behind both Grid views. `cfg` supplies `columns`, `conflictFn`, `findAssignment`, `onAdd`, `onRemove`, `onToggleLock`.
- `renderTASummaryTable(container, headers, rowFn)` — the "TA Summary" table under both schedule tabs.
- `renderLoadSection(which)` / `openAddLoadModal(which)` — Outside Duties (SE) and Outside Proctoring (PE), driven by the `LOAD_SECTIONS` config.
- `openDateMeetingForm(item, mode, listEl, index?)` — the one inline form behind **+ Add Date** (`mode: 'single'`), **+ Add Weekly Series** (`mode: 'series'`) and each row's **Edit** in the Assignments form's Specific Dates section, following `openDcForm()`'s toggle-off/`insertAdjacentElement('afterend')` pattern (the toggle key is `dataset.dmTarget`, `mode + ':' + index`, so two different rows' Edit forms replace rather than toggle each other). `index` is null when adding, otherwise the `date_meetings[]` position being edited — always `mode: 'single'`, and the form grows Save/Delete instead of Add. The form's first field is the optional session name; a series applies the same name to every row it generates, and the name is part of the duplicate test so two sessions differing only in name are distinct. Rows therefore carry no `×`; deletion lives in the edit form, matching Date-Specific Conflicts. A series walks the date range day by day and pushes one ordinary `date_meetings[]` row per matching weekday, skipping exact duplicates — the result is ordinary rows, with no second meeting concept anywhere downstream.
- `openAssignPicker(cfg)` — the assign-a-TA modal for both lab roles and exam proctoring.
- `lockBadge(locked, onToggle?)` — the only 🔒/🔓 renderer. Interactive when given `onToggle`, static otherwise (for cells whose parent already handles the click).
- `xBtn(onClick, title, extraCls?)` — the only delete affordance (`.btn-x`).
- `showWarnBox(div, html)` — shows/hides a `.warn-box` diagnostics panel.
- `gmailCopyBtn(tas)` — "Copy e-mail addresses" button (or `null` if no TA has an email) that copies `Name <email>, ...`; used in Summary headings and Meeting Finder.
- `mailtoBtn(tas, label, {alwaysShow})` — `mailto:` link that Bccs every TA with an email. Returns `null` when none do, unless `alwaysShow`, which instead renders it `.btn-disabled`. Must set `target="_blank"`: pywebview's WKWebView silently drops same-window `mailto:` navigation, and only new-window link activations reach the OS mail handler (`webview/platforms/cocoa.py`). Used on the TAs tab header and in Summary headings.
- `escHtml(s)` — required for anything user-named that reaches `innerHTML`.

Conflict detection (single source of truth, used by both the grids and the modals):
- `taLabConflictReasons(ta, lab, maps?)` and `taExamConflictReasons(ta, exam, maps?)` return human-readable reason strings. They deliberately **exclude** the SE/PE cap check, which the caller adds because only it knows the role. Pass `conflictMaps()` when calling in a loop. Both check `ta.date_conflicts[]` — the lab side skips entries with `ignore_for_labs` and clamps each conflict to the lab's own `date_start`/`date_end`; the exam side always enforces, no `ignore_for_labs` check.
  Both also handle `date_meetings[]`: `taLabConflictReasons()` re-runs all four sources (grad-course weekly meetings gated on `dateInRange`, grad-course `exams[]`, `other_commitments`, `date_conflicts[]`) against each dated session with exact-date tests, naming the date in the reason string; `taExamConflictReasons()` checks the exam's date against each assigned lab's dated sessions. They are the single source of truth for the assign-TA modals and both Grid views, so they are the only frontend place conflict logic changes.
  Neither checks lab-vs-lab double-booking — that constraint lives only in the solver.

## Styling

- All type goes through five tokens in `:root`: `--fs-xs` 11, `--fs-sm` 13, `--fs-base` 15, `--fs-lg` 17, `--fs-xl` 19. No literal `font-size` outside the print block.
- Colors go through the `:root` palette (`--blue-lt`/`--blue-dk`, `--green-lt`/`--green-dk`, `--amber-lt`/`--amber-dk`, `--purple-lt`/`--purple-dk`) and the warning set (`--warn-bg`, `--warn-border`, `--warn-text`, `--warn-text2`).
- All corners go through four radius tokens: `--r-sm` 4 (chips, small inline controls), `--r-md` 6 (the default — controls, buttons, cards, panels), `--r-lg` 12 (modals), `--r-pill` 999. No literal `border-radius` outside the print block, apart from `0` resets and `50%` circles.
- **One control base**: a single `:where(input:not([type=checkbox]):not([type=radio]), select, textarea)` rule right after `body` styles every text/number/date/time control in the app. It is wrapped in `:where()` on purpose — zero specificity, so `.data-table input`, `.ilist-row`'s quiet controls and `.form-group`'s `width: 100%` all override it without `!important`. The matching `:focus` rule is deliberately *not* wrapped, so the focus ring outranks them. Never add a second control base; extend this one.
- **One button base**: `.btn-sm, header button, .sched-controls button` share one rule, with `.sched-controls button` as the large-size modifier and `.btn-sm.btn-primary` / `.btn-sm.btn-danger` / `.btn-sm.btn-disabled` as variants. `.add-ta-btn` stays separate on purpose — it is a dashed ghost affordance inside grid cells, where a white shadowed button would be wrong. `.view-toggle button` must keep its `box-shadow: none`, or inactive segments inherit the drop shadow.
- **One row-list system**: `.ilist` (grouped inset list — one bordered container per group, hairline dividers, `.ilist-footer` for the add-action, `.ilist-empty` for the empty state) with `.il-label` / `.il-meta` / `.il-unit` / `.chip` as cell modifiers. It replaced the old `.sublist-item` and `.role-check-row` per-row cards. Controls inside `.ilist-row` are borderless at rest and reveal their border (and number spinners) on hover/focus, so the group frame is the only box. Build these through `inlineList()`, never by hand.
- One table system: `.data-table` inside `.data-table-wrap`, with `.lab-header` / `.ta-header` / `.summary-total` as row modifiers. The wrap uses `overflow-x: auto; overflow-y: hidden` — do not collapse those into the `overflow` shorthand, which resets the x-axis and kills horizontal scrolling. The static `.data-table-wrap`s around `#sched-table` / `#proctor-table` are the border for the hand-built tables in `renderLabView` / `renderProctorExamView` (which do *not* use `buildTable`), and `setViewMode()` toggles `.grid-mode` on them to drop that border in Grid view — don't remove them.
- One bordered surface: `.grid-outer, .meeting-grid-wrap, .cal-grid, .assign-grid-wrap, .data-table-wrap, .picker-list` share a single border+radius rule; each keeps only its own `overflow`. `.picker-list` is the one scrolling picker surface (import checklists and the assign-TA list).
- Workspace tabs are shown/hidden purely with the `.active` class (see `TAB_WORKSPACE`), never inline `style.display`.
- The Meeting Finder legend and heatmap are both driven by `HEAT_STOPS` / `heatColor()` so they cannot drift apart.

## Key conventions

- IDs are generated client-side with `uid()` (random hex string)
- `EMPTY_DATA` in `ta_scheduler.py` defines the schema for a blank schedule
- Native file dialogs use `_file_dialog()` via pywebview (`webview.FileDialog`)
- `_get_meetings(item)` in the solver returns all `(day, start_min, end_min)` tuples for an item, falling back to the top-level fields for legacy entries without a `meetings` array
- `POST /api/data` returns 400 when no file is open; the frontend falls back to Save As
