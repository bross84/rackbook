# Fatigue integration handoff — 2026-10-30

## Current state

- Hevy Fatigue implements `recovery-confirmation-v1` daily recommendations and
  `pattern-recovery-v1` pattern monitoring. Daily recovery is gradual; missing or
  insufficient data shows Continue Training as Normal. Pattern displays separate
  exact soreness, residual decaying load and a gradual trend. See its README.
- Rackbook keeps its original `shared-trial-v0` movement-performance trial and
  additionally freezes `hf-recovery-shadow-v1` daily actions on **new** observations.
  The pinned source model is `recovery-confirmation-v1` in `hevy_recovery_model.py`.
- The two models have different outputs: a daily training action is not a
  movement-performance prediction. Their results/metrics must not be conflated.
- Existing trial snapshots, completions, notes, cohort results and prior shadow
  outputs remain immutable. No backfill, automatic retries or historical repair.
- The trial remains controlled by the existing Performance model trial setting.
  Shadow outputs remain hidden until a workout is saved. Late observations are
  excluded from prospective counts, including a start marker arriving during capture.

## Reported homelab incident

The user updated Rackbook and confirmed both installed model versions, an enabled
trial (`preview=false`), and an available daily check-in bridge on October 30.
Two saved prospective observations from that day's workout had frozen shadow
status `unavailable`. A subsequent read-only call to `capture("2026-10-30", now)`
returned `available` without emitting an exception through the supplied tracer.

The original cause is **unknown**: the old code swallowed capture exceptions.
A successful later probe does not prove why an earlier capture failed. Preserve
those two unavailable records; do not recalculate them using later inputs and do
not resave/recreate the real workout as a test.

## New failure logging

`fatigue_trial_smoother.log_failure` writes WARNING messages to standard Python
logging, visible in Docker logs. Stable event names:

- `smoother_capture_unavailable`: source configuration, date validation, database
  open/read, history preparation, model calculation, or unexpected caller failure.
- `smoother_shadow_store_failed`: legacy recording succeeded but its additional
  shadow row could not be stored.

Each line includes model/source versions, validated date, phase, safe reason,
exception class and SQLite symbolic error name when available. Example:

```text
smoother_capture_unavailable model=hf-recovery-shadow-v1 source_model=recovery-confirmation-v1 date=2026-10-30 phase=read_workouts reason=missing_table:workout_sessions exception=OperationalError sqlite_error=SQLITE_ERROR
```

Missing configuration is `phase=configuration reason=bridge_not_configured`.
Locked/busy database reads use `reason=database_busy`; open errors include the
SQLite code (for example `SQLITE_CANTOPEN`). Model input errors identify their
phase and type without printing the offending data. Invalid dates are masked.
There are no raw ratings, workout inputs, credentials, database paths, arbitrary
exception text or traceback locals in these log messages. Available results and
normal `insufficient_data` results do not emit failure warnings.

Logging changes no stored payloads, model rules, versions, schemas or existing
records. A future failure can be diagnosed; the earlier two failures cannot be
explained retroactively by this change.

## Update the homelab

This follow-up requires rebuilding **Rackbook**; Hevy Fatigue changes in this
follow-up are documentation only. Retain the existing data volumes and server
`.env`; take the normal app-data backup before deployment.

```bash
cd /var/lib/docker-data/AppData/rackbook
git pull --ff-only
docker compose -f docker-compose.yml -f docker-compose.fatigue-bridge.yml up -d --build rackbook
```

Use both Compose files on every update. Preserve the verified
`HEVY_FATIGUE_DATA_VOLUME` value in the server's `.env`. Do not use the local
preview Compose file on the homelab. It has different container/volume names.

Confirm installation and watch logs:

```bash
docker exec rackbook python -c "import fatigue_trial_smoother as s; print(s.VERSION, s.model.MODEL_VERSION, callable(s.log_failure))"
docker logs --since 1h --timestamps rackbook 2>&1 | grep -E 'smoother_capture_unavailable|smoother_shadow_store_failed'
# Follow while recording the next new observation:
docker logs --follow --since 5m --timestamps rackbook
```

Expected version output ends with `True`. No matching warning lines simply means
no matching failure has been logged in the retained period; silence alone does
not prove the model recorded successfully. Docker log retention can remove old
lines, so collect the relevant time range when an incident occurs.

## Read-only verification

```bash
curl -fsS http://localhost:8126/fatigue-trial/settings
curl -fsS "http://localhost:8126/fatigue-trial/daily?day=$(date +%F)"
docker exec -i rackbook python - <<'PY'
from datetime import date, datetime, timezone
import fatigue_trial_smoother as s
# Use the athlete's local check-in date. The server/container may use UTC.
day = date.today().isoformat()
r = s.capture(day, datetime.now(timezone.utc))
print({k: r.get(k) for k in ('as_of_date', 'status', 'data_sufficient', 'model_version', 'source_model_version')})
PY
```

This probe reads inputs/calculates in memory; it never stores a trial record.
Use an explicit YYYY-MM-DD if the container date differs from the athlete's local
check-in date. `available` means the model has sufficient input now;
`insufficient_data` is normal coverage/reacquisition behavior; `unavailable` means
capture failed and should now have an accompanying warning.

For actual recording confirmation, use the next **new real workout**. Enter
pre-movement scores/plans, wait for Trial recorded / Result hidden before lifting,
then save normally. On `/trial`, expand its saved session: the original prediction
and separate frozen smoother action should both be present. Existing recorded
drafts are not upgraded or backfilled. Check `/fatigue-trial/dashboard` for the
new entry's `model_version=shared-trial-v0`, its `shadow.model_version`, `status`
and `prospective` flag. An unavailable frozen entry stays unavailable even if a
fresh probe succeeds.

## Continue on another PC

Pull both repositories (or clone them into sibling folders) and read these files
before changing anything:

1. Rackbook `AGENTS.md`, `docs/rackbook-context.md`, `docs/backlog.md`, this guide,
   and `docs/fatigue-trial.md`.
2. Hevy Fatigue `CLAUDE.md`, `docs/hevy-context.md`, `README.md`, and
   `docs/recommendation-replay.md`.

```bash
# Run within each existing checkout:
git pull --ff-only
```

Both production databases and encryption keys live on the homelab volumes, not
in Git. Historical replay exports and scratch files under Hevy Fatigue's
`data/analysis/` are intentionally ignored and will not appear on another PC.
Use consistent, read-only database backups for any new retrospective analysis;
never initialize/migrate production databases merely to inspect them. Mock Hevy
for tests; never create a real workout to test recording.

Rackbook development checks:

```bash
python -m venv .venv
# Activate .venv using the platform's normal activation command.
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t .
node tests/test_trial_dashboard.cjs
node tests/test_trial_shadow_ui.cjs
node tests/test_log_fatigue_trial.cjs
node tests/test_trial_settings.cjs
```

Hevy Fatigue development checks:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/test_recommendation_ui.cjs
```

Next work: deploy the logging update, collect new prospective observations, and
capture warning lines if unavailability recurs. Classifiable movement outcomes
remain necessary before judging the models. Do not tune rules to the two failed
captures, rewrite frozen outcomes or merge the cohorts.
