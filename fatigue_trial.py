"""Optional blinded trial. Experimental rules; never changes workout prescriptions.

Snapshots contain their evidence, so subsequent edits cannot rewrite predictions.
Only server-observed recording times qualify for prospective collection.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from statistics import median
from uuid import uuid4

from pydantic import BaseModel, Field
from typing import Literal

from database import get_db, get_rpe_percentage
from fatigue_context import timestamp
from fatigue_context import build_context
import fatigue
import fatigue_relationships
import soreness
import fatigue_trial_smoother as smoother
import logging

VERSION = "shared-trial-v0"


class SnapshotInput(BaseModel):
    session_key: str = Field(min_length=1, max_length=120)
    exercise_template_id: str = Field(min_length=1, max_length=120)
    workout_start: datetime
    local_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    soreness: int | None = Field(default=None, ge=0, le=3)
    pain: bool = False
    working_set_started: bool = False
    mode: Literal["strength", "hypertrophy"]
    planned_reps: int = Field(ge=1, le=100)
    planned_rpe: float | None = Field(default=None, ge=0, le=10)
    planned_weight_kg: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    exercise_order: int | None = Field(default=None, ge=0)


class TrialSettings(BaseModel):
    enabled: bool = False


class TrialStatus(TrialSettings):
    preview: bool


class MovementStart(BaseModel):
    session_key: str = Field(min_length=1, max_length=120)
    exercise_template_id: str = Field(min_length=1, max_length=120)


def mark_started(data):
    with closing(get_db()) as conn, conn:
        conn.execute("INSERT OR IGNORE INTO fatigue_trial_starts VALUES (?,?,?)",
                     (data.session_key, data.exercise_template_id, datetime.now(timezone.utc).isoformat()))
    return {"recorded": True}


class DailyCheckin(BaseModel):
    status: Literal["available", "stale", "unavailable"]
    source: str = "hevy-fatigue"
    scale: str = "0–4 (original)"
    date: str | None = None
    fetched_at: str
    timing: str = "date_only"
    ratings: dict[str, int | None] = Field(default_factory=dict)


class TrialResult(BaseModel):
    id: str
    exercise_template_id: str
    recorded_at: str
    model_version: str
    status: Literal["recorded", "completed"]
    prospective: bool
    pain: bool
    prediction: str | None = None
    observed: str | None = None
    reasons: list[str] | None = None
    across_sessions: dict | None = None
    evidence: dict | None = None
    notes: list[dict] | None = None
    actual: dict | None = None
    shadow: dict | None = None


class CompletionInput(BaseModel):
    hevy_workout_id: str = Field(min_length=1)


class TrialNote(BaseModel):
    kind: Literal["correction", "skipped", "workout_change", "advice_followed", "suggested_change", "actual_change"]
    text: str = Field(min_length=1, max_length=2000)


class TrialEvaluation(BaseModel):
    model_version: str
    exercise_template_id: str
    mode: str
    eligible_predictions: int
    required_predictions: int = 12
    review_at: str | None
    review_due: bool
    status: str
    metrics: dict
    observations: int
    skipped: int


def enabled():
    with closing(get_db()) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", ("fatigue_trial_enabled",)).fetchone()
    return bool(row and row[0] == "true")


def configure(value):
    with closing(get_db()) as conn, conn:
        conn.execute("INSERT INTO app_settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     ("fatigue_trial_enabled", "true" if value else "false"))
    return {"enabled": value, "preview": os.environ.get("RACKBOOK_READ_ONLY_PREVIEW") == "1"}


def daily(day, *, now=None):
    """Narrow local bridge: fixed query, read-only connection, no credentials or paths returned."""
    now = now or datetime.now(timezone.utc)
    result = dict(status="unavailable", fetched_at=now.isoformat())
    path = os.environ.get("HEVY_FATIGUE_DB_PATH")
    if not path:
        return DailyCheckin(**result).model_dump()
    try:
        datetime.strptime(day, "%Y-%m-%d")
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""SELECT date, tiredness, perceived_recovery, sore_quad_dom,
                sore_posterior, sore_upper_push, sore_upper_pull, joint_upper, joint_lower
                FROM daily_readiness WHERE date <= ? ORDER BY date DESC LIMIT 1""", (day,)).fetchone()
        if row:
            result.update(status="available" if row["date"] == day else "stale", date=row["date"],
                          ratings={key: row[key] for key in row.keys() if key != "date"})
    except (sqlite3.Error, ValueError, OSError):
        pass
    return DailyCheckin(**result).model_dump()


