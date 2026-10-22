"""
set_log.py — Rackbook's own record of every set you log.

Hevy cannot store an RPE below 6 (or 6.5), so the workout posted to Hevy loses it. This keeps each set exactly as
it was entered on the log page, with the RPE as typed, so history (and later a per-lift RPE chart) can use it.
Rows are written once Hevy has accepted the workout. Weights are in kg, as typed.
"""
from __future__ import annotations

from typing import Any

from database import get_db


def rows_from_entry(entry: dict[str, Any], hevy_workout_id: str | None) -> list[dict[str, Any]]:
    """One row per set of a logged workout. set_number counts from 1 within the exercise, warm-ups included."""
    rows = []
    for exercise in entry.get("exercises") or []:
        for number, s in enumerate(exercise.get("sets") or [], start=1):
            rows.append({
                "hevy_workout_id": hevy_workout_id,
                "workout_title": entry.get("title"),
                "workout_start": entry["start_time"],
                "workout_end": entry.get("end_time"),
                "exercise_template_id": exercise["exercise_template_id"],
                "exercise_title": exercise.get("title"),
                "set_number": number,
                "set_type": s.get("type") or "normal",
                "weight_kg": s.get("weight_kg"),
                "reps": s.get("reps"),
                "rpe": s.get("rpe"),
                "is_ts": 1 if s.get("ts") else 0,
            })
    return rows


def record(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with get_db() as conn:
        conn.executemany(
            """
            INSERT INTO logged_sets (
                hevy_workout_id, workout_title, workout_start, workout_end, exercise_template_id, exercise_title,
                set_number, set_type, weight_kg, reps, rpe, is_ts
            ) VALUES (
                :hevy_workout_id, :workout_title, :workout_start, :workout_end, :exercise_template_id, :exercise_title,
                :set_number, :set_type, :weight_kg, :reps, :rpe, :is_ts
            )
            """,
            rows,
        )


def main_lifts(titles: dict[str, str]) -> list[dict[str, Any]]:
    """
    One entry per key of titles (e.g. squat -> its Hevy title), in that order: the movement logged under that title with
    the most working sets that have an RPE. exercise_template_id is None while nothing is logged for it yet.
    """
    out = []
    with get_db() as conn:
        for key, title in titles.items():
            row = conn.execute(
                """
                SELECT exercise_template_id, COUNT(*) AS sets, COUNT(DISTINCT workout_start) AS sessions
                FROM logged_sets
                WHERE exercise_title = ? AND set_type NOT IN ('warmup', 'dropset') AND rpe IS NOT NULL
                GROUP BY exercise_template_id
                ORDER BY sets DESC
                LIMIT 1
                """,
                (title,),
            ).fetchone()
            out.append({
                "key": key,
                "title": title,
                "exercise_template_id": row["exercise_template_id"] if row else None,
                "sets": row["sets"] if row else 0,
                "sessions": row["sessions"] if row else 0,
            })
    return out


def for_exercise(exercise_template_id: str) -> list[dict[str, Any]]:
    """Every recorded set of one movement, oldest first."""
    with get_db() as conn:
        found = conn.execute(
            "SELECT * FROM logged_sets WHERE exercise_template_id = ? ORDER BY workout_start, id",
            (exercise_template_id,),
        ).fetchall()
    return [dict(r) for r in found]


def for_workouts(hevy_workout_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Recorded sets grouped by Hevy workout id, in the order they were logged."""
    ids = [i for i in hevy_workout_ids if i]
    if not ids:
        return {}
    with get_db() as conn:
        found = conn.execute(
            f"SELECT * FROM logged_sets WHERE hevy_workout_id IN ({','.join('?' * len(ids))}) ORDER BY id", ids
        ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in found:
        grouped.setdefault(r["hevy_workout_id"], []).append(dict(r))
    return grouped


def overlay_summary_rpe(summary: dict[str, Any], local_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    A summarized Hevy workout (workout_view.summarize_workout) with the RPEs Hevy dropped filled back in from our record.
    Same safety rule as overlay_exact_rpe: only when both sides hold the same sets, with the same reps and type, in order.
    """
    sets = [s for ex in summary["exercises"] for s in ex["sets"]]
    if not local_rows or len(sets) != len(local_rows):
        return summary
    if any(s.get("reps") != r.get("reps") or (s.get("type") or "normal") != r.get("set_type")
           for s, r in zip(sets, local_rows)):
        return summary
    for s, r in zip(sets, local_rows):
        if s.get("rpe") is None and r.get("rpe") is not None:
            s["rpe"] = r["rpe"]
    return summary


def overlay_exact_rpe(entries: list[dict[str, Any]], local_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Hevy history with the RPE Hevy could not store filled back in from our own record.

    A set's RPE is only filled when Hevy has none and we have one. Sets are matched by Hevy workout id and position
    within the workout. A workout is left exactly as Hevy has it unless both sides hold the same number of sets with
    the same reps and set type in the same order, so a mismatch can never put an RPE on the wrong set.
    """
    mine: dict[str, list[dict[str, Any]]] = {}
    for row in local_rows:
        if row.get("hevy_workout_id"):
            mine.setdefault(row["hevy_workout_id"], []).append(row)
    theirs: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        if entry.get("workout_id") in mine:
            theirs.setdefault(entry["workout_id"], []).append(index)
    out = [dict(e) for e in entries]
    for workout_id, indexes in theirs.items():
        rows = mine[workout_id]
        if len(rows) != len(indexes):
            continue
        if any(out[i].get("reps") != r.get("reps") or (out[i].get("set_type") or "normal") != r.get("set_type")
               for i, r in zip(indexes, rows)):
            continue
        for i, r in zip(indexes, rows):
            if out[i].get("rpe") is None and r.get("rpe") is not None:
                out[i]["rpe"] = r["rpe"]
    return out
