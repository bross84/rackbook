import gc
import os
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from database import get_db
from tests.test_fatigue import NOW, data
from progress import LIFT_TITLES


class FatigueRouteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"DB_PATH": os.path.join(self.tmp.name, "test.db")})
        env.start(); self.addCleanup(env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def seed(self, exercise="test-squat", key="squat", pattern="squat", values=None):
        ts, sets, observations, weights = data(values or [300]*12)
        with closing(get_db()) as conn, conn:
            conn.execute("INSERT INTO hevy_exercise_cache(id,title) VALUES (?,?)",(exercise,LIFT_TITLES[key]))
            conn.executemany("INSERT INTO training_max_history(exercise_template_id,e1rm_lb,weight_lb,reps,rpe,set_at) VALUES (?,?,200,1,8,?)",[(exercise,r["e1rm_lb"],r["set_at"]) for r in ts])
            conn.executemany("INSERT INTO logged_sets(exercise_template_id,hevy_workout_id,workout_start,set_number,set_type,reps,rpe) VALUES (?,?,?,1,'normal',?,?)",[(exercise,r["hevy_workout_id"],r["workout_start"],r["reps"],r["rpe"]) for r in sets])
            # Only test-selected pattern columns; production queries are parameterized.
            for r in observations:
                conn.execute("INSERT OR IGNORE INTO session_soreness(hevy_workout_id,workout_start,squat,bench_press) VALUES (?,?,0,1)",(r["hevy_workout_id"],NOW.isoformat()))
            conn.executemany("INSERT OR IGNORE INTO body_measurements(date,weight_kg) VALUES (?,?)",[(r["date"],r["weight_kg"]) for r in weights])

    def test_read_only_endpoint_and_unknown_history(self):
        with patch("main.hevy_client.HevyClient") as hevy:
            response=self.client.get("/movement-fatigue/unknown")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["action"],"collect")
        self.assertEqual(response.json()["points"],[])
        hevy.assert_not_called()

    def test_exact_ids_are_isolated_and_pattern_mapped(self):
        self.seed()
        self.seed("other", "bench", values=[400]*12)
        result=main.fatigue.load("test-squat",now=NOW)
        self.assertEqual(result["pattern"],"squat")
        self.assertEqual(len(result["points"]),12)
        self.assertTrue(all(p["e1rm_lb"]==300 for p in result["points"]))
        response=self.client.get("/movement-fatigue/test-squat")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["model_version"],"ts-trends-v2")

    def test_press_and_bench_share_soreness_not_performance(self):
        self.seed("press", "press")
        self.seed("bench", "bench",values=[250]*12)
        press=main.fatigue.load("press",now=NOW)
        bench=main.fatigue.load("bench",now=NOW)
        self.assertEqual(press["pattern"],"bench_press")
        self.assertEqual(press["recent_soreness"],1)
        self.assertTrue(all(p["e1rm_lb"]==300 for p in press["points"]))
        self.assertTrue(all(p["e1rm_lb"]==250 for p in bench["points"]))
