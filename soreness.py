"""Pre-session soreness: 0 none, 1 mild, 2 moderate, 3 severe; pain is separate."""
from contextlib import closing
from database import get_db


def patterns() -> dict[str, str]:
    """Use the same exact movement titles as fatigue analysis."""
    from progress import LIFT_TITLES
    return {LIFT_TITLES[key]: "bench_press" if key in ("bench", "press") else key
            for key in ("squat", "bench", "press", "deadlift")}


def editable(workout_id: str) -> bool:
    with closing(get_db()) as conn:
        return conn.execute("""SELECT 1 FROM logged_sets WHERE hevy_workout_id = ?
            UNION ALL SELECT 1 FROM session_soreness WHERE hevy_workout_id = ? LIMIT 1""",
            (workout_id, workout_id)).fetchone() is not None


def read(workout_id: str) -> dict:
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM session_soreness WHERE hevy_workout_id = ?", (workout_id,)).fetchone()
        saved = conn.execute("SELECT workout_start FROM logged_sets WHERE hevy_workout_id = ? LIMIT 1", (workout_id,)).fetchone()
    if row is None and saved is None:
        raise ValueError("No local record for this workout. Soreness editing is available for workouts saved through Rackbook.")
    return {key: {"level": row[key] if row else None, "pain": bool(row[key + "_pain"]) if row else False}
            for key in ("squat", "bench_press", "deadlift")}


def update(workout_id: str, ratings: dict) -> dict:
    """Patch only supplied patterns; retain workout identity and exact set records."""
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM session_soreness WHERE hevy_workout_id = ?", (workout_id,)).fetchone()
        saved = conn.execute("SELECT workout_start FROM logged_sets WHERE hevy_workout_id = ? LIMIT 1", (workout_id,)).fetchone()
        if row is None and saved is None:
            raise ValueError("No local record for this workout. Soreness editing is available for workouts saved through Rackbook.")
        current = {key: {"level": row[key] if row else None, "pain": bool(row[key + "_pain"]) if row else False}
                   for key in ("squat", "bench_press", "deadlift")}
        for key, value in ratings.items():
            current[key] = value or {"level": None, "pain": False}
        values = []
        for value in current.values():
            level, pain = value.get("level"), value.get("pain", False)
            values.extend((level, int(pain) if level is not None or pain else None))
        conn.execute("""INSERT INTO session_soreness
            (hevy_workout_id, workout_start, squat, squat_pain, bench_press, bench_press_pain, deadlift, deadlift_pain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hevy_workout_id) DO UPDATE SET
            squat=excluded.squat, squat_pain=excluded.squat_pain,
            bench_press=excluded.bench_press, bench_press_pain=excluded.bench_press_pain,
            deadlift=excluded.deadlift, deadlift_pain=excluded.deadlift_pain""",
            (workout_id, row["workout_start"] if row else saved["workout_start"], *values))
    return current


def record(workout_id: str | None, workout_start: str, ratings: dict) -> None:
    values = []
    for key in ("squat", "bench_press", "deadlift"):
        rating = ratings.get(key) or {}
        level, pain = rating.get("level"), rating.get("pain", False)
        # An untouched/cleared control is unknown, never zero soreness.
        values.extend((level, int(pain) if level is not None or pain else None))
    if all(value is None for value in values):
        return
    if not workout_id:
        raise ValueError("A saved workout id is required")
    with closing(get_db()) as conn, conn:
        conn.execute(
            """INSERT INTO session_soreness
               (hevy_workout_id, workout_start, squat, squat_pain,
                bench_press, bench_press_pain, deadlift, deadlift_pain)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(hevy_workout_id) DO NOTHING""",
            (workout_id, workout_start, *values),
        )
