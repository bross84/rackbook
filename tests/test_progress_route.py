"""Tests for GET /progress/data and the /progress page. The Hevy client is mocked: no network."""
import os
import shutil
import sys
import tempfile
import unittest
import warnings
from unittest import mock

warnings.filterwarnings("ignore", category=ResourceWarning)

_IMPORT_DIR = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_IMPORT_DIR, "import.db"))

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import progress  # noqa: E402
from database import get_db  # noqa: E402


class ProgressRouteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DB_PATH"] = os.path.join(self.tmp, "test.db")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

        patcher = mock.patch("main.hevy_client.HevyClient")
        self.hevy_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.hevy = self.hevy_cls.return_value

    def cache_exercise(self, template_id, title):
        with get_db() as conn:
            conn.execute("INSERT INTO hevy_exercise_cache (id, title) VALUES (?, ?)", (template_id, title))

    def add_weight(self, date, kg):
        with get_db() as conn:
            conn.execute("INSERT INTO body_measurements (date, weight_kg) VALUES (?, ?)", (date, kg))


class TestProgressData(ProgressRouteCase):
    def test_unknown_lift_is_rejected(self):
        self.assertEqual(422, self.client.get("/progress/data?lift=curl").status_code)

    def test_lift_missing_from_the_exercise_cache_is_a_404_that_says_to_sync(self):
        r = self.client.get("/progress/data?lift=bench")
        self.assertEqual(404, r.status_code)
        self.assertIn("Sync exercises", r.json()["detail"])

    def test_returns_e1rm_with_bodyweight_and_score(self):
        self.cache_exercise("BENCH1", progress.LIFT_TITLES["bench"])
        self.add_weight("2026-10-01", 80.0)
        self.hevy.exercise_history.return_value = [{
            "workout_id": "w1", "workout_start_time": "2026-10-02T17:00:00+00:00",
            "set_type": "normal", "weight_kg": 100.0, "reps": 5, "rpe": 8,
        }]
        r = self.client.get("/progress/data?lift=bench")
        self.assertEqual(200, r.status_code, r.text)
        body = r.json()
        self.assertEqual(("bench", progress.LIFT_TITLES["bench"]), (body["lift"], body["title"]))
        self.hevy.exercise_history.assert_called_once_with("BENCH1")
        (point,) = body["series"]
        self.assertEqual("2026-10-02", point["date"])
        self.assertGreater(point["e1rm_lb"], 220)
        self.assertEqual(round(80 * 2.20462, 1), point["bodyweight_lb"])
        self.assertGreater(point["dots"], 0)
        self.assertEqual(point["bodyweight_source_date"], "2026-10-01")
        self.assertEqual(point["bodyweight_age_days"], 1)
        self.assertEqual(point["bodyweight_weigh_in_count"], 1)

    def test_no_bodyweight_still_returns_the_e1rm(self):
        self.cache_exercise("SQ1", progress.LIFT_TITLES["squat"])
        self.hevy.exercise_history.return_value = [{
            "workout_id": "w1", "workout_start_time": "2026-10-02T17:00:00+00:00",
            "set_type": "normal", "weight_kg": 140.0, "reps": 5, "rpe": 8,
        }]
        (point,) = self.client.get("/progress/data?lift=squat").json()["series"]
        self.assertIsNone(point["bodyweight_lb"])
        self.assertIsNone(point["dots"])
        for key in ["bodyweight_source_date", "bodyweight_age_days", "bodyweight_weigh_in_count"]:
            self.assertIsNone(point[key])

    def test_no_api_key_is_a_400(self):
        self.cache_exercise("DL1", progress.LIFT_TITLES["deadlift"])
        self.hevy_cls.side_effect = ValueError("No Hevy API key configured.")
        self.assertEqual(400, self.client.get("/progress/data?lift=deadlift").status_code)


class TestProgressPage(ProgressRouteCase):
    def test_page_is_served_and_not_cached(self):
        r = self.client.get("/progress")
        self.assertEqual(200, r.status_code)
        self.assertEqual("no-cache", r.headers["cache-control"])
        self.assertIn("Progress", r.text)

    def test_chart_scripts_are_bundled_and_served_locally(self):
        for name in ["chart-4.4.0.umd.js", "hammer-2.0.8.min.js", "chartjs-plugin-zoom-2.2.0.min.js"]:
            path = "/static/vendor/" + name
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertGreater(len(response.content), 10000)
            self.assertIn(path, self.client.get("/progress").text)

    def test_log_page_links_to_progress(self):
        self.assertIn('href="/progress"', self.client.get("/log").text)


if __name__ == "__main__":
    unittest.main()
