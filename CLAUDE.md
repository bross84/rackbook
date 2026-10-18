# CLAUDE.md — Rackbook

For any AI coding tool working in this repo. `CLAUDE.md` carries the same information; keep the two in step.

## Project Overview
Rackbook: a personal workout logger and strength tracker (FastAPI) that plans set weights from an RPE table, saves finished workouts to Hevy, keeps its own record of every set, and builds RPE tables for squat/bench/deadlift from the user's own sets. It is no longer a 5/3/1-specific app; the 5/3/1 planner survives at `/legacy` only.

**Start with `docs/rackbook-context.md`** (architecture, domain terms, decisions, constraints), then `docs/backlog.md` (what is done, what is next). `README.md` is the overview; `plan.md` is only a history log of the original build.

- **Stack:** Python, FastAPI, stdlib `sqlite3` (no ORM), vanilla-JS frontend, one self-contained HTML file per page (`log.html` is the main one; no bundler)
- **DB:** path from `DB_PATH` env var; `/data/rackbook.db` in Docker
- **Tests:** `python -m unittest discover -s tests -t .` (pytest is not installed); run the whole suite before pushing
- **Infra:** Docker container on Ubuntu homelab (CasaOS), port 8126, reached over Tailscale (`tailscale serve`). There is no login. The app can write permanent workouts to the user's Hevy account (Hevy has no delete), so never post to the real Hevy account from tests or experiments — mock the Hevy client
- **Dev server:** `rackbook-dev` in `.claude/launch.json` (port 8127, local `rackbook.db`). Remove any test rows you add (ids starting `ZZ-`) afterwards

## Current state (2026-10-16)

- **Log page (`/log`)** is the product: RPE-planned weights from an e1RM or TM base per movement, the **TS** (a marked set that pins the movement's e1RM and sets its TM when the workout is saved), LSe1RM, kg/lb, Previous column, per-set e1RM, plate loader, per-exercise rest timer, drag to reorder, warm-ups not copied from past workouts and dropped when ticked.
- **Local set record** (`logged_sets`): every saved set with its exact RPE (Hevy drops RPE below 6 / 6.5). Anything read back from Hevy (Previous column, last-session e1RM, Progress) misses those RPEs; fixing that is in the backlog.
- **RPE tables** (`/rpe-charts`, `rpe_observed.py`): per lift, cells from the user's own sets, each workout with its own fitted e1RM, the TS counted as ordinary data, estimated cells only after a data gate (15 sets, 3 workouts, 4 reps of effort), nothing ever filled in from the table in use. Read-only; per-lift editable charts are next.
- **Movement stress**: compact session score/window on `/log`; `/stress` shows main-three overview, a movement selector, central/peripheral components, rolling totals, and retrospective saved-session history. Historical blank RPEs are estimated @5. Historical comparison windows use earlier sessions only; source workouts are never rewritten.
- **Microcycles** (`/microcycles`, `mesocycles.py`): single-week workout prescriptions load into `/log` with current movement refs. Fixed weights remain manual; all sets start unticked. A successful Hevy save records completion and exposes the next pending session; loading/discarding never advances. Separate local tables, revision checks, completed prescriptions kept intact. Mock Hevy in tests; `node tests/test_mesocycle_ui.cjs` covers loading/sequencing.
- **Do not undo without asking:** the TS pins the e1RM; measuring sets against the TS's e1RM was rejected as circular; estimates only from the user's data; warm-ups are not kept.
- The user works one feature at a time and checks it on his phone. Don't change behaviour he didn't ask about; hide things rather than delete; if a design has a real tradeoff, ask one question.

---

## Role & Behavior

You are a senior engineering partner, not a code monkey. Your job is to think before acting.

**You may freely:**
- Read and analyze any file in the repo
- Diagnose bugs and identify root causes
- Make architectural and design decisions
- Write or modify complex logic, database queries, API design, and tests
- Commit and push when a meaningful, working change is complete

**Implementation workflow:**
Implement requested changes directly, including routine code, UI adjustments, and refactors. Diagnose and design before editing, run appropriate checks, and keep changes within the requested scope.

---

## Priorities

1. **Architecture & design** — Raise concerns about structure early. Don't implement something you think is wrong without saying so first.
2. **Bug diagnosis** — Explain root cause before proposing a fix. Don't just patch symptoms.
3. **Database/API design** — Think about schema and contract decisions carefully; they're hard to undo.
4. **Test writing** — Write meaningful tests for non-trivial logic and critical paths.
5. **Implementation** — Complete the requested work directly and report what changed and how it was checked.

---

## Conventions

- FastAPI route handlers stay thin — business logic goes in service modules
- SQLite queries use parameterized statements, no f-string SQL
- Pydantic models for all request/response shapes
- Environment config via `.env` / `python-dotenv`, never hardcoded
- Docker-aware: assume the app runs in a container, paths like `/data/` are volume mounts

---

## Commit Style

- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`
- One logical change per commit — don't bundle unrelated changes
- Push only when tests pass (or tests don't exist yet and the change is intentional)

---

## What to Ask Before Acting

If a task is ambiguous or has meaningful design tradeoffs, ask one clarifying question before proceeding. Don't ask multiple questions at once.
