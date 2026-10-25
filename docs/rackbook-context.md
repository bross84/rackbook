# Rackbook — Project Context

Source of truth for architecture, schema, domain terms, decisions and constraints.
Read this file at the start of every task. Do not proceed if it is missing. What is done and what is next lives in [`backlog.md`](backlog.md); `plan.md` is only a history log of the original 5/3/1 build.

Last brought up to date: 2026-10-16.

Optional fatigue trial (2026-10-23): disabled-by-default recording/reveal panel on `/log`, isolated `fatigue_trial_*` storage, a read-only Hevy Fatigue check-in bridge and offline backup/replay tools. Normal workout saving remains independent. Experimental v0 rules, APIs, local Docker setup and limitations: [fatigue-trial.md](fatigue-trial.md). Live homelab coverage and prospective validation require its data; available local copies were empty. This does not consolidate the apps.

Automatic trial recording (2026-10-24): when enabled, the log records each unstarted movement after 1.5 seconds without edits once soreness and planned reps/RPE/weight are available. No record button is needed. Snapshots remain immutable, unknown answers stay unknown, late recordings remain excluded, and failures never block logging. Enter scores and wait for the recorded status before lifting; see the trial guide for details.

Model trial dashboard (2026-10-24): `/trial` and read-only `GET /fatigue-trial/dashboard` show named movements, separate model/mode cohorts, categorical expected/actual history, frozen pre-workout scores and saved set details. All history is available; unsaved snapshots are separated and reveal no predictions. They do not start the review clock or dilute coverage; review begins six weeks after recording the first saved prospective observation. Newly completed records also freeze the actual representative set; older records display available local saved measurements. Shared Chart.js controls support date ranges, zoom and tap/keyboard inspection. No Hevy calls or trial-record edits are performed by the dashboard.

Trial controls location (2026-10-25): Settings (`/legacy#settings`) owns the Performance model trial toggle, compact history and dashboard link. Model trial is absent from shared navigation and the Log start screen. The Log still reads the server setting at startup and retains automatic recording, in-workout daily check-in display and saved results. The `/trial` route remains directly accessible.

---

## What this is now

