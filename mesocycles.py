"""Local workout plans; no Hevy calls and no legacy-program state."""
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from database import get_db


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
    sessions: list[PlannedSession] = Field(min_length=1, max_length=14)


class PlanInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str = Field(default='', max_length=4000)
    weeks: list[PlannedWeek] = Field(min_length=1, max_length=26)
    revision: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def unique_sessions(self):
        ids = [s.id for w in self.weeks for s in w.sessions]
        if len(ids) != len(set(ids)):
            raise ValueError('Workout identities must be unique')
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
        raise PlanError('Mesocycle not found', 404)
    return row


def _view(conn, row):
    return dict(json.loads(row['document']), id=row['id'], revision=row['revision'],
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


def save_plan(data: PlanInput, plan_id=None):
    document = data.model_dump(exclude={'revision'})
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if plan_id is None:
            plan_id = str(uuid4())
            conn.execute('INSERT INTO mesocycles (id, document) VALUES (?, ?)',
                         (plan_id, json.dumps(document)))
        else:
            row = _row(conn, plan_id)
            if row['archived']:
                raise PlanError('This mesocycle is archived')
            if row['revision'] != data.revision:
                raise PlanError('This plan changed on another device. Reload it before saving.')
            old = {s['id']: s for w in json.loads(row['document'])['weeks'] for s in w['sessions']}
            new = {s['id']: s for w in document['weeks'] for s in w['sessions']}
            for done in conn.execute('SELECT session_id FROM mesocycle_completions WHERE mesocycle_id = ?', (plan_id,)):
                if new.get(done['session_id']) != old.get(done['session_id']):
                    raise PlanError('Completed workouts are kept as planned. Duplicate one to make a new workout.')
            conn.execute('UPDATE mesocycles SET document = ?, revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (json.dumps(document), plan_id))
        return _view(conn, _row(conn, plan_id))


def activate(plan_id):
    with get_db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if _row(conn, plan_id)['archived']:
            raise PlanError('This mesocycle is archived')
        conn.execute('UPDATE mesocycles SET active = 0 WHERE active = 1')
        conn.execute('UPDATE mesocycles SET active = 1 WHERE id = ?', (plan_id,))
        return _view(conn, _row(conn, plan_id))


def archive(plan_id):
    with get_db() as conn:
        _row(conn, plan_id)
        conn.execute('UPDATE mesocycles SET archived = 1, active = 0 WHERE id = ?', (plan_id,))


def validate_save(link: PlanLink, start):
    """Validate before the irreversible Hevy post; retries return the saved result."""
    with get_db() as conn:
        plan = _view(conn, _row(conn, link.mesocycle_id))
        if not any(s['id'] == link.session_id for w in plan['weeks'] for s in w['sessions']):
            raise PlanError('The planned workout no longer exists. Reload it or save this as an unplanned workout.')
        done = next((s for s in plan['completed'] if s['session_id'] == link.session_id), None)
        if done and done['workout_start'] != start:
            raise PlanError('This planned workout is already completed. Choose the next workout.')
        return done


def complete(link: PlanLink, hevy_id, start):
    with get_db() as conn:
        conn.execute('INSERT INTO mesocycle_completions (mesocycle_id, session_id, hevy_workout_id, workout_start) VALUES (?, ?, ?, ?) ON CONFLICT(mesocycle_id, session_id) DO NOTHING',
                     (link.mesocycle_id, link.session_id, hevy_id, start))
