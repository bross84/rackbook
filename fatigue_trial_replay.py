"""Offline evidence inventory/replay. Inputs are copied with SQLite backup, never migrated.

python fatigue_trial_replay.py --rackbook rackbook.db --hevy data/hevy_fatigue.db
    --output data/trial --rackbook-version <sha> --hevy-version <sha>

Versions must describe the supplied databases' deployments, or explicitly say unknown.
Current settings/edited historical observations are descriptive evidence, not as-recorded history.
"""
import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import fatigue
import fatigue_trial as trial
from fatigue_context import timestamp


def snapshot(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError("Snapshot destination must be a new file distinct from its source.")
    with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    return {"sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "snapshot_at": datetime.now(timezone.utc).isoformat()}


def rows(conn, query):
    return [dict(r) for r in conn.execute(query)]


def reconcile(local, imported):
    """Join only unambiguous workout/exercise groups; preserve Rackbook exact values.

    HF indices originate in Hevy, are zero-based and may have warm-up gaps. No
    ordinal match is assumed across those gaps. Uncertain identities stay unresolved.
    """
    mine, theirs = defaultdict(list), defaultdict(list)
    for row in local:
        mine[(row["hevy_workout_id"], row["exercise_template_id"])].append(row)
    for row in imported:
        theirs[(row["workout_id"], row["exercise_id"])].append(row)
    matches, unresolved = [], []
    for key in mine.keys() & theirs.keys():
        left, right = mine[key], theirs[key]
        left = [r for r in left if r.get("set_type") != "warmup"]
        index = {r["set_number"]: r for r in right}
        valid = len(left) == len(right) == len(index) and len({r["set_number"] for r in left}) == len(left)
        paired = []
        for a in left:
            b = index.get(a["set_number"]-1)
            valid = valid and b is not None and a.get("reps") == (b or {}).get("reps")
            # Whole-pound Hevy roundoff is allowed only to establish identity.
            if b and a.get("weight_kg") is not None and b.get("weight_lbs") is not None:
                valid = valid and abs(a["weight_kg"]*2.20462-b["weight_lbs"]) <= .51
            else:
                valid = False
            paired.append((a,b))
        if not valid:
            unresolved.append({"workout_id":key[0], "exercise_id":key[1], "reason":"Ambiguous identity, edited load/reps, missing values or index mismatch"})
            continue
        matches.extend({"workout_id":key[0],"exercise_id":key[1],"local_id":a["id"],"imported_id":b["id"],
                        "exact_weight_kg":a.get("weight_kg"),"exact_rpe":a.get("rpe"),"is_ts":a.get("is_ts")} for a,b in paired)
    return dict(matched_sets=matches, unresolved=unresolved, overlapping_movements=len(mine.keys() & theirs.keys()))


def metrics(examples):
    out = {}
    for mode in ("strength", "hypertrophy"):
        group = [r for r in examples if r["mode"] == mode]
        common=[r for r in group if r["candidate"]!="uncertain" and r["subjective_only"]!="uncertain" and r["observed"]!="unclassified"]
        out[mode] = {}
        for model in ("candidate", "subjective_only", "always_near_usual"):
            scored = [r for r in group if r[model] != "uncertain" and r["observed"] != "unclassified"]
            out[mode][model] = dict(total=len(group), eligible=len(scored),
                coverage=len(scored)/len(group) if group else None,
                missed_below_usual=sum(r["observed"]=="below_usual" and r[model]=="near_usual" for r in scored),
                unnecessary_warnings=sum(r["observed"]=="near_usual" and r[model]=="below_usual" for r in scored))
            out[mode][model].update(common_eligible=len(common),
                common_missed_below_usual=sum(r[model]=="near_usual" and r["observed"]=="below_usual" for r in common),
                common_unnecessary_warnings=sum(r[model]=="below_usual" and r["observed"]=="near_usual" for r in common))
    return out


def replay(rackbook_path, hevy_path):
    previous_db = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = str(rackbook_path)
    try:
        with closing(sqlite3.connect(Path(rackbook_path).as_uri()+"?mode=ro", uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            local=trial.with_order(rows(conn,"SELECT * FROM logged_sets ORDER BY workout_start,id"))
            observations=rows(conn,"SELECT * FROM session_soreness")
            ts=rows(conn,"SELECT * FROM training_max_history")
        with closing(sqlite3.connect(Path(hevy_path).as_uri()+"?mode=ro", uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            imported=rows(conn,"SELECT * FROM workout_logs")
            checkins=rows(conn,"SELECT * FROM daily_readiness ORDER BY date")
        joined=reconcile(local,imported)
        obs={r["hevy_workout_id"]:r for r in observations}
        daily={r["date"]:r for r in checkins}
        by_exercise=defaultdict(list)
        groups=defaultdict(list)
        for row in local:
            by_exercise[row["exercise_template_id"]].append(row)
            groups[(row["workout_start"],row["hevy_workout_id"],row["exercise_template_id"])].append(row)
        examples=[]
        for (start,workout_id,exercise), sets in sorted(groups.items()):
            at=timestamp(start)
            if at is None:
                continue
            mode="strength" if any(r.get("is_ts") for r in sets) else "hypertrophy"
            target=trial.representative(sets,mode)
            if target is None:
                continue
            baseline=trial.reference(by_exercise[exercise],target,mode,at)
            # Exclude the entire target session from the existing model as well.
            old=fatigue.load(exercise,now=at-timedelta(microseconds=1))
            pattern=old["pattern"]
            rating=obs.get(workout_id,{}).get(pattern) if pattern else None
            checkin=dict(status="available" if at.date().isoformat() in daily else "unavailable",
                         ratings=daily.get(at.date().isoformat(),{}))
            context=trial.today_context(exercise,at,old["pattern"])
            candidate,reasons=trial.assess(rating,checkin,baseline,context)
            subjective,_=trial.assess(rating,checkin,[None]*3,{"block_reasons":[]})
            examples.append(dict(workout_id=workout_id,exercise_id=exercise,start_time=start,mode=mode,
                candidate=candidate,subjective_only=subjective,always_near_usual="near_usual",
                observed=trial.performance(target,baseline,mode),reasons=reasons,
                existing_rackbook=dict(status=old["status"],action=old["action"],context=old["context"]),
                hevy_fatigue="Run the version-pinned legacy replay adapter; unlike outputs remain separate.",
                checkin_timing="same-day timing uncertain; descriptive only", baseline_ids=[r["id"] for r in baseline],
                history_caveat="Historical edits/settings/mapping availability cannot be reconstructed."))
        return dict(coverage=dict(local_sets=len(local),marked_top_sets=len(ts),soreness_records=len(observations),
                    hevy_workouts=len({r["workout_id"] for r in imported}),daily_checkins=len(checkins),
                    local_missing_rpe=sum(r.get("rpe") is None for r in local),
                    hevy_missing_rpe=sum(r.get("rpe") is None for r in imported),
                    daily_missing_ratings=sum(any(r.get(k) is None for k in ("tiredness","perceived_recovery")) for r in checkins)),
                    reconciliation=joined, chronological_comparison=examples, metrics=metrics(examples),
                    conclusion="Inconclusive. Historical timing, edits and sparse exact movement observations prevent prospective validation.")
    finally:
        if previous_db is None:
            os.environ.pop("DB_PATH",None)
        else:
            os.environ["DB_PATH"]=previous_db


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("rackbook","hevy","output","rackbook-version","hevy-version"):
        parser.add_argument("--"+key,required=True)
    parser.add_argument("--legacy-repo", help="Version-pinned sibling source; run using --legacy-python with its dependencies")
    parser.add_argument("--legacy-python", default=sys.executable)
    args=parser.parse_args()
    folder=Path(args.output).resolve(); folder.mkdir(parents=True,exist_ok=True)
    rack,hevy=folder/"rackbook.db",folder/"hevy-fatigue.db"
    provenance=dict(rackbook=snapshot(args.rackbook,rack),hevy_fatigue=snapshot(args.hevy,hevy),
                    rackbook_version=args.rackbook_version,hevy_version=args.hevy_version,model_version=trial.VERSION)
    (folder/"provenance.json").write_text(json.dumps(provenance,indent=2),encoding="utf-8")
    try:
        report=replay(rack,hevy)
    except sqlite3.OperationalError as exc:
        report=dict(coverage=None, conclusion="Unavailable: supplied database schema is incomplete. " + str(exc))
    legacy={}
    if args.legacy_repo and report.get("chronological_comparison"):
        for example in report["chronological_comparison"]:
            day=example["start_time"][:10]
            if day not in legacy:
                output=folder/("hevy-"+day+".json")
                completed=subprocess.run([args.legacy_python,str(Path(__file__).with_name("fatigue_trial_legacy.py")),
                    "--repo",args.legacy_repo,"--db",str(hevy),"--at",day,"--output",str(output)],
                    capture_output=True,text=True,timeout=60)
                legacy[day]=json.loads(output.read_text(encoding="utf-8")) if completed.returncode==0 else {"status":"unavailable", "reason":"Sibling runtime/schema is incompatible; no substitute output was calculated."}
            example["hevy_fatigue"]=legacy[day]
    (folder/"comparison.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"coverage":report["coverage"],"conclusion":report["conclusion"]},indent=2))


if __name__ == "__main__":
    main()