Rackbook is a personal workout logger and strength tracker that saves to [Hevy](https://hevyapp.com). It started as a 5/3/1 BBB planner and has moved away from that: the main thing now is the **log page** (`/log`), which plans each set's weight from an RPE table and a per-movement base number, saves the finished workout to Hevy, and keeps its own record of every set. On top of that it builds **RPE tables for squat, bench and deadlift from the user's own sets** (`/rpe-charts`). The original 5/3/1 program designer still works at `/legacy` but is no longer developed.

One user (Brian), one Hevy account. The app has no login; it is meant to sit on a private network (Docker on a CasaOS homelab, reached over Tailscale with `tailscale serve`). It can write permanent workouts to the user's Hevy account, so treat every real save as irreversible.

### How it is used

The log sends original kg values plus its current `weight_unit` (kg/lb). Only in lb mode does the Hevy payload round: to the nearest whole pound, .5 rounding up, then converted back to kg for Hevy without further rounding. kg mode sends weights exactly as entered (2.5 kg steps etc.). Exact local set records and TS calculations retain original values. Older API clients omitting weight_unit retain their existing unrounded behavior. Movement planning still uses the configured increments.

Per-exercise units (2026-10-25): a unit chip beside each movement name selects Follow page, kg or lb. Nullable `exercise_refs.weight_unit` persists this choice by Hevy template ID; existing preferences migrate to null (Follow page). The override applies to weight input, reference column, rounding increments, automatic planning, warm-ups and plate loading. Entered/manual and completed weights keep their canonical kg values when switching; only unticked automatic plans re-round. New exercises and restored drafts retain the choice. Workout payloads optionally include `exercises[].weight_unit`, overriding the workout-level unit for Hevy rounding without changing exact local set/TS records. The top-level toggle remains the default for unpinned movements. e1RM/TM and Previous retain their existing lb conventions.

On desktop (a mouse/fine pointer), the log's RPE field accepts direct numeric entry, with an adjacent arrow for the existing popup picker. Touch devices retain the full-size picker button. Both use RPE 4–10 in steps of 0.5, or blank for unrated. Invalid typed input blocks ticking and saving until corrected; Enter finishes editing and Escape returns to the last accepted value. This changes only entry: unticked RPE plans the weight, and completed-set RPE records the actual effort without changing its weight. Run `node tests/test_log_rpe_entry.cjs` for the standalone frontend regression checks.

Touch weight/reps fields use `inputmode="none"` and a docked number pad with a fixed Backspace/Clear/Next/Done column. Decimal stays in place but is disabled for reps. A newly opened field selects its current value; edits use its selection and dispatch the usual input event, retaining planning and draft saving. Next advances weight → reps → next set's weight (not RPE); Done closes the pad without ticking or saving a set. The page scrolls the field above the pad and hides the bottom workout bar while it is open. Tapping elsewhere, Escape, or a workout redraw closes it. Mouse entry uses the ordinary keyboard, including on hybrid devices. RPE continues to use its existing picker on touch. Regression checks: `node tests/test_log_keypad.cjs`.

Brian lifts 3 days a week and logs on his phone in the gym. He works up to a single (a 1 @7 or 1 @8) on his primary squat and bench each session, marks it as the **TS**, and does back-off sets of 5 at lower RPEs. Day 1: squat, bench, Pendlay rows (plus a deadlift single). Day 2: a supplementary squat (a different Hevy exercise), press, stiff-legged deadlifts. Day 3: deadlift, bench, squat. The goal behind the RPE tables is a personal RPE chart per main lift that fills in over months from real sets.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI |
| Database | SQLite at `DB_PATH` (`/data/rackbook.db` inside Docker) — `sqlite3` stdlib, no ORM |
| Frontend | Vanilla JS, one HTML file per page, no bundler/build step; Progress uses locally bundled Chart.js and zoom scripts |
| HTTP client | `httpx` for Hevy API calls |
| Deployment | Docker + docker-compose on CasaOS homelab, port 8126 (8125 is reserved by the sibling service `hevy-fatigue`) |
| PWA | Desktop and mobile PWA (`static/manifest.webmanifest`, `static/sw.js`) |
| Tests | `python -m unittest discover -s tests -t .` (pytest is not installed). Also run on GitHub for every push |

---

## Pages and routes

The six main pages share an inline `rackbook-theme` style block for the blue/slate light/dark palette, cards, controls, page titles and navigation. Each includes the same seven destinations with `aria-current="page"` on the active page; the legacy/settings page keeps its existing navigation and theme selector with matching colors. Keep the common rules in step across pages. The log's additional rules retain the 900px landscape split layout, allow portrait tablets to use available width, and increase touch input heights. Existing hidden states, keyboard modes, scoring and saving behavior are unchanged. Browser theme colors and the PWA manifest follow the palette.

| Page | File | What it is |
|---|---|---|
| `/log` | `log.html` | The workout log. The main page. |
| `/microcycles` | `mesocycles.html` | Plan one week of workouts and load the flexible sequence into the log; `/mesocycles` remains an alias |
| `/recent` | `recent.html` | Latest Hevy workouts |
| `/progress` | `progress.html` | Each main lift's e1RM, 7-day bodyweight and DOTS-style score over time |
| `/stress` | `stress.html` | Main three movement overview, selector, stress components, rolling totals, and retrospective session history |
| `/trial` | `trial.html` | Model trial observations, expected/actual performance history, collection progress and unsaved snapshots |
| `/rpe-charts` | `rpe_charts.html` | RPE tables built from the user's own sets (Squat, Bench, Deadlift, General tabs) |
| `/legacy` | `index.html` | Settings only: Hevy API key, exercise cache sync, unit preference (the old 5/3/1 Workout and Program tabs were removed 2026-10-19; their backend routes remain) |
| `/health` | | `{"status":"ok"}` |

Routes used by the log, RPE and progress pages (the legacy planner has many more, see `main.py`):

| Route | Purpose |
|---|---|
| `POST /hevy/workouts` | Save a finished workout to Hevy, then record its TS rows and every set locally |
| `GET /hevy/workouts` | Recent workouts, summarised |
| `GET /hevy/exercise-state/{template_id}` | A movement's e1RM and previous sets, from its last Hevy session |
| `GET /training-max/{template_id}` | A movement's latest saved TS |
| `POST /movement-stress/{template_id}` | Read-only stress for checked `sets`, optional all-entered `preview_sets`, aligned per-set scores and Hevy/local history; never saves a workout |
| `GET /stress/movements` | Cached movements, identifying the main squat, bench and deadlift by the Progress titles |
| `GET /movement-stress/{template_id}/history?days=56` | Saved-session stress history and current rolling totals; days=0 means all available history |
| `GET/PUT /exercise-refs[/{template_id}]` | Per-movement settings |
| `GET /rpe-table` | The RPE table in use, as `[rpe, reps, fraction]` rows |
| `GET /rpe-observed`, `GET /rpe-observed/group/{lift}` | Grouped Squat/Bench/Deadlift counts and charts; Squat includes low-bar and paused high-bar |
| `GET /rpe-observed/{template_id}` | Existing exact-movement local chart retained for compatibility |
| `POST /rpe-history/import-bs-bridge` | Explicit chart-only import of assigned movements from BS-Bridge history; no Hevy writes |
| `GET /rpe-chart-assignments` | Shared movement assignments edited through the Microcycle Builder |
| `GET /progress/data?lift=` | A main lift's series for the Progress page |
| `GET /exercises`, `POST /exercises/sync` | The cached Hevy exercise list |
| `GET /settings`, `POST /settings/api-key` | Whether a Hevy key is set (never returns it), and saving it (204, empty body) |
| `GET/POST /api/mesocycles`, `GET/PUT /api/mesocycles/{id}` | List/create/read/update saved local plans with revision checking |
| `POST /api/mesocycles/{id}/activate`, `/archive` | Choose one active sequence; archival retains its document and completion history |
| `POST /body-weight/sync`, `GET /body-weight` | Daily body weight from Hevy |

---

## Key files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, routes and request/response models. Handlers stay thin; logic goes in the modules below |
| `database.py` | `init_db()`, schema DDL and `ALTER TABLE` migrations, `get_db()`, RPE table loading (`get_rpe_percentage`) |
| `hevy_client.py` | Hevy API client and encrypted API key storage |
| `workout_payload.py` | Pure: builds the body posted to Hevy, trimming an RPE Hevy can't store |
| `workout_view.py` | Pure: summarises Hevy workouts for `/recent` |
| `exercise_state.py` | Pure: a movement's e1RM and previous sets from Hevy history; `e1rm_lb` |
| `training_max.py` | The TS: building rows from a saved workout, `record`, `latest`, `history` |
| `refs_store.py` | Per-movement settings (`exercise_refs`) |
| `set_log.py` | The local record of every set (`logged_sets`), and the lookups the RPE page uses |
| `stress_index.py`, `stress_service.py` | Pure, versioned stress calculation and rolling windows; bounded 60-second Hevy history cache |
| `rpe_observed.py` | Pure: RPE table fit and estimates; separate strength reference per movement/workout |
| `rpe_history.py` | Scoped BS-Bridge history import, local-record precedence, chart sources and grouped chart services |
| `progress.py`, `strength_score.py`, `body_weight.py` | The Progress page; `LIFT_TITLES` in `progress.py` maps squat/bench/deadlift/press to Hevy exercise titles |
| `log.html` | The log page. All its CSS and JS are inline |
| `mesocycles.py`, `mesocycles.html` | Typed plan models, local storage/completion services, and self-contained mesocycle editor |
| `rpe_charts.html`, `progress.html`, `recent.html` | The other pages |
| `data/rpe_chart.csv`, `data/rpe_chart_user.csv` | The RPE table. The user's file wins when present; the table is loaded into `rpe_chart` at startup and reloaded when the file changes. Baked into the Docker image, so changing it means redeploying |
| `wave_math.py`, `program_parser.py`, `index.html` | The legacy 5/3/1 planner |
| `docker-compose.yml`, `Dockerfile` | Deployment |
| `requirements.txt` | Must stay in sync with all imports in `.py` files |

---

## Domain terms (as the app uses them)

- **Microcycle** — a flexible ordered series of workouts covering one week; no calendar dates or missed-day advancement. New plans start blank. Add day is always visible; Remove day can remove the final uncompleted day. Empty plans can be saved but cannot be activated. There is no week selector, Add week or Copy week control. Duplicate a microcycle for reuse with fresh session ids and no completion marks. The API enforces exactly one week per plan, retaining its existing `weeks` wrapper and mesocycle endpoint/table names for compatibility. Each session has a stable id. Plans live as validated JSON in `mesocycles`, with revision, active and archived flags. `mesocycle_completions` links a session to a saved Hevy workout. Only one plan can be active (partial unique index). These tables do not reuse or alter legacy program/block state.
- **Planned workout loading** — the builder or log start card loads a selected pending session into a new local draft, carrying reps, RPE, TS, notes and optional fixed kg. Automatic weights use current per-movement refs and loaded history; fixed weights set `manual=true`. Every loaded set starts unticked. A matching existing draft is resumed; replacement of a different draft requires confirmation. Plans are never overwritten by actual logged weights/reps. The payload's optional `planned_session` contains `mesocycle_id` and `session_id`; the server validates it before posting to Hevy and records completion only after success. Same-session/start retries reuse the recorded result; a different workout cannot complete the same prescription twice. Discard does not advance. Completion recording failures return a saved-workout warning rather than invite another Hevy post. Completed prescriptions cannot be edited/deleted from a plan; duplicate them to reuse. Future edits require the latest revision. Unsaved editor changes are backed up in device localStorage. Standalone frontend checks: `node tests/test_mesocycle_ui.cjs`.
- **Program naming** — optional `program_name` plus positive integer `cycle` and `week` on each plan generate `ProgramCycle.Week.Day` workout titles (BS-Bridge1.1.1). Day numbers follow session order. Microcycle duplication increments week, retains program/cycle and resets completion with fresh ids; cycle changes and week resets are manual. Server validation generates names authoritatively. Empty program preserves legacy custom names. Once a session is completed, the editor locks naming metadata; the server rejects edits/removals that would rename completed sessions. Existing loaded log drafts keep their saved title.
  During editing, missing or invalid cycle/week numbers display as `?` in generated previews. Explicit blanks survive redraw and local draft restoration; only absent legacy fields default to 1. Required integer inputs block saving incomplete naming.
- **Builder movement picker** — catalog and latest ten Hevy workouts load together; movements sort by latest performed timestamp before alphabetical ties, both initially and when searching. Search requires all words and caps results after sorting. Recent movements absent from the catalog remain available. Refresh list is in a separate footer and reloads history too. If history fails, the picker reports the alphabetical fallback while keeping the catalog usable.
- **Delete microcycle** — saved plan cards expose Delete with confirmation. The existing archive endpoint hides and deactivates the plan, preserving its document and completion links. Deleting the plan open in the editor clears that editor and its device draft; unrelated drafts stay open.
- **Completed microcycle library** — fully completed nonempty plans appear in a separate counted, collapsed-by-default section below unfinished plans. Their Edit, Duplicate and Delete actions remain available. Library refreshes preserve expansion state; empty plans are not classified as completed.
- **Microcycle activation** — saved cards expose Activate/Deactivate with explicit status. Only one plan can be active; deactivation preserves prescriptions, completions and editor changes. `POST /api/mesocycles/{id}/deactivate` is idempotent. Completing the final day (saved or manually marked) deactivates the plan; startup repairs older completed active plans. Completed plans cannot be activated; duplicate for reuse. Undoing a manual mark leaves the plan inactive until explicitly activated.
- **Log microcycle selection** — the start card lists all saved plans and selects the active one (or first available). Changing selection only previews its next pending session; loading activates the selected plan and invokes the existing checked-set/draft loader. Empty, complete or movement-free next sessions have explanatory text instead of a load button. Regression check: `node tests/test_log_plan_selection.cjs`.
  A Workout day selector defaults to the first pending session but allows any pending day. Saved-workout completions remain visible and disabled; manual marks remain selectable for undo. Loading a later day does not mark earlier days completed; progress records saved workouts or explicitly marked prior training. Movement-free days show guidance while other days remain selectable.
  Mark already completed explicitly records prior training without a Hevy write via `POST /api/mesocycles/{plan_id}/sessions/{session_id}/complete`. Completion has a null Hevy id and a marking timestamp, not a claimed historical workout date. The transaction validates plan/day, rejects archived plans and preserves existing completion on retries. Manual completions also protect the original prescription and prevent logging that same planned day twice. No automatic title matching is performed.
  Undo completion uses `DELETE` on that same endpoint to remove only a completion with a null Hevy id. Linked saved workouts are rejected. Missing marks are an idempotent success; missing days and archived plans are rejected. The selector keeps manual marks accessible even after all days are complete.
- **e1RM** — estimated one-rep max, in lb inside the code (`LB_PER_KG = 2.20462`). For a set: weight ÷ the RPE table's fraction for its reps and RPE.
- **RPE table** — `(rpe, reps) → fraction of e1RM`. The user's table is built entirely on one fact: it depends only on **k = reps + (10 − RPE)**, the reps to failure the set is equivalent to. A 5 @7 and an 8 @10 are the same cell value. Verified on all comparable cells of `rpe_chart_user.csv`.
- **TS** — a set the user marks (tap its set number: set → warm-up → TS → failure → drop set). It pins the movement's e1RM and, **when the workout is saved**, sets the movement's TM. Every TS is kept in `training_max_history`. Needs a weight, reps and an RPE.
- **TM** — training max = latest saved TS's e1RM × `tm_pct` (default 95%, per movement). Without a saved TS it falls back to the last session's best set × `tm_pct`.
- **Basis** — per movement, which number plans weights: `e1rm` or `tm`. Set by tapping the e1RM or TM tile.
- **e1RM tile logic** — if the movement has a TS (marked and ticked in this workout, else the latest saved), that is the e1RM and **nothing outranks it**, however high another set's e1RM is. With no TS it is the best set today (highest e1RM), until a set is done the one from the last session.
- **LSe1RM** — per movement (default on): after a set is ticked, the next sets plan from that set's e1RM instead of the base.
- **Planned weight** — base × RPE table fraction, rounded to the movement's step (`step_kg` 2.5 / `step_lb` 5 by default, finer for micro-loaded lifts). Weights are stored and posted in **kg**; lb is a reference, and a kg/lb switch chooses which one is typed.
- **Warm-ups** — never copied when starting from a past workout; a ticked warm-up drops out of the workout after ~0.8 s and is **not** saved to Hevy or the local record (deliberate: the user sees no value in warm-up history). `+ Warm-up sets` builds them on request.
- **Rest timer** — starts when a working set is ticked; each movement has its own time (`exercise_refs.rest_sec`, NULL = use the bottom-bar default); the alarm is deliberately loud.

---

## Hevy integration and its limits

- **Exercise list** — `GET /v1/exercise_templates`, cached in `hevy_exercise_cache`, refreshed via `POST /exercises/sync`.
- **Workout create** — only the `/log` page writes to Hevy: `POST /hevy/workouts` builds the body with `build_hevy_workout` and sends it with `HevyClient.create_workout`. Hevy has **no delete endpoint**, so every success is a permanent workout. Test with the Hevy client mocked, never against the real account.
- **Hevy cannot store an RPE below 6 or 6.5.** `build_hevy_workout` leaves such an RPE blank in what it posts. The exact RPE is kept in `logged_sets`. Anything that reads history back **from Hevy** (the Previous column, the last-session e1RM, the Progress page) therefore never sees those RPEs. Overlaying the local record onto Hevy history is a known gap (see the backlog).
- **API key** — stored encrypted in `app_settings` (Fernet key at `/data/app.key`), never hardcoded or committed; `GET /settings` never returns it.
- Errors from Hevy and key problems come back as HTTP errors through `_call_hevy` in `main.py`.

---

## The local record of sets

`logged_sets` (written by `set_log.record` after Hevy accepts the workout) has one row per saved set: workout start/end, Hevy workout id, exercise template id and title, set number within the exercise, type, `weight_kg`, `reps`, exact `rpe`, `is_ts`. A failure to record is logged but does not fail the save (a retry would post the workout to Hevy twice). Rows exist only from the day this was deployed; Hevy history is not backfilled.

---

## RPE tables from the user's own sets (`rpe_observed.py`, `/rpe-charts`)

The aim: a personal RPE table for squat, bench and deadlift (and the general table for everything else) built from real data and filled in over months, never from guesses and never from the table in use. The page shows the table in use only for comparison (and, if the user switches it on, in empty cells).

How it works, in order:

1. Sets used: not warm-ups or drop sets, with a weight, reps and an RPE. Every set counts, **the TS included**; no set is a reference.
2. Each movement in each workout gets its own e1RM. A straight line in k, `f(k) = 1 − slope·(k − 1)` (a true RPE 10 single = 100%), is fitted to all sets; then the curve is redrawn through the sets themselves (average share per k, kept non-increasing) and the e1RMs refitted, a few rounds. The overall scale is fixed only by the straight-line fit and that 100% pin.
3. A cell = the average share (set weight ÷ its workout's fitted e1RM) of the sets at that exact RPE and reps, with the count `n` and the gap to the table in use.
4. **Data gate** per lift (constants in `rpe_observed.py`): `MIN_SETS = 15`, `MIN_WORKOUTS = 3`, `MIN_K_SPAN = 4.0` reps of effort between the hardest and easiest sets. Until it is passed no cell is estimated and the page shows progress toward it.
5. Once passed, cells with no sets are **estimated** by interpolating the curve (shown as `est`), never from the table in use, and left empty past the hardest and easiest effort logged.
6. A "fitted curve" card shows the straight-line slope against the table's, and each workout's fitted e1RM against the e1RM the TS gave from the table.

Why this shape (decisions, do not undo without asking): measuring sets against the TS's e1RM was rejected as **circular** because that e1RM comes from the table's own value at the TS's cell; the TS single must count as data; nothing the user sees may be filled in from the table; estimates need a stated amount of data first.

Reference the user pointed to: the RTS article on customising an RPE chart (https://store.reactivetrainingsystems.com/blogs/advanced-concepts/customizing-your-rpe-chart): the same structure (a rep-max curve shifted by reps in reserve, 1RM = 100%), but it pins the curve with tested 1RM/4RM/8RM efforts and uses segments with different slopes (steeper near the top). Possible refinements are in the backlog.

## Movement stress (2026-10-17)

The log previews all entered working sets live, including unchecked sets, in the per-set Stress column and the compact session value. The duplicate total row below the sets is hidden. Checked rows use actual RPE; unchecked rows use planned RPE. Each preview contribution uses the same session reference, so unrounded values sum to the preview total. Unchecked contributions are grey. Total and session-value colours compare the preview to the existing band: grey without a scored set/baseline, green within, red above, amber below. The numeric session-window line is hidden on the log; ranges remain in tooltips/accessibility labels and the dashboard. Only checked sets enter rolling totals or the finished workout payload. API `sets` remains checked-only; optional `preview_sets` supplies the draft for `preview`, `preview_set_scores`, and `preview_status`. `set_scores` aligns with checked `sets`. Warm-up/unsupported contributions are null. No stress request writes a workout. Tests: `node tests/test_log_set_stress.cjs`, plus the Python stress tests.

`/log` keeps rolling totals, components, and history details calculated and available in the API but hidden on the card to preserve space for sets. The same backend calculation scores history. Warm-ups do not count. Variants remain separate Hevy template ids; duplicate cards for one template share the aggregate movement score. A draft is a new exposure, not the source workout it was copied from.

`rackbook-stress-v1` is an RTS-inspired training-dose estimate. It uses the heaviest usable set and a fixed default rep-max curve as its reference, independently of the user's loading chart, TS, TM, and LSe1RM. Ties use higher RPE, then fewer reps, so reordering does not change the score. For relative load I: CS = reps × 10^-6 × exp(14.72311 × I); PS = 0.5365534125622946 × I × sum(1.23927^(RPE − 10 − j), j=0..reps−1); total = (PS + CS)/2. Missing RPE is estimated @5, explicitly authorized by Brian for his easy/unrated sets; exact local RPE always wins. These fitted constants are a versioned starting convention, not a claim to reproduce RTS or measure physiological fatigue directly. A missing/invalid weight, reps or uncovered curve point is skipped and surfaced, not silently treated as a measured zero.

The local sets of a saved workout replace its Hevy snapshot for stress, preserving unstorable RPEs and avoiding duplicate sets. Raw records are not changed. No schema migration. Remote read failures are displayed as unavailable, with retry; no fabricated zero baseline.

The session window is 80–120% of the median prior session total in the trailing 56 days, excluding the draft. Elevated is above 120%; much higher above 150%. With no history there is no window; fewer than six prior sessions is provisional. Estimated baseline sessions are counted visibly. These are descriptive comparisons, not recovery/safety thresholds. Rolling 7/28-day totals are trailing elapsed durations, excluding their exact lower boundary and including the current completed draft sets once at the draft's start timestamp. Missed weeks contribute no work to totals but never create artificial zero-dose baseline sessions. Future and timezone-less historical timestamps are excluded. Days since last exposure is shown alongside.

History cache: 60 seconds, up to 128 movements, invalidated for affected movements after a successful Hevy workout save. UI requests are debounced and stale responses cannot overwrite a newer draft. Stress is computed on request and never stored as a permanent historical score, allowing later model refinement to recalculate history consistently.

The `/stress` dashboard opens with the main three movements and a selector for any cached exercise. It shows saved-session components, a calendar-time chart, current rolling totals, current session window, and a historical table with each workout's earlier-only session window, as-of-workout rolling totals, and estimated/unscored counts. History ranges are display filters only: older sessions are still used where needed to establish a baseline or trailing total. History is recalculated on read from all available Hevy/local data without changing source records or requiring a backfill. Warm-up-only sessions are excluded; working sets that cannot be scored remain visible as incomplete. Workouts sharing an identical timestamp do not establish precedence for each other's baseline. The dashboard includes saved history only; current draft metrics remain on `/log`. Navigation links are on Log, Progress, and RPE tables.

---

## Database schema

UI navigation: all seven app pages have a Back button. It uses browser history only when the referring page is from the same origin and there is a prior entry; directly opened secondary pages fall back to `/log`. On a directly opened root/log page with no prior app page, Back is disabled. Navigation preserves the existing locally saved workout draft.

The stress chart shades each session's historical lower/upper total-stress window. Missing baselines break the shaded band; isolated known windows remain visible. Total points above the range are red and points below are hollow, drawn above the component curves. Axis bounds include the upper window, so a low-work session cannot clip its reference range. The history table retains exact values and provisional labels.

Foreign keys are enforced (`PRAGMA foreign_keys = ON` in `get_db()`). Always verify columns with `PRAGMA table_info`; `database.py` is the full DDL, and columns added later are `ALTER TABLE`s in `init_db()`.

### Tables the current app uses

```
logged_sets            id, hevy_workout_id, workout_title, workout_start, workout_end,
                       exercise_template_id, exercise_title, set_number, set_type,
                       weight_kg, reps, rpe, is_ts, recorded_at
exercise_refs          exercise_template_id PK, basis ('e1rm'|'tm'), ls, tm_pct, step_kg, step_lb,
                       bar_kg, chain_kg, rest_sec (NULL = default); old e1rm_lb/tm_lb/auto unused
training_max_history   id, exercise_template_id, e1rm_lb, weight_lb, reps, rpe, set_at, recorded_at
rpe_chart              rpe, reps, percentage (PK rpe+reps), loaded from the CSV
hevy_exercise_cache    id (Hevy template id), title, primary_muscle, cached_at
body_measurements      date PK, weight_kg, lean_mass_kg, fat_percent, synced_at
app_settings           key PK, value (Hevy API key encrypted, RPE table source hash, ...)
```

### Legacy 5/3/1 planner tables

```
programs → tiers, blocks (cycles) → days → exercise_slots   (template layer)
programs → active_blocks                                     (live layer)
active_blocks → session_log (set-by-set), e1rm_log           (history)
microcycles                                                  (older cycle table)
```

---

## Legacy 5/3/1 planner (backend only; its page was removed 2026-10-19)

Programs are program-agnostic: tiers (behaviours `percentage`, `fixed`, `progression`, `free`), wave structure per exercise slot (`wave_params` JSON), microcycles numbered and user-labelled. All percentages derive from RPE (`target_rpe` and `actual_rpe` per set). `test_session_route.py` pins its current session and e1RM behaviour; `expectedFailure` tests there mark known bugs.

`wave_math.py` is pure (no DB, no HTTP): Epley e1RM (`weight × (1 + reps/30)`, a single is the weight), Joker qualification within `JOKER_BAND = 0.05` of the AMRAP e1RM, `session_e1rm` (mean of the AMRAP e1RM and qualifying Joker e1RMs), `working_weight` and `bbb_weight` (3-element percentage lists indexed by week − 1), rounding to 2.5 kg. Jokers with no RPE are excluded before the filter.

---

## Hard constraints

| Constraint | Rule |
|---|---|
| DB path | Read from `os.environ["DB_PATH"]`. Never hardcode. |
| DB library | `sqlite3` stdlib only. No SQLAlchemy, no Alembic. |
| SQL safety | Parameterised queries only. No f-string SQL. |
| Frontend | Vanilla JS, one self-contained HTML file per page, no bundler, no build step. Do not split a page's CSS/JS out. |
| Pure modules | `wave_math.py`, `workout_payload.py`, `workout_view.py`, `exercise_state.py`, `rpe_observed.py`: no DB access, no HTTP, no side effects. |
| Weights | Stored and posted in kg. Planned weights round to the movement's step (default 2.5 kg / 5 lb), never unrounded floats. |
| Hevy writes | Only via `POST /hevy/workouts`. Never post to the real account from tests or experiments. |
| Schema changes | New tables in the `CREATE TABLE IF NOT EXISTS` block, new columns as `ALTER TABLE` in `init_db()`; verify with `PRAGMA table_info`. |
| Table values | Nothing in the RPE tables view may be filled in from the table in use; estimates come from the user's sets only. |
| Deletions | No permanent deletions without explicit written instruction. Hide or retire things rather than delete (the user's preference). |
| Commits | The coding assistant may commit and push finished work. Use conventional commits, one logical change each, and run the full suite before pushing. |

---

## Working conventions

- FastAPI route handlers stay thin — business logic goes in service modules; Pydantic models for all request/response shapes; config via `.env` / `python-dotenv`.
- Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`), one logical change per commit. Push only when the tests pass.
- **One feature at a time**: build it small, check it live (the user uses it on a phone), then the next. Do not change behaviour the user did not ask about; when a design has a real tradeoff, ask one question.
- Add tests for non-trivial logic. The suite takes about 12 s; run all of it before pushing.
- Windows checkout: files use CRLF in the working tree (git warns about LF→CRLF; harmless). Edit with tools that preserve line endings.
- Dev servers (`.claude/launch.json`): `rackbook-dev` on port 8127 uses `.env` (`DB_PATH=./rackbook.db`, the local database). The `rackbook` config on 8126 fails if the local Docker container is already using that port. Test data written to the local database must be removed afterwards (use template ids starting `ZZ-`).
- `index.html`'s `fetchJson` and the log page's `api()` read JSON bodies; `POST /settings/api-key` answers 204 with an empty body, which `fetchJson` must tolerate.

---

## Deployment

```bash
git pull && docker compose up -d --build     # in the repo folder on the server
curl -s localhost:8126/health                # {"status":"ok"}
```

The database lives in the named volume `rackbook-data` at `/data/rackbook.db`, with the Hevy key's encryption key at `/data/app.key`; both survive rebuilds. Only `docker compose down -v` wipes them. Logs: `docker logs rackbook -f`.

For HTTPS and phone access, `tailscale serve --bg 8126` (inside the Tailscale container if it runs as one, which is host-networked here, so `http://localhost:8126` works). The Hevy API key is entered once at `/legacy#settings`.

Local Docker on Windows (Docker Desktop) also works with the same compose file; an old container named `531bbb` from before the rename may be holding port 8126 on the dev PC.

---

## Development workflow

The coding assistant handles architecture, implementation, debugging, and validation directly; Brian reviews and checks the result on his phone. Read this file, `CLAUDE.md` / `AGENTS.md`, `backlog.md`, and [`development.md`](development.md).

Microcycle conversion (2026-10-17): startup atomically converts existing multiweek plans, retaining their original JSON in `mesocycle_week_backups`. Empty extra weeks are removed from the active document; populated or previously completed future weeks become separate one-week microcycles. Completion links move with their sessions. `mesocycle_session_aliases` resolves old URLs and in-flight log drafts, including idempotent save retries, to their new plan ids. Unsaved multiweek editor drafts are recovered as separate one-week drafts on the device. This feature does not use the legacy planner’s `microcycles` table.


## Pre-session movement-pattern soreness (2026-10-18)

The log offers separate Squat, Bench/Press and Deadlift soreness check-ins on each workout draft. Levels are absolute labels: None=0, Mild=1, Moderate=2, Severe=3. Pain or injury is an independent boolean per pattern; it can be flagged without selecting a soreness level. Untouched/cleared levels remain unknown, never implicitly zero. Controls persist with the device draft and are not copied into new workouts from history or plans.

`WorkoutEntry.soreness` accepts optional pattern objects (`squat`, `bench_press`, `deadlift`), each with nullable strict integer `level` (0–3) and strict boolean `pain` (default false). After Hevy succeeds, `soreness.record` stores observations in `session_soreness`, keyed by Hevy workout id and workout start. Unanswered patterns stay null; a pain-only observation retains a null level. Fully unanswered check-ins create no row. Repeat local writes preserve the first observation. A local write failure returns a saved-workout warning, never a retry-inducing error after Hevy success. These observations are local only and do not change Hevy payloads or training prescriptions.

This is the data-collection step for a fatigue model. The intended analysis uses marked TS e1RM as the primary performance reference, training volume/rep/RPE history, and bodyweight trends. Soreness is a local movement-pattern observation, not a systemic fatigue score. Numeric levels are ordinal categories, not calibrated fatigue units. Pain/injury must remain separate from soreness and volume-progression scoring. The first provisional trend model is described below. Checks: `node tests/test_log_soreness.cjs`, `tests/test_soreness.py` (mocked Hevy).


## TS performance and soreness trends (2026-10-18)

`fatigue.py` implements `ts-trends-v3`; `GET /movement-fatigue/{template_id}` is a read-only local-data endpoint with typed response models in `main.py`. `/stress` loads an independent Performance & soreness panel for the selected movement; stress-history failures do not block it. The stress History range never changes the active TS baseline. Refresh reloads local analysis. It does not call Hevy or change plans, refs, set history, RPE tables or bodyweight. Bodyweight sync remains on Progress.

- Performance uses saved `training_max_history` TS values only, one per normalized workout timestamp. No best-set substitution or table refit. Exercise ids remain separate. Exact main-lift titles from `progress.LIFT_TITLES` map squat/deadlift individually and bench/press to shared `bench_press` soreness; unassigned variants show performance but no routine training-change suggestions.
- Reset the baseline at every gap of **21 days or longer** in this movement's saved sessions, or when currently inactive for 21 days. Old history remains visible. Twelve comparable TS sessions are required: same reps and RPE within one point of latest. There is **no minimum waiting period in weeks**. A TS older than 21 days cannot drive a current suggestion. Compare matched medians from the latest six with the previous six. At least five sessions in each half must have paired BW, soreness and complete local set reps/RPE, and the last three movement sessions need soreness check-ins. Missing requirements leave status `building_baseline`, action `collect`, and comparative metrics null. Declining means at least 3% lower and all latest three matched TS values below the prior matched median; improving means at least 3% higher. Other results are stable. These are provisional product rules, not validated physiological thresholds.
- BW is the trailing seven-calendar-day mean as of each session, requiring at least two distinct dates. No future measurements or old-weight carry-forward. BW coverage is part of the collection gate; the same matched observations are used for every comparison. Display BW change and e1RM/BW alongside absolute e1RM change; the ratio is descriptive, not a correction, and BW loss does not establish the cause of a decline. A BW median change of 1% is the initial context flag.
- Volume comes from exact local non-warm-up sets, with session sets/reps, median reps/RPE and seven-day set counts exposed in observations. Missing local set/rep data blocks routine suggestions. Three consecutive movement sessions need soreness ratings; unknown never counts as zero. Repeated soreness means at least two of three rated moderate/severe. Pain is separate: a flag on the latest movement session, recent three movement sessions, or latest explicit pattern check-in within 21 days blocks progression suggestions, including a check-in on another workout.
- Suggestions are manual trials: decline with repeated soreness → one fewer back-off set at the next two exposures, retain TS/reps, reassess (a lone TS cannot lose a back-off set). Decline with low soreness and falling BW → review BW/recovery context. Other decline → review reps/effort before adding volume. After 18 comparable TS sessions with three groups of six (at least five matched in each) and consecutive declining groups plus a recorded set reduction or rep change, consider a new block with another exercise and a separate baseline. This observes co-occurring changes, not a proven causal intervention.
- Stable TS, all latest soreness None/Mild, stable BW, unchanged median sets/total reps, no rise in exposure frequency, and no material median-RPE increase (over 0.5) can suggest one extra back-off set at one weekly exposure, then reassess after three comparable TS sessions. Improving TS holds volume. Missing logged RPE suppresses the extra-set trial. The model never automatically changes training.

The UI shows four raw-history charts from the first session: marked TS e1RM, seven-day BW, working-set counts and categorical soreness. Unknowns and gaps of 21 days are never bridged; old-baseline points are grey and pain is a separate marker. During collection a session counter and paired-data coverage replace verdicts and comparative percentage tiles; direct pain reports remain visible. Charts are observations, not fitted trend lines or predictions. Reaching 12 sessions only enables provisional heuristics, not an accuracy guarantee. The API `collection` object exposes eligibility and coverage counts. The UI also exposes the rule explanation, source link and raw TS/BW/soreness observations. Monitoring rationale: https://pubmed.ncbi.nlm.nih.gov/28463642/ ; recovery monitoring: https://pubmed.ncbi.nlm.nih.gov/29345524/ . These consensus statements do not validate Rackbook's numerical rules or specific set-change suggestions. Checks: `tests/test_fatigue.py`, `tests/test_fatigue_route.py`, `node tests/test_fatigue_ui.cjs`; all test workouts are mocked/disposable.


## Movement-card check-ins and saved soreness edits (2026-10-18)

Soreness/pain controls are inside the matching movement cards on `/log`, using exact main-lift titles from `progress.LIFT_TITLES` via `GET /soreness/patterns`. Bench and Press share `bench_press`; unknown variants are not inferred. Duplicate cards stay synchronized. The former workout-wide panel is hidden. Missing configuration leaves the log usable with a retry hint. No ratings are copied from history or plans.

Ticking the final outstanding working set collapses the card to its header with Completed and Reopen. Unfinished working sets prevent automatic collapse even if the last row is ticked first. Warm-ups do not count toward completion. Reopening keeps a completed card open across redraws, until another completion; unticking or adding a set leaves it open. `ex.collapsed` persists in the normal device draft. Rest timers and checked-set saving retain their existing behavior.

Recent workouts exposes Edit soreness only when a local set record or soreness record exists (`WorkoutView.soreness_editable`). `GET /workout-soreness/{id}` reads current check-ins; `PATCH` accepts supplied pattern objects using the existing strict 0–3/pain validation. Each supplied pattern replaces that pattern's check-in; null clears it. The UI submits only changed patterns, so unrelated check-ins are preserved. Updates merge with current values inside a local transaction, retaining the original workout start, exact sets, TS records and microcycle links. A missed check-in can be added from a local set record even if no soreness row exists. Unknown workout ids return 404 without Hevy calls; Hevy-only history is not backfilled. The original save's insert-on-conflict behavior remains unchanged; intentional edits use `soreness.update`. Editing makes no Hevy writes and fatigue analysis reads the corrected observations on its next request.

Validation: full Python suite, standalone frontend checks including `tests/test_log_collapse.cjs` and `tests/test_log_soreness.cjs`, and phone-width browser tests with disposable data and a mocked Hevy client.


## Browser favicon (2026-10-19)

All seven HTML pages declare `/static/icon-192.png` as their PNG favicon, reusing the existing barbell app icon. `/favicon.ico` serves the same file with `image/png` and revalidation headers for browsers requesting the conventional fallback path. The manifest and Apple home-screen icon links retain their existing behavior.

## Mobile RPE entry (2026-10-20)

The log's compact RPE button displays a gauge for an unrated set and the numeric value after selection. Clear restores the gauge. Accessible button labels retain the RPE value; the icon is decorative. Fine-pointer typing remains available above 600px; narrow layouts use the picker button.


## Scoped BS-Bridge RPE history (2026-10-20)

The one-time import is complete. Its panel is now hidden on the RPE page; imported snapshots continue contributing. The import service and hidden controls are retained for recovery.

Movement contribution is configured in the Microcycle Builder: Squat, Bench, Deadlift, General, or Do not contribute. There is no separate Press chart; press can contribute to General. Assignments follow exact exercise IDs across historical renames, with no runtime title matching. New movements start excluded. A one-time migration preserves the four previously approved assignments from existing local/imported records: low-bar and paused high-bar squat to Squat, close-grip bench to Bench, conventional deadlift to Deadlift. It never overwrites an explicit choice or assigns newly encountered movements by name.

The RPE page's BS-Bridge history section offers an explicit import. `rpe_history.fetch_bridge` reads all Hevy workout pages and selects case-insensitive BS-Bridge title variants, including a space before numbering. No other program is imported. All pages must succeed before persistence begins. Only normal/failure sets with finite positive weight, positive integer reps and a recorded valid RPE qualify. Warm-ups, drop sets, unrated sets and invalid records are omitted without substituting an RPE. Import retains the original workout id/start and exercise id; historical TS markers are not invented.

`rpe_history_imports` stores immutable chart-only snapshots keyed by `(hevy_workout_id, exercise_template_id)`. A transaction inserts missing snapshots; retries and concurrent requests cannot duplicate them. A local `logged_sets` snapshot for the same workout/movement prevents import and takes precedence at read time even if recorded after the import, or if unrated. Exact low-RPE records are not replaced with Hevy's blanks. No source workout, local set, TS/TM, soreness, fatigue record, movement reference or microcycle completion is rewritten. These imports feed only RPE charts. Assigned local logs contribute normally; the BS-Bridge title restriction applies to historical imports.

`rpe_chart_assignments` stores each movement's global group and revision. Save plan persists assignment changes in the plan transaction; Cancel leaves saved assignments untouched. The selection applies across microcycles and reclassifies existing local/imported chart data without rewriting sets. Completed days allow assignment edits while prescriptions remain locked. Revision conflicts roll back the complete save. Old clients omitting assignments retain saved choices. General uses the same observed-data fitting and gates when it has assigned data; otherwise it displays the existing loading table as a reference. Assignment does not change the table used to plan weights.

The charts use `GET /rpe-observed/group/{lift}` and display usable local/imported counts by source movement. The older exact-movement endpoint retains its local-only behavior. The fit normalizes each `(workout id, exercise id)` independently, so two squat variants on one date never share an absolute max. Distinct workouts, rather than movement count, satisfy the existing three-workout gate. The 15-set and effort-spread gates remain unchanged. Fitted references list dates including years and movement names; pooled references are not compared against another movement's saved TS. Estimated rep columns through 12 are displayed when returned by the model.

No age cutoff or age weighting is added: all qualifying BS-Bridge history contributes. A real tested max, if implemented later, must be dated and attached to the appropriate movement/session rather than used as a universal historical anchor. The current fit and its assumptions remain unchanged beyond separate movement/workout references.

Validation: mocked paginated history, program/movement scope, historical rename, invalid/unrated exclusions, exact local precedence, idempotence, failed reads, independent same-day movement references and workout gates are covered in `tests/test_rpe_history.py`. Frontend import/refresh/source/estimate/error behavior: `node tests/test_rpe_chart_import.cjs`. Browser import and retry verified at phone width in a disposable DB with mocked responses; homelab import is a separate deployment action.


## Fatigue timing and confirmed related work (2026-10-21)

The fatigue model now uses exact local set history across exercises to contextualize **extra-set suggestions only**. `fatigue_context.py` calculates time since the prior exact-exercise and confirmed-pattern exposure, plus other related exercises' working sets/distinct workouts during `[session start − 7 days, session start)`. Warm-ups/future records are excluded. No part of the assessed workout enters its pre-session context; individual set timestamps/order are not available. Each row contributes once per relevant pattern. Exact TS histories, main shortcut cards and soreness-entry mappings stay separate.

Relationships live in `fatigue_relationships` (`exercise_template_id`, `patterns_json`, `reviewed_at`). `GET /fatigue/relationships` lists locally recorded exercises, confirmed choices and inactive suggestions; it never persists a suggestion. `PUT /fatigue/relationships/{exercise_id}` explicitly confirms a unique list of zero to three patterns (`squat`, `bench_press`, `deadlift`). Empty means confirmed Not related; absent means unreviewed. Unknown local exercises return 404 and invalid/duplicate patterns return 422. Suggestions prioritize existing exact main-lift titles, then cached muscles: quadriceps→squat, hamstrings/lower_back→deadlift, glutes→squat+deadlift, chest/shoulders/triceps→bench_press; others have no suggestion. The Stress editor allows adjusting and explicitly saving these choices. No history records or baselines are rewritten when mapping changes; context is recalculated on the next read.

`GET /movement-fatigue/{id}` adds per-point interval/workload fields and a typed `context` object with reference/recent/latest comparisons, current idle interval, pending mappings, later work, extra-set eligibility and block reasons. The model version is `ts-trends-v3`. The 12-session gate and 21-day exact-movement reset remain unchanged.

Before returning `try_set`, require at least three available interval/count observations in the previous six matched TS sessions. Compare that group's medians with both recent-group medians and the latest assessed TS context. Exact-exercise gaps block when longer by more than `max(1 day, 25% of reference)`. Pattern spacing blocks differences in either direction at the same tolerance. Related seven-day sets block absolute changes greater than `max(2 sets, 25% of reference)`. The current idle gap uses the exact-exercise tolerance too. Additional exact/confirmed related work after the assessed TS, missing timing context, or an unreviewed exercise in the relevant comparison history blocks extra-set advice. Pending review covers the earliest matched point minus 21 days through assessment time. Unknown workload/spacing is null rather than invented zero. An otherwise eligible extra-set trial becomes `hold` with a specific explanation; descriptive trends, collection counts and existing reductions/rep-review/exercise-review/pain rules retain their behavior.

The Stress panel shows a compact spacing/workload summary, links pending review to the editor, and exposes interval/count columns in the observations table. Saves are local only; a failed save retains choices for retry, and successful saves refresh current analysis. Stale analysis responses cannot overwrite a newer selection/save. These are provisional comparability tolerances, not a recovery curve or measured fatigue percentage. Local history only: no Hevy backfill or imported RPE-history contribution. Validation includes `tests/test_fatigue_context.py`, `tests/test_fatigue_relationships.py`, endpoint integration and `node tests/test_fatigue_relationships_ui.cjs`, plus a mocked phone preview.


## Visual Stress overview and separate details (2026-10-21)

`/stress` now prioritizes compact main-three shortcuts, a selected-movement baseline counter and four raw observation charts, plus a session-stress chart with rolling totals. During collection it shows no premature trend verdict. Pain reports remain visible. Explanations, comparison percentages, spacing diagnostics, observation/history tables and the related-work editor are on `/stress/details`, reached through View details. Both routes serve the same self-contained `stress.html`; a route-based display mode reuses existing calculations/renderers without maintaining duplicate pages. The details route has the same no-cache behavior. Shared navigation still points to the overview.

Movement id and stress-history range are carried through `movement`/`days` query parameters in both directions and persisted in the address bar. Direct details links restore a valid selection; unknown ids fall back to the existing main/first movement and unsupported ranges retain the default. `#relationshipEditor` opens relationship review on the details route. Only the overview loads the main shortcut histories; both views retain independent stress/fatigue loading and errors.

Relationship saves now show a prominent live confirmation naming the exercise and the workload patterns activated (or Not related). A successful button remains labelled ✓ Saved and disabled until a checkbox changes; edits show Unsaved changes and re-enable saving. Failures use an alert and Retry save, preserving the pending choices. Suggestions are still inactive until explicitly saved, and the workload mapping still makes no changes to Hevy or workout sets.

Validation: `node tests/test_stress_dashboard_ui.cjs` covers compact rendering, collection/pain, parameter-preserving links and deep-link fallbacks; existing fatigue/editor checks cover details and save feedback; mocked API tests cover both routes. Phone-width browser validation uses disposable data and mocked Hevy.


- Progress comparison dates and bodyweight provenance (2026-10-21): all summary tiles retain the shared first/last scored workout period, now showing full workout dates, endpoint bodyweights and source dates/ages/counts. `/progress/data` adds nullable `bodyweight_source_date`, `bodyweight_age_days` and `bodyweight_weigh_in_count`. Bodyweight remains the seven-day average at the latest available weigh-in, carried forward through day 14; day 15 is unavailable. Progress-only metadata leaves fatigue calculations and stored measurements intact. Responsive intermediate date ticks include full years; missing observations break every chart line. Hover, tap and keyboard focus show session details including unavailable values; arrow keys move between sessions. Checks: Python suite and `node tests/test_progress_ui.cjs`; mocked phone/desktop browser inspection could not complete because the browser tool timed out reaching the local preview.


### Progress chart exploration (2026-10-21)

Both Progress charts share an independently zoomable date window. Quick ranges end at the latest recorded session (30/90/180/365 days or All); exact dates are under Choose exact dates. Zoom buttons and mouse drag narrow the window; Earlier/Later move half a window with one-day minimum steps; Reset restores all history. Touch keeps vertical page scrolling, with large zoom/navigation buttons and tap-to-inspect. Session hit regions span the space between observations, keyboard arrows step through sessions, and both detail panels/date guides follow the selected session. Axes fit visible observations, empty ranges remain explicit, missing values break lines, and full years distinguish dates. The summary tiles retain the original shared overall comparison period regardless of zoom. Lift changes reset the view; resize preserves its dates. No new dependencies or backend/data changes. Verification: `node tests/test_progress_ui.cjs`, mocked browser at 390px and 1280px including range selection and mouse drag.


### Progress chart renderer — Hevy-Fatigue reference (2026-10-22)

The Progress renderer now uses the same Chart.js 4.4.0 engine as Hevy-Fatigue’s `static/index.html`. Reviewed `_trendChartBaseOptions`, `_vfBuildBarLineChart`, `_exmBuildLineChart`, `.vf-chart-wrap`, and compact segmented controls. The reference establishes sizing/visual treatment; Rackbook does not adopt its readiness formulas, thresholds, rest-day zeroes or data assumptions. This supersedes the handwritten SVG renderer described above.

`progress.html` keeps its page logic inline and loads three versioned local files from `static/vendor/`: Chart.js, Hammer.js and chartjs-plugin-zoom. Licenses, upstream archive locations and SHA-256 hashes are in that directory. No CDN or bundler is needed; Docker’s existing COPY and `/static` mount include the assets. Other pages retain their existing renderers.

Desktop has an overall-summary sidebar with two stacked chart cards; phone/tablet layouts place the compact summary above the charts. Plot parents have explicit 260px desktop/220px phone heights and `maintainAspectRatio:false`, so axes, strokes and text do not enlarge with page width. Small labeled axes, restrained grids/markers, compact legends, and a floating hover/tap tooltip follow the reference. A shared inspector provides full dates, e1RM/BW/score, nullable provenance and previous/next/select controls; focusable canvases support Left/Right/Home/End and +/−/Escape. The same inspector handles sessions with missing score/BW instead of snapping to a different session.

The initial chart window is the latest 12 weeks relative to the last session. 4/8/12 weeks, one year, All and Custom set one shared window. Controls and plugin gestures support mouse drag-to-zoom, Shift-drag pan, Ctrl-wheel and touch pinch/horizontal pan. Touch retains vertical page scrolling through `touch-action:pan-y`. Numeric timestamp axes preserve elapsed time across gaps; nulls stay in every dataset with `spanGaps:false`. Axes fit observations within the window; explicit overlays explain empty windows or missing scores. Overall summary comparisons still use first/last scored sessions (or e1RM history if no score exists), independently of the chart window. The seven-day average and 14-day carry-forward, stored readings, backend calculation and fatigue behavior are unchanged.

Charts are destroyed before lift reload/replacement; responses are checked after JSON parsing to reject stale loads. Theme changes recreate charts using current CSS colors; Chart.js handles resizing without resetting dates. Verification includes `node tests/test_progress_ui.cjs`, the Progress API/static-asset tests, and mocked browser checks at 390px and desktop width for range selection, drag zoom, keyboard/tap inspection, missing observations, zero/one sessions and repeated lift switches.

### Stress chart presentation (2026-10-22)

Stress dashboard and details charts use the same locally bundled Chart.js/zoom libraries and presentation as Progress: responsive canvas sizing, real elapsed-time axes, date ticks, zoom/pan and date controls, hover/tap details and keyboard session inspection. `static/stress-charts.js` renders both stress history and performance/soreness observations. The four observation charts synchronize their date window and selected session. Missing observations remain gaps, 21-day observation breaks remain disconnected, soreness stays categorical, prior-baseline observations remain muted, pain flags remain visible, and historical usual-range shading and above/below markers are retained. Detached charts are destroyed when movement/range views change. No scoring, baseline gates or source data change. Checks: `node tests/test_stress_charts.cjs`, existing fatigue/dashboard UI checks and Progress UI checks.
