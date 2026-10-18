"""Pre-session soreness: 0 none, 1 mild, 2 moderate, 3 severe; pain is separate."""
from contextlib import closing
from database import get_db


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
