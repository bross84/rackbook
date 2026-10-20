"""BS-Bridge chart imports use a disposable DB and mocked Hevy reads only."""
from contextlib import closing
import copy
import gc
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import main
from database import get_db
import rpe_history
import rpe_observed
import set_log


def exercise(title, template="sq", sets=None):
    return {"title": title, "exercise_template_id": template, "sets": sets if sets is not None else [
        {"type": "normal", "weight_kg": 100, "reps": 5, "rpe": 7},
        {"type": "normal", "weight_kg": 110, "reps": 1, "rpe": 8},
    ]}


def workout(wid="w1", title="BS-Bridge1.1.1", exercises=None):
    return {"id": wid, "title": title, "start_time": "2025-01-01T10:00:00Z",
            "exercises": exercises if exercises is not None else [exercise(rpe_history.GROUPS["squat"][0])]}


def client_for(workouts):
    client = Mock()
    client.list_workouts.return_value = {"page": 1, "page_count": 1, "workouts": workouts}
    return client


class RpeHistoryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"DB_PATH": os.path.join(self.temp.name, "test.db")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def count(self, table):
        # Only fixed table names from the test, never request input.
        queries = {"imports": "SELECT COUNT(*) FROM rpe_history_imports",
                   "local": "SELECT COUNT(*) FROM logged_sets",
                   "ts": "SELECT COUNT(*) FROM training_max_history",
                   "soreness": "SELECT COUNT(*) FROM session_soreness"}
        with closing(get_db()) as conn:
            return conn.execute(queries[table]).fetchone()[0]

    def local(self, wid, title, template, sets, start="2025-01-01T10:00:00.000Z"):
        set_log.record(set_log.rows_from_entry({"title": "BS-Bridge1.1.1", "start_time": start,
            "exercises": [{"title": title, "exercise_template_id": template, "sets": sets}]}, wid))

    def test_only_bridge_titles_and_four_approved_movements(self):
        approved = [title for group in rpe_history.GROUPS.values() for title in group]
        all_ex = [exercise(title, str(i)) for i, title in enumerate(approved + [
            "Deadlift, Romanian w/Belt", "Straight Leg Deadlift", "Overhead Press (Barbell)", "Pendlay Row (Barbell)"])]
        workouts = [workout(str(i), title, all_ex) for i, title in enumerate([
            "BS-Bridge1.1.1", "BS-BRIDGE 2.4.3", "BS-Bridge 1.2.1",
            "Other BS-Bridge1.1.1", "BS-Bridged", "5/3/1", "BS-Bridgeworkout"])]
        prepared = rpe_history.fetch_bridge(client_for(workouts))
        self.assertEqual(12, len(prepared["sessions"]))
        self.assertEqual(set(approved), {r["exercise_title"] for r in prepared["sessions"]})
        result = rpe_history.store_import(prepared)
        self.assertEqual((12, 24), (result["sessions_imported"], result["sets_imported"]))
        self.assertEqual(0, self.count("local"))
        self.assertEqual(0, self.count("ts"))
        self.assertEqual(0, self.count("soreness"))

    def test_pagination_does_not_stop_before_older_bridge_workouts(self):
        fake = Mock()
        fake.list_workouts.side_effect = [
            {"page_count": 3, "workouts": [workout("other", "Other program")]},
            {"page_count": 3, "workouts": [workout()]},
            {"page_count": 3, "workouts": [workout(), workout("older")]},
        ]
        prepared = rpe_history.fetch_bridge(fake)
        self.assertEqual(2, len(prepared["sessions"]))
        self.assertEqual(3, fake.list_workouts.call_count)
        self.assertEqual(3, prepared["workouts_scanned"])

    def test_historical_renames_match_the_same_approved_id_not_similar_names(self):
        title = rpe_history.GROUPS["squat"][1]
        fake = client_for([
            workout("older", exercises=[exercise("Squat, High Bar, Pauses", "paused"),
                                        exercise("Squat, High Bar, Pauses", "different")]),
            workout("newer", exercises=[exercise(title, "paused")]),
        ])
        prepared = rpe_history.fetch_bridge(fake)
        self.assertEqual(2, len(prepared["sessions"]))
        self.assertTrue(all(r["exercise_template_id"] == "paused" for r in prepared["sessions"]))
        self.assertTrue(all(r["exercise_title"] == title for r in prepared["sessions"]))

    def test_empty_account_is_a_successful_no_op(self):
        fake = Mock()
        fake.list_workouts.return_value = {"page_count": 0, "workouts": []}
        self.assertEqual(0, rpe_history.store_import(rpe_history.fetch_bridge(fake))["sets_imported"])

    def test_unrated_warmups_drops_and_invalid_sets_do_not_become_observations(self):
        valid = exercise("x")["sets"][0]
        sets = [valid, {**valid, "type": "failure"}, *[
            {**valid, **change} for change in [{"rpe": None}, {"type": "warmup"}, {"type": "dropset"},
                {"weight_kg": 0}, {"weight_kg": float("nan")}, {"reps": 0}, {"reps": 1.5},
                {"rpe": 11}, {"rpe": True}, {"weight_kg": "100"}]]]
        raw = workout(exercises=[exercise(rpe_history.GROUPS["bench"][0], "bench", sets)])
        prepared = rpe_history.fetch_bridge(client_for([raw]))
        self.assertEqual(2, len(prepared["sessions"][0]["sets"]))
        rpe_history.store_import(prepared)
        rows = rpe_history.chart_sets()["bench"]
        self.assertEqual(2, len(rows))
        self.assertTrue(all(row["is_ts"] == 0 for row in rows))
        self.assertEqual("2025-01-01T10:00:00Z", rows[0]["workout_start"])

    def test_retry_is_idempotent_and_preserves_exact_local_snapshot(self):
        title = rpe_history.GROUPS["squat"][0]
        self.local("w1", title, "sq", [{"weight_kg": 90, "reps": 5, "rpe": 5, "ts": True}])
        prepared = rpe_history.fetch_bridge(client_for([workout(), workout("older")]))
        first = rpe_history.store_import(prepared)
        again = rpe_history.store_import(prepared)
        self.assertEqual((1, 1), (first["sessions_imported"], first["local_sessions_preserved"]))
        self.assertEqual((0, 1, 1), (again["sessions_imported"], again["sessions_already_imported"], again["local_sessions_preserved"]))
        rows = rpe_history.chart_sets()["squat"]
        local = [r for r in rows if r["hevy_workout_id"] == "w1"]
        self.assertEqual(1, len(local))
        self.assertEqual((5, 90, 1), (local[0]["rpe"], local[0]["weight_kg"], local[0]["is_ts"]))
        self.assertEqual(1, self.count("imports"))
        self.assertEqual(1, self.count("local"))

    def test_local_snapshot_added_later_wins_even_when_unrated(self):
        prepared = rpe_history.fetch_bridge(client_for([workout()]))
        rpe_history.store_import(prepared)
        self.local("w1", rpe_history.GROUPS["squat"][0], "sq", [{"weight_kg": 90, "reps": 5, "rpe": None}])
        rows = rpe_history.chart_sets()["squat"]
        self.assertEqual(1, len(rows))
        self.assertIsNone(rows[0]["rpe"])
        self.assertEqual(0, rpe_history.list_lifts()[0]["sets"])

    def test_network_failure_leaves_no_partial_import(self):
        fake = Mock()
        fake.list_workouts.side_effect = [{"page_count": 2, "workouts": [workout()]}, RuntimeError("network")]
        with self.assertRaises(RuntimeError):
            rpe_history.store_import(rpe_history.fetch_bridge(fake))
        self.assertEqual(0, self.count("imports"))

    def test_api_uses_only_mocked_hevy_reads_and_chart_counts_include_paused_squats(self):
        raw = workout(exercises=[exercise(rpe_history.GROUPS["squat"][0]),
                                  exercise(rpe_history.GROUPS["squat"][1], "paused")])
        fake = client_for([raw])
        with patch("main._call_hevy", side_effect=lambda fn: fn(fake)):
            response = self.client.post("/rpe-history/import-bs-bridge")
        self.assertEqual(200, response.status_code)
        self.assertEqual(4, response.json()["sets_imported"])
        fake.create_workout.assert_not_called()
        self.assertEqual(4, self.client.get("/rpe-observed").json()[0]["sets"])
        data = self.client.get("/rpe-observed/group/squat").json()
        self.assertEqual((4, 1), (data["gate"]["sets"], data["gate"]["workouts"]))
        self.assertEqual(2, len(data["sources"]))
        self.assertEqual(2, len(data["fit"]["sessions"]))
        self.assertEqual(422, self.client.get("/rpe-observed/group/press").status_code)


