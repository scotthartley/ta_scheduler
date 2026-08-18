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
roles:              [{id, label, se_value, course_name?, exempt_from_split?}]
grad_courses:       [{id, name, section, day, start_min, end_min, meetings?, exams?, date_start?, date_end?}]
labs:               [{id, name, section, day, start_min, end_min, meetings?, date_meetings?, exams?, date_start?, date_end?, roles[]}]
                    date_meetings[]: [{date, start_min, end_min, label?}]
                    roles[]: [{role_id, count, preferred_experienced}]
tas:                [{id, name, email?, experience, max_se, max_pe, grad_course_ids[],
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

Assignments | Exams | TAs | Graduate Courses | Schedule Assignments | Schedule Proctoring | Summary | Meeting Finder

"Assignments" is UI text only — the JSON key is still `labs`, and so are every function name (`renderLabForm`, `duplicateLab`, …) and the docx export's "Lab Assignments" heading. An entry there is a lab section or any other duty a TA is assigned to.

## Solver (greedy — lab scheduling)

Hard constraints (eligibility filters):
1. Role count: assignments per role ≤ configured count
2. SE cap: total SE assigned to a TA ≤ their max_se
3. No double-booking: a TA cannot hold two labs that clash. Precomputed once into `lab_conflicts` (`lab_id → frozenset` of clashing lab ids), so `double_booked()` is a set-membership test rather than a nested scan. Pairwise rule:
   - **weekly × weekly** — same weekday + time overlap. Deliberately does *not* consult date ranges, preserving the conservative behavior that predates `date_meetings[]`.
   - **weekly × dated** — the dated meeting's weekday matches the weekly meeting's day, times overlap, and the dated meeting's date falls inside the weekly lab's `date_start`/`date_end` (an absent bound never excludes).
   - **dated × dated** — same *date* + time overlap. This exactness is what stops two one-off sessions on the same weekday but different dates from being falsely reported as double-booked.
4. Availability: a TA cannot be assigned to a lab that conflicts with any of their grad course meetings or other commitments. `ta_fixed_times` entries are `(day, start, end, date_start, date_end)` — the trailing range is the grad course's own (`None, None` for `other_commitments`, which recur all term). Weekly lab meetings are matched by weekday and ignore the range; a `date_meetings[]` session additionally requires its date to fall inside it. A `date_meetings[]` session is also checked against the TA's grad courses' `exams[]` sittings by exact date (`ta_fixed_dates`); weekly lab meetings deliberately are **not** — a one-off exam should not block an entire weekly series.
5. `date_conflicts[]`: evaluated per (TA, lab) pair, not folded into the flat, lab-agnostic fixed-times list — a conflict's effect on a given lab depends on that lab's own `date_start`/`date_end`. The conflict's date span is clamped to the lab's `date_start`/`date_end` (when present) before being expanded into weekday+time windows checked against that lab's meetings; if the lab has no date range set, the check falls back to the conflict's own unclamped span. Entries with `ignore_for_labs` are skipped entirely for this check. Because the app has no per-occurrence lab-assignment model, a lab that's actively meeting on the conflicting weekday within the (clamped) window is blocked entirely, not just for the specific date(s) within the conflict — the residual imprecision the `ignore_for_labs` toggle exists to work around. A `date_meetings[]` session *has* a real date, so it skips all of that and goes straight through `_date_conflict_overlaps(dc, date_obj, s, e)` — the exact-date test, no weekday collapsing and no clamping. That path is strictly more precise and is the one case where `ignore_for_labs` should not be needed.

**Duties with no fixed meeting time** (grading, stockroom hours, …) are modelled
as ordinary meeting-less `labs[]` entries — `meetings: []`, `day: null`, no
`date_meetings[]` — whose SE comes from their role's `se_value`, like any other
assignment. There is no separate per-TA duty list. Such an entry is
unconstrained by hard constraints 3–5 *by construction*: every one of those
checks loops over the entry's meetings, so with none they can never fire, and
only the role count (1) and the SE cap (2) bind. The slot list is built purely
from `lab.roles[].count` minus locked seats and never consults meetings, so
duty seats are solver-fillable exactly like lab seats.

The solver's objectives, in priority order. The first is a **hard rule**
enforced by ranking + repair; the rest are weighted preferences:

1. **Load band** — every TA's *slack* (`max_se − used_se`) inside a shared
   1-SE window: loads balanced *relative to each TA's own cap* ("x to x+1 SE
   from max"), over TAs with `max_se > 0`, ε = 0.001. Unfilled seats still
   outrank it — an empty seat never buys balance — and when the band is
   unreachable the solver does best effort and reports the leftovers (see the
   `load_band` diagnostic below).
2. Few split (multi-role) TAs.
3. Split TAs get the lighter loads.
4. Per-role experienced-TA counts honored — the band outranks this one too:
   reaching it may trade an experienced seat away (see the tier-2 move in
   `_rebalance_loads()`), with the trade surfaced in `unfulfilled_experience`.

Scoring (higher is better), with all magnitudes as **user-configurable
weights** — defaults live in `_DEFAULT_SETTINGS` in `ta_scheduler.py`, the
single source of truth (mirrored in `DEFAULT_SETTINGS` in
`static/index.html`), and are overridden per-schedule by `data["settings"]`,
edited via the Preferences (⚙) modal. `_BASE_SCORE` is the exception: it's a
constant offset added identically to every candidate for a slot, so it never
affects ranking, and is not user-configurable. Iteration count (`solver_iterations`,
default 100) is also user-configurable via Preferences even though it's a
performance/quality tradeoff rather than a scoring weight — see below.

- `_BASE_SCORE` 1000 (fixed, not configurable)
- `+ experience_bonus` (default 200) — role has `preferred_experienced` and the TA is experienced
- `− new_role_penalty × (1 + roles already held)` — default 400 per new (TA, role) pairing.
  Charged whenever the role is not already in `st["roles"][ta_id]`, **including a
  TA's first role**: that is what lets a TA already in a role outrank an idle one.
  Scaling by roles already held makes the objective "minimize the total number of
  distinct (TA, role) pairings" rather than a binary one-vs-many flag.
  Roles flagged `exempt_from_split` are skipped here and are never added to
  `st["roles"]`, so they neither pay the charge nor inflate the multiplier for
  anyone else's next role (see "Roles").
- `+ slack × load_balance_weight` — default 500 per SE unit of remaining
  headroom (`max_se − current SE`). Balance is measured **relative to each TA's
  own cap**: with equal caps this is rank-identical to the old
  `− current SE × weight` form (the cap is a constant per-candidate offset), so
  the break-evens below are unchanged; with mixed caps it prefers the TA with
  more slack, which is what the load band wants.
- `+ random tiebreak`

(`split_load_weight`, a former surcharge on the load term for already-split
TAs, was **removed** — measured near-inert, because a TA usually splits on the
last course block placed, when no seats remain to withhold;
`_lighten_split_tas()` is what actually delivers objective 3. A stale
`split_load_weight` key may linger in old files' saved `settings` blobs; it is
merged in but never read.)

Every term here is a **scoring** term, never an eligibility filter. Only
`eligible_tas()` (role count, SE cap, double-booking, availability) can leave a
slot unfilled, so no weight — at any magnitude — can turn a fillable slot into an
unfilled one. A split TA who is the last candidate for a seat still takes it.

The rest of this section describes the relationship between the *default*
values; it changes if the user edits their weights via Preferences.

There are **two** break-evens against `load_balance_weight`, measured in the
slack *difference* between two candidates (with equal caps, their load
difference), and the second is the one that decides whether loads come out even:

- **First role** — `new_role_penalty / load_balance_weight` = **0.8 SE** at the
  defaults. Once an idle TA has that much more slack than a TA who already holds
  the role, the idle one outscores them, so a role's last seats can land on a
  fresh person even when an existing holder is still under their cap. That is
  the intended "near-cap TAs yield" behavior, and the first thing to check when
  a role looks more scattered than expected.
- **Second role** — doubled by the `1 + len(roles_held)` multiplier, so **1.6 SE**.
  A TA holding one role is only pulled into a second once they fall this far
  behind an idle rival. This is the number that has to stay *below* a typical
  `max_se`, or load balancing can never pull anyone into a second role at all and
  even loads become a matter of luck (see the note at the end of this section).

`new_role_penalty` was **800** until it was measured against a real file and
halved. At 800 the second-role break-even is 3.2 SE — above a typical `max_se` of
3, i.e. unreachable — and balance depended entirely on a lucky per-pass block
draw. The tradeoff is real and unchanged in direction: raising it concentrates
roles harder at the cost of lumpier loads (slack pools in one or two TAs), and
800 remains the setting to reach for when near-zero split TAs matters more than
even loads. But it should be a deliberate choice, not the default, because uneven
loads are what users notice and object to first.

The highest-scoring eligible TA is assigned to each slot. Slot *order* is
re-derived inside `_greedy_pass()` on every pass, in **course blocks (by
`lab["name"]`), fail-first within each block**:

```
(course_order[lab["name"]],           # drawn fresh per pass
 eligible_count[(lab_id, role_id)],   # hoisted; locked-only state
 -se_value, random.random())
```

This mirrors the proctoring solver's ordering, for the same reason: blocking by
course is what lets `new_role_penalty` concentrate at all, since a TA who has
opened a role is the cheap candidate for the rest of that course only while the
slots stay consecutive and that TA's SE headroom is still free. Without blocking
the key is dominated by candidate-pool size, which barely varies across a file's
labs (19–21 of 21 TAs on a representative file), so the order collapses to the
`labs[]` order — and the last course listed reaches the solver only after every
other course has drained the pool of un-split TAs. A one-section course at the
end of that list *must* then be staffed by TAs who already hold another role, and
no weight can undo it: greedy has no lookahead and nothing reserves capacity.
The block order is **drawn per pass, not sorted**, for the same reason as on the
proctoring side — any fail-first rule over blocks pins the loosest course last on
every pass.

`eligible_count` is per `(lab_id, role_id)`, measured once from locked-only
state; only the count is hoisted, not the order built from it.

The solver runs up to a configurable number of iterations (`solver_iterations`,
default 100) and keeps the best by

```
(unfilled seats, band excess, experienced-TA shortfall, slack imbalance, split TAs)
```

It formerly kept the fewest unfilled slots alone and **broke at the first pass
with zero unfilled**, which made the iterations dead weight on any file that is
not capacity-tight: the first pass fills every seat, the loop breaks, and the
remaining draws never run (measured — `solver_iterations` 1 vs 100 cost the same
single pass on a representative file, so raising the default 50 → 100 changed
nothing there). Ranking on real quality terms is what turns those draws into
quality, and the per-pass block order is what makes the draws differ.

**The term order is the priority order, and it is load-bearing:**

- **unfilled** — a pass that staffs more seats always wins, so no amount of
  quality can cost a seat.
- **band excess** — `round(max(0, max_slack − min_slack − 1.0), 3)` over TAs
  with `max_se > 0`, quantized to 3 decimals so float noise cannot split ties.
  This is the hard band rule, and it sits *above* the experience term
  deliberately: reaching the band may cost an experienced seat, the trade
  `_rebalance_loads()`'s tier-2 move enacts. The window is shared but its
  position x is free — no integer alignment, since 0.5-SE roles exist.
- **experienced-TA shortfall** — a staffing requirement the user typed per role.
  `exp_requirements` covers every requirement with `preferred_experienced > 0`,
  including ones whose slots are fully locked and generate no solver slot,
  because the `unfulfilled_experience` diagnostic counts those too. Without this
  term a pass that shorts a section by an experienced TA wins on the terms below
  — a real regression that ranking introduced, caught by `status` flipping
  `feasible` → `partial`.
- **slack imbalance** — `slack_ss`, the sum of squared slack over every TA with
  a positive cap, including the unassigned — fine balance beyond the band. With
  the seat total fixed (which it is, once `unfilled` ties), a sum of squares is
  minimised exactly when the slacks are equal, and it falls fastest by lifting
  the TA with the *most* slack — the least-loaded relative to their own cap.
- **split TAs** — concentration, as a last tiebreak among passes equal on
  everything above. Counted the way `renderTASummary()`'s `role-split` column
  counts it, so exempt roles are excluded.

**Imbalance must rank above splits.** Ranking splits first was a real regression
and is the trap to avoid re-introducing: the two objectives pull in opposite
directions whenever a course has a single section (see the note at the end of
this section), so ranking on splits picks, out of every draw, exactly the pass
that strands TAs on a token load. Worse, it is *silent* and it overrides the user
— someone who has already turned `new_role_penalty` down to rebalance gets their
balanced passes generated and then discarded, so the preference appears to do
nothing. Uneven loads are the thing users notice and object to first; splits are
a refinement on top.

Deliberately **not** the full score sum: this stays a feasibility-first ranking
over named quantities, so a user's locked assignments are never traded away for a
better global objective — the same tradeoff the proctoring solver documents
rejecting below.

There is no early exit from the loop: with `slack_ss` in the key there is no
"perfect" value to stop on, and a full 100 passes costs ~30 ms on a 53-seat file
(~300 ms at `solver_iterations = 1000`).

### The repair passes

The winning pass goes through two local-move repairs, in a fixed order:
`_rebalance_loads()` improves the slack multiset until the band holds (or no
legal move remains), then `_lighten_split_tas()` permutes loads *within* that
multiset so the split TAs end on the lighter ones — so rebalance must run
first. They share their bookkeeping: `_seat_state()` rebuilds per-TA
load/role/booking state from an assignment list, `_move_legal()` is the
static-conflict / lab-conflict / SE-cap check mirroring `eligible_tas()`, and
`_exp_cost()` is the experienced-shortfall delta of a proposed handoff. The two
driver loops stay separate on purpose — their move rules and invariants differ,
and merging them would obscure both.

### `_rebalance_loads()` — the band repair

Hands a non-locked seat from a low-slack TA to a TA whose slack is **more than
one seat's SE larger** — exactly the condition for `slack_ss` to strictly
decrease (delta `−2·se_value·(gap − se_value)`) — repeating until no legal move
remains. This is the mechanism that actually enforces the hard band; the
ranking term above only selects the best available draw.

It exists because the band and the experience preferences can be **coupled in
every draw**. Measured on a real file after one experienced TA's `max_se`
dropped 3 → 2: of 1000 passes, *every* zero-shortfall pass left one TA
stranded on a token load, and *every* balanced pass shorted a section by 1–2
experienced TAs — the good pass simply isn't in the distribution, so no number
of iterations finds it. A local move decouples the objectives: on that file the
stranded TA was experienced, so taking a seat from an experienced full-load
donor restored the spread at zero cost to the experience counts.

Experience is handled in **two tiers**, because the band outranks the typed
experience preference:

- **Tier 1** (always preferred): the best move that does not raise any slot's
  experienced-TA shortfall (`_exp_cost() ≤ 0`).
- **Tier 2** (only when no tier-1 move exists *and* the slack spread still
  exceeds 1 + ε): the best move from the same search that *does* raise a
  shortfall — an experienced seat is traded to reach the band, and the trade
  surfaces in the `unfulfilled_experience` diagnostic. Every move still
  requires the strict `slack_ss` decrease, so termination is unchanged, and
  tier 2 can never fire once the band holds: experience is only ever traded to
  *reach* the band, never for polish beyond it.

Safety: the seat stays filled (`unfilled` unchanged), every eligibility check
mirrors `eligible_tas()`, and locked seats are never touched. Unlike the
lighten step, the receiver **may open a new pairing** — split count can rise,
which is the documented priority order (balance outranks concentration); among
equal-gap moves the candidate ranking still prefers a receiver already holding
the role and a donor shedding their last seat of it. Zero-SE seats are skipped
(moving one cannot change balance, and would break the termination argument).

On the coupled file this takes every seed from `{1×1, 2×8, 3×12}` to the
integer-optimal `{2×10, 3×11}` with zero experienced shortfall — a result no
single greedy pass produced — at the price of two extra split TAs, all of whom
end on the lighter 2-SE load after the lighten step below runs.

### `_lighten_split_tas()` — split TAs get the lighter loads

Runs **after** `_rebalance_loads()`. Hands seats from split TAs to
less-fragmented TAs who already hold the same role and have **exactly one
seat's SE more slack**. The goal is that if some TAs must be split, they should
be the ones carrying less work relative to their cap.

A greedy pass cannot arrange that itself: a TA becomes split on whichever
course block runs last, and by then there are no seats left to withhold from
them (this is why the old `split_load_weight` score surcharge was inert and got
removed). The measured result was the exact inverse of what is wanted: across
30 solves of the representative file, **every** split TA sat at the SE cap
(mean 3.00) while every TA on the lighter load held one role (mean 2.23). The
pass ranking cannot select the good case either, because the draws do not
contain it — of 3000 passes at optimal balance, 1522 put every split TA at the
cap, and the best of the remainder reached only a 2.75 mean.

The **exact-slack-swap** condition (`slack[receiver] − slack[donor] ==
se_value`, ε 0.001) is what makes this safe to run after ranking *and* after
the band repair: donor and receiver trade slacks, so the slack multiset — and
therefore both `band_excess` and `slack_ss`, the terms everything upstream was
selected on — is provably unchanged. Requiring the receiver to already hold the
role means no new pairing is opened, so split count cannot rise; a donor
reduced to one role lowers it. Every remaining check goes through
`_move_legal()` plus same-slot occupancy, so a repaired seat is one the solver
could have assigned in the first place, and locked assignments are skipped
outright. Unlike the band repair, this pass has no hard rule to reach, so it
never trades an experience preference — any move with `_exp_cost() > 0` is
rejected.

Termination: each move strictly lowers `Σ len(roles_held) × used_se`, because the
receiver is strictly less fragmented than the donor. The iteration cap is a
float-arithmetic backstop, not the mechanism.

On the representative file this takes the mean split-TA load from 3.00 to **2.06**
(mean single-role load 2.23 → 2.81) with load spread, split count, filled seats
and status all unchanged, and no measurable runtime cost.

### The `load_band` diagnostic

After both repairs, the final assignment is checked against the band over TAs
with `max_se > 0`. If the slack spread still exceeds 1 + ε, each TA whose slack
exceeds `min_slack + 1.0` is reported in `diagnostics["load_band"]` as
`{ta_name, assigned_se, max_se}` and `status` flips to `partial` — these are
the under-loaded TAs the band could not lift, because conflicts blocked their
remaining seats or too few seats exist. `renderSchedule()` renders them in the
warn box as "Load balance outside target band".

Locked assignments are always preserved; the solver fills remaining slots.

`random.random()` in `score()` and the per-pass block draw are the only things
that vary between iterations, so everything else is hoisted out of
`_greedy_pass()` and computed once: the `static_conflicts` frozenset of
`(ta_id, lab_id)` pairs, the `lab_meetings` map, `eligible_count`, and the
`experienced_tas` / `exp_requirements` inputs to the ranking. `initial_state()`
returns a fresh mutable state per pass. Changing what `eligible_tas()` reads means
re-checking whether it still belongs in the precomputed set.

**Weights cannot fix a shortage of un-split TAs.** When a course has a single
section, its seats need that many *distinct* TAs (a TA cannot hold two seats in
the same section), so a file can force splits arithmetically: with N TAs, a
one-section course needing S seats, and other courses needing at least T TAs at
their SE cap, `S + T > N` makes `S + T − N` splits unavoidable. Past that floor
`new_role_penalty` saturates — 800 → 5000 changed nothing on a representative
file.

**"No TA on a light load" and "few split TAs" are directly opposed** under a
one-section course, because its seat-holders can only take on more work by
crossing into another course — i.e. by splitting. Balance is the side users
care about, which is why the load band is a hard rule, the pass ranking puts
imbalance above splits, and `new_role_penalty` is the dial to reach for when
loads come out lumpy:

The number that matters is the **second-role break-even**,
`new_role_penalty × 2 / load_balance_weight` (see the two break-evens above), and
the rule is that it must stay **below a typical `max_se`**. Above it, a TA already
holding one role can never be pulled into a second by load balancing at *any*
load, so the light-load TAs are stranded no matter how many iterations run and
balance depends entirely on a lucky block draw. At the old 800 default it was
3.2 SE against a `max_se` of 3 — just over the line, which is exactly why this
looked like a solver bug rather than a tuning problem. At the current 400 it is
1.6 SE and balance is reliable.

Measured on the representative file (53 SE across 21 TAs, `max_se` 3): 400 hits
the integer-optimal spread — 10 TAs at 2 SE, 11 at 3, nobody below — on every seed
within the default 100 iterations (~30 ms), where 800 needs ~1000 iterations
(~300 ms) to reach the same place and otherwise strands a TA at 1 SE.

Note that **changing a default only affects files that have never opened
Preferences**: `savePreferences()` writes every `PREF_FIELD_IDS` key into
`data["settings"]` unconditionally, so one visit to the modal pins every value
against future default changes. Reset-to-defaults + Save in that modal is the
way to pick them up — and also the way a previously saved file sheds a removed
setting's stale key (e.g. `split_load_weight`).

## Solver (greedy — proctoring)

Endpoint: `/api/schedule-proctoring`

Hard constraints:
1. PE cap: total PE assigned to a TA ≤ their max_pe (including outside_proctoring)
2. No double-booking: a TA cannot proctor two exams with overlapping times on the same date
3. No conflict with assigned lab meetings. Weekly meetings are matched exam-weekday vs. lab-weekday, gated on `_date_in_range(exam.date, lab.date_start, lab.date_end)` — an exam outside the lab's active term does not block. One-off `date_meetings[]` sessions are matched on the exact date instead (`ta_lab_dates`, checked next to the `date_conflicts` block since it needs the parsed exam date rather than the weekday, which also puts it below the `time_tbd`/`tbd` early returns that must exempt it).
4. No conflict with grad course regular meetings (weekday, gated on the exam's date falling inside the course's `date_start`/`date_end` via `_date_in_range` — matching the assigned-lab check, so a finals-week exam isn't blocked by a course that has already ended) or grad course exams (date-specific)
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

Also runs up to a configurable number of iterations (default 100), keeping the best result. It gets similar hoisting
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
every pass. Redrawing lets some iterations hand that course an early
block, and best-of-N keeps a draw that worked out. (Sorting blocks fail-first
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

The iterations select on **unfilled count only**, stopping at the first
feasible pass — they buy feasibility, never quality. Selecting the
highest-*scoring* feasible pass instead was measured: it improves the global
objective (distinct (TA, course) pairings 23.0 → 21.1) but costs ~8× the
runtime and consistently overrides a user's locked assignment as a seed for
concentration, since the global optimum concentrates somewhere else. Left as-is
deliberately.

When the best of the passes still leaves slots unfilled, each `unfilled`
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

### `exempt_from_split`

A role may carry `exempt_from_split: true` — the "Allow split" checkbox in each
Roles panel row. It takes the role out of the concentration objective in **both**
directions: `score()` never charges `new_role_penalty` for it, and it is never
added to `st["roles"]`, so holding it does not raise the `1 + len(roles_held)`
multiplier that prices a TA's *other* roles. Only load balancing and the hard
constraints then decide who takes it. `renderTASummary()`'s `role-split` count
filters exempt roles out for the same reason — that column reports on the
objective, so it must not count something the objective ignores.

The flag lives on the **role**, not on the assignment or the role requirement,
because `score()` only ever sees `rr["role_id"]` against a flat set of role ids —
nothing about the lab reaches it. A per-requirement flag would make a TA's charge
depend on which seat greedy happened to fill first (exempt seat first → the role
is absent from the set → the later real seat is charged; other order → it isn't),
which is order-dependence the multi-pass best-of would surface as flapping. Since
`ensureCourseRole()` mints a 1:1 role per course name, flagging the role is
already per-duty control in practice.

Intended for meeting-less duty assignments (grading, stockroom hours) where
spreading the work across TAs is fine and concentration is not a goal. Absent on
every pre-existing role; read defensively (`r.get("exempt_from_split")`) rather
than migrated, matching the rest of this codebase.

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
- `inlineList(items, {empty, footer})` — the one row-list builder; emits an `.ilist` grouped inset list. `items` is `[{cells, subCells, onRemove, removeTitle}]`, where a cell is a string (wrapped in `.il-label`) or a DOM node, so lists with live inputs go through it too. `footer` is a node or array of nodes rendered as the group's last row — every add-action lives there rather than in a card of its own. Used by Meeting Times, course exams, Other Commitments, Date-Specific Conflicts, Role Requirements and both Roles-panel groups.
  - `subCells` is optional and makes the row **two lines** — `cells` (what the entry *is*) on top, `subCells` (how it behaves) beneath, wrapped in `.il-lines` / `.il-line`. The `×` is appended **inside line 1** rather than beside the stack, so it centres on the entry's name for free; as a sibling of `.il-lines` it would centre on the whole block and land in the gutter between the lines. Opt-in per item: an item without it takes the original flat path and produces byte-identical DOM, so the single-line lists are unaffected. Only the Roles panel uses it — a role's name, course chip, SE value and "Allow split" flag do not fit the 400px `.roles-panel` on one line.
  - Two alignment details are load-bearing and look wrong the moment they drift: line 2 is inset by `calc(var(--il-pad-x) + 1px)` to cancel the border+padding that indents line 1's leading text `<input>`, so both lines share a left edge (`--il-pad-x` is declared on `.ilist` and consumed by the quiet-control rule, so the two cannot disagree); and `.il-exempt` carries `padding-right` matching `.btn-x`'s side padding so its right edge lines up with the `×` glyph above rather than overshooting it.
- `renderAssignGrid(container, cfg)` — the TA × slot matrix behind both Grid views. `cfg` supplies `columns`, `conflictFn`, `findAssignment`, and — as **pure mutators, no `markDirty()` and no re-render** — `assign(ta, col)` / `unassign(ta, col)`, plus `refresh()` (`renderSchedule` / `renderProctoring`). The grid itself owns `markDirty()` + `cfg.refresh()` for every edit it makes, because a drag-and-drop swap performs up to four mutations and must produce a single re-render. There is no `onToggleLock`: `asgn.locked = !asgn.locked` was identical in both callers and the grid already holds `asgn`. `assign()` only ever pushes, so the grid pairs it with `unassign()` at the same coordinate first (`place()`) — the idempotence a swap needs.
  - **Drag and drop**: each `.cell-pill` is `draggable`, with the drag state in the module-level `_dragGridAssignment = {ta, col}` next to `_dragAssignment` / `_dragProctorAssignment`. Dropping on an **empty** cell moves the seat to that coordinate — same row = new lab/role or exam, different row = the seat transfers to that row's TA. Dropping on an **occupied** cell **swaps** the two: `{(srcTa,srcCol),(destTa,destCol)}` → `{(srcTa,destCol),(destTa,srcCol)}`. Trading the columns and trading the TAs give the same pair, which is what makes the swap unambiguous — and also what makes a swap sharing a row *or* a column with the source a no-op, so `dropTarget()` rejects those along with a drop on the source cell itself. Results are always `locked: true`, like every other manual grid edit. **Conflict cells accept drops**, highlighted amber instead of blue — matching the grid's existing click behavior, where an X cell is already clickable to assign.
  - The `dragover` / `dragleave` / `drop` listeners are **delegated on the `<table>`** (a full grid is hundreds of cells), resolving the cell via `e.target.closest('td.assign-cell')` against a `Map` of cell → `{ta, col, filled, conflict}` built in the body loop. `drop` reads and immediately nulls `_dragGridAssignment`, since the re-render destroys the pill and its `dragend` may never fire. The pill deliberately omits `renderLabView`'s `e.target !== chip` dragstart guard — the pill's area is mostly its `xBtn`/`lockBadge` children, and since neither is draggable the drag source is the pill either way.
  - `_gridDragJustEnded` (set by `gridDragEnded()`, cleared next tick) exists because the whole `<td>` carries a click handler that toggles the lock or assigns, and some browsers fire a click after a drop or an aborted drag. Both `td.onclick` handlers bail while it is set.
- `renderTASummaryTable(container, headers, rowFn)` — the "TA Summary" table under both schedule tabs.
- `renderLoadSection(which)` / `openAddLoadModal(which)` — Outside Proctoring (PE), driven by the `LOAD_SECTIONS` config. `LOAD_SECTIONS` holds a single entry today; it stays parameterised because the two-entry shape is what the renderer was written against.
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
- **One row-list system**: `.ilist` (grouped inset list — one bordered container per group, hairline dividers, `.ilist-footer` for the add-action, `.ilist-empty` for the empty state) with `.il-label` / `.il-meta` / `.il-unit` / `.il-exempt` / `.chip` as cell modifiers, and `.il-lines` / `.il-line` for two-line rows (see `inlineList`'s `subCells`). It replaced the old `.sublist-item` and `.role-check-row` per-row cards. Controls inside `.ilist-row` are borderless at rest and reveal their border (and number spinners) on hover/focus, so the group frame is the only box — **checkboxes are excluded** from that quieting, since they have no border or background of their own and blanking them hides the control. Build these through `inlineList()`, never by hand.
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
