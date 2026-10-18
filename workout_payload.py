"""
workout_payload.py — Pure builder for the body of Hevy's POST /v1/workouts.
No DB access, no HTTP calls, no side effects.

Hevy's rules (docs/hevy-api.md): snake_case keys wrapped in {"workout": {...}}; set type is one of
warmup / normal / failure / dropset; rpe is one of 6, 7, 7.5, 8, 8.5, 9, 9.5, 10 or null.
An RPE Hevy cannot store (below 6, or 6.5) is simply left blank.
Weights arrive in kg. When weight_unit is supplied, round to whole units in that
display unit before posting kg to Hevy. Local records retain the entered weights.
"""
from __future__ import annotations

from datetime import datetime
from math import floor, inf, nextafter
from typing import Any

SET_TYPES = ("warmup", "normal", "failure", "dropset")
HEVY_RPE_VALUES = (6.0, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0)
LB_PER_KG = 2.20462262185


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"Invalid timestamp: {value!r}") from exc


def build_hevy_workout(entry: dict[str, Any]) -> dict[str, Any]:
    """
    Convert kg inputs into Hevy's request body, rounding in the requested display unit.
    Raises ValueError if the workout can't be sent.
    """
    title = (entry.get("title") or "").strip()
    weight_unit = entry.get('weight_unit')
    if weight_unit not in (None, 'kg', 'lb'):
        raise ValueError('Weight unit must be kg or lb.')
    if not title:
        raise ValueError("Workout needs a title.")

    start = _parse_time(entry.get("start_time"))
    end = _parse_time(entry.get("end_time"))
    if end < start:
        raise ValueError("Workout end time is before its start time.")

    exercises = []
    for raw_exercise in entry.get("exercises") or []:
        template_id = (raw_exercise.get("exercise_template_id") or "").strip()
        name = raw_exercise.get("title") or template_id or "exercise"
        if not template_id:
            raise ValueError(f"{name} has no Hevy exercise id.")

        sets = []
        for number, raw_set in enumerate(raw_exercise.get("sets") or [], start=1):
            set_type = raw_set.get("type") or "normal"
            if set_type not in SET_TYPES:
                raise ValueError(f"{name} set {number}: unknown set type {set_type!r}.")

            weight_kg = raw_set.get("weight_kg")
            if weight_kg is not None and weight_kg < 0:
                raise ValueError(f"{name} set {number}: weight can't be negative.")
            if weight_kg is not None and weight_unit is not None:
                factor = LB_PER_KG if weight_unit == 'lb' else 1
                amount = float(weight_kg) * factor
                # A kg -> lb round trip can land one float below an exact .5.
                if weight_unit == 'lb':
                    amount = nextafter(amount, inf)
                weight_kg = floor(amount + 0.5) / factor
            reps = raw_set.get("reps")
            if reps is not None and reps < 0:
                raise ValueError(f"{name} set {number}: reps can't be negative.")

            rpe = raw_set.get("rpe")
            if rpe is not None and not 0 <= float(rpe) <= 10:
                raise ValueError(f"{name} set {number}: RPE must be between 0 and 10.")
            if rpe is not None and float(rpe) not in HEVY_RPE_VALUES:
                rpe = None

            sets.append(
                {
                    "type": set_type,
                    "weight_kg": float(weight_kg) if weight_kg is not None else None,
                    "reps": reps,
                    "rpe": float(rpe) if rpe is not None else None,
                }
            )
        if not sets:
            continue

        exercise: dict[str, Any] = {"exercise_template_id": template_id, "sets": sets}
        notes = (raw_exercise.get("notes") or "").strip()
        if notes:
            exercise["notes"] = notes
        exercises.append(exercise)

    if not exercises:
        raise ValueError("Add at least one completed set before saving.")

    workout: dict[str, Any] = {
        "title": title,
        "start_time": entry["start_time"],
        "end_time": entry["end_time"],
        "exercises": exercises,
    }
    description = (entry.get("description") or "").strip()
    if description:
        workout["description"] = description
    return {"workout": workout}
