"""Run the sibling app's actual formulas on an ephemeral, earlier-only DB copy.

Invoke in the Hevy Fatigue Python/Docker runtime, with its source repo mounted:
python /tools/fatigue_trial_legacy.py --repo /hevy --db /snapshots/hevy-fatigue.db
    --at 2026-10-22 --output /results/hevy-2026-10-22.json

No startup hook, migration, importer or Hevy client method is invoked. Historical
same-day check-ins and present-day settings remain explicitly timing-uncertain.
"""
import argparse
from contextlib import closing
from datetime import date
import importlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import types


def run(repo, source, day):
    target = date.fromisoformat(day)
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder)/"replay.db"
        with closing(sqlite3.connect(Path(source).resolve().as_uri()+"?mode=ro",uri=True)) as src:
            with closing(sqlite3.connect(copy)) as dst:
                src.backup(dst)
                # HF logs have only dates; exclude all target-day training rather
                # than guessing intraday availability. Retain that day's check-in
                # for descriptive replay, explicitly not prospective validation.
                dst.execute("DELETE FROM workout_logs WHERE date >= ?",(day,))
                dst.execute("DELETE FROM workout_sessions WHERE workout_date >= ?",(day,))
                dst.execute("DELETE FROM daily_readiness WHERE date > ?",(day,))
                dst.commit()
        os.environ["DB_PATH"]=str(copy)
        sys.path.insert(0,str(Path(repo).resolve()))
        # Runtime guard: replay must never contact Hevy or any other service.
        def offline(*args,**kwargs):
            raise RuntimeError("Network access is disabled during historical replay")
        socket.socket.connect=offline
        # The calculation module imports its synchronization entry points at
        # module load. Replace only those write-capable entry points with guards;
        # calculation functions and their SQLAlchemy models remain original.
        blocked_importer=types.ModuleType("importer")
        blocked_importer.import_hevy_data=offline
        blocked_importer.reclassify_existing_sessions=offline
        sys.modules["importer"]=blocked_importer
        app=importlib.import_module("main")
        database=importlib.import_module("database")
        class ReplayDate(date):
            @classmethod
            def today(cls):
                return cls(target.year,target.month,target.day)
        app.date_type=ReplayDate
        session=database.SessionLocal()
        try:
            output=app.get_training_load(days=60,db=session)
            result=dict(date=day,timing="same-day check-in timing uncertain; all target-day workouts excluded",
                        historical_settings="Current settings and mappings; original edit history unavailable",
                        today=output["today"],thresholds=output["thresholds"])
        finally:
            session.close()
            database.engine.dispose()
        return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("repo","db","at","output"):
        parser.add_argument("--"+key,required=True)
    args=parser.parse_args()
    result=run(args.repo,args.db,args.at)
    Path(args.output).write_text(json.dumps(result,indent=2,default=str),encoding="utf-8")
