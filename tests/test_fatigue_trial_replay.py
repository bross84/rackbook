from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import fatigue_trial_replay as replay


class ReplayCase(unittest.TestCase):
    def test_backup_is_consistent_and_cannot_overwrite_source_or_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/"live.db"; target=Path(folder)/"copy.db"
            with closing(sqlite3.connect(source)) as conn, conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE observation(value INTEGER)")
                conn.execute("INSERT INTO observation VALUES (0)")
                conn.commit()
                provenance=replay.snapshot(source,target)
            self.assertEqual(len(provenance["sha256"]),64)
            with closing(sqlite3.connect(target)) as conn:
                self.assertEqual(conn.execute("SELECT value FROM observation").fetchone()[0],0)
            with self.assertRaises(ValueError): replay.snapshot(source,source)
            with self.assertRaises(ValueError): replay.snapshot(source,target)

    def sample(self):
        return ([dict(id=1,hevy_workout_id="w",exercise_template_id="e",set_number=1,set_type="normal",reps=5,weight_kg=100,rpe=4,is_ts=1)],
                [dict(id=2,workout_id="w",exercise_id="e",set_number=0,reps=5,weight_lbs=220,rpe=None)])

    def test_exact_local_values_and_ts_survive_missing_hevy_rpe(self):
        local,hevy=self.sample()
        result=replay.reconcile(local,hevy)
        self.assertEqual(result["matched_sets"][0]["exact_rpe"],4)
        self.assertEqual(result["matched_sets"][0]["exact_weight_kg"],100)
        self.assertEqual(result["matched_sets"][0]["is_ts"],1)
        self.assertIsNone(hevy[0]["rpe"])

    def test_duplicates_and_edited_loads_are_unresolved(self):
        local,hevy=self.sample()
        self.assertEqual(len(replay.reconcile(local,hevy+hevy)["unresolved"]),1)
        hevy[0]["weight_lbs"]=210
        self.assertEqual(replay.reconcile(local,hevy)["matched_sets"],[])
        self.assertEqual(len(replay.reconcile(local,hevy)["unresolved"]),1)

    def test_baselines_and_modes_are_scored_separately(self):
        examples=[dict(mode="strength",candidate="uncertain",subjective_only="below_usual",always_near_usual="near_usual",observed="below_usual")]
        result=replay.metrics(examples)
        self.assertEqual(result["strength"]["candidate"]["eligible"],0)
        self.assertEqual(result["strength"]["always_near_usual"]["missed_below_usual"],1)
        self.assertIsNone(result["hypertrophy"]["candidate"]["coverage"])
