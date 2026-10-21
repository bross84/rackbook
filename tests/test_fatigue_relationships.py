import gc
import os
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi.testclient import TestClient
import main
from database import get_db, init_db
from progress import LIFT_TITLES
from tests.test_fatigue import NOW


class RelationshipRoutesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"DB_PATH": os.path.join(self.tmp.name, "test.db")})
        env.start(); self.addCleanup(env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def seed(self, key="leg", title="Leg press", muscle="quadriceps"):
        with closing(get_db()) as conn, conn:
            conn.execute("INSERT INTO hevy_exercise_cache(id,title,primary_muscle) VALUES (?,?,?)", (key, title, muscle))
            conn.execute("""INSERT INTO logged_sets(exercise_template_id,exercise_title,hevy_workout_id,
                workout_start,set_number,set_type,reps,rpe) VALUES (?,?,'workout',?,1,'normal',10,8)""",
                (key, title, NOW.isoformat()))

    def test_empty_database_and_get_never_confirms_suggestions(self):
        self.assertEqual(self.client.get("/fatigue/relationships").json(), [])
        self.seed()
        with patch("main.hevy_client.HevyClient") as hevy:
            first = self.client.get("/fatigue/relationships").json()[0]
        hevy.assert_not_called()
        self.assertEqual(first["suggested_patterns"], ["squat"])
        self.assertEqual(first["patterns"], [])
        self.assertFalse(first["reviewed"])
        self.assertIsNone(first["reviewed_at"])
        with closing(get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fatigue_relationships").fetchone()[0], 0)

    def test_suggestions_cover_muscles_and_main_titles(self):
        cases = [("hamstrings", ["deadlift"]), ("lower_back", ["deadlift"]),
                 ("glutes", ["squat", "deadlift"]), ("chest", ["bench_press"]),
                 ("shoulders", ["bench_press"]), ("triceps", ["bench_press"]),
                 ("biceps", []), (None, [])]
        for i, (muscle, expected) in enumerate(cases):
            self.seed(str(i), "Exercise " + str(i), muscle)
        self.seed("main", LIFT_TITLES["bench"], "biceps")
        result = {r["exercise_template_id"]: r for r in self.client.get("/fatigue/relationships").json()}
        for i, (_, expected) in enumerate(cases):
            self.assertEqual(result[str(i)]["suggested_patterns"], expected)
        self.assertEqual(result["main"]["suggested_patterns"], ["bench_press"])

    def test_confirm_edit_and_explicit_empty_preserve_workouts(self):
        self.seed()
        with closing(get_db()) as conn:
            original = [tuple(r) for r in conn.execute("SELECT * FROM logged_sets")]
        with patch("main.hevy_client.HevyClient") as hevy:
            for choices in (["deadlift", "squat"], [], [], ["bench_press"]):
                response = self.client.put("/fatigue/relationships/leg", json={"patterns": choices})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertTrue(result["reviewed"])
                self.assertIsNotNone(result["reviewed_at"])
                self.assertEqual(set(result["patterns"]), set(choices))
        hevy.assert_not_called()
        init_db()  # additive migration is repeatable and retains confirmed choices
        with closing(get_db()) as conn:
            self.assertEqual([tuple(r) for r in conn.execute("SELECT * FROM logged_sets")], original)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fatigue_relationships").fetchone()[0], 1)
            self.assertEqual(main.fatigue_relationships.confirmed(conn), {"leg": ["bench_press"]})

    def test_validation_and_unrecorded_exercise(self):
        self.seed()
        for body in ({}, {"patterns": ["unknown"]}, {"patterns": ["squat", "squat"]}, {"patterns": None}):
            self.assertEqual(self.client.put("/fatigue/relationships/leg", json=body).status_code, 422)
        self.assertEqual(self.client.put("/fatigue/relationships/missing", json={"patterns": []}).status_code, 404)

    def test_logged_exercise_missing_from_cache_still_editable(self):
        self.seed()
        with closing(get_db()) as conn, conn:
            conn.execute("DELETE FROM hevy_exercise_cache")
        result = self.client.get("/fatigue/relationships").json()[0]
        self.assertEqual(result["title"], "Leg press")
        self.assertEqual(result["suggested_patterns"], [])
        self.assertEqual(self.client.put("/fatigue/relationships/leg", json={"patterns": ["squat"]}).status_code, 200)
