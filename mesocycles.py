"""Local workout plans; no Hevy calls and no legacy-program state."""
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from database import get_db
import rpe_assignments
from rpe_assignments import Assignment


class PlannedSet(BaseModel):
    reps: int = Field(ge=1, le=100)
    rpe: float | None = Field(default=None, ge=4, le=10)
    weight_kg: float | None = Field(default=None, ge=0, le=2000)
    type: Literal['normal', 'failure', 'dropset'] = 'normal'
    ts: bool = False

    @field_validator('rpe')
    @classmethod
    def half_steps(cls, value):
        if value is not None and value * 2 != int(value * 2):
            raise ValueError('RPE must use half-point steps')
        return value


class PlannedMovement(BaseModel):
    exercise_template_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default='', max_length=2000)
    sets: list[PlannedSet] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def one_ts(self):
        if sum(s.ts for s in self.sets) > 1:
            raise ValueError('Only one TS per movement')
        return self


class PlannedSession(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    exercises: list[PlannedMovement] = Field(default_factory=list, max_length=30)


class PlannedWeek(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sessions: list[PlannedSession] = Field(default_factory=list, max_length=14)


class PlanInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    program_name: str = Field(default='', max_length=90)
    cycle: int = Field(default=1, ge=1, le=9999)
    week: int = Field(default=1, ge=1, le=9999)
    notes: str = Field(default='', max_length=4000)
    weeks: list[PlannedWeek] = Field(min_length=1, max_length=1)
    revision: int = Field(default=0, ge=0)
    rpe_assignments: dict[str, Assignment] = Field(default_factory=dict, max_length=420)

    @model_validator(mode='after')
    def unique_sessions(self):
        self.program_name = self.program_name.strip()
        if self.program_name:
            self.name = f'{self.program_name}{self.cycle}.{self.week}'
            for index, session in enumerate(self.weeks[0].sessions, 1):
                session.name = f'{self.name}.{index}'
        ids = [s.id for w in self.weeks for s in w.sessions]
        if len(ids) != len(set(ids)):
            raise ValueError('Workout identities must be unique')
        movement_ids = {ex.exercise_template_id for w in self.weeks for s in w.sessions for ex in s.exercises}
        if not set(self.rpe_assignments).issubset(movement_ids):
            raise ValueError('RPE chart assignments must belong to movements in this microcycle')
        return self


class PlanLink(BaseModel):
    mesocycle_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)


class Completion(BaseModel):
    session_id: str
    hevy_workout_id: str | None
    workout_start: str


class PlanView(PlanInput):
    id: str
    active: bool
    archived: bool
    completed: list[Completion]


class PlanError(Exception):
    def __init__(self, message, status=409):
        self.status = status
        super().__init__(message)


def _row(conn, plan_id):
    row = conn.execute('SELECT * FROM mesocycles WHERE id = ?', (plan_id,)).fetchone()
    if row is None:
        raise PlanError('Microcycle not found', 404)
    return row


def _view(conn, row):
    document = json.loads(row['document'])
    ids = {ex['exercise_template_id'] for w in document['weeks'] for s in w['sessions'] for ex in s['exercises']}
    return dict(document, id=row['id'], revision=row['revision'], rpe_assignments=rpe_assignments.read(conn, ids),
                active=bool(row['active']), archived=bool(row['archived']),
                completed=[dict(r) for r in conn.execute(
                    'SELECT session_id, hevy_workout_id, workout_start FROM mesocycle_completions WHERE mesocycle_id = ?', (row['id'],))])


def list_plans():
    with get_db() as conn:
        return [_view(conn, row) for row in conn.execute(
            'SELECT * FROM mesocycles WHERE archived = 0 ORDER BY active DESC, updated_at DESC, id')]


def get_plan(plan_id):
    with get_db() as conn:
        return _view(conn, _row(conn, plan_id))


def resolve_plan(plan_id, session_id):
    """Old links and in-flight log drafts survive splitting a multiweek plan."""
    with get_db() as conn:
        alias = conn.execute('SELECT plan_id FROM mesocycle_session_aliases WHERE original_plan_id = ? AND session_id = ?',
                             (plan_id, session_id)).fetchone()
        return _view(conn, _row(conn, alias['plan_id'] if alias else plan_id))


def migrate_single_week_plans():
    """Keep real future work and completions; remove only empty week scaffolding."""
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for row in conn.execute('SELECT * FROM mesocycles').fetchall():
            document = json.loads(row['document'])
            if len(document['weeks']) <= 1:
                continue
            conn.execute('INSERT INTO mesocycle_week_backups (plan_id, document, revision) VALUES (?, ?, ?) ON CONFLICT(plan_id) DO NOTHING',
                         (row['id'], row['document'], row['revision']))
            completed = {r['session_id'] for r in conn.execute(
                'SELECT session_id FROM mesocycle_completions WHERE mesocycle_id = ?', (row['id'],))}
            kept = []
            conn.execute('UPDATE mesocycles SET active = 0 WHERE id = ?', (row['id'],))
            for index, week in enumerate(document['weeks']):
                if index and not any(s['exercises'] or s['id'] in completed for s in week['sessions']):
                    continue
                target = row['id'] if index == 0 else str(uuid4())
                data = dict(document, weeks=[week])
                if index:
                    data['name'] = (document['name'][:90] + ' · ' + week['name'][:25])[:120]
                    conn.execute('INSERT INTO mesocycles (id, document, archived) VALUES (?, ?, ?)',
                                 (target, json.dumps(data), row['archived']))
                    for session in week['sessions']:
                        conn.execute('INSERT INTO mesocycle_session_aliases (original_plan_id, session_id, plan_id) VALUES (?, ?, ?)',
                                     (row['id'], session['id'], target))
                        conn.execute('UPDATE mesocycle_completions SET mesocycle_id = ? WHERE mesocycle_id = ? AND session_id = ?',
                                     (target, row['id'], session['id']))
                else:
                    conn.execute('UPDATE mesocycles SET document = ?, revision = revision + 1 WHERE id = ?',
                                 (json.dumps(data), target))
                kept.append((target, week))
            if row['active']:
                pending = next((target for target, week in kept if any(s['id'] not in completed and s['exercises'] for s in week['sessions'])), kept[0][0])
                conn.execute('UPDATE mesocycles SET active = 1 WHERE id = ?', (pending,))


def save_plan(data: PlanInput, plan_id=None):
    document = data.model_dump(exclude={'revision', 'rpe_assignments'})
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if plan_id is None:
            plan_id = str(uuid4())
            conn.execute('INSERT INTO mesocycles (id, document) VALUES (?, ?)',
                         (plan_id, json.dumps(document)))
        else:
            row = _row(conn, plan_id)
            if row['archived']:
                raise PlanError('This microcycle is archived')
            if row['revision'] != data.revision:
                raise PlanError('This plan changed on another device. Reload it before saving.')
            old = {s['id']: s for w in json.loads(row['document'])['weeks'] for s in w['sessions']}
            new = {s['id']: s for w in document['weeks'] for s in w['sessions']}
            for done in conn.execute('SELECT session_id FROM mesocycle_completions WHERE mesocycle_id = ?', (plan_id,)):
                if new.get(done['session_id']) != old.get(done['session_id']):
                    raise PlanError('Completed workouts are kept as planned. Duplicate one to make a new workout.')
            conn.execute('UPDATE mesocycles SET document = ?, revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (json.dumps(document), plan_id))
        try:
            rpe_assignments.save(conn, data.rpe_assignments)
        except ValueError as exc:
            raise PlanError(str(exc))
        return _view(conn, _row(conn, plan_id))


def activate(plan_id):
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _row(conn, plan_id)
        if row['archived']:
            raise PlanError('This microcycle is archived')
        if not json.loads(row['document'])['weeks'][0]['sessions']:
            raise PlanError('Add a day before using this microcycle')
        conn.execute('UPDATE mesocycles SET active = 0 WHERE active = 1')
        conn.execute('UPDATE mesocycles SET active = 1 WHERE id = ?', (plan_id,))
        return _view(conn, _row(conn, plan_id))


def archive(plan_id):
    with get_db() as conn:
        _row(conn, plan_id)
        conn.execute('UPDATE mesocycles SET archived = 1, active = 0 WHERE id = ?', (plan_id,))


def mark_completed(plan_id, session_id):
    """Record a day already trained elsewhere; never create a Hevy workout."""
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _row(conn, plan_id)
        if row['archived']:
            raise PlanError('This microcycle is archived')
        sessions = json.loads(row['document'])['weeks'][0]['sessions']
        if not any(s['id'] == session_id for s in sessions):
            raise PlanError('Workout day not found', 404)
        conn.execute('INSERT INTO mesocycle_completions (mesocycle_id, session_id, hevy_workout_id, workout_start) VALUES (?, ?, ?, ?) ON CONFLICT(mesocycle_id, session_id) DO NOTHING',
                     (plan_id, session_id, None, datetime.now(timezone.utc).isoformat()))
        return _view(conn, row)


def undo_manual_completion(plan_id, session_id):
    """Remove only a local prior-training mark, preserving saved workout links."""
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = _row(conn, plan_id)
        if row['archived']:
            raise PlanError('This microcycle is archived')
        if not any(s['id'] == session_id for s in json.loads(row['document'])['weeks'][0]['sessions']):
            raise PlanError('Workout day not found', 404)
        completion = conn.execute('SELECT hevy_workout_id FROM mesocycle_completions WHERE mesocycle_id = ? AND session_id = ?', (plan_id, session_id)).fetchone()
        if completion and completion['hevy_workout_id'] is not None:
            raise PlanError('Only manually marked completion can be undone. Saved workouts retain their history.')
        conn.execute('DELETE FROM mesocycle_completions WHERE mesocycle_id = ? AND session_id = ? AND hevy_workout_id IS NULL', (plan_id, session_id))
        return _view(conn, row)


def clear_initial_day_placeholders():
    """One-time conversion of the old three untouched default days, preserving a backup."""
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        key = 'microcycle_blank_days_v1'
        if conn.execute('SELECT 1 FROM app_settings WHERE key = ?', (key,)).fetchone():
            return
        for row in conn.execute('SELECT * FROM mesocycles').fetchall():
            doc = json.loads(row['document'])
            sessions = doc['weeks'][0]['sessions']
            done = conn.execute('SELECT 1 FROM mesocycle_completions WHERE mesocycle_id = ? LIMIT 1', (row['id'],)).fetchone()
            if ([s['name'] for s in sessions] == ['Day 1', 'Day 2', 'Day 3']
                    and not any(s['exercises'] for s in sessions) and not done):
                conn.execute('INSERT INTO mesocycle_week_backups (plan_id, document, revision) VALUES (?, ?, ?) ON CONFLICT(plan_id) DO NOTHING',
                             (row['id'], row['document'], row['revision']))
                doc['weeks'][0]['sessions'] = []
                conn.execute('UPDATE mesocycles SET document = ?, revision = revision + 1, active = 0 WHERE id = ?',
                             (json.dumps(doc), row['id']))
        conn.execute('INSERT INTO app_settings (key, value) VALUES (?, ?)', (key, 'done'))


def validate_save(link: PlanLink, start):
    """Validate before the irreversible Hevy post; retries return the saved result."""
    plan = resolve_plan(link.mesocycle_id, link.session_id)
    if not any(s['id'] == link.session_id for w in plan['weeks'] for s in w['sessions']):
        raise PlanError('The planned workout no longer exists. Reload it or save this as an unplanned workout.')
    done = next((s for s in plan['completed'] if s['session_id'] == link.session_id), None)
    if done and done['workout_start'] != start:
        raise PlanError('This planned workout is already completed. Choose the next workout.')
    return done


def complete(link: PlanLink, hevy_id, start):
    plan = resolve_plan(link.mesocycle_id, link.session_id)
    with get_db() as conn:
        conn.execute('INSERT INTO mesocycle_completions (mesocycle_id, session_id, hevy_workout_id, workout_start) VALUES (?, ?, ?, ?) ON CONFLICT(mesocycle_id, session_id) DO NOTHING',
                     (plan['id'], link.session_id, hevy_id, start))