def representative(rows, mode):
    working = [r for r in rows if r.get("set_type", "normal") != "warmup"]
    if mode == "strength":
        marked = [r for r in working if r.get("is_ts")]
        return marked[0] if len(marked) == 1 else None
    # Do not select a later/better set when the first working set is incomplete.
    return working[0] if working and working[0].get("set_type", "normal") == "normal" and not any(r.get("is_ts") for r in working) else None


def eligible(row, target, mode):
    if not row or any(row.get(k) is None for k in ("weight_kg", "reps", "rpe")):
        return False
    if row["weight_kg"] <= 0 or row["reps"] <= 0 or target.get("rpe") is None:
        return False
    if target.get("exercise_order") is not None and row.get("exercise_order") != target["exercise_order"]:
        return False
    if mode == "strength":
        return row["reps"] == target["reps"] and abs(row["rpe"] - target["rpe"]) <= 1
    return target.get("weight_kg") is not None and abs(row["weight_kg"] - target["weight_kg"]) < .01 and abs(row["rpe"] - target["rpe"]) <= 1


def reference(rows, target, mode, at):
    sessions = {}
    for row in rows:
        when = timestamp(row.get("workout_start"))
        if when is None or when >= at:
            continue
        sessions.setdefault((when, row.get("hevy_workout_id")), []).append(row)
    selected = []
    previous = at
    for (when, _), group in sorted(sessions.items(), key=lambda pair: pair[0][0], reverse=True):
        if previous - when >= timedelta(days=21):
            break
        previous = when
        # Repeated exercise occurrences / duplicate set identities are ambiguous.
        numbers = [r.get("set_number") for r in group]
        if len(numbers) != len(set(numbers)):
            continue
        row = representative(sorted(group, key=lambda r: r.get("set_number", 0)), mode)
        if eligible(row, target, mode):
            selected.append(dict(row))
        if len(selected) == 3:
            break
    return selected


def performance(row, baseline, mode, chart=None):
    if len(baseline) < 3 or not all(eligible(row, s, mode) for s in baseline):
        return "unclassified"
    if mode == "strength":
        def e1rm(s):
            fraction = chart.get(f"{float(s['rpe'])}:{s['reps']}") if chart is not None else get_rpe_percentage(s["rpe"], s["reps"])
            return s["weight_kg"] / fraction if fraction else None
        values = [e1rm(s) for s in baseline]
        current = e1rm(row)
        if current is None or any(v is None for v in values):
            return "unclassified"
        return "below_usual" if current / median(values) - 1 <= -.03 else "near_usual"
    if not all(eligible(s, row, mode) for s in baseline):
        return "unclassified"
    reps, rpe = median(s["reps"] for s in baseline), median(s["rpe"] for s in baseline)
    if row["reps"] <= reps - 1 or (row["reps"] == reps and row["rpe"] >= rpe + 1):
        return "below_usual"
    return "near_usual" if row["reps"] >= reps else "unclassified"


