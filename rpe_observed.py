"""
rpe_observed.py — The RPE table your own logged sets describe, one lift at a time. Nothing here uses the numbers of the
table in use; it only appears beside the result, for comparison.

How a set is read. A set of `reps` at `rpe` is as hard as a set to failure of k = reps + (10 - rpe) reps, so sets at
different RPEs and rep counts that share a k measure the same point of one curve: the share of your max you can lift
for k reps. A true RPE 10 single (k = 1) is 100% by definition.

The scale. Every workout has its own e1RM. A straight line in k (f(k) = 1 - slope * (k - 1)) is fitted to all the sets
to give each workout its e1RM, and then the curve is re-drawn through the sets themselves (their average share at each k,
kept non-increasing) and the e1RMs refitted to it, a few rounds. Every set counts, the TS included: no set is the
reference, so nothing is measured against a number that came from the table.

The cells. A cell is the average share of the sets logged at that exact RPE and reps, with the count. Once a lift has
enough data (the gate: sets, workouts and spread of effort) the cells you haven't hit are estimated by interpolating
that curve between the points your sets measured, and marked as estimates; beyond the hardest or easiest effort your sets
reach they stay empty. Pure: no DB access.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Callable

from exercise_state import LB_PER_KG

PctLookup = Callable[[float, int], "float | None"]
SKIPPED_TYPES = ("warmup", "dropset")

# Enough data to estimate the cells you haven't hit: all three must hold, per lift.
MIN_SETS = 15
MIN_WORKOUTS = 3
MIN_K_SPAN = 4.0   # the hardest and easiest efforts logged are at least this many reps apart

MIN_SLOPE, MAX_SLOPE, SLOPE_STEP = 0.005, 0.08, 0.0001
EST_RPES = [10 - 0.5 * i for i in range(11)]   # 10 down to 5
EST_REPS = list(range(1, 13))


def _k(reps: int, rpe: float) -> float:
    return reps + 10 - rpe


def _usable(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sets that can say anything: not warm-ups or drop sets, with a weight, reps and an RPE."""
    out = []
    for s in sets:
        if s["set_type"] in SKIPPED_TYPES or not s["weight_kg"] or not s["reps"] or s["rpe"] is None:
            continue
        out.append({
            "start": s["workout_start"], "weight": float(s["weight_kg"]), "reps": int(s["reps"]),
            "rpe": float(s["rpe"]), "k": _k(int(s["reps"]), float(s["rpe"])), "ts": bool(s["is_ts"]),
            "workout": s.get("hevy_workout_id") or s["workout_start"],
            "session": (s.get("hevy_workout_id") or s["workout_start"], s.get("exercise_template_id", "")),
            "exercise_title": s.get("exercise_title"),
        })
    return out


def _by_workout(use: list[dict[str, Any]]) -> dict[tuple[str, str], list[tuple[float, float]]]:
    out: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    for u in use:
        out[u["session"]].append((u["weight"], u["k"]))
    return out


def _solve(slope: float, pts: list[tuple[float, float]]):
    """(log of the workout's e1RM, squared misses) along the straight line at this slope, or None if it goes non-positive."""
    logs = []
    for weight, k in pts:
        f = 1 - slope * (k - 1)
        if f <= 0.05:
            return None
        logs.append(math.log(weight / f))
    mean = sum(logs) / len(logs)
    return mean, sum((x - mean) ** 2 for x in logs)


def _fit_slope(workouts: dict[tuple[str, str], list[tuple[float, float]]]):
    """(sum of squared misses, slope, number of sets fitted, number of workouts that pin it), or None.
    Only workouts with sets at two or more different k say anything about the slope."""
    informative = {start: pts for start, pts in workouts.items() if len({k for _, k in pts}) > 1}
    if not informative:
        return None
    best = None
    for i in range(int(round((MAX_SLOPE - MIN_SLOPE) / SLOPE_STEP)) + 1):
        slope = MIN_SLOPE + i * SLOPE_STEP
        total = 0.0
        for pts in informative.values():
            solved = _solve(slope, pts)
            if solved is None:
                total = math.inf
                break
            total += solved[1]
        if best is None or total < best[0]:
            best = (total, slope)
    if best is None or math.isinf(best[0]):
        return None
    return best[0], best[1], sum(len(p) for p in informative.values()), len(informative)


