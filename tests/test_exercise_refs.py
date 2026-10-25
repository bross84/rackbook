"""Per-movement settings, the RPE table endpoint, and the exercise-state endpoint the log page reads."""
import csv
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import warnings
from unittest import mock

import httpx

warnings.filterwarnings("ignore", category=ResourceWarning)

_IMPORT_DIR = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_IMPORT_DIR, "import.db"))

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
import main  # noqa: E402

USER_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rpe_chart_user.csv")


class RefsCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {"DB_PATH": os.path.join(self.tmp, "t.db"), "RPE_CHART_PATH": USER_CSV})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)


class TestMovementSettings(RefsCase):

    def test_starts_empty(self):
        self.assertEqual([], self.client.get("/exercise-refs").json())

    def test_defaults_are_e1rm_last_set_on_and_95_percent(self):
        r = self.client.put("/exercise-refs/tpl-bench", json={})
        self.assertEqual(
            {"exercise_template_id": "tpl-bench", "basis": "e1rm", "ls": True, "tm_pct": 0.95, "step_kg": 2.5, "step_lb": 5.0, "bar_kg": 20.0, "chain_kg": 0.0, "rest_sec": None, "weight_unit": None}, r.json()
        )

    def test_save_and_list(self):
        r = self.client.put("/exercise-refs/tpl-squat", json={"basis": "tm", "ls": False, "tm_pct": 0.9})
        self.assertEqual(200, r.status_code, r.text)
        expected = {"exercise_template_id": "tpl-squat", "basis": "tm", "ls": False, "tm_pct": 0.9, "step_kg": 2.5, "step_lb": 5.0, "bar_kg": 20.0, "chain_kg": 0.0, "rest_sec": None, "weight_unit": None}
        self.assertEqual(expected, r.json())
        self.assertEqual([expected], self.client.get("/exercise-refs").json())

    def test_saving_again_updates_instead_of_duplicating(self):
        self.client.put("/exercise-refs/tpl-squat", json={"basis": "tm"})
        self.client.put("/exercise-refs/tpl-squat", json={"basis": "e1rm", "ls": False})
        rows = self.client.get("/exercise-refs").json()
        self.assertEqual(1, len(rows))
        self.assertEqual(("e1rm", False), (rows[0]["basis"], rows[0]["ls"]))

    def test_movements_are_kept_apart(self):
        self.client.put("/exercise-refs/a", json={"basis": "tm"})
        self.client.put("/exercise-refs/b", json={"basis": "e1rm"})
        self.assertEqual(
            {"a": "tm", "b": "e1rm"},
            {r["exercise_template_id"]: r["basis"] for r in self.client.get("/exercise-refs").json()},
        )

    def test_per_movement_units_persist_and_can_follow_page_again(self):
        for exercise, unit in [('curl', 'lb'), ('squat', 'kg'), ('bench', None)]:
            response = self.client.put('/exercise-refs/' + exercise, json={'weight_unit': unit})
            self.assertEqual(200, response.status_code, response.text)
        units = {r['exercise_template_id']: r['weight_unit'] for r in self.client.get('/exercise-refs').json()}
        self.assertEqual(units, dict(curl='lb', squat='kg', bench=None))
        self.assertIsNone(self.client.put('/exercise-refs/curl', json={'weight_unit': None}).json()['weight_unit'])
        self.assertEqual(422, self.client.put('/exercise-refs/curl', json={'weight_unit': 'stone'}).status_code)

    def test_unit_migration_keeps_existing_preferences_and_follows_page(self):
        self.client.put('/exercise-refs/curl', json={'step_kg': 0.5, 'step_lb': 2.5, 'rest_sec': 90})
        with database.get_db() as conn:
            conn.execute('ALTER TABLE exercise_refs DROP COLUMN weight_unit')
        database.init_db()
        database.init_db()
        row = self.client.get('/exercise-refs').json()[0]
        self.assertIsNone(row['weight_unit'])
        self.assertEqual((row['step_kg'], row['step_lb'], row['rest_sec']), (0.5, 2.5, 90))

    def test_rejects_unknown_basis_and_silly_tm_percentages(self):
        for bad in ({"basis": "percent"}, {"tm_pct": 0.2}, {"tm_pct": 1.5}):
            self.assertEqual(422, self.client.put("/exercise-refs/x", json=bad).status_code, bad)

    def test_the_rounding_step_is_saved_per_movement(self):
        self.client.put("/exercise-refs/pullup", json={"step_kg": 0.5})
        self.client.put("/exercise-refs/squat", json={})
        steps = {r["exercise_template_id"]: r["step_kg"] for r in self.client.get("/exercise-refs").json()}
        self.assertEqual({"pullup": 0.5, "squat": 2.5}, steps)

    def test_the_lb_rounding_step_is_saved_per_movement_too(self):
        self.client.put("/exercise-refs/pullup", json={"step_kg": 0.5, "step_lb": 1})
        self.client.put("/exercise-refs/squat", json={})
        steps = {r["exercise_template_id"]: (r["step_kg"], r["step_lb"]) for r in self.client.get("/exercise-refs").json()}
        self.assertEqual({"pullup": (0.5, 1.0), "squat": (2.5, 5.0)}, steps)

    def test_the_bar_and_chains_are_saved_per_movement(self):
        self.client.put("/exercise-refs/ssb-squat", json={"bar_kg": 30})
        self.client.put("/exercise-refs/bench", json={"chain_kg": 20})
        self.client.put("/exercise-refs/deadlift", json={})
        got = {r["exercise_template_id"]: (r["bar_kg"], r["chain_kg"]) for r in self.client.get("/exercise-refs").json()}
        self.assertEqual({"ssb-squat": (30.0, 0.0), "bench": (20.0, 20.0), "deadlift": (20.0, 0.0)}, got)

    def test_rest_time_is_saved_per_movement_and_none_means_the_default(self):
        self.client.put("/exercise-refs/squat", json={"rest_sec": 240})
        self.client.put("/exercise-refs/curl", json={"rest_sec": 0})   # 0 is "off", not "default"
        self.client.put("/exercise-refs/bench", json={})
        got = {r["exercise_template_id"]: r["rest_sec"] for r in self.client.get("/exercise-refs").json()}
        self.assertEqual({"squat": 240, "curl": 0, "bench": None}, got)

    def test_rejects_a_silly_rest_time(self):
        for bad in (-1, 3601):
            self.assertEqual(422, self.client.put("/exercise-refs/x", json={"rest_sec": bad}).status_code, bad)

    def test_rejects_a_silly_bar_or_chain_weight(self):
        for body in ({"bar_kg": -1}, {"bar_kg": 101}, {"chain_kg": -5}, {"chain_kg": 201}):
            self.assertEqual(422, self.client.put("/exercise-refs/x", json=body).status_code, body)

    def test_rejects_a_silly_lb_step(self):
        for bad in (0, -1, 0.2, 60):
            self.assertEqual(422, self.client.put("/exercise-refs/x", json={"step_lb": bad}).status_code, bad)

    def test_rejects_a_silly_rounding_step(self):
        for bad in (0, -1, 0.1, 25):
            self.assertEqual(422, self.client.put("/exercise-refs/x", json={"step_kg": bad}).status_code, bad)

    def test_a_database_from_the_earlier_version_gains_the_new_columns(self):
        path = os.environ["DB_PATH"]
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE exercise_refs")
        conn.execute(
            "CREATE TABLE exercise_refs (exercise_template_id TEXT PRIMARY KEY, e1rm_lb REAL, tm_lb REAL,"
            " basis TEXT NOT NULL DEFAULT 'e1rm', auto INTEGER NOT NULL DEFAULT 0, updated_at DATETIME)"
        )
        conn.execute("INSERT INTO exercise_refs (exercise_template_id, basis) VALUES ('old', 'tm')")
        conn.commit()
        conn.close()
        database.init_db()
        self.assertEqual(
            [{"exercise_template_id": "old", "basis": "tm", "ls": True, "tm_pct": 0.95, "step_kg": 2.5, "step_lb": 5.0, "bar_kg": 20.0, "chain_kg": 0.0, "rest_sec": None, "weight_unit": None}],
            self.client.get("/exercise-refs").json(),
        )