def assess(level, checkin, baseline, context):
    reasons = list(context.get("block_reasons", []))
    ratings = checkin.get("ratings", {})
    if level is None:
        reasons.append("Pre-movement soreness is unknown.")
    if checkin["status"] != "available" or any(ratings.get(k) is None for k in ("tiredness", "perceived_recovery")):
        reasons.append("Today's daily tiredness/recovery check-in is incomplete or unavailable.")
    if len(baseline) < 3:
        reasons.append("Fewer than three comparable prior exposures.")
    if reasons:
        return "uncertain", reasons
    low = level >= 2 or ratings["tiredness"] >= 3 or ratings["perceived_recovery"] >= 3
    return ("below_usual" if low else "near_usual"), ["Experimental soreness/tiredness/recovery thresholds; daily regional soreness is not counted twice."]


def today_context(exercise_id, at, fallback_pattern=None):
    """Apply existing spacing/workload tolerances to three prior exposures and today.

    Trend gates remain separate: a Today comparison does not require a ready TS trend.
    """
    with closing(get_db()) as conn:
        all_sets = [dict(r) for r in conn.execute("SELECT * FROM logged_sets ORDER BY workout_start,id")]
        links = fatigue_relationships.confirmed(conn)
    pattern = fallback_pattern
    reviewed = links.get(exercise_id, [])
    if not pattern and len(reviewed) == 1:
        pattern = reviewed[0]
    times = sorted({timestamp(r["workout_start"]) for r in all_sets if r["exercise_template_id"] == exercise_id
                    and r["set_type"] != "warmup" and timestamp(r["workout_start"]) and timestamp(r["workout_start"]) < at})
    points = [dict(start_time=t.isoformat()) for t in times if at-t < timedelta(days=21)]
    previous = points[-3:]
    current = dict(start_time=at.isoformat())
    return build_context(points+[current], previous, [current], current, all_sets, links, exercise_id, pattern, at, recent_minimum=1)


def with_order(rows):
    sessions = {}
    result = []
    for row in rows:
        key = (row.get("hevy_workout_id"), row["workout_start"])
        exercises = sessions.setdefault(key, [])
        exercise = row["exercise_template_id"]
        if exercise not in exercises:
            exercises.append(exercise)
        result.append({**row, "exercise_order": exercises.index(exercise)})
    return result


def non_ts_trends(rows, observations, pattern, at):
    groups = {}
    for row in rows:
        when = timestamp(row["workout_start"])
        if when and when <= at:
            groups.setdefault((when,row.get("hevy_workout_id")),[]).append(row)
    points = []
    for (when,workout_id), group in sorted(groups.items(),key=lambda p:p[0][0]):
        first = representative(group,"hypertrophy")
        base = reference(rows, first or {}, "hypertrophy", when) if first else []
        observed = performance(first,base,"hypertrophy")
        observation = next((o for o in observations if o["hevy_workout_id"]==workout_id),{})
        points.append(dict(start_time=when.isoformat(), observed=observed,
            reps=first.get("reps") if first else None, rpe=first.get("rpe") if first else None,
            working_sets=sum(r["set_type"]!="warmup" for r in group), soreness=observation.get(pattern) if pattern else None))
    # Each long break starts a separate cohort; no synthetic TS or automatic progression.
    active=[]
    for p in points:
        if active and timestamp(p["start_time"])-timestamp(active[-1]["start_time"]) >= timedelta(days=21):
            active=[]
        active.append(p)
    eligible_points=[p for p in active if p["observed"]!="unclassified"]
    ready=len(eligible_points)>=12 and len(active)>=3 and all(p["soreness"] is not None for p in active[-3:])
    return dict(status=("review" if all(p["observed"]=="below_usual" for p in eligible_points[-3:]) else "maintain/monitor") if ready else "insufficient evidence",
                message="Comparable first-set performance, effort, dose and soreness; no automatic progression.",
                points=points, eligible_sessions=len(eligible_points), required_sessions=12)