class MovementReferenceCase(unittest.TestCase):
    def test_two_movements_on_same_day_get_separate_maxes_and_do_not_double_workout_gate(self):
        rows = []
        for day in range(1, 4):
            for template, strength in [("low", 200), ("paused", 100)]:
                for reps, rpe in [(1, 7), (5, 5), (5, 6.5), (5, 7.5), (3, 8)]:
                    rows.append({"hevy_workout_id": str(day), "workout_start": f"2025-01-{day:02}T10:00:00Z",
                        "exercise_template_id": template, "exercise_title": template, "set_type": "normal",
                        "weight_kg": strength * (1 - .03 * (reps + 10 - rpe - 1)),
                        "reps": reps, "rpe": rpe, "is_ts": 0})
        before = copy.deepcopy(rows)
        built = rpe_observed.build_observed(rows, [], lambda r, n: .99)
        fit = rpe_observed.fit_curve(rows, [], lambda r, n: .99)
        self.assertEqual((30, 3, True), (built["gate"]["sets"], built["gate"]["workouts"], built["gate"]["passed"]))
        self.assertAlmostEqual(.03, fit["slope"], places=4)
        self.assertEqual(6, len(fit["sessions"]))
        self.assertAlmostEqual(2, fit["sessions"][0]["e1rm_lb"] / fit["sessions"][1]["e1rm_lb"], places=4)
        for cell in built["cells"]:
            k = cell["reps"] + 10 - cell["rpe"]
            self.assertAlmostEqual(1 - .03 * (k - 1), cell["observed"], delta=.005)
        self.assertEqual(before, rows)

    def test_different_movement_strengths_cannot_fake_an_informative_session(self):
        rows = [{"workout_start": "2025-01-01", "hevy_workout_id": "same", "exercise_template_id": template,
                 "set_type": "normal", "weight_kg": weight, "reps": reps, "rpe": 8, "is_ts": 0}
                for template, weight, reps in [("low", 200, 1), ("paused", 100, 5)]]
        self.assertIsNone(rpe_observed.fit_curve(rows, [], lambda r, n: None))
        self.assertEqual([], rpe_observed.build_observed(rows, [], lambda r, n: None)["cells"])
