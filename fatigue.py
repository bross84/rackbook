"""Versioned, descriptive TS trend rules. Pure analysis; never changes prescriptions.

Thresholds are provisional product rules, not validated fatigue/recovery cutoffs.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from math import isfinite
from statistics import median

from database import get_db

MODEL_VERSION = "ts-trends-v2"
BASELINE_SESSIONS = 12
WINDOW_SESSIONS = 6
MIN_PAIRED_PER_WINDOW = 5
GAP_DAYS = 21
CHANGE_PCT = 3.0
BW_CHANGE_PCT = 1.0
LB_PER_KG = 2.20462


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def _positive(value):
    return isinstance(value, (int, float)) and isfinite(value) and value > 0


def _change(before, after):
    return (after / before - 1) * 100 if before else None


def analyze(ts_rows, set_rows, observations, measurements, *, pattern=None, now=None):
    now = now or datetime.now(timezone.utc)
    # Normalize timestamps, use only saved data known as of assessment, one point/session.
    sessions = {}
    for row in set_rows:
        at = _time(row.get("workout_start"))
        if at is None or at > now or row.get("set_type") == "warmup":
            continue
        item = sessions.setdefault(at, {"sets": [], "ts": None, "workout_id": None})
        item["sets"].append(row)
        item["workout_id"] = row.get("hevy_workout_id") or item["workout_id"]
    for row in ts_rows:
        at = _time(row.get("set_at"))
        if at is None or at > now or not _positive(row.get("e1rm_lb")):
            continue
        item = sessions.setdefault(at, {"sets": [], "ts": None, "workout_id": None})
        item["ts"] = row  # latest recorded TS if a session has duplicate entries
    obs = {r["hevy_workout_id"]: r for r in observations}
    weights = {}
    for row in measurements:
        at = _time(row.get("date"))
        if at and at <= now and _positive(row.get("weight_kg")):
            weights[at.date()] = row["weight_kg"]
    points = []
    for at, item in sorted(sessions.items()):
        ts = item["ts"]
        window = [(day, value) for day, value in weights.items() if at.date() - timedelta(days=6) <= day <= at.date()]
        bw = sum(v for _, v in window) / len(window) if len(window) >= 2 else None
        observation = obs.get(item["workout_id"], {})
        working = item["sets"]
        rpes = [r["rpe"] for r in working if r.get("rpe") is not None]
        reps = [r["reps"] for r in working if r.get("reps") is not None]
        rolling_sets = sum(len(value["sets"]) for when, value in sessions.items() if at - timedelta(days=7) < when <= at)
        points.append(dict(dose_complete=bool(working) and all(r.get("reps") is not None and r.get("rpe") is not None for r in working), rolling_sets_7=rolling_sets, start_time=at.isoformat(), e1rm_lb=ts["e1rm_lb"] if ts else None,
            ts_reps=ts["reps"] if ts else None, ts_rpe=ts["rpe"] if ts else None,
            bodyweight_kg=bw, bw_readings=len(window),
            relative_e1rm=(ts["e1rm_lb"] / LB_PER_KG / bw) if ts and bw else None,
            working_sets=len(working) if working else None, total_reps=sum(reps) if reps else None,
            median_reps=median(reps) if reps else None, median_rpe=median(rpes) if rpes else None,
            soreness=observation.get(pattern) if pattern else None,
            pain=bool(observation.get(pattern + "_pain")) if pattern else False))
    baseline_start = 0
    for i in range(1, len(points)):
        if (_time(points[i]["start_time"]) - _time(points[i-1]["start_time"])).total_seconds() >= GAP_DAYS * 86400:
            baseline_start = i
    active = points[baseline_start:]
    stale = bool(active and (now - _time(active[-1]["start_time"])).total_seconds() >= GAP_DAYS * 86400)
    if stale:
        active = []
    comparable = []
    latest_ts = next((p for p in reversed(active) if p["e1rm_lb"] is not None), None)
    if latest_ts:
        comparable = [p for p in active if p["e1rm_lb"] is not None and p["ts_reps"] == latest_ts["ts_reps"]
                      and abs(p["ts_rpe"] - latest_ts["ts_rpe"]) <= 1]
    def complete(point):
        return point["bodyweight_kg"] is not None and point["soreness"] is not None and point["dose_complete"]

    # Require observations in both halves; recent check-ins cannot validate old sparse history.
    previous_window = comparable[-BASELINE_SESSIONS:-WINDOW_SESSIONS]
    recent_window = comparable[-WINDOW_SESSIONS:]
    previous = [p for p in previous_window if complete(p)]
    recent = [p for p in recent_window if complete(p)]
    recent_sessions = active[-3:]
    rated = [p["soreness"] for p in recent_sessions if p["soreness"] is not None]
    stale_ts = bool(latest_ts and (now - _time(latest_ts["start_time"])).total_seconds() >= GAP_DAYS * 86400)
    ready = (len(comparable) >= BASELINE_SESSIONS and len(previous) >= MIN_PAIRED_PER_WINDOW
             and len(recent) >= MIN_PAIRED_PER_WINDOW and len(rated) == 3 and not stale_ts)
    collection = dict(ready=ready, sessions=len(comparable), required_sessions=BASELINE_SESSIONS,
        previous_paired=len(previous), recent_paired=len(recent), required_paired_per_window=MIN_PAIRED_PER_WINDOW,
        window_sessions=WINDOW_SESSIONS, recent_ratings=len(rated), required_recent_ratings=3)
    result = dict(model_version=MODEL_VERSION, pattern=pattern, as_of=now.isoformat(),
        baseline_start=active[0]["start_time"] if active else None, gap_reset=baseline_start > 0 or stale,
        comparable_sessions=len(comparable), needed_sessions=BASELINE_SESSIONS, collection=collection,
        status="building_baseline", action="collect",
        message="Collecting your baseline. Charts show your recorded history; interpretations start after 12 comparable marked-TS sessions with enough BW, soreness and set data.",
        reasons=[], e1rm_change_pct=None, bw_change_pct=None, relative_change_pct=None,
        sets_change=None, recent_sets=None, recent_soreness=None, points=points)
    if stale:
        result["message"] = "No movement session in 21 days. Start a fresh baseline when training resumes; previous observations remain on the charts."
    pattern_observations = [r for r in observations if pattern and _time(r.get("workout_start"))
                            and now - timedelta(days=GAP_DAYS) < _time(r["workout_start"]) <= now
                            and (r.get(pattern) is not None or r.get(pattern + "_pain") is not None)]
    latest_pattern = max(pattern_observations, key=lambda r: _time(r["workout_start"])) if pattern_observations else None
    if (latest_pattern and latest_pattern.get(pattern + "_pain")) or any(p["pain"] for p in recent_sessions):
        result.update(status="pain_flag", action="review_pain", message="Pain or injury was flagged in a recent check-in. This is a recorded flag, separate from the trend model.")
        return result
    if stale_ts:
        result["message"] = "The latest marked TS is over 21 days old. Record fresh TS results before using trend suggestions."
        return result
    if not ready:
        if len(comparable) >= BASELINE_SESSIONS:
            result["message"] = "You have 12 comparable TS sessions. Keep collecting matched BW, soreness and set data before interpretations begin."
        return result
    # All comparisons use the same matched observations (at least five in each group of six).
    base = median(p["e1rm_lb"] for p in previous)
    delta = _change(base, median(p["e1rm_lb"] for p in recent))
    decline = delta <= -CHANGE_PCT and all(p["e1rm_lb"] < base for p in recent[-3:])
    result.update(status="declining" if decline else "improving" if delta >= CHANGE_PCT else "stable",
                  action="hold", message="Keep the current sets while monitoring the next sessions.", e1rm_change_pct=delta)
    result["reasons"].append("Provisional interpretation: matched medians from the latest six versus previous six comparable TS sessions. More observations do not guarantee accuracy.")
    comparison_points = previous + recent
    result["bw_change_pct"] = _change(median(p["bodyweight_kg"] for p in previous), median(p["bodyweight_kg"] for p in recent))
    result["relative_change_pct"] = _change(median(p["relative_e1rm"] for p in previous), median(p["relative_e1rm"] for p in recent))
    result["reasons"].append("BW is the trailing seven-day mean, with at least two weigh-ins per TS session. e1RM/BW is context, not a correction or explanation.")
    result["sets_change"] = median(p["working_sets"] for p in recent) - median(p["working_sets"] for p in previous)
    result["recent_sets"] = median(p["working_sets"] for p in recent)
    result["reasons"].append(
        "Median session dose: "
        f"{median(p['working_sets'] for p in previous):g} to {result['recent_sets']:g} sets; "
        f"{median(p['total_reps'] for p in previous):g} to {median(p['total_reps'] for p in recent):g} reps."
    )
    result["recent_soreness"] = median(rated)
    high = sum(value >= 2 for value in rated) >= 2
    low = all(value <= 1 for value in rated)
    def cadence(group):
        first, last = _time(group[0]["start_time"]), _time(group[-1]["start_time"])
        exposures = sum(first <= _time(p["start_time"]) <= last for p in active)
        return (last - first).total_seconds() / max(1, exposures - 1)

    losing_bw = result["bw_change_pct"] <= -BW_CHANGE_PCT
    if decline and high:
        result.update(action="reduce_set", message="Consider one fewer back-off set at the next two exposures, keeping the TS and rep target consistent; then reassess.")
        if result["recent_sets"] <= 1:
            result.update(action="review_reps", message="There is no back-off volume to remove. Review the rep target and effort before adding work.")
    elif decline and losing_bw:
        result.update(action="review_bw", message="TS e1RM and BW are both falling. Review the BW trend and recovery context before adding volume or changing exercises; BW loss does not establish the cause.")
    elif decline:
        earlier = [p for p in comparable[-18:-12] if complete(p)]
        persistent = (len(comparable) >= 18 and len(earlier) >= MIN_PAIRED_PER_WINDOW
                      and median(p["e1rm_lb"] for p in previous) <= median(p["e1rm_lb"] for p in earlier) * .97)
        changed_reps = median(p["median_reps"] for p in recent if p["median_reps"] is not None) != median(p["median_reps"] for p in previous if p["median_reps"] is not None)
        if persistent and (result["sets_change"] <= -1 or changed_reps):
            result.update(action="consider_block", message="The decline spans 18 comparable TS sessions, with fewer sets or changed reps in the latest group. Consider a new block with a different exercise; start a separate TS baseline for it.")
        else:
            result.update(action="review_reps", message="Review the rep prescription and effort rather than adding sets during a TS decline. Change one variable, then reassess; consider a new block if the decline persists after adjustments.")
    elif (result["status"] == "stable" and low and abs(result["bw_change_pct"]) < BW_CHANGE_PCT
          and result["sets_change"] == 0
          and median(p["total_reps"] for p in recent) == median(p["total_reps"] for p in previous)
          and cadence(recent) >= cadence(previous)
          and all(p["median_rpe"] is not None for p in comparison_points)
          and median(p["median_rpe"] for p in recent) <= median(p["median_rpe"] for p in previous) + .5):
        result.update(action="try_set", message="If more progress is the goal, consider one extra back-off set at one weekly exposure. Keep other variables consistent and reassess after three comparable TS sessions.")
    elif high:
        result["message"] = "Soreness is repeatedly moderate or severe. Hold volume and monitor performance before adding sets."
    return result


def load(exercise_template_id, *, now=None):
    # Exact movement ids stay separate. Only explicit main-lift titles assign a pattern.
    from progress import LIFT_TITLES
    with closing(get_db()) as conn:
        ts = [dict(r) for r in conn.execute("SELECT * FROM training_max_history WHERE exercise_template_id = ? ORDER BY set_at, id", (exercise_template_id,))]
        sets = [dict(r) for r in conn.execute("SELECT * FROM logged_sets WHERE exercise_template_id = ? ORDER BY workout_start, id", (exercise_template_id,))]
        title_row = conn.execute("SELECT title FROM hevy_exercise_cache WHERE id = ?", (exercise_template_id,)).fetchone()
        title = title_row["title"] if title_row else next((r["exercise_title"] for r in reversed(sets) if r.get("exercise_title")), "")
        key = next((key for key, value in LIFT_TITLES.items() if value == title), None)
        pattern = "bench_press" if key in ("bench", "press") else key
        observations = [dict(r) for r in conn.execute("SELECT * FROM session_soreness")]
        measurements = [dict(r) for r in conn.execute("SELECT date, weight_kg FROM body_measurements ORDER BY date")]
    return analyze(ts, sets, observations, measurements, pattern=pattern, now=now)
