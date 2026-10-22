import copy
import gc
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import database
import set_log
from workout_repair import repair


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(gc.collect)
        self.path = os.path.join(self.temp.name, "test.db")
        self.env = patch.dict(os.environ, DB_PATH=self.path)
        self.env.start()
        self.addCleanup(self.env.stop)
        database.init_db()
        self.workout = {"id": "affected", "title": "Test", "start_time": "2026-10-20T12:00:00Z",
                        "end_time": "2026-10-20T13:00:00Z", "exercises": [{
                            "exercise_template_id": "sq", "title": "Squat", "sets": [
                                {"type": "normal", "weight_kg": 100, "reps": 1, "rpe": None},
                                {"type": "normal", "weight_kg": 80, "reps": 5, "rpe": None}]}]}
        rows = set_log.rows_from_entry(self.workout, "affected")
        rows[0].update(rpe=5, is_ts=1)
        set_log.record(rows[:1])
        self.client = Mock(spec=["get_workout"])
        self.client.get_workout.return_value = self.workout
        self.backup = os.path.join(self.temp.name, "before.db")

    def rows(self):
        with database.get_db() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM logged_sets ORDER BY id")]

    def test_preview_apply_repeat_and_preservation(self):
        original = self.rows()
        with database.get_db() as conn:
            conn.execute("INSERT INTO session_soreness (hevy_workout_id,workout_start,squat) VALUES ('affected','date',2)")
            conn.execute("INSERT INTO training_max_history (exercise_template_id,set_at,weight_lb,reps,rpe,e1rm_lb) VALUES ('sq','date',220,1,5,250)")
            conn.execute("INSERT INTO mesocycles (id,document) VALUES ('plan','{}')")
            conn.execute("INSERT INTO mesocycle_completions (mesocycle_id,session_id,hevy_workout_id,workout_start) VALUES ('plan','day','affected','date')")
            protected = [conn.execute(query).fetchall() for query in (
                'SELECT * FROM session_soreness', 'SELECT * FROM training_max_history',
                'SELECT * FROM mesocycle_completions')]
        self.assertEqual(len(repair("affected", self.client)), 1)
        self.assertEqual(self.rows(), original)
        added = repair("affected", self.client, backup=self.backup)
        self.assertIsNone(added[0]["rpe"])
        self.assertEqual(added[0]["is_ts"], 0)
        self.assertEqual(self.rows()[0], original[0])
        self.assertEqual(repair("affected", self.client, backup=self.backup), [])
        with sqlite3.connect(self.backup) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM logged_sets").fetchone()[0], 1)
        with database.get_db() as conn:
            self.assertEqual(conn.execute("SELECT squat FROM session_soreness").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM training_max_history").fetchone()[0], 1)
            after = [conn.execute(query).fetchall() for query in (
                'SELECT * FROM session_soreness', 'SELECT * FROM training_max_history',
                'SELECT * FROM mesocycle_completions')]
            self.assertEqual(after, protected)

    def test_hevy_values_and_no_invented_ts(self):
        self.workout['exercises'][0]['sets'][1].update(rpe=8, ts=True)
        additions = repair('affected', self.client, backup=self.backup)
        self.assertEqual(additions[0]['rpe'], 8)
        self.assertEqual(additions[0]['weight_kg'], 80)
        self.assertEqual(additions[0]['is_ts'], 0)

    def test_ambiguous_and_conflicting_matches_abort(self):
        original = copy.deepcopy(self.workout)
        for mutate in [lambda w: w["exercises"].append(copy.deepcopy(w["exercises"][0])),
                       lambda w: w["exercises"][0]["sets"][0].update(reps=3),
                       lambda w: w.update(id="different"),
                       lambda w: w["exercises"][0]["sets"][0].update(weight_kg=90)]:
            self.workout = copy.deepcopy(original)
            mutate(self.workout)
            self.client.get_workout.return_value = self.workout
            with self.assertRaises(ValueError):
                repair("affected", self.client, backup=self.backup)
            self.assertFalse(os.path.exists(self.backup))
            self.assertEqual(len(self.rows()), 1)

    def test_no_overwrite_backup_or_add_warmups(self):
        self.workout["exercises"][0]["sets"][1]["type"] = "warmup"
        self.assertEqual(repair("affected", self.client), [])
        self.workout["exercises"][0]["sets"][1]["type"] = "normal"
        with open(self.backup, "w") as f:
            f.write("keep")
        with self.assertRaises(FileExistsError):
            repair("affected", self.client, backup=self.backup)
        self.assertEqual(len(self.rows()), 1)
