# Workout save confirmation and scoped repair (2026-10-21)

Finish and save to Hevy opens a native modal showing the workout title, completed-set count and a list/count of unticked working sets excluded from the upload. Warm-ups do not enter the excluded working-set count. Keep training receives initial focus; Keep training and Escape close the modal without changing the draft. Existing RPE/TS validation remains before confirmation. Only Save to Hevy posts the captured entry. The existing saving lock prevents duplicate clicks, and a failed request retains the draft and advises checking Recent before retrying an uncertain save.

`workout_repair.py` is an explicit operator tool, with no app endpoint, editor, automatic sync or Hevy writes. Run it in the environment containing the actual production database and encrypted Hevy credentials. It reads one workout using `HevyClient.get_workout`, compares by Hevy ID, unique movement and set position, checks saved anchors and refuses conflicts or repeated movement identities. Exact local weights can match their original value or the existing whole-pound upload conversion. Existing rows (including exact RPE and TS) are never updated. New working rows retain Hevy weights/reps/types/RPE, including null RPE, and always have `is_ts=0`. Missing warm-ups are excluded.

Compare first:

```sh
python workout_repair.py WORKOUT_ID
```

Apply only after reviewing the comparison:

```sh
python workout_repair.py WORKOUT_ID --apply --backup /data/workout-repair-before.sqlite
```

The backup path must not exist. SQLite's backup API creates a consistent snapshot before insertion, while an immediate transaction serializes writers. Backup integrity and repaired records are checked before committing. Running the repair again adds nothing. It changes only `logged_sets`, preserving TS history, soreness, exercise refs and microcycle completion. A workout without any existing local records requires manual investigation and is refused. Position conflicts require manual investigation rather than guessed alignment.

Requested affected ID: `PsMpdA4heNB`. Production repair is pending access to its actual records. The checkout's `.env` points at `./rackbook.db`, which has no logged workouts. The local Docker container is `531bbb` using `/data/531bbb.db`, which has no `logged_sets` table. Neither is a verified source for this repair; neither was modified.

The user supplied production URL `http://192.168.68.3:8126/`; health and recent-workout reads succeed. Existing SSH authentication as `bross` is denied. The supplied ID is a Hevy share-page identifier, while the production API exposes UUID workout IDs. Reading the shared page exposed no workout metadata to establish an unambiguous UUID match. Do not assume the newest workout is the affected one. Repair stopped without any database or Hevy modifications; a verified UUID match and production filesystem access are still needed.

Checks: `node tests/test_log_save_confirmation.cjs` covers summary counts, warm-up exclusion, initial focus, cancellation, closed-dialog submission, repeated clicks, successful save and retained drafts on failures. Existing log and microcycle checks cover entry validation and checked-only payloads. `tests/test_workout_repair.py` uses mocked Hevy and disposable SQLite databases for preview/apply/repeat, preserved exact values and related records, unknown RPE/TS, backup preservation, warm-up exclusion and ambiguous/conflicting identities. Browser phone verification remains pending: the in-app browser timed out reaching the disposable localhost preview.
