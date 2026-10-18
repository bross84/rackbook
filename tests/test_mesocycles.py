"""Real temporary SQLite; Hevy is mocked for every workout-save test."""
import os
import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault('DB_PATH', os.path.join(tempfile.mkdtemp(), 'import.db'))
from fastapi.testclient import TestClient
import httpx
import main
import mesocycles


def document():
    return {'name':'Strength block', 'weeks':[
        {'name':'Week 1', 'sessions':[
            {'id':'day-a','name':'Squat day','exercises':[
                {'exercise_template_id':'squat','title':'Squat','sets':[
                    {'reps':1,'rpe':8,'ts':True}, {'reps':5,'rpe':7},
                    {'reps':5,'weight_kg':100}]}]},
            {'id':'day-b','name':'Bench day','exercises':[]},
            {'id':'day-c','name':'Squat day','exercises':[]}]}]}


class MesocycleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.environ['DB_PATH'] = os.path.join(self.tmp,'test.db')
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.mock = patch('main.hevy_client.HevyClient')
        self.hevy = self.mock.start().return_value
        self.addCleanup(self.mock.stop)
        self.hevy.create_workout.return_value = {'id':'saved-planned'}

    def create(self):
        response = self.client.post('/api/mesocycles', json=document())
        self.assertEqual(200,response.status_code,response.text)
        return response.json()

    def workout(self, plan):
        return {'title':'Squat day','start_time':'2026-10-17T10:00:00Z',
                'end_time':'2026-10-17T11:00:00Z',
                'planned_session':{'mesocycle_id':plan['id'],'session_id':'day-a'},
                'exercises':[{'exercise_template_id':'squat','title':'Squat','sets':[
                    {'type':'normal','weight_kg':100,'reps':5,'rpe':7}]}]}

    def test_store_plan_without_hevy_and_activate_exactly_one(self):
        a,b=self.create(),self.create()
        self.assertEqual(1,a['revision'])
        first_set=a['weeks'][0]['sessions'][0]['exercises'][0]['sets'][0]
        self.assertEqual(1,first_set['reps'])
        self.assertTrue(first_set['ts'])
        self.assertIsNone(first_set['weight_kg'])
        self.assertFalse(a['active'])
        self.client.post('/api/mesocycles/'+a['id']+'/activate')
        self.client.post('/api/mesocycles/'+b['id']+'/activate')
        self.assertEqual([b['id']], [p['id'] for p in self.client.get('/api/mesocycles').json() if p['active']])
        self.hevy.create_workout.assert_not_called()

    def test_loading_plan_and_discarding_draft_do_not_advance_it(self):
        p=self.create()
        for _ in range(2):
            response=self.client.get('/api/mesocycles/'+p['id'])
            self.assertEqual([],response.json()['completed'])
        self.hevy.create_workout.assert_not_called()

    def test_revision_conflict_and_protection_of_completed_prescriptions(self):
        p=self.create()
        updated=deepcopy(p);updated['notes']='Changed'
        response=self.client.put('/api/mesocycles/'+p['id'],json=updated)
        self.assertEqual(2,response.json()['revision'])
        self.assertEqual(409,self.client.put('/api/mesocycles/'+p['id'],json=p).status_code)
        mesocycles.complete(mesocycles.PlanLink(mesocycle_id=p['id'],session_id='day-a'),'done','start')
        current=self.client.get('/api/mesocycles/'+p['id']).json()
        current['weeks'][0]['sessions'][0]['name']='Do not rewrite'
        self.assertEqual(409,self.client.put('/api/mesocycles/'+p['id'],json=current).status_code)
        current['weeks'][0]['sessions'][0]['name']='Squat day'
        current['weeks'][0]['sessions'][2]['name']='Future edit'
        self.assertEqual(200,self.client.put('/api/mesocycles/'+p['id'],json=current).status_code)

    def test_advance_only_after_success_and_retry_does_not_post_twice(self):
        p=self.create(); entry=self.workout(p)
        self.hevy.create_workout.side_effect=httpx.ConnectError('offline')
        self.assertEqual(502,self.client.post('/hevy/workouts',json=entry).status_code)
        self.assertEqual([],self.client.get('/api/mesocycles/'+p['id']).json()['completed'])
        self.hevy.create_workout.side_effect=None
        response=self.client.post('/hevy/workouts',json=entry)
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual('saved-planned',response.json()['id'])
        done=self.client.get('/api/mesocycles/'+p['id']).json()['completed']
        self.assertEqual(['day-a'],[d['session_id'] for d in done])
        original=self.client.get('/api/mesocycles/'+p['id']).json()['weeks'][0]['sessions'][0]
        self.assertEqual(1,original['exercises'][0]['sets'][0]['reps'])
        self.assertEqual(2,self.hevy.create_workout.call_count)
        self.assertEqual(200,self.client.post('/hevy/workouts',json=entry).status_code)
        self.assertEqual(2,self.hevy.create_workout.call_count)
        entry['start_time']='2026-10-18T10:00:00Z'
        self.assertEqual(409,self.client.post('/hevy/workouts',json=entry).status_code)
        self.assertEqual(2,self.hevy.create_workout.call_count)

    def test_bad_plan_link_is_rejected_before_hevy_write(self):
        p=self.create();entry=self.workout(p)
        entry['planned_session']['session_id']='missing'
        self.assertEqual(409,self.client.post('/hevy/workouts',json=entry).status_code)
        self.hevy.create_workout.assert_not_called()

    def test_progress_recording_failure_does_not_invite_duplicate_save(self):
        p=self.create()
        with self.assertLogs('main',level='ERROR'), patch('main.mesocycles.complete',side_effect=RuntimeError('disk full')):
            response=self.client.post('/hevy/workouts',json=self.workout(p))
        self.assertEqual(200,response.status_code)
        self.assertIn('Do not save',response.json()['plan_warning'])
        self.hevy.create_workout.assert_called_once()

    def test_archive_preserves_document_and_completion(self):
        p=self.create()
        mesocycles.complete(mesocycles.PlanLink(mesocycle_id=p['id'],session_id='day-a'),'done','start')
        self.client.post('/api/mesocycles/'+p['id']+'/activate')
        response=self.client.post('/api/mesocycles/'+p['id']+'/archive')
        self.assertEqual(204,response.status_code)
        self.assertEqual([],self.client.get('/api/mesocycles').json())
        retained=self.client.get('/api/mesocycles/'+p['id']).json()
        self.assertTrue(retained['archived']);self.assertEqual(1,len(retained['completed']))

    def test_validation_and_page(self):
        for change in ('duplicate','rpe','ts'):
            doc=document();sets=doc['weeks'][0]['sessions'][0]['exercises'][0]['sets']
            if change=='duplicate':doc['weeks'][0]['sessions'][2]['id']='day-a'
            elif change=='rpe':sets[0]['rpe']=7.2
            else:sets[1]['ts']=True
            self.assertEqual(422,self.client.post('/api/mesocycles',json=doc).status_code)
        self.assertEqual(404,self.client.get('/api/mesocycles/missing').status_code)
        page=self.client.get('/mesocycles')
        self.assertEqual(200,page.status_code)
        self.assertEqual('no-cache',page.headers['cache-control'])
        self.hevy.create_workout.assert_not_called()

    def test_database_restart_preserves_saved_plan(self):
        p=self.create()
        main.init_db()
        restored=self.client.get('/api/mesocycles/'+p['id']).json()
        self.assertEqual(p['weeks'],restored['weeks'])

    def test_old_multiweek_plans_split_without_losing_work_or_draft_links(self):
        old=mesocycles.PlanInput(**document()).model_dump(exclude={'revision'})
        future=deepcopy(old['weeks'][0]['sessions'][0]);future['id']='future'
        old['weeks'] += [{'name':'Week 2','sessions':[future]},
                         {'name':'Week 3','sessions':[{'id':'empty','name':'Empty','exercises':[]}]},
                         {'name':'Week 4','sessions':[{'id':'past','name':'Completed','exercises':[]}]}]
        with main.get_db() as conn:
            conn.execute('INSERT INTO mesocycles (id,document,active) VALUES (?,?,1)',('old',json.dumps(old)))
        mesocycles.complete(mesocycles.PlanLink(mesocycle_id='old',session_id='day-a'),'first','first-start')
        mesocycles.complete(mesocycles.PlanLink(mesocycle_id='old',session_id='past'),'past-id','past-start')
        mesocycles.migrate_single_week_plans()
        plans=self.client.get('/api/mesocycles').json()
        self.assertEqual(3,len(plans))
        self.assertTrue(all(len(p['weeks'])==1 for p in plans))
        with main.get_db() as conn:
            backup=conn.execute('SELECT document FROM mesocycle_week_backups WHERE plan_id = ?',('old',)).fetchone()
        self.assertEqual(old,json.loads(backup['document']))
        resolved=self.client.get('/api/mesocycles/old/sessions/future').json()
        self.assertNotEqual('old',resolved['id'])
        self.assertTrue(resolved['active'])
        self.assertEqual(future,resolved['weeks'][0]['sessions'][0])
        past=mesocycles.resolve_plan('old','past')
        self.assertEqual('past-id',past['completed'][0]['hevy_workout_id'])
        link=mesocycles.PlanLink(mesocycle_id='old',session_id='future')
        self.assertIsNone(mesocycles.validate_save(link,'future-start'))
        mesocycles.complete(link,'future-id','future-start')
        self.assertEqual('future-id',mesocycles.validate_save(link,'future-start')['hevy_workout_id'])
        mesocycles.migrate_single_week_plans()
        self.assertEqual({p['id'] for p in plans},{p['id'] for p in self.client.get('/api/mesocycles').json()})
        self.assertEqual(422,self.client.post('/api/mesocycles',json=old).status_code)

    def test_empty_extra_weeks_are_removed_and_old_page_alias_still_works(self):
        old=document()
        old['weeks'] += [{'name':'Week 2','sessions':[{'id':'empty','name':'Day 1','exercises':[]}]}]
        with main.get_db() as conn:
            conn.execute('INSERT INTO mesocycles (id,document) VALUES (?,?)',('old',json.dumps(old)))
        mesocycles.migrate_single_week_plans()
        plans=self.client.get('/api/mesocycles').json()
        self.assertEqual(1,len(plans));self.assertEqual(1,len(plans[0]['weeks']))
        for url in ('/microcycles','/mesocycles'):
            html=self.client.get(url).text
            self.assertIn('Microcycle Builder',html)
            self.assertNotIn('id="addWeek"',html)
            self.assertNotIn('Copy to next week',html)

    def test_blank_microcycle_can_be_saved_then_days_added_and_last_removed(self):
        doc=document();doc['weeks'][0]['sessions']=[]
        response=self.client.post('/api/mesocycles',json=doc)
        self.assertEqual(200,response.status_code,response.text)
        plan=response.json();url='/api/mesocycles/'+plan['id']
        self.assertEqual(409,self.client.post(url+'/activate').status_code)
        plan['weeks'][0]['sessions']=[{'id':'custom-day','name':'My day','exercises':[]}]
        added=self.client.put(url,json=plan).json()
        self.assertEqual('custom-day',added['weeks'][0]['sessions'][0]['id'])
        added['weeks'][0]['sessions']=[]
        removed=self.client.put(url,json=added)
        self.assertEqual(200,removed.status_code)
        self.assertEqual([],self.client.get(url).json()['weeks'][0]['sessions'])

    def test_old_untouched_day_defaults_clear_once_without_removing_real_plans(self):
        doc=document();doc['weeks'][0]['sessions']=[{'id':'d'+str(i),'name':'Day '+str(i),'exercises':[]} for i in (1,2,3)]
        blank=self.client.post('/api/mesocycles',json=doc).json()
        real=self.create()
        with main.get_db() as conn:
            conn.execute('DELETE FROM app_settings WHERE key = ?',('microcycle_blank_days_v1',))
        mesocycles.clear_initial_day_placeholders()
        self.assertEqual([],self.client.get('/api/mesocycles/'+blank['id']).json()['weeks'][0]['sessions'])
        self.assertEqual(real['weeks'],self.client.get('/api/mesocycles/'+real['id']).json()['weeks'])
        intentional=self.client.post('/api/mesocycles',json=doc).json()
        mesocycles.clear_initial_day_placeholders()
        self.assertEqual(3,len(self.client.get('/api/mesocycles/'+intentional['id']).json()['weeks'][0]['sessions']))


if __name__=='__main__':unittest.main()