def record(data, *, now=None):
    if not enabled():
        raise ValueError("The optional model trial is disabled.")
    now = now or datetime.now(timezone.utc)
    start = timestamp(data.workout_start.isoformat())
    if start is None or start > now:
        raise ValueError("Workout start must not be in the future.")
    # A supplied calendar date is only for the user's local daily questionnaire.
    day = datetime.strptime(data.local_date, "%Y-%m-%d").date()
    if abs((day - now.date()).days) > 1:
        raise ValueError("Check-in date must be today in your timezone.")
    with closing(get_db()) as conn:
        existing = conn.execute("SELECT id FROM fatigue_trial_snapshots WHERE session_key=? AND exercise_template_id=?",
                                (data.session_key, data.exercise_template_id)).fetchone()
        if existing:
            return read(existing[0])
        rows = [r for r in with_order([dict(r) for r in conn.execute("SELECT * FROM logged_sets ORDER BY workout_start,id")]) if r["exercise_template_id"]==data.exercise_template_id]
        started = conn.execute("SELECT 1 FROM fatigue_trial_starts WHERE session_key=? AND exercise_template_id=?",
                               (data.session_key, data.exercise_template_id)).fetchone()
        chart = {f"{float(r['rpe'])}:{r['reps']}":r['percentage'] for r in conn.execute("SELECT * FROM rpe_chart")}
    target = dict(reps=data.planned_reps, rpe=data.planned_rpe, weight_kg=data.planned_weight_kg, exercise_order=data.exercise_order)
    baseline = reference(rows, target, data.mode, start)
    old = fatigue.load(data.exercise_template_id, now=start)
    context = today_context(data.exercise_template_id, now, old["pattern"])
    checkin = daily(data.local_date, now=now)
    prediction, reasons = assess(data.soreness, checkin, baseline, context)
    late = bool(started) or data.working_set_started or any(timestamp(r["workout_start"]) == start for r in rows)
    if now - start >= timedelta(hours=18):
        late = True
    snapshot = dict(input=data.model_dump(mode="json"), daily=checkin, baseline=baseline,
                    existing_rackbook=old, context=context, rpe_table=chart, prediction=prediction, reasons=reasons,
                    soreness_source="rackbook-pre-movement", soreness_scale="0–3", assessed_at=now.isoformat())
    # Capture only for a genuinely new observation. Existing snapshots are never backfilled.
    try:
        shadow = smoother.capture(data.local_date, now)
    except Exception:
        logging.getLogger(__name__).warning('Shadow capture failed; legacy trial remains available.')
        shadow = smoother.unavailable(data.local_date, now)
    created = False
    trial_id = str(uuid4())
    try:
        with closing(get_db()) as conn, conn:
            # Shadow capture can take time. Recheck the durable first-set marker
            # while holding the insert lock so intervening starts are excluded.
            conn.execute("BEGIN IMMEDIATE")
            late = late or bool(conn.execute(
                "SELECT 1 FROM fatigue_trial_starts WHERE session_key=? AND exercise_template_id=?",
                (data.session_key, data.exercise_template_id)).fetchone())
            conn.execute("""INSERT INTO fatigue_trial_snapshots
                (id, session_key, exercise_template_id, workout_start, recorded_at, model_version, prospective, pain, snapshot)
                VALUES (?,?,?,?,?,?,?,?,?)""", (trial_id, data.session_key, data.exercise_template_id, start.isoformat(),
                now.isoformat(), VERSION, int(not late), int(data.pain or any((checkin.get("ratings", {}).get(k) or 0) > 0 for k in ("joint_upper", "joint_lower"))), json.dumps(snapshot)))
        created = True
    except sqlite3.IntegrityError:
        with closing(get_db()) as conn:
            trial_id = conn.execute("SELECT id FROM fatigue_trial_snapshots WHERE session_key=? AND exercise_template_id=?",
                                   (data.session_key, data.exercise_template_id)).fetchone()[0]
    if created:
        try:
            smoother.store(trial_id, shadow)
        except Exception:
            logging.getLogger(__name__).warning('Shadow trial storage failed; legacy trial is preserved.')
    return read(trial_id)


