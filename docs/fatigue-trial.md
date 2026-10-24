# Optional shared-model trial v0

This is the pre-merge trial, not a consolidation or a validated fatigue measure. Both apps remain operational. The setting is disabled by default; enable **Optional model trial** on the log's start screen. Existing workload scores and TS trends remain separate.

## Recording and review

Select movement soreness/pain answers and enter intended working sets. With the trial enabled, each movement records automatically after a 1.5-second pause in edits once soreness, planned reps, RPE and weight are available. No per-movement record button is required. The server-timed immutable snapshot includes observations, the daily check-in actually read, exercise-specific history, workload/spacing context, RPE table and model version. Wait for **Trial recorded · Result hidden** before lifting. Later edits do not replace the original snapshot. Unknown soreness stays unknown; incomplete plans wait for input. Failed recording leaves logging available and retries on the next pre-set edit. Concurrent requests are suppressed and existing snapshots are reused. The first working-set tick is recorded independently; unticking does not erase it. Automatic recording skips movements already started; server-marked late entries, already saved sessions and entries more than 18 hours after workout start are excluded from prospective evaluation. Instrumentation cannot establish that an unlogged physical set has not happened: enter scores before lifting, not just before ticking.

Successful workout saving reveals frozen expected/observed classifications. Missing, removed or incompatible working sets are unclassified. Corrections and suggested/actual training changes are append-only notes, never replacements for original predictions. Enabled trials record missing assessments when a workout is saved. Trial failures are caught after normal Hevy/local/TS/microcycle saving and must never cause a second Hevy post.

`GET /fatigue-trial/comparisons` retains results after navigation. `GET /fatigue-trial/evaluation` separates model-version/exact-exercise/strength-hypertrophy cohorts, compares candidate/subjective-only/always-usual baselines and reports coverage, missed below-usual sessions and unnecessary warnings. Review is due six weeks after first recording; fewer than 12 eligible predictions or absence of either outcome remains inconclusive. Notes record interventions; no causal benefit is claimed.

## Frozen experimental rules

- Movement soreness retains its original 0–3 scale, daily ratings their original 0–4 scale, and unknown remains null. Daily regional soreness is context rather than a second movement-soreness input. Pain/injury and daily nonzero joint concerns remain separate from predictions.
- Moderate/severe movement soreness or daily tiredness/poor recovery 3–4 predicts possible below-usual performance only with complete evidence/context. Otherwise uncertain. Complete low ratings support near usual. Exposure alone never recommends adding work.
- Reference: latest three eligible earlier exact-exercise exposures. A 21-day gap resets collection. Duplicate identities remain unresolved. Changed exercise order is incompatible when recorded. Today's workload/spacing reuse `fatigue_context` tolerances (25%, one-day/two-set floors) against the latest three earlier exposures. Unknown related-movement mappings are never zero workload.
- Strength: exactly one marked TS, equal reps, RPE within one point; an e1RM fall of at least 3% is below usual. Recording-time RPE table is frozen for reference and outcome. TS flags are never inferred from imports.
- Hypertrophy: first working set, normal type, no TS, same load within 0.01 kg, RPE within one point. At least one fewer rep or equal reps with at least one higher RPE is below usual. Incompatible outcomes remain unclassified. Lower-load back-off work cannot substitute for a matched first set.
- Across sessions: existing strength rules retain their 12-session/paired-data/context gates. Non-TS shows performance, effort, dose and soreness points; review/maintain-monitor waits for 12 classified comparisons and three recent soreness records. Three consecutive below-usual comparisons supports review. No automatic progression or synthetic TS.

Rule changes require a new `MODEL_VERSION` and evaluation cohort. Original availability of edited historical observations, exercise mappings and settings cannot be reconstructed; replay carries that limitation.

## Read-only daily bridge

Set server-only `HEVY_FATIGUE_DB_PATH` through a read-only Docker mount. The bridge selects only `daily_readiness` ratings, never credentials, and never initializes/writes the sibling database. `GET /fatigue-trial/daily?day=YYYY-MM-DD` returns original values/source date/fetch time and available/stale/unavailable. Rest-day records remain in Hevy Fatigue. Its date-only schema cannot prove historical same-day timing; prospective snapshots freeze values actually read.

On the homelab add a Compose override mounting the actual sibling volume/directory at `/bridge:ro` and set the database path under it. Include SQLite WAL/SHM sidecars for a live WAL database, or mount a consistent SQLite backup export. The existing Tailscale endpoint and port 8126 remain the gym entry point.

For an existing Docker named volume, `docker-compose.fatigue-bridge.yml` provides the read-only mount (including WAL sidecars). First verify the volume name and `/data/hevy_fatigue.db` in the running sibling container. Set `HEVY_FATIGUE_DATA_VOLUME` to that verified volume, then use both Compose files when updating Rackbook. The external-volume declaration refuses to create an empty replacement. Retain the variable and the override in the homelab's normal update configuration so a later update does not remove the bridge.

```sh
HEVY_FATIGUE_DATA_VOLUME=<verified-existing-volume> docker compose -f docker-compose.yml -f docker-compose.fatigue-bridge.yml up -d --build rackbook
```

## Offline inventory and replay

Obtain SQLite backups on the hosts actually running the apps and record deployed image/code revisions. A checkout HEAD is not proof of deployed version. Never run importers or migrations against production for analysis.

```powershell
.venv/Scripts/python.exe fatigue_trial_replay.py --rackbook <rackbook-backup.db> --hevy <hevy-backup.db> --output data/replay-2026-10-23 --rackbook-version <deployed-sha-or-unknown> --hevy-version <deployed-sha-or-unknown>
```

Use a new output directory. The tool creates consistent backups, records hashes/time/version provenance, inventories missing evidence and reconciles by workout/exercise IDs. Exact local weights/RPE/TS survive. Ambiguities/duplicates/edits remain unresolved. Nothing is imported into either app. `comparison.json` contains chronological earlier-only examples and separate strength/hypertrophy baseline metrics. Imported-only workouts remain coverage evidence rather than invented local TS/soreness. Sparse results are inconclusive.

Add `--legacy-repo <version-pinned-hevy-source>` and `--legacy-python <its-runtime>` to run the sibling's actual Today/fatigue/pattern formulas separately. Alternatively invoke `fatigue_trial_legacy.py` in its Docker runtime with source/snapshots/output mounted. The adapter uses disposable copies, excludes target-day workouts (HF sets have only dates), truncates future check-ins and freezes the sibling clock. It calls calculations directly without startup/migrations/importers and blocks outbound sockets. Unlike outputs retain their own semantics. Incompatible runtimes/schemas show unavailable rather than substitute formulas. Current settings/mappings and later historical edits remain uncertain.

## Docker Desktop and remaining validation

`docker compose -f docker-compose.local.yml up -d --build` updates the existing `531bbb` container on port 8126, retaining external volume `531bbb-ar_531bbb-data` and `/data/531bbb.db`. The standard homelab Compose file is unchanged. Before updating, use SQLite backup inside the running container and retain its previous image tag. Local Compose disables Hevy writes for preview checks; remove `RACKBOOK_READ_ONLY_PREVIEW` when intentionally using it as a real logger. Homelab Compose does not set it.

Available local Rackbook data had zero local sets/TS, and the Hevy Fatigue file was empty. Meaningful live-data reconciliation/replay requires homelab snapshots. Phone usability and prospective collection remain necessary before a merge decision.
