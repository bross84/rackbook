"""Optional integration check against the sibling's actual calculation code."""
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
import json

ROOT=Path(__file__).resolve().parents[1]
SIBLING=ROOT.parent/"hevy-fatigue"


@unittest.skipUnless(importlib.util.find_spec("sqlalchemy") and (SIBLING/"database.py").exists(),
                     "Requires version-pinned sibling source and its SQLAlchemy runtime")
class LegacyAdapterCase(unittest.TestCase):
    def test_real_formulas_frozen_date_future_exclusion_and_source_unchanged(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"data") as folder:
            source=Path(folder)/"hevy.db"; output=Path(folder)/"output.json"
            with patch.dict(os.environ,{"DB_PATH":str(source)}):
                spec=importlib.util.spec_from_file_location("trial_test_hf_schema",SIBLING/"database.py")
                module=importlib.util.module_from_spec(spec)
                sys.modules[spec.name]=module
                try:
                    spec.loader.exec_module(module)
                    module.Base.metadata.create_all(module.engine)
                    module.engine.dispose()
                finally:
                    sys.modules.pop(spec.name,None)
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute("INSERT INTO daily_readiness(date,tiredness,perceived_recovery) VALUES ('2026-10-22',0,0)")
                conn.execute("INSERT INTO daily_readiness(date,tiredness,perceived_recovery) VALUES ('2026-10-23',4,4)")
                conn.execute("INSERT INTO workout_logs(date,exercise_title,workout_id,is_conditioning) VALUES ('2026-10-23','Future','future',0)")
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            result=subprocess.run([sys.executable,str(ROOT/"fatigue_trial_legacy.py"),"--repo",str(SIBLING),"--db",str(source),"--at","2026-10-22","--output",str(output)],
                env={**os.environ,"TEMP":folder,"TMP":folder},capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["today"]["date"],"2026-10-22")
            self.assertEqual(data["today"]["tiredness"],0)
            self.assertEqual(data["today"]["fatigue_score"],0)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
