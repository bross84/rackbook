"""Tests for GET /hevy/workouts and the /recent page route. The Hevy client is mocked: no network."""
import os
import shutil
import sys
import tempfile
import unittest
import warnings
from unittest import mock

import httpx
from cryptography.fernet import InvalidToken

warnings.filterwarnings("ignore", category=ResourceWarning)

_IMPORT_DIR = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_IMPORT_DIR, "import.db"))

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

RAW_PAGE = {
    "page": 1,
    "page_count": 3,
    "workouts": [
        {
            "id": "w1",
            "title": "Day 1",
            "start_time": "2026-09-30T17:00:00+00:00",
            "end_time": "2026-09-30T17:58:00+00:00",
            "exercises": [
                {
                    "index": 0,
                    "title": "Squat (Barbell)",
                    "exercise_template_id": "tpl-squat",
                    "sets": [{"index": 0, "type": "normal", "weight_kg": 120, "reps": 5, "rpe": 6}],
                }
            ],
        }
    ],
}


def _status_error(code):
    request = httpx.Request("GET", "https://api.hevyapp.com/v1/workouts")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, request=request))


class WorkoutsRouteCase(unittest.TestCase):

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
        self.hevy.list_workouts.return_value = RAW_PAGE


class TestListHevyWorkouts(WorkoutsRouteCase):

    def test_returns_summarised_page(self):
        r = self.client.get("/hevy/workouts")
        self.assertEqual(200, r.status_code, r.text)
        body = r.json()
        self.assertEqual((1, 3), (body["page"], body["page_count"]))
        w = body["workouts"][0]
        self.assertEqual(("w1", "Day 1", 58, 1), (w["id"], w["title"], w["duration_minutes"], w["working_sets"]))
        s = w["exercises"][0]["sets"][0]
        self.assertEqual((120.0, 264.6, 5, 6.0), (s["weight_kg"], s["weight_lb"], s["reps"], s["rpe"]))

    def _record(self, reps, rpe, workout_id="w1", set_type="normal"):
        import set_log
        set_log.record([{
            "hevy_workout_id": workout_id, "workout_title": "Day 1", "workout_start": "2026-09-30T17:00:00+00:00",
            "workout_end": None, "exercise_template_id": "tpl-squat", "exercise_title": "Squat (Barbell)",
            "set_number": 1, "set_type": set_type, "weight_kg": 120, "reps": reps, "rpe": rpe, "is_ts": 0}])

    def test_rpe_hevy_dropped_comes_back_from_the_local_record(self):
        page = {**RAW_PAGE, "workouts": [{**RAW_PAGE["workouts"][0], "exercises": [
            {**RAW_PAGE["workouts"][0]["exercises"][0], "sets": [{"index": 0, "type": "normal", "weight_kg": 120, "reps": 5}]}]}]}
        self.hevy.list_workouts.return_value = page
        self._record(5, 5.5)
        s = self.client.get("/hevy/workouts").json()["workouts"][0]["exercises"][0]["sets"][0]
        self.assertEqual(5.5, s["rpe"])

    def test_local_rpe_is_not_used_when_the_sets_do_not_line_up(self):
        page = {**RAW_PAGE, "workouts": [{**RAW_PAGE["workouts"][0], "exercises": [
            {**RAW_PAGE["workouts"][0]["exercises"][0], "sets": [{"index": 0, "type": "normal", "weight_kg": 120, "reps": 5}]}]}]}
        self.hevy.list_workouts.return_value = page
        self._record(3, 5.5)
        s = self.client.get("/hevy/workouts").json()["workouts"][0]["exercises"][0]["sets"][0]
        self.assertIsNone(s["rpe"])

    def test_passes_paging_through_to_hevy(self):
        self.client.get("/hevy/workouts?page=2&page_size=5")
        self.hevy.list_workouts.assert_called_once_with(page=2, page_size=5)

    def test_page_size_over_hevy_maximum_is_rejected(self):
        self.assertEqual(422, self.client.get("/hevy/workouts?page_size=11").status_code)

    def test_page_zero_is_rejected(self):
        self.assertEqual(422, self.client.get("/hevy/workouts?page=0").status_code)

    def test_empty_account(self):
        self.hevy.list_workouts.return_value = {"page": 1, "page_count": 1, "workouts": []}
        body = self.client.get("/hevy/workouts").json()
        self.assertEqual([], body["workouts"])

    def test_no_api_key_is_a_400_with_the_reason(self):
        self.hevy_cls.side_effect = ValueError("No Hevy API key configured.")
        r = self.client.get("/hevy/workouts")
        self.assertEqual(400, r.status_code)
        self.assertIn("No Hevy API key", r.json()["detail"])

    def test_undecryptable_stored_key_is_a_400(self):
        self.hevy_cls.side_effect = InvalidToken()
        r = self.client.get("/hevy/workouts")
        self.assertEqual(400, r.status_code)
        self.assertIn("Save it again", r.json()["detail"])

    def test_hevy_rejecting_the_key_is_a_502_that_mentions_the_key(self):
        self.hevy.list_workouts.side_effect = _status_error(401)
        r = self.client.get("/hevy/workouts")
        self.assertEqual(502, r.status_code)
        self.assertIn("rejected the API key", r.json()["detail"])

    def test_other_hevy_errors_are_a_502_with_the_status(self):
        self.hevy.list_workouts.side_effect = _status_error(500)
        r = self.client.get("/hevy/workouts")
        self.assertEqual(502, r.status_code)
        self.assertIn("500", r.json()["detail"])

    def test_network_failure_is_a_502(self):
        self.hevy.list_workouts.side_effect = httpx.ConnectError("down")
        r = self.client.get("/hevy/workouts")
        self.assertEqual(502, r.status_code)
        self.assertIn("reach Hevy", r.json()["detail"])


