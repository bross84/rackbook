"""Chart-only BS-Bridge history. Never writes to Hevy or the live set/TS record."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
import json
import math
import re

from database import get_db
import progress
import rpe_observed

GROUPS = {
    "squat": (progress.LIFT_TITLES["squat"], "Squat, High Bar, Paused"),
    "bench": (progress.LIFT_TITLES["bench"],),
    "deadlift": (progress.LIFT_TITLES["deadlift"],),
}
BRIDGE = re.compile(r"^\s*bs[\s-]*bridge(?=$|[\d\s._:-])", re.IGNORECASE)


def _usable(raw):
    weight, reps, rpe = raw.get("weight_kg"), raw.get("reps"), raw.get("rpe")
    return (raw.get("type", "normal") in ("normal", "failure")
            and isinstance(weight, (int, float)) and not isinstance(weight, bool)
            and math.isfinite(weight) and weight > 0
            and isinstance(reps, int) and not isinstance(reps, bool) and reps > 0
            and isinstance(rpe, (int, float)) and not isinstance(rpe, bool)
            and math.isfinite(rpe) and 0 <= rpe <= 10)


def fetch_bridge(client):
    """Read every page before any persistence; select only the four approved movements."""
    workouts = {}
    approved_ids = {}
    scanned = set()
    page = 1
    while True:
        data = client.list_workouts(page=page, page_size=10)
        pages = int(data["page_count"])
        if pages == 0 and page == 1 and not data.get("workouts"):
            break
        if not 1 <= pages <= 10000:
            raise ValueError("Hevy returned an invalid workout page count.")
        for workout in data.get("workouts", []):
            scanned.add(workout.get("id"))
            if not BRIDGE.match(workout.get("title") or ""):
                continue
            wid, start = workout.get("id"), workout.get("start_time")
            if not wid or not start:
                raise ValueError("A BS-Bridge workout is missing its id or start time.")
            datetime.fromisoformat(start.replace("Z", "+00:00"))
            workouts[str(wid)] = workout
            for ex in workout.get("exercises", []):
                title, template = ex.get("title"), ex.get("exercise_template_id")
                if any(title in titles for titles in GROUPS.values()):
                    if not template:
                        raise ValueError("A selected BS-Bridge movement is missing its exercise id.")
                    approved_ids[template] = title
        if page >= pages:
            break
        page += 1
    selected = []
    for wid, workout in workouts.items():
        movements = {}
        for ex in workout.get("exercises", []):
            template = ex.get("exercise_template_id")
            if template not in approved_ids:
                continue
            # Same ID remains the same exercise after a rename; never infer a different ID from similar names.
            item = movements.setdefault(template, {
                "hevy_workout_id": wid, "exercise_template_id": template,
                "exercise_title": approved_ids[template], "workout_title": workout["title"],
                "workout_start": workout["start_time"], "sets": [],
            })
            item["sets"].extend({"type": s.get("type", "normal"), "weight_kg": s["weight_kg"],
                                 "reps": s["reps"], "rpe": s["rpe"]}
                                for s in ex.get("sets", []) if _usable(s))
        selected.extend(item for item in movements.values() if item["sets"])
    return {"workouts_scanned": len(scanned), "sessions": selected}


def store_import(prepared):
    added = sets_added = preserved = existing = 0
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        for item in prepared["sessions"]:
            identity = (item["hevy_workout_id"], item["exercise_template_id"])
            if conn.execute("""SELECT 1 FROM logged_sets WHERE hevy_workout_id = ?
                               AND exercise_template_id = ? LIMIT 1""", identity).fetchone():
                preserved += 1
                continue
            cursor = conn.execute("""INSERT INTO rpe_history_imports
                (hevy_workout_id, exercise_template_id, exercise_title, workout_title, workout_start, sets_json)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
                (*identity, item["exercise_title"], item["workout_title"], item["workout_start"], json.dumps(item["sets"])))
            if cursor.rowcount:
                added += 1
                sets_added += len(item["sets"])
            else:
                existing += 1
    return {"workouts_scanned": prepared["workouts_scanned"], "sessions_imported": added,
            "sets_imported": sets_added, "local_sessions_preserved": preserved,
            "sessions_already_imported": existing}


def chart_sets():
    """Exact local movement snapshots always win; imported sets stay isolated from other features."""
    with closing(get_db()) as conn:
        local = [dict(r) for r in conn.execute("SELECT * FROM logged_sets ORDER BY workout_start, id")]
        imported = [dict(r) for r in conn.execute("SELECT * FROM rpe_history_imports ORDER BY workout_start, exercise_template_id")]
    # Check all local rows, even if renamed or unrated, before using an imported snapshot.
    identities = {(r["hevy_workout_id"], r["exercise_template_id"]) for r in local}
    approved_ids = {row["exercise_template_id"]: row["exercise_title"] for row in [*local, *imported]
                    if any(row["exercise_title"] in titles for titles in GROUPS.values())}
    out = {key: [] for key in GROUPS}
    for row in local:
        title = approved_ids.get(row["exercise_template_id"])
        for key, titles in GROUPS.items():
            if title in titles:
                out[key].append({**row, "exercise_title": title, "source": "rackbook"})
    for item in imported:
        if (item["hevy_workout_id"], item["exercise_template_id"]) in identities:
            continue
        for key, titles in GROUPS.items():
            if item["exercise_title"] not in titles:
                continue
            for i, s in enumerate(json.loads(item["sets_json"]), 1):
                out[key].append({**{k: v for k, v in item.items() if k not in ("sets_json", "imported_at")},
                                 "set_number": i, "set_type": s["type"], "weight_kg": s["weight_kg"],
                                 "reps": s["reps"], "rpe": s["rpe"], "is_ts": 0, "source": "hevy_import"})
    return out


def sources(rows):
    counts = defaultdict(Counter)
    for row in rows:
        if not rpe_observed._usable([row]):
            continue
        key = (row["exercise_template_id"], row["exercise_title"])
        counts[key][row["source"]] += 1
    return [{"exercise_template_id": template, "title": title,
             "local_sets": count["rackbook"], "imported_sets": count["hevy_import"]}
            for (template, title), count in sorted(counts.items(), key=lambda item: item[0][1])]


def list_lifts():
    result = []
    for key, rows in chart_sets().items():
        usable = rpe_observed._usable(rows)
        movement_sources = sources(rows)
        primary = next((s for s in movement_sources if s["title"] == GROUPS[key][0]),
                       movement_sources[0] if movement_sources else None)
        result.append({"key": key, "title": GROUPS[key][0],
                       "exercise_template_id": primary["exercise_template_id"] if primary else None,
                       "sets": len(usable), "sessions": len({r["workout"] for r in usable})})
    return result


def build_group(key, chart):
    rows = chart_sets()[key]
    built = rpe_observed.build_observed(rows, [], chart)
    # A pooled chart cannot compare its variant-specific references to one movement's saved TS.
    built["fit"] = rpe_observed.fit_curve(rows, [], chart)
    return {"exercise_template_id": "group:" + key, "title": GROUPS[key][0],
            "sources": sources(rows), **built}
