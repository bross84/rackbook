"""Time/workload comparability checks, not a physiological recovery estimate."""
from datetime import datetime, timedelta, timezone
from statistics import median


def timestamp(value):
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def days(later, earlier):
    return (later - earlier).total_seconds() / 86400 if earlier is not None else None


def typical(points, field, minimum=3):
    values = [p[field] for p in points if p[field] is not None]
    return median(values) if len(values) >= minimum else None


def build_context(points, previous, recent, latest_ts, rows, links, target_id, pattern, now):
    events = []
    for row in rows:
        at = timestamp(row.get("workout_start"))
        if at is None or at > now or row.get("set_type") == "warmup":
            continue
        exercise_id = row.get("exercise_template_id") or target_id
        events.append(dict(at=at, exercise_id=exercise_id,
            title=row.get("exercise_title") or exercise_id,
            workout_id=row.get("hevy_workout_id") or at.isoformat()))
    exposures = {e["at"] for e in events if pattern and pattern in links.get(e["exercise_id"], [])}
    # A saved TS establishes an exact-movement exposure even if its local set write failed.
    if pattern and pattern in links.get(target_id, []):
        exposures.update(timestamp(p["start_time"]) for p in points)
    previous_at = None
    for point in points:
        at = timestamp(point["start_time"])
        earlier = [t for t in exposures if t < at]
        relevant = [e for e in events if at - timedelta(days=7) <= e["at"] < at]
        unreviewed = any(e["exercise_id"] not in links for e in relevant)
        related = [e for e in relevant if e["exercise_id"] != target_id
                   and pattern and pattern in links.get(e["exercise_id"], [])]
        # Unknown mappings cannot be silently represented as zero related work.
        unknown_spacing = any(e["exercise_id"] not in links and
            (max(earlier) if earlier else at - timedelta(days=21)) <= e["at"] < at for e in events)
        point.update(days_since_exercise=days(at, previous_at),
            days_since_pattern=days(at, max(earlier)) if earlier and not unknown_spacing else None,
            related_sets_7_before=len(related) if pattern and not unreviewed else None,
            related_workouts_7_before=len({e["workout_id"] for e in related}) if pattern and not unreviewed else None)
        previous_at = at

    assessed = previous + recent
    start = min((timestamp(p["start_time"]) for p in assessed), default=None)
    if start is None and points:
        start = timestamp(points[-12:][0]["start_time"])
    pending = {}
    for event in events:
        if start and start - timedelta(days=21) <= event["at"] <= now and event["exercise_id"] not in links:
            pending[event["exercise_id"]] = event["title"]
    last = points[-1] if points else None
    latest = latest_ts
    context = dict(
        reference_exercise_days=typical(previous, "days_since_exercise"),
        reference_pattern_days=typical(previous, "days_since_pattern"),
        reference_related_sets_7=typical(previous, "related_sets_7_before"),
        recent_exercise_days=typical(recent, "days_since_exercise"),
        recent_pattern_days=typical(recent, "days_since_pattern"),
        recent_related_sets_7=typical(recent, "related_sets_7_before"),
        latest_exercise_days=latest["days_since_exercise"] if latest else None,
        latest_pattern_days=latest["days_since_pattern"] if latest else None,
        latest_related_sets_7=latest["related_sets_7_before"] if latest else None,
        current_exercise_days=days(now, timestamp(last["start_time"])) if last else None,
        pending_mappings=[dict(exercise_template_id=key, title=value) for key, value in sorted(pending.items())],
        additional_work_since_ts=False, extra_sets_eligible=False, block_reasons=[])
    reasons = context["block_reasons"]
    if not pattern:
        reasons.append("No movement-pattern context is available for this exercise.")
    if pending:
        reasons.append("Review related-movement mappings before adding sets.")
    for key, label, both_directions in (
        ("exercise_days", "Exact-exercise spacing", False),
        ("pattern_days", "Related-pattern spacing", True),
        ("related_sets_7", "Related seven-day set workload", True),
    ):
        reference = context["reference_" + key]
        values = [context["recent_" + key], context["latest_" + key]]
        if reference is None or any(value is None for value in values):
            reasons.append(label + " has insufficient comparison history.")
            continue
        floor = 2 if key == "related_sets_7" else 1
        tolerance = max(floor, abs(reference) * .25)
        if any((abs(value - reference) if both_directions else value - reference) > tolerance for value in values):
            reasons.append(label + " differs from the baseline; hold extra sets until the context is comparable.")
    normal = context["reference_exercise_days"]
    current = context["current_exercise_days"]
    if normal is not None and current is not None and current - normal > max(1, normal * .25):
        reasons.append("The current break is longer than usual; a past successful session does not justify extra sets now.")
    if latest:
        assessed_at = timestamp(latest["start_time"])
        additional_target = any(timestamp(p["start_time"]) > assessed_at for p in points)
        additional_related = any(e["at"] > assessed_at and pattern and pattern in links.get(e["exercise_id"], []) for e in events)
        context["additional_work_since_ts"] = additional_target or additional_related
        if context["additional_work_since_ts"]:
            reasons.append("Additional target or related work occurred after the latest assessed TS; reassess before adding sets.")
    return context