class TestRecentPage(WorkoutsRouteCase):

    def test_recent_page_is_served(self):
        r = self.client.get("/recent")
        self.assertEqual(200, r.status_code)
        self.assertIn("Recent workouts", r.text)


ENTRY = {
    "title": "BS-Bridge 1.3.3",
    "start_time": "2026-10-09T17:00:00Z",
    "end_time": "2026-10-09T18:00:00Z",
    "exercises": [
        {
            "exercise_template_id": "tpl-squat",
            "title": "Squat, Low Bar w/ Belt",
            "sets": [
                {"type": "warmup", "weight_kg": 50, "reps": 5},
                {"type": "normal", "weight_kg": 120, "reps": 5, "rpe": 6},
                {"type": "normal", "weight_kg": 127.5, "reps": 8, "rpe": 5},
            ],
        }
    ],
}


class TestCreateHevyWorkout(WorkoutsRouteCase):

    def setUp(self):
        super().setUp()
        self.hevy.create_workout.return_value = {"id": "new-1"}

    def _post(self, **overrides):
        return self.client.post("/hevy/workouts", json={**ENTRY, **overrides})

    def test_saves_and_returns_the_new_id(self):
        r = self._post()
        self.assertEqual(200, r.status_code, r.text)
        self.assertEqual("new-1", r.json()["id"])

    def test_sends_hevys_body_with_kg_and_wrapped_in_workout(self):
        self._post()
        (body,), _ = self.hevy.create_workout.call_args
        w = body["workout"]
        self.assertEqual("BS-Bridge 1.3.3", w["title"])
        sets = w["exercises"][0]["sets"]
        self.assertEqual([50.0, 120.0, 127.5], [s["weight_kg"] for s in sets])
        self.assertEqual("tpl-squat", w["exercises"][0]["exercise_template_id"])

    def test_unstorable_rpe_is_left_blank(self):
        r = self._post()
        self.assertEqual({"id": "new-1"}, r.json())
        (body,), _ = self.hevy.create_workout.call_args
        self.assertIsNone(body["workout"]["exercises"][0]["sets"][2]["rpe"])

    def test_rounds_upload_in_pounds_and_preserves_exact_local_weights(self):
        factor=2.20462262185
        weights=[132.34/factor,132.51/factor]
        response=self._post(weight_unit='lb',exercises=[{'exercise_template_id':'t','sets':[{'weight_kg':kg,'reps':5} for kg in weights]}])
        self.assertEqual(200,response.status_code,response.text)
        body=self.hevy.create_workout.call_args.args[0]
        sent=body['workout']['exercises'][0]['sets']
        self.assertAlmostEqual(132,sent[0]['weight_kg']*factor)
        self.assertAlmostEqual(133,sent[1]['weight_kg']*factor)
        with main.get_db() as conn:
            stored=conn.execute('SELECT weight_kg FROM logged_sets ORDER BY set_number').fetchall()
        self.assertEqual(weights,[row['weight_kg'] for row in stored])

    def test_unstorable_rpe_adds_no_note(self):
        self._post()
        (body,), _ = self.hevy.create_workout.call_args
        self.assertNotIn("notes", body["workout"]["exercises"][0])

    def test_rpe_outside_0_to_10_is_422(self):
        entry = {**ENTRY, "exercises": [{"exercise_template_id": "t", "sets": [{"reps": 5, "rpe": 11}]}]}
        self.assertEqual(422, self.client.post("/hevy/workouts", json=entry).status_code)

    def test_invalid_workout_is_422_and_nothing_is_sent(self):
        for bad in ({"exercises": []}, {"title": " "}, {"end_time": "2026-10-09T16:00:00Z"}):
            r = self._post(**bad)
            self.assertEqual(422, r.status_code, bad)
        self.hevy.create_workout.assert_not_called()

    def test_unknown_set_type_is_rejected(self):
        entry = {**ENTRY, "exercises": [{"exercise_template_id": "t", "sets": [{"type": "amrap", "reps": 5}]}]}
        self.assertEqual(422, self.client.post("/hevy/workouts", json=entry).status_code)

    def test_no_api_key_is_a_400(self):
        self.hevy_cls.side_effect = ValueError("No Hevy API key configured.")
        self.assertEqual(400, self._post().status_code)

    def test_hevy_validation_error_message_is_passed_along(self):
        request = httpx.Request("POST", "https://api.hevyapp.com/v1/workouts")
        response = httpx.Response(400, request=request, json={"error": "Invalid exercise_template_id"})
        self.hevy.create_workout.side_effect = httpx.HTTPStatusError("bad", request=request, response=response)
        r = self._post()
        self.assertEqual(502, r.status_code)
        self.assertIn("Invalid exercise_template_id", r.json()["detail"])

    def test_hevy_unreachable_is_a_502(self):
        self.hevy.create_workout.side_effect = httpx.ConnectError("down")
        self.assertEqual(502, self._post().status_code)


class TestLogPage(WorkoutsRouteCase):

    def test_log_page_is_served(self):
        r = self.client.get("/log")
        self.assertEqual(200, r.status_code)
        self.assertIn("Log workout", r.text)


if __name__ == "__main__":
    unittest.main()