def read(trial_id):
    with closing(get_db()) as conn:
        row = conn.execute("SELECT * FROM fatigue_trial_snapshots WHERE id=?", (trial_id,)).fetchone()
        notes = [dict(r) for r in conn.execute("SELECT kind,text,recorded_at FROM fatigue_trial_notes WHERE trial_id=? ORDER BY id", (trial_id,))]
    if not row:
        raise ValueError("Trial record not found.")
    result = dict(id=row["id"], exercise_template_id=row["exercise_template_id"], recorded_at=row["recorded_at"],
                  model_version=row["model_version"], prospective=bool(row["prospective"]), pain=bool(row["pain"]),
                  status="completed" if row["completion"] else "recorded")
    if row["completion"]:
        snapshot = json.loads(row["snapshot"])
        result["shadow"] = smoother.read(trial_id)
        result.update(prediction=snapshot["prediction"], reasons=snapshot["reasons"], evidence=snapshot,
                      notes=notes, **json.loads(row["completion"]))
    # Do not even serialize verdict/input-reference fields before completion.
    return result


def complete(trial_id, workout_id):
    with closing(get_db()) as conn:
        trial = conn.execute("SELECT * FROM fatigue_trial_snapshots WHERE id=?", (trial_id,)).fetchone()
        all_rows = with_order([dict(r) for r in conn.execute("SELECT * FROM logged_sets ORDER BY workout_start,id")])
        rows = [r for r in all_rows if r["hevy_workout_id"]==workout_id and r["exercise_template_id"]==(trial["exercise_template_id"] if trial else "")]
        observations = [dict(r) for r in conn.execute("SELECT * FROM session_soreness")]
    if not trial:
        raise ValueError("Trial record not found.")
    if trial["completion"]:
        return read(trial_id)
    saved = [r for r in all_rows if r["hevy_workout_id"]==workout_id]
    if not saved or any(timestamp(r["workout_start"]) != timestamp(trial["workout_start"]) for r in saved):
        raise ValueError("A matching locally saved workout is required before revealing the result.")
    snapshot = json.loads(trial["snapshot"])
    numbers = [r["set_number"] for r in rows]
    row = representative(rows, snapshot["input"]["mode"]) if len(numbers) == len(set(numbers)) else None
    observed = performance(row, snapshot["baseline"], snapshot["input"]["mode"], snapshot["rpe_table"])
    old = snapshot["existing_rackbook"]
    across = dict(status="insufficient evidence", message="Still collecting a baseline.")
    if snapshot["input"]["mode"] == "strength" and old["collection"]["ready"]:
        across = dict(status="review" if old["status"] in ("declining", "pain_flag") else "maintain/monitor",
                      message=old["message"], model_version=old["model_version"])
    elif snapshot["input"]["mode"] == "hypertrophy":
        across=non_ts_trends([r for r in all_rows if r["exercise_template_id"]==trial["exercise_template_id"]],
                             observations, old["pattern"], timestamp(trial["workout_start"]))
        if snapshot["context"]["block_reasons"]:
            across.update(status="insufficient evidence", message="Workload/spacing context is not comparable. " + " ".join(snapshot["context"]["block_reasons"]))
    completion = dict(observed=observed, across_sessions=across,
                      actual={k: row.get(k) for k in ('weight_kg', 'reps', 'rpe')} if row else None)
    with closing(get_db()) as conn, conn:
        conn.execute("UPDATE fatigue_trial_snapshots SET completion=?, hevy_workout_id=? WHERE id=? AND completion IS NULL",
                     (json.dumps(completion), workout_id, trial_id))
    return read(trial_id)


def complete_workout(workout_id, workout_start):
    with closing(get_db()) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id,workout_start FROM fatigue_trial_snapshots WHERE completion IS NULL")
               if timestamp(r["workout_start"]) == timestamp(workout_start)]
    return [complete(key, workout_id) for key in ids]


