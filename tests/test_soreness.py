"""Soreness stays local; all Hevy calls are mocked."""
import gc
import os
from contextlib import closing
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from database import get_db


class SorenessCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"DB_PATH": os.path.join(self.tmp.name, "test.db")})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.entry = dict(title="Test", start_time="2026-10-18T10:00:00Z",
                          end_time="2026-10-18T11:00:00Z", exercises=[dict(exercise_template_id="mock-squat", sets=[dict(type="normal", weight_kg=100, reps=5, rpe=7)])],
                          soreness=dict(squat=dict(level=0), bench_press=dict(level=2), deadlift=dict(pain=True)))

    def test_saved_locally_not_sent_to_hevy(self):
        with patch("main._call_hevy", return_value={"id": "mock-workout"}):
            response = self.client.post("/hevy/workouts", json=self.entry)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("soreness", main.build_hevy_workout(self.entry)["workout"])
        with closing(get_db()) as conn:
            row = conn.execute("SELECT * FROM session_soreness").fetchone()
        self.assertEqual((row["squat"], row["bench_press"], row["deadlift"]), (0, 2, None))
        self.assertEqual((row["squat_pain"], row["bench_press_pain"], row["deadlift_pain"]), (0, 0, 1))

    def test_invalid_rating_rejected_before_hevy(self):
        self.entry["soreness"]["squat"] = dict(level=4)
        with patch("main._call_hevy") as hevy:
            self.assertEqual(self.client.post("/hevy/workouts", json=self.entry).status_code, 422)
        hevy.assert_not_called()

    def test_missing_ratings_are_not_no_soreness(self):
        self.entry["soreness"] = {}
        with patch("main._call_hevy", return_value={"id": "mock-workout"}):
            self.assertEqual(self.client.post("/hevy/workouts", json=self.entry).status_code, 200)
        with closing(get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM session_soreness").fetchone()[0], 0)

    def test_local_failure_returns_warning_without_inviting_retry(self):
        with patch("main._call_hevy", return_value={"id": "mock-workout"}), patch("main.soreness.record", side_effect=RuntimeError("disk")), self.assertLogs("main", level="ERROR"):
            response = self.client.post("/hevy/workouts", json=self.entry)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Do not save", response.json()["plan_warning"])

    def test_failed_hevy_save_does_not_record_soreness(self):
        from fastapi import HTTPException
        with patch("main._call_hevy", side_effect=HTTPException(502, "mock failure")):
            self.assertEqual(self.client.post("/hevy/workouts", json=self.entry).status_code, 502)
        with closing(get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM session_soreness").fetchone()[0], 0)

    def test_all_levels_and_strict_validation(self):
        for value in (0, 1, 2, 3):
            self.assertEqual(main.PatternSoreness(level=value).level, value)
        from pydantic import ValidationError
        for value in (-1, 4, 1.5, True, "1"):
            with self.assertRaises(ValidationError):
                main.PatternSoreness(level=value)

    def test_repeated_local_record_preserves_observation(self):
        main.soreness.record("mock-workout", self.entry["start_time"], self.entry["soreness"])
        main.soreness.record("mock-workout", self.entry["start_time"], dict(squat=dict(level=3)))
        with closing(get_db()) as conn:
            rows = conn.execute("SELECT * FROM session_soreness").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["squat"], 0)

    def test_edit_preserves_other_patterns_and_never_calls_hevy(self):
        main.soreness.record("mock-workout", self.entry["start_time"], self.entry["soreness"])
        with patch("main._call_hevy") as hevy:
            response = self.client.patch("/workout-soreness/mock-workout", json={"deadlift": {"level": 1, "pain": False}})
            self.assertEqual(response.status_code, 200)
            ratings = self.client.get("/workout-soreness/mock-workout").json()
        hevy.assert_not_called()
        self.assertEqual(ratings["squat"]["level"], 0)
        self.assertEqual(ratings["bench_press"], {"level": 2, "pain": False})
        self.assertEqual(ratings["deadlift"], {"level": 1, "pain": False})
        self.client.patch("/workout-soreness/mock-workout", json={"deadlift": None})
        self.assertEqual(self.client.get("/workout-soreness/mock-workout").json()["deadlift"], {"level": None, "pain": False})

    def test_add_forgotten_rating_to_unrated_saved_workout(self):
        self.entry["soreness"] = None
        with patch("main._call_hevy", return_value={"id": "mock-workout"}):
            self.client.post("/hevy/workouts", json=self.entry)
        with closing(get_db()) as conn:
            before = [dict(row) for row in conn.execute("SELECT * FROM logged_sets")]
        with patch("main._call_hevy") as hevy:
            response = self.client.patch("/workout-soreness/mock-workout", json={"deadlift": {"level": 0}})
        hevy.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deadlift"]["level"], 0)
        self.assertIsNone(response.json()["squat"]["level"])
        with closing(get_db()) as conn:
            self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM logged_sets")], before)
            self.assertEqual(conn.execute("SELECT workout_start FROM session_soreness").fetchone()[0], self.entry["start_time"])

    def test_edit_rejects_unknown_workout_and_invalid_rating(self):
        with patch("main._call_hevy") as hevy:
            self.assertEqual(self.client.get("/workout-soreness/missing").status_code, 404)
            self.assertEqual(self.client.patch("/workout-soreness/missing", json={"squat": {"level": 1}}).status_code, 404)
            self.assertEqual(self.client.patch("/workout-soreness/missing", json={"squat": {"level": 4}}).status_code, 422)
        hevy.assert_not_called()

    def test_pattern_titles_match_fatigue_mapping(self):
        patterns = self.client.get("/soreness/patterns").json()
        self.assertEqual(patterns[main.progress.LIFT_TITLES["deadlift"]], "deadlift")
        self.assertEqual(patterns[main.progress.LIFT_TITLES["press"]], "bench_press")

    def test_recent_exposes_editor_only_for_locally_recorded_workouts(self):
        main.soreness.record("mock-workout", self.entry["start_time"], self.entry["soreness"])
        history = {"page": 1, "page_count": 1, "workouts": [
            {"id": "mock-workout", "title": "Local", "exercises": []},
            {"id": "older-hevy-only", "title": "Older", "exercises": []},
        ]}
        with patch("main._call_hevy", return_value=history):
            response = self.client.get("/hevy/workouts")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([w["soreness_editable"] for w in response.json()["workouts"]], [True, False])
