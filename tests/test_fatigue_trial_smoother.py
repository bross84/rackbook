"""New shadow observations never replace legacy predictions, completions or cohorts."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import gc
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import database
import fatigue_trial as trial
import fatigue_trial_smoother as shadow
import trial_dashboard

NOW=datetime(2026,10,30,15,tzinfo=timezone.utc)


class ShadowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.rack=Path(self.tmp.name)/'rack.db';self.hevy=Path(self.tmp.name)/'hevy.db'
        env=patch.dict(os.environ,{'DB_PATH':str(self.rack),'HEVY_FATIGUE_DB_PATH':str(self.hevy)})
        env.start();self.addCleanup(env.stop);self.addCleanup(gc.collect)
        database.init_db();trial.configure(True)
        with closing(sqlite3.connect(self.hevy)) as c,c:
            c.executescript('''CREATE TABLE daily_readiness(date TEXT PRIMARY KEY,tiredness INTEGER,perceived_recovery INTEGER,
                sore_quad_dom INTEGER,sore_posterior INTEGER,sore_upper_push INTEGER,sore_upper_pull INTEGER,joint_upper INTEGER,joint_lower INTEGER);
                CREATE TABLE workout_sessions(hevy_workout_id TEXT PRIMARY KEY,workout_date TEXT);
                CREATE TABLE workout_logs(workout_id TEXT,weight_lbs REAL,reps INTEGER);''')
            for i in range(5):
                day=(NOW.date()-timedelta(days=i)).isoformat()
                c.execute('INSERT INTO daily_readiness VALUES (?,?,?,?,?,?,?,?,?)',(day,2,2,2,2,2,2,0,0))
            for i in (50,40,30,5,2):
                c.execute('INSERT INTO workout_sessions VALUES (?,?)',(str(i),(NOW.date()-timedelta(days=i)).isoformat()))
                c.execute('INSERT INTO workout_logs VALUES (?,100,10)',(str(i),))

    def payload(self,key='new'):
        return trial.SnapshotInput(session_key=key,exercise_template_id='squat',workout_start=NOW-timedelta(minutes=5),
            local_date=NOW.date().isoformat(),soreness=0,mode='strength',planned_reps=1,planned_rpe=8,planned_weight_kg=100)

    def save(self,record,key='saved'):
        with closing(database.get_db()) as c,c:
            c.execute('''INSERT INTO logged_sets(hevy_workout_id,workout_start,exercise_template_id,set_number,set_type,weight_kg,reps,rpe,is_ts)
                VALUES (?,?,?,1,'normal',100,1,8,1)''',(key,(NOW-timedelta(minutes=5)).isoformat(),'squat'))
        return trial.complete(record['id'],key)

    def stored(self,key):
        with closing(database.get_db()) as c:
            return tuple(c.execute('SELECT snapshot,completion,model_version FROM fatigue_trial_snapshots WHERE id=?',(key,)).fetchone())

    def test_capture_uses_actual_pinned_model_read_only_and_excludes_same_day(self):
        before=hashlib.sha256(self.hevy.read_bytes()).hexdigest()
        output=shadow.capture('2026-10-30',NOW)
        self.assertTrue(output['data_sufficient'])
        self.assertEqual(output['combined_score'],12.)
        self.assertEqual(output['smoothed_score'],12.)
        self.assertEqual(output['model_version'],shadow.VERSION)
        self.assertEqual(output['source_model_version'],'recovery-confirmation-v1')
        self.assertEqual(before,hashlib.sha256(self.hevy.read_bytes()).hexdigest())
        self.assertNotIn('api_key',json.dumps(output))
        with closing(sqlite3.connect(self.hevy)) as c,c:
            for day in ('2026-10-30','2026-10-31'):
                c.execute('INSERT INTO workout_sessions VALUES (?,?)',(day,day))
                c.execute('INSERT INTO workout_logs VALUES (?,999999,100)',(day,))
        self.assertEqual(output,shadow.capture('2026-10-30',NOW))

    def test_unsaved_outputs_hidden_and_completed_outputs_are_frozen(self):
        rec=trial.record(self.payload(),now=NOW)
        self.assertNotIn('shadow',rec)
        dashboard=trial_dashboard.dashboard()
        self.assertNotIn('shadow',dashboard['entries'][0])
        self.assertEqual(dashboard.get('shadow_cohorts',[]),[])
        with closing(database.get_db()) as c:
            frozen=c.execute('SELECT snapshot FROM fatigue_trial_shadow WHERE trial_id=?',(rec['id'],)).fetchone()[0]
        with closing(sqlite3.connect(self.hevy)) as c,c:
            c.execute('UPDATE daily_readiness SET tiredness=4,perceived_recovery=4')
        with patch.object(shadow,'capture',side_effect=AssertionError('Existing record must not recalculate')):
            self.assertEqual(rec,trial.record(self.payload(),now=NOW))
        done=self.save(rec)
        self.assertEqual(done['shadow']['input_sha256'],json.loads(frozen)['input_sha256'])
        self.assertEqual(done['shadow']['combined_score'],json.loads(frozen)['combined_score'])
        self.assertNotIn('inputs',done['shadow'])
        self.assertEqual(trial_dashboard.dashboard()['entries'][0]['shadow'],done['shadow'])

    def test_existing_predictions_results_and_evaluation_are_byte_preserved(self):
        old=trial.record(self.payload('old'),now=NOW)
        self.save(old)
        # Simulate an observation collected before the new table/arm existed.
        with closing(database.get_db()) as c,c:
            c.execute('DELETE FROM fatigue_trial_shadow WHERE trial_id=?',(old['id'],))
        original=self.stored(old['id']);evaluation=trial.evaluation(now=NOW)
        database.init_db()
        self.assertEqual(original,self.stored(old['id']))
        with patch.object(shadow,'capture',side_effect=AssertionError('No historical backfill')):
            trial.record(self.payload('old'),now=NOW)
        self.assertIsNone(shadow.read(old['id']))
        # A separate append-only shadow row cannot alter legacy cohort metrics.
        shadow.store(old['id'],shadow.capture('2026-10-30',NOW))
        self.assertEqual(original,self.stored(old['id']))
        self.assertEqual(evaluation,trial.evaluation(now=NOW))
        self.assertEqual(len(shadow.summaries()),1)
        self.assertEqual(shadow.summaries()[0]['classified_outcomes'],0)

    def test_unavailable_and_reacquiring_bridge_never_imply_freshness(self):
        with patch.dict(os.environ,{'HEVY_FATIGUE_DB_PATH':''}):
            output=shadow.capture('2026-10-30',NOW)
        self.assertFalse(output['data_sufficient'])
        self.assertEqual(output['recommendation_label'],'Continue Training as Normal')
        with closing(sqlite3.connect(self.hevy)) as c,c:
            c.execute("DELETE FROM daily_readiness WHERE date < '2026-10-29'")
        output=shadow.capture('2026-10-30',NOW)
        self.assertEqual(output['consecutive_checkins'],2)
        self.assertFalse(output['data_sufficient'])
        self.assertEqual(output['status'],'insufficient_data')

    def test_late_and_unsaved_snapshots_do_not_enter_shadow_counts(self):
        data=self.payload();data.working_set_started=True
        rec=trial.record(data,now=NOW)
        self.assertEqual(shadow.summaries(),[])
        self.save(rec)
        self.assertEqual(shadow.summaries(),[])

    def test_shadow_storage_error_preserves_legacy_record(self):
        with patch.object(shadow,'store',side_effect=sqlite3.OperationalError('test failure')):
            rec=trial.record(self.payload(),now=NOW)
        self.assertEqual(rec['status'],'recorded')
        self.assertIsNone(shadow.read(rec['id']))

    def test_movement_started_during_capture_is_excluded_from_prospective_evaluation(self):
        original=shadow.capture
        def capture_and_start(day,now):
            trial.mark_started(trial.MovementStart(session_key='new',exercise_template_id='squat'))
            return original(day,now)
        with patch.object(shadow,'capture',side_effect=capture_and_start):
            rec=trial.record(self.payload(),now=NOW)
        self.assertFalse(rec['prospective'])
        self.save(rec)
        self.assertEqual(shadow.summaries(),[])

    def test_frozen_arm_remains_readable_after_a_future_arm_version_change(self):
        rec=trial.record(self.payload(),now=NOW)
        before=shadow.read(rec['id'])
        with patch.object(shadow,'VERSION','future-shadow-v2'):
            self.assertEqual(before,shadow.read(rec['id']))

    def test_capture_failure_logs_stage_and_sqlite_cause_without_changing_records(self):
        rec=trial.record(self.payload(),now=NOW)
        self.save(rec)
        before=self.stored(rec['id'])
        frozen=shadow.read(rec['id'])
        with closing(sqlite3.connect(self.hevy)) as c,c:
            c.execute('DROP TABLE workout_sessions')
        with self.assertLogs(shadow.logger,level='WARNING') as logs:
            result=shadow.capture('2026-10-30',NOW)
        message=' '.join(logs.output)
        self.assertIn('smoother_capture_unavailable',message)
        self.assertIn('phase=read_workouts',message)
        self.assertIn('reason=missing_table:workout_sessions',message)
        self.assertIn('sqlite_error=SQLITE_ERROR',message)
        self.assertEqual(result['status'],'unavailable')
        self.assertEqual(before,self.stored(rec['id']))
        self.assertEqual(frozen,shadow.read(rec['id']))
        self.assertNotIn('phase',result)
        self.assertNotIn('reason',result)

    def test_logging_does_not_expose_input_values_paths_or_credentials(self):
        sensitive='private-health-input API_KEY=not-a-real-key /private/database.db'
        with patch.object(shadow.model,'build_history',side_effect=ValueError(sensitive)):
            with self.assertLogs(shadow.logger,level='WARNING') as logs:
                result=shadow.capture('2026-10-30',NOW)
        message=' '.join(logs.output)
        self.assertIn('phase=calculate',message)
        self.assertIn('reason=invalid_value',message)
        self.assertIn('exception=ValueError',message)
        self.assertNotIn(sensitive,message)
        self.assertNotIn(str(self.hevy),message)
        self.assertNotIn('ratings',message)
        self.assertEqual(result['status'],'unavailable')

    def test_missing_configuration_and_locked_database_are_distinct(self):
        with patch.dict(os.environ,{'HEVY_FATIGUE_DB_PATH':''}):
            with self.assertLogs(shadow.logger,level='WARNING') as logs:
                shadow.capture('2026-10-30',NOW)
        self.assertIn('phase=configuration',logs.output[0])
        self.assertIn('reason=bridge_not_configured',logs.output[0])
        with patch.object(shadow.sqlite3,'connect',side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertLogs(shadow.logger,level='WARNING') as logs:
                shadow.capture('2026-10-30',NOW)
        self.assertIn('phase=open_database',logs.output[0])
        self.assertIn('reason=database_busy',logs.output[0])

    def test_available_and_insufficient_data_do_not_emit_failure_logs(self):
        with patch.object(shadow.logger,'warning') as warning:
            self.assertEqual(shadow.capture('2026-10-30',NOW)['status'],'available')
            with closing(sqlite3.connect(self.hevy)) as c,c:
                c.execute("DELETE FROM daily_readiness WHERE date < '2026-10-29'")
            self.assertEqual(shadow.capture('2026-10-30',NOW)['status'],'insufficient_data')
        warning.assert_not_called()

    def test_unexpected_capture_and_storage_failures_log_without_breaking_legacy(self):
        with patch.object(shadow,'capture',side_effect=RuntimeError('sensitive input')):
            with self.assertLogs(shadow.logger,level='WARNING') as logs:
                rec=trial.record(self.payload(),now=NOW)
        self.assertEqual(rec['status'],'recorded')
        self.assertIn('phase=capture_call',logs.output[0])
        self.assertIn('exception=RuntimeError',logs.output[0])
        self.assertNotIn('sensitive input',' '.join(logs.output))
        self.assertEqual(shadow.read(rec['id'])['status'],'unavailable')
        with patch.object(shadow,'store',side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertLogs(shadow.logger,level='WARNING') as logs:
                second=trial.record(self.payload('other'),now=NOW)
        self.assertEqual(second['status'],'recorded')
        self.assertIn('smoother_shadow_store_failed',logs.output[0])
        self.assertIn('phase=store',logs.output[0])
        self.assertIsNone(shadow.read(second['id']))

    def test_existing_record_does_not_retry_or_log_a_new_capture(self):
        rec=trial.record(self.payload(),now=NOW)
        frozen=shadow.read(rec['id'])
        with patch.object(shadow,'capture',side_effect=AssertionError('No retry')):
            with patch.object(shadow.logger,'warning') as warning:
                self.assertEqual(rec,trial.record(self.payload(),now=NOW))
        warning.assert_not_called()
        self.assertEqual(frozen,shadow.read(rec['id']))
