"""Builder-owned chart assignments, using temporary databases and no real Hevy writes."""
from contextlib import closing
import gc
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from database import get_db, init_db
import main
import rpe_assignments
import rpe_history
import set_log


def plan_payload(group='general', template='custom', revision=0):
    return {'name': 'Plan', 'weeks': [{'name': 'Week 1', 'sessions': [{'id': 'day', 'name': 'Day',
        'exercises': [{'exercise_template_id': template, 'title': 'Arbitrary movement name',
                       'sets': [{'reps': 5, 'rpe': 7}]}]}]}],
        'rpe_assignments': {template: {'group': group, 'revision': revision}}}


class AssignmentCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'DB_PATH': os.path.join(self.temp.name, 'test.db')})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(gc.collect)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def create(self, payload=None):
        response = self.client.post('/api/mesocycles', json=payload or plan_payload())
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def local(self, template='custom', title='Arbitrary movement name'):
        set_log.record(set_log.rows_from_entry({'title': 'Workout', 'start_time': '2026-10-20T10:00:00Z',
            'exercises': [{'exercise_template_id': template, 'title': title, 'sets': [
                {'weight_kg': 100, 'reps': 5, 'rpe': 7}, {'weight_kg': 110, 'reps': 1, 'rpe': 8}]}]}, 'w1'))

    def test_user_assignment_controls_arbitrary_names_and_general_has_observations(self):
        self.local()
        self.assertTrue(all(lift['sets'] == 0 for lift in self.client.get('/rpe-observed').json()))
        saved = self.create()
        self.assertEqual({'group': 'general', 'revision': 1}, saved['rpe_assignments']['custom'])
        response = self.client.get('/rpe-observed/group/general')
        self.assertEqual(200, response.status_code)
        self.assertEqual(2, response.json()['sets_used'])
        self.assertEqual('Arbitrary movement name', response.json()['sources'][0]['title'])
        self.assertEqual(2, response.json()['sources'][0]['local_sets'])
        self.assertEqual(422, self.client.get('/rpe-observed/group/press').status_code)
        self.assertEqual(saved['rpe_assignments'], self.client.get('/rpe-chart-assignments').json())

    def test_reassignment_moves_history_without_rewriting_sets_or_prescriptions(self):
        self.local()
        saved = self.create()
        with closing(get_db()) as conn:
            before = [dict(r) for r in conn.execute('SELECT * FROM logged_sets')]
            prescription = conn.execute('SELECT document FROM mesocycles WHERE id = ?', (saved['id'],)).fetchone()[0]
        saved['rpe_assignments']['custom']['group'] = 'bench'
        response = self.client.put('/api/mesocycles/' + saved['id'], json=saved)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(2, response.json()['rpe_assignments']['custom']['revision'])
        self.assertEqual(2, self.client.get('/rpe-observed/group/bench').json()['sets_used'])
        self.assertEqual(0, self.client.get('/rpe-observed/group/general').json()['sets_used'])
        updated = response.json()
        updated['rpe_assignments']['custom']['group'] = None
        self.assertEqual(200, self.client.put('/api/mesocycles/' + saved['id'], json=updated).status_code)
        self.assertEqual(0, self.client.get('/rpe-observed/group/bench').json()['sets_used'])
        with closing(get_db()) as conn:
            self.assertEqual(before, [dict(r) for r in conn.execute('SELECT * FROM logged_sets')])
            self.assertEqual(prescription, conn.execute('SELECT document FROM mesocycles WHERE id = ?', (saved['id'],)).fetchone()[0])

    def test_stale_assignment_from_another_plan_rolls_back_the_whole_save(self):
        first = self.create()
        second = self.create(plan_payload(revision=1))
        first['rpe_assignments']['custom']['group'] = 'squat'
        self.assertEqual(200, self.client.put('/api/mesocycles/' + first['id'], json=first).status_code)
        second['rpe_assignments']['custom']['group'] = 'deadlift'
        second['notes'] = 'Must not leak from failed transaction'
        response = self.client.put('/api/mesocycles/' + second['id'], json=second)
        self.assertEqual(409, response.status_code)
        self.assertIn('RPE chart assignment changed', response.json()['detail'])
        reread = self.client.get('/api/mesocycles/' + second['id']).json()
        self.assertEqual('', reread['notes'])
        self.assertEqual(second['revision'], reread['revision'])
        self.assertEqual('squat', reread['rpe_assignments']['custom']['group'])

    def test_completed_prescription_can_change_shared_classification_only(self):
        saved = self.create()
        marked = self.client.post('/api/mesocycles/' + saved['id'] + '/sessions/day/complete').json()
        before = marked['weeks']
        marked['rpe_assignments']['custom']['group'] = 'deadlift'
        response = self.client.put('/api/mesocycles/' + saved['id'], json=marked)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(before, response.json()['weeks'])
        self.assertEqual('deadlift', response.json()['rpe_assignments']['custom']['group'])
        bad = response.json()
        bad['weeks'][0]['sessions'][0]['exercises'][0]['sets'][0]['reps'] = 9
        self.assertEqual(409, self.client.put('/api/mesocycles/' + saved['id'], json=bad).status_code)

    def test_invalid_and_hidden_movement_assignments_are_rejected(self):
        for group in ['press', 'anything']:
            self.assertEqual(422, self.client.post('/api/mesocycles', json=plan_payload(group)).status_code)
        body = plan_payload()
        body['rpe_assignments']['not-in-plan'] = {'group': 'squat'}
        self.assertEqual(422, self.client.post('/api/mesocycles', json=body).status_code)
        self.assertEqual({}, self.client.get('/rpe-chart-assignments').json())

    def test_import_selects_assigned_ids_not_names_and_exclusion_keeps_saved_imports(self):
        saved = self.create()
        fake = type('Fake', (), {'list_workouts': lambda self, **kwargs: {'page_count': 1, 'workouts': [
            {'id': 'old', 'title': 'BS-Bridge1.1.1', 'start_time': '2025-01-01T10:00:00Z', 'exercises': [
                {'exercise_template_id': 'custom', 'title': 'Historical name', 'sets': [{'type': 'normal', 'weight_kg': 100, 'reps': 5, 'rpe': 7}]},
                {'exercise_template_id': 'unassigned', 'title': 'Squat, Low Bar w/ Belt', 'sets': [{'type': 'normal', 'weight_kg': 100, 'reps': 5, 'rpe': 7}]}]}]}})()
        with patch('main._call_hevy', side_effect=lambda fn: fn(fake)):
            response = self.client.post('/rpe-history/import-bs-bridge')
        self.assertEqual(1, response.json()['sets_imported'])
        self.assertEqual(1, self.client.get('/rpe-observed/group/general').json()['gate']['sets'])
        saved['rpe_assignments']['custom']['group'] = None
        self.client.put('/api/mesocycles/' + saved['id'], json=saved)
        self.assertEqual(0, self.client.get('/rpe-observed/group/general').json()['gate']['sets'])
        with closing(get_db()) as conn:
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM rpe_history_imports').fetchone()[0])
        self.assertEqual([], rpe_history.fetch_bridge(fake)['sessions'])

    def test_migration_preserves_previous_approved_choices_once(self):
        self.local('old-squat', 'Squat, Low Bar w/ Belt')
        self.local('old-press', 'Overhead Press (Barbell)')
        with closing(get_db()) as conn, conn:
            conn.execute("DELETE FROM app_settings WHERE key = 'rpe_builder_assignments_v1'")
        init_db()
        self.assertEqual({'group': 'squat', 'revision': 1}, rpe_assignments.all_assignments()['old-squat'])
        self.assertNotIn('old-press', rpe_assignments.all_assignments())
        with closing(get_db()) as conn, conn:
            rpe_assignments.save(conn, {'old-squat': rpe_assignments.Assignment(group=None, revision=1)})
        init_db()
        self.assertIsNone(rpe_assignments.all_assignments()['old-squat']['group'])
        self.local('new-same-name', 'Squat, Low Bar w/ Belt')
        self.assertNotIn('new-same-name', rpe_assignments.all_assignments())

    def test_older_plan_client_does_not_reset_shared_assignments(self):
        saved = self.create()
        del saved['rpe_assignments']
        response = self.client.put('/api/mesocycles/' + saved['id'], json=saved)
        self.assertEqual(200, response.status_code)
        self.assertEqual('general', response.json()['rpe_assignments']['custom']['group'])
        with closing(get_db()) as conn:
            doc = json.loads(conn.execute('SELECT document FROM mesocycles WHERE id = ?', (saved['id'],)).fetchone()[0])
        self.assertNotIn('rpe_assignments', doc)
