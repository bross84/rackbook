import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient
import main
import set_log
import stress_service


class TestStressRoute(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree,self.tmp,True)
        env=mock.patch.dict(os.environ,{'DB_PATH':os.path.join(self.tmp,'test.db')})
        env.start(); self.addCleanup(env.stop)
        self.client=TestClient(main.app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__,None,None,None)
        patcher=mock.patch('main.hevy_client.HevyClient')
        self.hevy=patcher.start().return_value; self.addCleanup(patcher.stop)
        stress_service.invalidate(); self.addCleanup(stress_service.invalidate)
        self.start=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        self.hevy.exercise_history.return_value=[{'workout_id':'h1','workout_start_time':self.start,
            'set_type':'normal','weight_kg':100,'reps':5,'rpe':None}]

    def test_preview_caches_history_but_updates_live_sets_and_local_rpe(self):
        entry={'title':'Test','start_time':self.start,'exercises':[{'exercise_template_id':'bench','sets':[
            {'type':'normal','weight_kg':100,'reps':5,'rpe':4.5}]}]}
        set_log.record(set_log.rows_from_entry(entry,'h1'))
        first=self.client.post('/movement-stress/bench',json={'sets':[]})
        self.assertEqual(200,first.status_code,first.text)
        data=first.json()
        self.assertEqual(1,data['window']['sessions'])
        self.assertEqual(0,data['rolling_7']['estimated_sets'])
        second=self.client.post('/movement-stress/bench',json={'sets':[
            {'type':'normal','weight_kg':100,'reps':5,'rpe':8}]})
        self.assertEqual(200,second.status_code,second.text)
        self.assertGreater(second.json()['rolling_7']['total'],data['rolling_7']['total'])
        self.hevy.exercise_history.assert_called_once_with('bench')
        self.hevy.create_workout.assert_not_called()

    def test_isolates_movements_and_handles_network_errors(self):
        self.client.post('/movement-stress/bench',json={'sets':[]})
        self.client.post('/movement-stress/squat',json={'sets':[]})
        self.assertEqual(2,self.hevy.exercise_history.call_count)
        import httpx
        self.hevy.exercise_history.side_effect=httpx.ConnectError('offline')
        result=self.client.post('/movement-stress/new',json={'sets':[]})
        self.assertEqual(502,result.status_code)
        self.hevy.create_workout.assert_not_called()

    def test_live_preview_exposes_aligned_rows_without_committing_unchecked_sets(self):
        planned = [{'type':'normal','weight_kg':100,'reps':5,'rpe':8},
                   {'type':'warmup','weight_kg':50,'reps':5,'rpe':5},
                   {'type':'normal','weight_kg':90,'reps':8,'rpe':None}]
        initial = self.client.post('/movement-stress/bench', json={'sets':[]}).json()
        response = self.client.post('/movement-stress/bench', json={'sets':[], 'preview_sets':planned})
        self.assertEqual(200, response.status_code, response.text)
        data = response.json()
        self.assertEqual(2, data['preview']['sets'])
        self.assertIsNone(data['preview_set_scores'][1])
        self.assertEqual(0, data['session']['sets'])
        self.assertEqual(initial['rolling_7'], data['rolling_7'])
        self.assertEqual(initial['rolling_28'], data['rolling_28'])
        self.assertAlmostEqual(data['preview']['total'], sum(s['total'] for s in data['preview_set_scores'] if s))
        self.hevy.create_workout.assert_not_called()

    def test_rejects_invalid_input_before_reading_hevy(self):
        for body in ({'sets':[{'weight_kg':100,'reps':5,'rpe':11}]},
                     {'session_start':'2026-10-17T10:00:00'}):
            response=self.client.post('/movement-stress/bench',json=body)
            self.assertEqual(422,response.status_code)
        self.hevy.exercise_history.assert_not_called()

    def test_dashboard_retroactively_scores_history_and_shares_preview_cache(self):
        response=self.client.get('/movement-stress/bench/history?days=0')
        self.assertEqual(200,response.status_code,response.text)
        data=response.json()
        self.assertEqual('bench',data['exercise_template_id'])
        self.assertEqual(1,data['available_sessions'])
        self.assertEqual(1,data['sessions'][0]['score']['estimated_sets'])
        self.assertIsNone(data['sessions'][0]['window']['median'])
        self.client.post('/movement-stress/bench',json={'sets':[]})
        self.hevy.exercise_history.assert_called_once_with('bench')
        self.hevy.create_workout.assert_not_called()

    def test_dashboard_catalog_identifies_main_lifts_and_retains_other_movements(self):
        with main.get_db() as conn:
            conn.executemany('INSERT INTO hevy_exercise_cache (id,title) VALUES (?,?)',[
                ('sq',main.progress.LIFT_TITLES['squat']),('bp',main.progress.LIFT_TITLES['bench']),
                ('dl',main.progress.LIFT_TITLES['deadlift']),('row','Pendlay Row (Barbell)')])
        result=self.client.get('/stress/movements')
        self.assertEqual(200,result.status_code,result.text)
        values={r['id']:r['primary_key'] for r in result.json()}
        self.assertEqual({'sq':'squat','bp':'bench','dl':'deadlift','row':None},values)
        self.hevy.exercise_history.assert_not_called()

    def test_dashboard_page_and_invalid_history_range(self):
        response=self.client.get('/stress')
        self.assertEqual(200,response.status_code)
        self.assertIn('no-cache',response.headers['cache-control'])
        detail=self.client.get('/stress/details?movement=bench&days=180')
        self.assertEqual(200,detail.status_code)
        self.assertIn('no-cache',detail.headers['cache-control'])
        self.assertIn('detailsLink',response.text)
        self.assertIn('dashboardLink',detail.text)
        self.assertEqual(422,self.client.get('/movement-stress/bench/history?days=-1').status_code)
        self.hevy.exercise_history.assert_not_called()


if __name__=='__main__':
    unittest.main()
