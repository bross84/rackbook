"""Explicit, local-only repair of one identified workout. No Hevy writes.

Run on the production host with DB_PATH and FERNET_KEY_PATH configured:
python workout_repair.py WORKOUT_ID
python workout_repair.py WORKOUT_ID --apply --backup /data/repair-before.sqlite
The first invocation only compares. Ambiguous comparisons abort without writes.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from database import get_db
from set_log import rows_from_entry
from workout_payload import build_hevy_workout


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def missing_rows(workout, existing):
    """Require unique movement/position identities and matching saved anchors."""
    workout_id = workout.get("id")
    if not workout_id or not existing:
        raise ValueError("Need an identified Hevy workout and existing Rackbook records.")
    exercises = workout.get("exercises") or []
    ids = [ex["exercise_template_id"] for ex in exercises]
    if len(ids) != len(set(ids)):
        raise ValueError("Ambiguous repeated movement in Hevy workout.")
    rows = rows_from_entry(workout, workout_id)
    for row in rows:
        row["is_ts"] = 0  # Hevy has no Rackbook TS marker; never infer one.
        if row["set_type"] not in ("normal", "failure", "dropset", "warmup"):
            raise ValueError("Unsupported set type; stop for review.")
    expected = {(r["exercise_template_id"], r["set_number"]): r for r in rows}
    seen = set()
    for local in existing:
        key = (local["exercise_template_id"], local["set_number"])
        remote = expected.get(key)
        if key in seen or remote is None:
            raise ValueError("Ambiguous or missing set position.")
        seen.add(key)
        if (local["hevy_workout_id"] != workout_id
                or _time(local["workout_start"]) != _time(workout["start_time"])
                or local["workout_title"] != workout["title"]
                or local["reps"] != remote["reps"]
                or local["set_type"] != remote["set_type"]):
            raise ValueError("Workout/set identity mismatch; stop for review.")
        # Original kg values may have been uploaded rounded to whole pounds.
        weights = [local["weight_kg"]]
        if local["weight_kg"] is not None:
            weights.append(build_hevy_workout({
                "title": "comparison", "start_time": workout["start_time"],
                "end_time": workout["end_time"], "weight_unit": "lb",
                "exercises": [{"exercise_template_id": key[0], "sets": [{
                    "weight_kg": local["weight_kg"], "reps": local["reps"]}]}]
            })["workout"]["exercises"][0]["sets"][0]["weight_kg"])
        if not any((w is None and remote["weight_kg"] is None) or
                   (w is not None and remote["weight_kg"] is not None and
                    math.isclose(w, remote["weight_kg"], abs_tol=1e-6)) for w in weights):
            raise ValueError("Set weight mismatch; stop for review.")
        if remote["rpe"] is not None and remote["rpe"] != local["rpe"]:
            raise ValueError("Set RPE mismatch; stop for review.")
    return [r for r in rows if (r["exercise_template_id"], r["set_number"]) not in seen
            and r["set_type"] != "warmup"]


def repair(workout_id, client, *, backup=None):
    """Compare using a read-only Hevy client; backup required to apply additions."""
    workout = client.get_workout(workout_id)
    if workout.get("id") != workout_id:
        raise ValueError("Hevy returned a different workout ID.")
    with closing(get_db()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = [dict(r) for r in conn.execute(
            "SELECT * FROM logged_sets WHERE hevy_workout_id = ? ORDER BY id", (workout_id,))]
        additions = missing_rows(workout, existing)
        if backup is None or not additions:
            return additions
        path = Path(backup)
        # Exclusive creation prevents accidentally overwriting a previous backup.
        with path.open("xb"):
            pass
        # Backup through a separate reader while this transaction holds the writer lock.
        with closing(get_db()) as source, closing(sqlite3.connect(path)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Backup integrity check failed.")
        conn.executemany(
            "INSERT INTO logged_sets (hevy_workout_id, workout_title, workout_start, workout_end, "
            "exercise_template_id, exercise_title, set_number, set_type, weight_kg, reps, rpe, is_ts) "
            "VALUES (:hevy_workout_id, :workout_title, :workout_start, :workout_end, "
            ":exercise_template_id, :exercise_title, :set_number, :set_type, :weight_kg, :reps, :rpe, :is_ts)",
            additions)
        repaired = [dict(r) for r in conn.execute(
            "SELECT * FROM logged_sets WHERE hevy_workout_id = ? ORDER BY id", (workout_id,))]
        if missing_rows(workout, repaired):
            raise ValueError("Repair verification failed.")
        if repaired[:len(existing)] != existing:
            raise ValueError("Existing records changed.")
        return additions


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from hevy_client import HevyClient
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workout_id")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error("--apply requires a new --backup path")
    rows = repair(args.workout_id, HevyClient(), backup=args.backup if args.apply else None)
    print(json.dumps({"applied": args.apply, "missing_sets": rows}, indent=2))
