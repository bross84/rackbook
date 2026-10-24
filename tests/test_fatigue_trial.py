import os
import gc
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
import main
import fatigue_trial as trial
import fatigue_relationships
from database import get_db
from progress import LIFT_TITLES

NOW = datetime(2026, 10, 22, 15, tzinfo=timezone.utc)


class TrialCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"DB_PATH": str(Path(self.tmp.name)/"rack.db"), "HEVY_FATIGUE_DB_PATH": ""})
        env.start(); self.addCleanup(env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def payload(self, **changes):
        return trial.SnapshotInput(session_key="session", exercise_template_id="squat", workout_start=NOW-timedelta(minutes=5),
            local_date="2026-10-22", mode="strength", planned_reps=1, planned_rpe=8, planned_weight_kg=100, **changes)

    def test_disabled_and_hidden_and_idempotent(self):
        with self.assertRaises(ValueError):
            trial.record(self.payload(), now=NOW)
        trial.configure(True)
        result = trial.record(self.payload(soreness=0), now=NOW)
        self.assertNotIn("prediction", result)
        self.assertNotIn("evidence", result)
        self.assertNotIn("reasons", result)
        repeat = trial.record(self.payload(soreness=3, pain=True), now=NOW)
        self.assertEqual(result, repeat)
        response = self.client.get("/fatigue-trial/snapshots/"+result["id"]).json()
        self.assertNotIn("prediction", response)
        self.assertNotIn("snapshot", response)
        self.assertNotIn("across_sessions", response)
        self.assertTrue(response["prospective"])

    def test_server_started_and_late_entries(self):
        trial.configure(True)
        trial.mark_started(trial.MovementStart(session_key="session", exercise_template_id="squat"))
        self.assertFalse(trial.record(self.payload(), now=NOW)["prospective"])

    def test_bridge_preserves_zero_missing_scale_and_staleness(self):
        path = Path(self.tmp.name)/"hevy.db"
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("CREATE TABLE daily_readiness(date TEXT, tiredness INTEGER, perceived_recovery INTEGER, sore_quad_dom INTEGER, sore_posterior INTEGER, sore_upper_push INTEGER, sore_upper_pull INTEGER, joint_upper INTEGER, joint_lower INTEGER)")
            conn.execute("INSERT INTO daily_readiness(date,tiredness,perceived_recovery,sore_quad_dom) VALUES ('2026-10-22',0,NULL,4)")
        with patch.dict(os.environ, {"HEVY_FATIGUE_DB_PATH": str(path)}):
            checkin = trial.daily("2026-10-22", now=NOW)
            self.assertEqual(checkin["ratings"]["tiredness"], 0)
            self.assertIsNone(checkin["ratings"]["perceived_recovery"])
            self.assertEqual(checkin["ratings"]["sore_quad_dom"], 4)
            self.assertEqual(checkin["timing"], "date_only")
            self.assertEqual(trial.daily("2026-10-23")["status"], "stale")
            self.assertEqual(trial.daily("2026-10-21")["status"], "unavailable")
        self.assertEqual(trial.daily("2026-10-22")["status"], "unavailable")

    def test_unknown_is_not_near_usual_and_pain_is_separate(self):
        daily = dict(status="available", ratings=dict(tiredness=0, perceived_recovery=0))
        context = dict(block_reasons=[])
        self.assertEqual(trial.assess(None, daily, [1]*3, context)[0], "uncertain")
        self.assertEqual(trial.assess(0, daily, [1]*3, context)[0], "near_usual")
        self.assertEqual(trial.assess(2, daily, [1]*3, context)[0], "below_usual")
        self.assertEqual(trial.assess(2, daily, [1]*3, dict(block_reasons=["Changed spacing"]))[0], "uncertain")
        trial.configure(True)
        self.assertTrue(trial.record(self.payload(pain=True), now=NOW)["pain"])

    def row(self, **changes):
        return dict(weight_kg=100, reps=5, rpe=8, set_type="normal", is_ts=False, set_number=1, **changes)

    def test_hypertrophy_matching_and_missing_first_set(self):
        base = [self.row() for _ in range(3)]
        worse = {**self.row(), "reps":4}
        self.assertEqual(trial.performance(worse, base, "hypertrophy"), "below_usual")
        self.assertEqual(trial.performance({**self.row(), "rpe":9}, base, "hypertrophy"), "below_usual")
        self.assertEqual(trial.performance({**self.row(), "weight_kg":80}, base, "hypertrophy"), "unclassified")
        self.assertEqual(trial.performance({**self.row(), "rpe":None}, base, "hypertrophy"), "unclassified")
        self.assertIsNone(trial.representative([{**self.row(), "rpe":None}, self.row()], "hypertrophy")["rpe"])

    def test_earlier_only_gap_reset_duplicates_and_ts_identity(self):
        target = self.row()
        rows = [{**self.row(), "workout_start": (NOW-timedelta(days=i*3)).isoformat(), "hevy_workout_id":str(i)} for i in range(4)]
        base = trial.reference(rows, target, "hypertrophy", NOW)
        self.assertEqual(len(base),3)
        self.assertTrue(all(trial.timestamp(r["workout_start"]) < NOW for r in base))
        self.assertEqual(trial.reference(rows, target, "hypertrophy", NOW+timedelta(days=22)), [])
        self.assertEqual(trial.reference(rows+rows, target, "hypertrophy", NOW), [])
        self.assertIsNone(trial.representative([target], "strength"))
        self.assertIsNone(trial.representative([{**target,"is_ts":True}]*2,"strength"))

    def test_completion_requires_matching_saved_workout_and_freezes(self):
        trial.configure(True)
        record = trial.record(self.payload(), now=NOW)
        with self.assertRaises(ValueError):
            trial.complete(record["id"], "not-saved")
        with closing(get_db()) as conn, conn:
            conn.execute("INSERT INTO logged_sets(hevy_workout_id,workout_start,exercise_template_id,set_number,set_type,weight_kg,reps,rpe,is_ts) VALUES (?,?,?,1,'normal',100,1,8,1)",
                         ("saved", (NOW-timedelta(minutes=5)).isoformat(), "squat"))
        done = trial.complete(record["id"], "saved")
        self.assertEqual(done["observed"], "unclassified")
        self.assertEqual(done["prediction"], "uncertain")
        trial.note(record["id"], trial.TrialNote(kind="correction", text="Changed soreness"))
        corrected=trial.read(record["id"])
        self.assertEqual(done["evidence"],corrected["evidence"])
        self.assertEqual(corrected["notes"][0]["text"],"Changed soreness")
        self.assertEqual(corrected, trial.complete(record["id"], "other"))

    def test_complete_positive_cohort_uses_frozen_chart_and_excludes_future(self):
        trial.configure(True)
        with closing(get_db()) as conn, conn:
            for i in range(1,5):
                conn.execute("INSERT INTO logged_sets(hevy_workout_id,workout_start,exercise_template_id,exercise_title,set_number,set_type,weight_kg,reps,rpe,is_ts) VALUES (?,?,?,?,1,'normal',100,1,8,1)",
                    (str(i),(NOW-timedelta(days=3*i)).isoformat(),"squat",LIFT_TITLES["squat"]))
            conn.execute("INSERT INTO logged_sets(hevy_workout_id,workout_start,exercise_template_id,set_number,set_type,weight_kg,reps,rpe,is_ts) VALUES ('future',?,'squat',1,'normal',500,1,8,1)",((NOW+timedelta(days=3)).isoformat(),))
        fatigue_relationships.save("squat",["squat"])
        with patch.object(trial,"daily",return_value=dict(status="available",ratings=dict(tiredness=0,perceived_recovery=0))):
            record=trial.record(self.payload(soreness=0),now=NOW)
        with closing(get_db()) as conn, conn:
            conn.execute("INSERT INTO logged_sets(hevy_workout_id,workout_start,exercise_template_id,set_number,set_type,weight_kg,reps,rpe,is_ts) VALUES ('saved',?,'squat',1,'normal',96,1,8,1)",((NOW-timedelta(minutes=5)).isoformat(),))
            conn.execute("DELETE FROM rpe_chart")
        result=trial.complete(record["id"],"saved")
        self.assertEqual(result["prediction"],"near_usual",result["reasons"])
        self.assertEqual(result["observed"],"below_usual")
        self.assertEqual([r["weight_kg"] for r in result["evidence"]["baseline"]],[100]*3)
        evaluation=trial.evaluation(now=NOW+timedelta(weeks=7))[0]
        self.assertEqual(evaluation["eligible_predictions"],1)
        self.assertTrue(evaluation["review_due"])
        self.assertIn("inconclusive",evaluation["status"])

    def test_changed_exercise_order_is_incompatible(self):
        base=[{**self.row(),"exercise_order":0}]*3
        self.assertEqual(trial.performance({**self.row(),"exercise_order":1},base,"hypertrophy"),"unclassified")

    def test_optional_failure_does_not_fail_hevy_save(self):
        entry=dict(title="Test",start_time=NOW.isoformat(),end_time=(NOW+timedelta(hours=1)).isoformat(),
            exercises=[dict(exercise_template_id="squat",title="Squat",sets=[dict(type="normal",weight_kg=100,reps=5,rpe=8)])])
        with patch("main.hevy_client.HevyClient") as cls, patch.object(trial,"complete_workout",side_effect=RuntimeError("trial down")):
            cls.return_value.__enter__.return_value.create_workout.return_value={"id":"saved"}
            # _call_hevy uses the client directly rather than a context manager.
            cls.return_value.create_workout.return_value={"id":"saved"}
            response=self.client.post("/hevy/workouts",json=entry)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn("Do not save the workout again",response.json()["plan_warning"])
            cls.return_value.create_workout.assert_called_once()
        with closing(get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM logged_sets WHERE hevy_workout_id='saved'").fetchone()[0],1)

    def test_isolated_local_preview_rejects_remote_workout_write(self):
        with patch.dict(os.environ,{"RACKBOOK_READ_ONLY_PREVIEW":"1"}), patch("main.hevy_client.HevyClient") as hevy:
            self.assertEqual(self.client.post("/hevy/workouts",json={}).status_code,403)
            hevy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