def _non_increasing(points: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    """Pool adjacent points that go the wrong way (a higher k with a higher share) so the curve never rises."""
    blocks: list[list[float]] = []   # [mean, weight, first index, count]
    for i, (_, share, n) in enumerate(points):
        blocks.append([share, float(n), i, 1])
        while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
            b = blocks.pop()
            a = blocks[-1]
            total = a[1] + b[1]
            a[0] = (a[0] * a[1] + b[0] * b[1]) / total
            a[1] = total
            a[3] += b[3]
    out = []
    for mean, _, first, count in blocks:
        for j in range(int(first), int(first) + int(count)):
            out.append((points[j][0], mean))
    return out


def _interp(curve: list[tuple[float, float]], k: float) -> float | None:
    if k < curve[0][0] or k > curve[-1][0]:
        return None
    for (k0, v0), (k1, v1) in zip(curve, curve[1:]):
        if k0 <= k <= k1:
            return v0 if k1 == k0 else v0 + (v1 - v0) * (k - k0) / (k1 - k0)
    return curve[-1][1]


def _refine(workouts: dict[tuple[str, str], list[tuple[float, float]]], slope: float, rounds: int = 60):
    """Each workout's e1RM (kg) and the curve [(k, share)] drawn through the sets, pinned at (1, 100%)."""
    e1rm = {}
    for start, pts in workouts.items():
        solved = _solve(slope, pts)
        e1rm[start] = math.exp(solved[0]) if solved else max(w for w, _ in pts)
    anchor_logs = sum(math.log(v) for v in e1rm.values())
    curve: list[tuple[float, float]] = []
    for _ in range(rounds):
        pooled: dict[float, list[float]] = defaultdict(list)
        for start, pts in workouts.items():
            for weight, k in pts:
                pooled[k].append(weight / e1rm[start])
        points = [(k, sum(v) / len(v), len(v)) for k, v in sorted(pooled.items())]
        smooth = _non_increasing(points)
        curve = smooth if smooth and smooth[0][0] == 1.0 else [(1.0, 1.0)] + smooth
        updated = {}
        for start, pts in workouts.items():
            updated[start] = math.exp(sum(math.log(w / _interp(curve, k)) for w, k in pts) / len(pts))
        # the overall scale is not something the sets can pin; keep it where the straight-line fit put it
        shift = math.exp((anchor_logs - sum(math.log(v) for v in updated.values())) / len(updated))
        updated = {s: v * shift for s, v in updated.items()}
        change = max(abs(updated[s] - e1rm[s]) / e1rm[s] for s in e1rm)
        e1rm = updated
        if change < 1e-9:
            break
    return e1rm, curve


def build_observed(sets: list[dict[str, Any]], ts_history: list[dict[str, Any]], chart: PctLookup) -> dict[str, Any]:
    """
    sets: logged_sets rows for one lift (weight_kg, reps, rpe, set_type, is_ts, workout_start).
    ts_history is unused here (kept so callers pass the same arguments as fit_curve).
    chart: the RPE table in use, rpe/reps -> fraction of e1RM or None, only to sit beside each value.
    Returns the observed cells, the data gate, and (once the gate is passed) the estimated cells.
    """
    use = _usable(sets)
    workouts = _by_workout(use)
    ks = [u["k"] for u in use]
    gate = {
        "passed": False,
        "sets": len(use), "min_sets": MIN_SETS,
        "workouts": len({u["workout"] for u in use}), "min_workouts": MIN_WORKOUTS,
        "k_span": (max(ks) - min(ks)) if ks else 0.0, "min_k_span": MIN_K_SPAN,
    }
    fitted = _fit_slope(workouts)
    result: dict[str, Any] = {"sets_used": 0, "ts_sets": 0, "cells": [], "estimated": [], "gate": gate}
    if fitted is None:
        return result
    e1rm, curve = _refine(workouts, fitted[1])

    buckets: dict[tuple[float, int], list[float]] = defaultdict(list)
    ts_count: dict[tuple[float, int], int] = defaultdict(int)
    for u in use:
        key = (u["rpe"], u["reps"])
        buckets[key].append(u["weight"] / e1rm[u["session"]])
        ts_count[key] += 1 if u["ts"] else 0
    result["sets_used"] = len(use)
    result["ts_sets"] = sum(ts_count.values())
    result["cells"] = [
        {"rpe": rpe, "reps": reps, "n": len(v), "ts": ts_count[(rpe, reps)], "observed": sum(v) / len(v), "chart": chart(rpe, reps)}
        for (rpe, reps), v in sorted(buckets.items(), key=lambda kv: (-kv[0][0], kv[0][1]))
    ]

    gate["passed"] = len(use) >= MIN_SETS and gate["workouts"] >= MIN_WORKOUTS and gate["k_span"] >= MIN_K_SPAN
    if gate["passed"]:
        for rpe in EST_RPES:
            for reps in EST_REPS:
                if (rpe, reps) in buckets:
                    continue
                value = _interp(curve, _k(reps, rpe))
                if value is not None:
                    result["estimated"].append({"rpe": rpe, "reps": reps, "estimated": value, "chart": chart(rpe, reps)})
    return result


def fit_curve(sets: list[dict[str, Any]], ts_history: list[dict[str, Any]], chart: PctLookup) -> dict[str, Any] | None:
    """
    The straight-line slope (fraction of the max lost per extra rep to failure) and each workout's e1RM that best fit the
    sets, or None when no workout has sets at two different k. Alongside, the table in use's slope and the e1RM the TS gave.
    """
    use = _usable(sets)
    workouts = _by_workout(use)
    fitted = _fit_slope(workouts)
    if fitted is None:
        return None
    sse, slope, fitted_sets, informative = fitted
    anchors = sorted(ts_history, key=lambda t: t["set_at"])
    sessions = []
    metadata = {u["session"]: u for u in use}
    for session in sorted(workouts, key=lambda key: (metadata[key]["start"], key)):
        start = metadata[session]["start"]
        solved = _solve(slope, workouts[session])
        if solved is None:
            continue
        table = None
        for t in anchors:
            if t["set_at"] > start:
                break
            table = t
        sessions.append({
            "workout_start": start,
            "exercise_title": metadata[session]["exercise_title"],
            "e1rm_lb": math.exp(solved[0]) * LB_PER_KG,
            "table_e1rm_lb": table["e1rm_lb"] if table else None,
            "sets": len(workouts[session]),
        })
    low, high = chart(10.0, 2), chart(10.0, 10)
    return {
        "slope": slope,
        "table_slope": (low - high) / 8 if low is not None and high is not None else None,
        "rms_error": math.sqrt(sse / fitted_sets),
        "informative_sessions": informative,
        "sets_fitted": fitted_sets,
        "sessions": sessions,
    }