def record_skips(workout_id, workout_start, exercises):
    if not enabled():
        return
    with closing(get_db()) as conn, conn:
        recorded={r[0] for r in conn.execute("SELECT exercise_template_id FROM fatigue_trial_snapshots WHERE workout_start=?", (timestamp(workout_start).isoformat(),))}
        for exercise in exercises:
            if exercise not in recorded:
                conn.execute("INSERT OR IGNORE INTO fatigue_trial_skips VALUES (?,?,?,?)",
                    (workout_id, exercise, datetime.now(timezone.utc).isoformat(), "No trial snapshot before workout save"))


def note(trial_id, data):
    read(trial_id)
    with closing(get_db()) as conn, conn:
        conn.execute("INSERT INTO fatigue_trial_notes(trial_id,kind,text,recorded_at) VALUES (?,?,?,?)",
                     (trial_id, data.kind, data.text, datetime.now(timezone.utc).isoformat()))
    return {"recorded": True}


def history():
    with closing(get_db()) as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM fatigue_trial_snapshots ORDER BY recorded_at DESC LIMIT 100")]
    return [read(key) for key in ids]


def evaluation(*, now=None):
    now=now or datetime.now(timezone.utc)
    with closing(get_db()) as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM fatigue_trial_snapshots ORDER BY recorded_at")]
        skips=[dict(r) for r in conn.execute("SELECT * FROM fatigue_trial_skips")]
    groups={}
    for row in rows:
        snapshot=json.loads(row["snapshot"])
        key=(row["model_version"],row["exercise_template_id"],snapshot["input"]["mode"])
        groups.setdefault(key,[]).append((row,snapshot))
    result=[]
    for (version,exercise,mode), items in groups.items():
        scored=[]
        for row,snapshot in items:
            if not row["completion"] or not row["prospective"]:
                continue
            observed=json.loads(row["completion"])["observed"]
            subjective,_=assess(snapshot["input"]["soreness"],snapshot["daily"],[None]*3,{"block_reasons":[]})
            scored.append(dict(candidate=snapshot["prediction"],subjective_only=subjective,always_near_usual="near_usual",observed=observed))
        metrics={}
        common=[r for r in scored if r["candidate"]!="uncertain" and r["subjective_only"]!="uncertain" and r["observed"]!="unclassified"]
        for model in ("candidate","subjective_only","always_near_usual"):
            eligible_rows=[r for r in scored if r[model]!="uncertain" and r["observed"]!="unclassified"]
            metrics[model]=dict(eligible=len(eligible_rows), coverage=len(eligible_rows)/len(scored) if scored else 0,
                missed_below_usual=sum(r[model]=="near_usual" and r["observed"]=="below_usual" for r in eligible_rows),
                unnecessary_warnings=sum(r[model]=="below_usual" and r["observed"]=="near_usual" for r in eligible_rows))
            metrics[model].update(common_eligible=len(common),
                common_missed_below_usual=sum(r[model]=="near_usual" and r["observed"]=="below_usual" for r in common),
                common_unnecessary_warnings=sum(r[model]=="below_usual" and r["observed"]=="near_usual" for r in common))
        eligible_rows=[r for r in scored if r["candidate"]!="uncertain" and r["observed"]!="unclassified"]
        completed_times=[timestamp(row['recorded_at']) for row,_ in items if row['completion'] and row['prospective']]
        review_at=min(completed_times)+timedelta(weeks=6) if completed_times else None
        ready=len(eligible_rows)>=12 and {r["observed"] for r in eligible_rows}=={"near_usual","below_usual"}
        result.append(dict(model_version=version,exercise_template_id=exercise,mode=mode,
            eligible_predictions=len(eligible_rows),review_at=review_at.isoformat() if review_at else None,review_due=bool(review_at and now>=review_at),
            status="ready for provisional review" if ready and review_at and now>=review_at else "inconclusive; continue collection",
            metrics=metrics,observations=len(scored),skipped=sum(r["exercise_template_id"]==exercise for r in skips)))
    return result
