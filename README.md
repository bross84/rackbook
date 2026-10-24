# Rackbook

A personal workout logger and strength tracker that saves to [Hevy](https://hevyapp.com). You log sets by RPE, the app plans each weight from the movement's e1RM or training max, and it builds RPE tables for your main lifts from your own sets. Not tied to any one programme.

Deployed via Docker on CasaOS, used as a desktop and mobile PWA. It has no login, so keep it on a private network (see [Deployment](#deployment)).

---

## What it does

- **Workout log** (`/log`) — load a planned microcycle workout, start empty or copy a recent Hevy workout (its warm-ups are not copied), pick exercises, tick sets off, and save the finished workout to Hevy via `POST /v1/workouts`. A draft lives in the browser until you save.
- **Microcycle Builder** (`/microcycles`) — start blank and add or remove days to plan one week of workouts with per-set reps, RPE, optional fixed weights and TS markers. Duplicate a microcycle to reuse its prescription, save and activate a plan, then load its next workout from the log. The sequence advances only when a workout saves successfully, without calendar dates. Saved plans and completion history live in the app's SQLite volume.
  - Weights are entered and posted in kg, with lb beside them as a reference; a kg/lb switch flips which one you type in.
  - Set a weight by RPE: it is filled in from the RPE table and a base number per movement, either the e1RM or the TM. LSe1RM can plan each set from the last ticked set's e1RM instead.
  - **TS** — mark a set as a movement's TS. It pins that movement's e1RM (nothing outranks it, even a higher set), and when the workout is saved it sets the movement's TM (its e1RM × the TM %), which holds until the next saved TS.
  - Set types: set, warm-up, TS, failure, drop set. A ticked warm-up drops out of the workout (it is not saved), and `+ Warm-up sets` builds them on request.
  - Each set shows its e1RM; a Previous column shows last time's sets; a plate loader shows the plates for the next set; each exercise has its own rest time and a louder alarm at the end; exercises can be dragged to reorder.
- **Own record of sets** — every set of a saved workout is also kept in the `logged_sets` table with the exact RPE. Hevy cannot store an RPE below 6 or 6.5, so this keeps what Hevy drops.
- **RPE tables** (`/rpe-charts`) — for squat, bench and deadlift, a table of RPE by reps built from your own logged sets, next to the table in use. Each workout gets its own fitted e1RM (nothing is measured against the table's own numbers), and once a lift has enough data the cells you haven't hit are estimated from your other sets. A General tab shows the table every other movement shares. Read-only for now.
- **Progress** (`/progress`) — each main lift's e1RM (Hevy history + the RPE table) against your 7-day average bodyweight (Apple Health via Hevy) and a DOTS-style strength score, so a cut can be told apart from lost strength. Set `DOTS_SEX=female` for the female coefficients (default male). The Hevy exercise each lift reads is `LIFT_TITLES` in `progress.py`.
- **Recent workouts** (`/recent`) — your latest Hevy workouts.
- **Movement stress** (`/stress`) — squat, bench, and deadlift overview plus a movement selector, central/peripheral breakdowns, rolling 7/28-day totals, and retrospective session history. Historical blank RPEs are marked as @5 estimates; saved workouts are not modified. The log shows only the compact session score and window.
- **Model trial dashboard** (`/trial`) — expected versus actual performance categories over time, frozen pre-workout scores, saved-set details and collection progress by movement, model and training mode. Unsaved draft snapshots appear separately and do not count toward evaluation. See [the trial guide](docs/fatigue-trial.md).
- **Settings** (`/legacy#settings`) — the Hevy API key, exercise cache sync and unit preference. The old 5/3/1 Workout and Program tabs were removed from this page (2026-10-19); the backend routes and data for them remain.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI |
| Database | SQLite at `DB_PATH` (`/data/rackbook.db` inside Docker) |
| DB access | `sqlite3` stdlib — no ORM |
| Frontend | Vanilla JS, one self-contained HTML file per page, no bundler |
| Deployment | Docker + docker-compose, CasaOS |

---

## RPE table

`data/rpe_chart.csv` is the built-in table. If `data/rpe_chart_user.csv` exists it is used instead. Either is loaded into the `rpe_chart` table on startup and reloaded when the file changes. The file is baked into the Docker image, so changing it means redeploying.

---

## Legacy 5/3/1 planner

Kept for reference. The `/legacy` page now shows only Settings; the planner's screens are gone.

### Three tiers

| Tier | Description |
|---|---|
| **Main** | Primary lift. Percentage-based sets from training max. Top set is AMRAP. Optional Joker sets. |
| **BBB** | Same or complementary lift. 5×10 at 65/70/75% of averaged e1RM by week. Freely adjustable. |
| **Accessory** | Free-log only. No prescribed weight or sets. |

### e1RM rules

- **AMRAP sets** — anchor the e1RM after every top set using the Epley formula
- **Joker sets** — averaged and included only if within ±5% of the current AMRAP-anchored e1RM
- **RPE-less Jokers** — excluded from e1RM calculation entirely

### Wave structure

| Week | Main % | BBB % |
|---|---|---|
| 1 | 75% | 65% |
| 2 | 80% | 70% |
| 3 | 85% (+ AMRAP) | 75% |

3-week wave repeats; minimum 8-week block. New e1RM from each AMRAP anchors the following week's working weights.

---

## Database schema (overview)

```
logged_sets             every set of every saved workout, RPE as typed
exercise_refs           per movement: basis (e1RM/TM), TM %, rounding step, bar, chains, rest time
training_max_history    every TS saved, newest last
rpe_chart               the RPE table in use, loaded from the CSV
hevy_exercise_cache     exercise list pulled from Hevy
body_measurements       daily body weight synced from Hevy
app_settings            the Hevy API key (encrypted) and other settings

programs → blocks → days → exercise_slots   (legacy 5/3/1 template layer)
programs → active_blocks                    (legacy live layer)
active_blocks → session_log, e1rm_log       (legacy set log and e1RM history)
```

The full schema is in `database.py`.

---

## Key files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app and routes |
| `database.py` | Schema, `init_db()`, migrations, RPE table loading |
| `hevy_client.py` | Hevy API client — exercise list, recent workouts, exercise history, workout create |
| `workout_payload.py` | Builds the body posted to Hevy |
| `exercise_state.py` | A movement's e1RM and previous sets, from its last Hevy session |
| `training_max.py` | The TS and TM |
| `refs_store.py` | Per-movement settings |
| `set_log.py` | The local record of sets |
| `rpe_observed.py` | RPE tables built from your own sets |
| `progress.py`, `strength_score.py`, `body_weight.py` | The Progress page |
| `log.html` | Workout log (`/log`) |
| `rpe_charts.html` | RPE tables (`/rpe-charts`) |
| `progress.html`, `recent.html` | Progress and recent workouts |
| `index.html`, `wave_math.py`, `program_parser.py` | The legacy 5/3/1 planner |
| `docs/backlog.md` | What is done and what is next |
| `docs/hevy-api.md` | Hevy API notes |

---

## Hevy integration

- **Exercise list** — `GET /v1/exercise_templates`, stored in `hevy_exercise_cache`, refreshable via `POST /exercises/sync`
- **Workout create** — `POST /v1/workouts`, only from the log page (`POST /hevy/workouts`). Hevy has no delete endpoint, so every success is permanent. An RPE Hevy can't store is left blank in what is posted; the exact value stays in `logged_sets`.
- **API key** — stored encrypted in `app_settings`, never hardcoded or committed

---

## Hard constraints

| Constraint | Rule |
|---|---|
| DB access | `sqlite3` stdlib only. No SQLAlchemy, no Alembic. |
| Frontend | Vanilla JS, one self-contained HTML file per page. No bundler, no build step. |
| DB path | Read from `os.environ` as `DB_PATH`. Never hardcode. |
| Commits | Conventional commits, one logical change each. Push only after the required tests pass. |
| Deletions | No permanent deletions without explicit written instruction. |
| Column names | Always verify with `PRAGMA table_info`. Never assume. |

---

## Development model

The coding assistant handles design, implementation, and validation directly. Brian reviews the result and checks it on his phone.

Read [`docs/rackbook-context.md`](docs/rackbook-context.md), [`docs/backlog.md`](docs/backlog.md), and [`docs/development.md`](docs/development.md) for project context and the development workflow.

Tests: `python -m unittest discover -s tests -t .`

---

## Deployment

### Homelab updates with the Hevy Fatigue bridge

From `/var/lib/docker-data/AppData/rackbook` on the server, run:

```bash
git pull --ff-only && docker compose -f docker-compose.yml -f docker-compose.fatigue-bridge.yml up -d --build rackbook
```

Use both Compose files on every update to keep the daily check-in bridge connected. Compose reads the server's `.env` file alongside them, which must contain:

```dotenv
HEVY_FATIGUE_DATA_VOLUME=hevy-fatigue_hevy-data
```

This server-specific `.env` file stays on the server and is not committed to Git. The bridge mounts the existing Hevy Fatigue volume read-only.

Verify that Rackbook can read the check-in:

```bash
curl -fsS "http://localhost:8126/fatigue-trial/daily?day=$(date +%F)" | python3 -m json.tool
```

`available` means today's check-in was read; `stale` means an older check-in was read; `unavailable` means no check-in could be retrieved. Enable **Performance model trial** on the Log start screen to use check-ins in trial assessments.

### Deployment without the bridge

```bash
docker compose up -d --build
```

App runs on port **8126** (8125 is reserved by hevy-fatigue on the same host). The database persists at `/data/rackbook.db` in the `rackbook-data` volume, with the encryption key for the Hevy API key at `/data/app.key`.

There is no login. To use it away from the home network, put it behind Tailscale, for example `tailscale serve --bg 8126` (run inside the Tailscale container if it runs as one), rather than exposing the port.

---

## License

MIT