class TestRpeTableEndpoint(RefsCase):

    def test_serves_the_users_table(self):
        rows = self.client.get("/rpe-table").json()["rows"]
        with open(USER_CSV, newline="", encoding="utf-8") as f:
            expected = sum(1 for _ in csv.DictReader(f))
        self.assertEqual(expected, len(rows))
        by_pair = {(r[0], int(r[1])): r[2] for r in rows}
        self.assertAlmostEqual(0.826, by_pair[(8.0, 5)], places=4)
        self.assertEqual(1.0, by_pair[(10.0, 1)])


def _entry(workout, start, set_type, kg, reps, rpe, title):
    return {
        "workout_id": workout, "workout_title": title, "workout_start_time": start,
        "set_type": set_type, "weight_kg": kg, "reps": reps, "rpe": rpe,
    }


class TestExerciseStateEndpoint(RefsCase):

    def setUp(self):
        super().setUp()
        patcher = mock.patch("main.hevy_client.HevyClient")
        self.hevy_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.hevy = self.hevy_cls.return_value
        self.hevy.exercise_history.return_value = [
            _entry("w1", "2026-09-30T17:00:00+00:00", "warmup", 49.9, 5, None, "BS-Bridge1.3.1"),
            _entry("w1", "2026-09-30T17:00:00+00:00", "normal", 120.2, 5, 6, "BS-Bridge1.3.1"),
            _entry("w1", "2026-09-30T17:00:00+00:00", "normal", 132.45, 5, 8, "BS-Bridge1.3.1"),
        ]

    def test_returns_the_e1rm_and_the_set_it_came_from(self):
        r = self.client.get("/hevy/exercise-state/tpl-squat")
        self.assertEqual(200, r.status_code, r.text)
        body = r.json()
        self.assertTrue(body["found"])
        self.assertEqual(("BS-Bridge1.3.1", 292.0, 5, 8.0), (body["workout_title"], body["set_weight_lb"], body["set_reps"], body["set_rpe"]))
        self.assertEqual(round(292 / 0.826, 1), body["e1rm_lb"])
        self.hevy.exercise_history.assert_called_once_with("tpl-squat")

    def test_no_history_is_found_false_not_an_error(self):
        self.hevy.exercise_history.return_value = []
        r = self.client.get("/hevy/exercise-state/tpl-new")
        self.assertEqual(200, r.status_code)
        self.assertEqual((False, None), (r.json()["found"], r.json()["e1rm_lb"]))

    def test_no_api_key_is_a_400(self):
        self.hevy_cls.side_effect = ValueError("No Hevy API key configured.")
        self.assertEqual(400, self.client.get("/hevy/exercise-state/x").status_code)

    def test_hevy_failure_is_a_502(self):
        self.hevy.exercise_history.side_effect = httpx.ConnectError("down")
        self.assertEqual(502, self.client.get("/hevy/exercise-state/x").status_code)


if __name__ == "__main__":
    unittest.main()
