import csv
import hashlib
import io
import os
import sqlite3


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_db() as conn:
        # Rename old blocks table (microcycle level) before executescript creates the new blocks table.
        # executescript issues an implicit COMMIT, which also commits this rename.
        try:
            conn.execute("ALTER TABLE blocks RENAME TO microcycles")
        except Exception:
            pass  # already renamed, or new DB (table doesn't exist yet)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fatigue_trial_snapshots (
                id TEXT PRIMARY KEY,
                session_key TEXT NOT NULL,
                exercise_template_id TEXT NOT NULL,
                workout_start TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prospective INTEGER NOT NULL,
                pain INTEGER NOT NULL,
                snapshot TEXT NOT NULL,
                completion TEXT,
                hevy_workout_id TEXT,
                UNIQUE(session_key, exercise_template_id)
            );
            CREATE TABLE IF NOT EXISTS fatigue_trial_starts (
                session_key TEXT NOT NULL,
                exercise_template_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY(session_key, exercise_template_id)
            );
            CREATE TABLE IF NOT EXISTS fatigue_trial_skips (
                hevy_workout_id TEXT NOT NULL,
                exercise_template_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                reason TEXT NOT NULL,
                PRIMARY KEY(hevy_workout_id, exercise_template_id)
            );
            CREATE TABLE IF NOT EXISTS fatigue_trial_notes (
                id INTEGER PRIMARY KEY,
                trial_id TEXT NOT NULL REFERENCES fatigue_trial_snapshots(id),
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fatigue_relationships (
                exercise_template_id TEXT PRIMARY KEY NOT NULL,
                patterns_json TEXT NOT NULL,
                reviewed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_soreness (
                hevy_workout_id TEXT PRIMARY KEY NOT NULL,
                workout_start TEXT NOT NULL,
                squat INTEGER CHECK(squat BETWEEN 0 AND 3),
                squat_pain INTEGER CHECK(squat_pain IN (0, 1)),
                bench_press INTEGER CHECK(bench_press BETWEEN 0 AND 3),
                bench_press_pain INTEGER CHECK(bench_press_pain IN (0, 1)),
                deadlift INTEGER CHECK(deadlift BETWEEN 0 AND 3),
                deadlift_pain INTEGER CHECK(deadlift_pain IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS mesocycles (
                id TEXT PRIMARY KEY,
                document TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_mesocycle ON mesocycles(active) WHERE active = 1;
            CREATE TABLE IF NOT EXISTS mesocycle_completions (
                mesocycle_id TEXT NOT NULL REFERENCES mesocycles(id),
                session_id TEXT NOT NULL,
                hevy_workout_id TEXT,
                workout_start TEXT NOT NULL,
                completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (mesocycle_id, session_id)
            );
            CREATE TABLE IF NOT EXISTS mesocycle_session_aliases (
                original_plan_id TEXT NOT NULL REFERENCES mesocycles(id),
                session_id TEXT NOT NULL,
                plan_id TEXT NOT NULL REFERENCES mesocycles(id),
                PRIMARY KEY (original_plan_id, session_id)
            );
            CREATE TABLE IF NOT EXISTS mesocycle_week_backups (
                plan_id TEXT PRIMARY KEY REFERENCES mesocycles(id),
                document TEXT NOT NULL,
                revision INTEGER NOT NULL,
                backed_up_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                total_weeks INTEGER NOT NULL,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id),
                name TEXT NOT NULL,
                behaviour TEXT NOT NULL CHECK(behaviour IN ('tm','e1rm','ddp','free')),
                display_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id),
                block_number INTEGER NOT NULL,
                label TEXT
            );

            CREATE TABLE IF NOT EXISTS microcycles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id),
                block_id INTEGER REFERENCES blocks(id),
                cycle_number INTEGER NOT NULL,
                label TEXT
            );

            CREATE TABLE IF NOT EXISTS days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL REFERENCES microcycles(id),
                day_number INTEGER NOT NULL,
                label TEXT
            );

            CREATE TABLE IF NOT EXISTS exercise_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_id INTEGER NOT NULL REFERENCES days(id),
                tier_id INTEGER NOT NULL REFERENCES tiers(id),
                hevy_exercise_id TEXT NOT NULL,
                hevy_exercise_name TEXT NOT NULL,
                slot_order INTEGER NOT NULL DEFAULT 0,
                wave_params TEXT,
                target_rpe REAL,
                source_params TEXT
            );

            CREATE TABLE IF NOT EXISTS active_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                program_id INTEGER NOT NULL REFERENCES programs(id),
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                current_cycle INTEGER NOT NULL DEFAULT 1,
                current_day INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','completed','abandoned'))
            );

            CREATE TABLE IF NOT EXISTS session_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                active_block_id INTEGER NOT NULL REFERENCES active_blocks(id),
                exercise_slot_id INTEGER NOT NULL REFERENCES exercise_slots(id),
                week_number INTEGER NOT NULL,
                day_number INTEGER NOT NULL,
                set_number INTEGER NOT NULL,
                set_type TEXT NOT NULL,
                planned_weight_kg REAL,
                actual_weight_kg REAL,
                reps INTEGER,
                target_rpe REAL,
                actual_rpe REAL,
                hevy_workout_id TEXT,
                logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS e1rm_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                active_block_id INTEGER NOT NULL REFERENCES active_blocks(id),
                exercise_slot_id INTEGER NOT NULL REFERENCES exercise_slots(id),
                e1rm_kg REAL NOT NULL,
                source TEXT NOT NULL
                    CHECK(source IN ('amrap','joker_avg','manual')),
                logged_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS hevy_exercise_cache (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                primary_muscle TEXT,
                cached_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rpe_chart (
                rpe  REAL NOT NULL,
                reps INTEGER NOT NULL,
                percentage REAL NOT NULL,
                PRIMARY KEY (rpe, reps)
            );

            CREATE TABLE IF NOT EXISTS training_max_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_template_id TEXT NOT NULL,
                e1rm_lb REAL NOT NULL,
                weight_lb REAL NOT NULL,
                reps INTEGER NOT NULL,
                rpe REAL NOT NULL,
                set_at TEXT NOT NULL,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exercise_refs (
                exercise_template_id TEXT PRIMARY KEY,
                e1rm_lb REAL,
                tm_lb REAL,
                basis TEXT NOT NULL DEFAULT 'e1rm' CHECK(basis IN ('e1rm','tm')),
                auto INTEGER NOT NULL DEFAULT 0,
                ls INTEGER NOT NULL DEFAULT 1,
                tm_pct REAL NOT NULL DEFAULT 0.95,
                step_kg REAL NOT NULL DEFAULT 2.5,
                step_lb REAL NOT NULL DEFAULT 5,
                bar_kg REAL NOT NULL DEFAULT 20,
                chain_kg REAL NOT NULL DEFAULT 0,
                rest_sec INTEGER,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS logged_sets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hevy_workout_id TEXT,
                workout_title TEXT,
                workout_start TEXT NOT NULL,
                workout_end TEXT,
                exercise_template_id TEXT NOT NULL,
                exercise_title TEXT,
                set_number INTEGER NOT NULL,
                set_type TEXT NOT NULL,
                weight_kg REAL,
                reps INTEGER,
                rpe REAL,
                is_ts INTEGER NOT NULL DEFAULT 0,
                recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_logged_sets_exercise ON logged_sets (exercise_template_id, workout_start);

            CREATE TABLE IF NOT EXISTS rpe_chart_assignments (
                exercise_template_id TEXT PRIMARY KEY,
                chart_group TEXT CHECK(chart_group IN ('squat', 'bench', 'deadlift', 'general')),
                revision INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS rpe_history_imports (
                hevy_workout_id TEXT NOT NULL,
                exercise_template_id TEXT NOT NULL,
                exercise_title TEXT NOT NULL,
                workout_title TEXT NOT NULL,
                workout_start TEXT NOT NULL,
                sets_json TEXT NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (hevy_workout_id, exercise_template_id)
            );

            CREATE TABLE IF NOT EXISTS body_measurements (
                date TEXT PRIMARY KEY,
                weight_kg REAL NOT NULL,
                lean_mass_kg REAL,
                fat_percent REAL,
                synced_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)

        try:
            conn.execute("ALTER TABLE exercise_slots ADD COLUMN source_params TEXT")
        except Exception:
            pass  # column already exists

        for ddl in (
            "ALTER TABLE exercise_refs ADD COLUMN ls INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE exercise_refs ADD COLUMN tm_pct REAL NOT NULL DEFAULT 0.95",
            "ALTER TABLE exercise_refs ADD COLUMN step_kg REAL NOT NULL DEFAULT 2.5",
            "ALTER TABLE exercise_refs ADD COLUMN step_lb REAL NOT NULL DEFAULT 5",
            "ALTER TABLE exercise_refs ADD COLUMN bar_kg REAL NOT NULL DEFAULT 20",
            "ALTER TABLE exercise_refs ADD COLUMN chain_kg REAL NOT NULL DEFAULT 0",
            "ALTER TABLE exercise_refs ADD COLUMN rest_sec INTEGER",
            "ALTER TABLE exercise_refs ADD COLUMN weight_unit TEXT CHECK(weight_unit IN ('kg', 'lb'))",
        ):
            try:
                conn.execute(ddl)
            except Exception:
                pass  # column already exists

        try:
            conn.execute(
                "ALTER TABLE microcycles ADD COLUMN block_id INTEGER REFERENCES blocks(id)"
            )
        except Exception:
            pass  # column already exists or table didn't exist yet

        _seed_rpe_chart(conn)
        from rpe_assignments import migrate_legacy
        migrate_legacy(conn)


_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_BUILTIN_RPE_CSV = os.path.join(_DATA_DIR, "rpe_chart.csv")
_USER_RPE_CSV = os.path.join(_DATA_DIR, "rpe_chart_user.csv")
_RPE_SOURCE_KEY = "rpe_chart_source"


def _rpe_csv_path() -> str:
    """The user's own table wins. RPE_CHART_PATH overrides it (used by tests); the built-in table is the fallback."""
    override = os.environ.get("RPE_CHART_PATH")
    if override:
        return override
    return _USER_RPE_CSV if os.path.exists(_USER_RPE_CSV) else _BUILTIN_RPE_CSV


def _seed_rpe_chart(conn: sqlite3.Connection) -> None:
    """Make the rpe_chart table match the chosen CSV, replacing it when the file changes.
    A hash of the file is kept in app_settings so an unchanged file is not reloaded on every start."""
    with open(_rpe_csv_path(), "rb") as f:
        raw = f.read()
    digest = hashlib.sha256(raw).hexdigest()
    stored = conn.execute("SELECT value FROM app_settings WHERE key = ?", (_RPE_SOURCE_KEY,)).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM rpe_chart").fetchone()[0]
    if count > 0 and stored is not None and stored[0] == digest:
        return
    rows = [
        (float(r["rpe"]), int(r["reps"]), float(r["percentage"]))
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8")))
    ]
    conn.execute("DELETE FROM rpe_chart")
    conn.executemany("INSERT INTO rpe_chart (rpe, reps, percentage) VALUES (?, ?, ?)", rows)
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_RPE_SOURCE_KEY, digest),
    )


def get_rpe_percentage(rpe: float, reps: int) -> float | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT percentage FROM rpe_chart WHERE rpe = ? AND reps = ?",
            (rpe, reps),
        ).fetchone()
    return float(row["percentage"]) if row else None
