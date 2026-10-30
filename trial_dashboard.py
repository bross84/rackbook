"""Read-only trial history; unsaved snapshots never reveal frozen predictions."""
from contextlib import closing
import json
from typing import Literal

from pydantic import BaseModel, Field

from database import get_db
import fatigue_trial as trial
import fatigue_trial_smoother as smoother


class SetObservation(BaseModel):
    weight_kg: float | None = None
    reps: int | None = None
    rpe: float | None = None


class DashboardEntry(BaseModel):
    id: str
    exercise_template_id: str
    title: str
    workout_start: str
    recorded_at: str
    model_version: str
    prospective: bool
    status: Literal['recorded', 'completed']
    mode: Literal['strength', 'hypertrophy'] | None = None
    prediction: str | None = None
    observed: str | None = None
    soreness: int | None = None
    pain: bool | None = None
    daily: trial.DailyCheckin | None = None
    planned: SetObservation | None = None
    actual: SetObservation | None = None
    reasons: list[str] = Field(default_factory=list)
    notes: list[dict] = Field(default_factory=list)
    shadow: dict | None = None


class DashboardCohort(trial.TrialEvaluation):
    title: str


class Dashboard(BaseModel):
    entries: list[DashboardEntry]
    cohorts: list[DashboardCohort]
    shadow_cohorts: list[dict] | None = None


def dashboard():
    with closing(get_db()) as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM fatigue_trial_snapshots ORDER BY workout_start, recorded_at, id')]
        names = {r['id']: r['title'] for r in conn.execute('SELECT id, title FROM hevy_exercise_cache')}
        saved = trial.with_order([dict(r) for r in conn.execute('SELECT * FROM logged_sets ORDER BY workout_start, id')])
        for r in reversed(saved):
            if r.get('exercise_title'):
                names.setdefault(r['exercise_template_id'], r['exercise_title'])
        for r in conn.execute('SELECT document FROM mesocycles'):
            for week in json.loads(r['document'])['weeks']:
                for session in week['sessions']:
                    for ex in session['exercises']:
                        names.setdefault(ex['exercise_template_id'], ex['title'])
        notes = {}
        for r in conn.execute('SELECT trial_id, kind, text, recorded_at FROM fatigue_trial_notes ORDER BY id'):
            notes.setdefault(r['trial_id'], []).append({k: r[k] for k in ('kind', 'text', 'recorded_at')})
    entries = []
    for row in rows:
        entry = dict(id=row['id'], exercise_template_id=row['exercise_template_id'],
                     title=names.get(row['exercise_template_id'], 'Movement ' + row['exercise_template_id']),
                     workout_start=row['workout_start'], recorded_at=row['recorded_at'],
                     model_version=row['model_version'], prospective=bool(row['prospective']),
                     status='completed' if row['completion'] else 'recorded')
        if row['completion']:
            snapshot, completion = json.loads(row['snapshot']), json.loads(row['completion'])
            data = snapshot['input']
            actual = completion.get('actual')
            if 'actual' not in completion:  # Older records predate frozen actual-set storage.
                sets = [r for r in saved if r['hevy_workout_id'] == row['hevy_workout_id'] and r['exercise_template_id'] == row['exercise_template_id']]
                numbers = [r['set_number'] for r in sets]
                actual = trial.representative(sets, data['mode']) if len(numbers) == len(set(numbers)) else None
            entry['shadow'] = smoother.read(row['id'])
            entry.update(mode=data['mode'], prediction=snapshot['prediction'], observed=completion['observed'],
                         soreness=data['soreness'], pain=bool(row['pain']), daily=snapshot['daily'],
                         planned=dict(weight_kg=data.get('planned_weight_kg'), reps=data['planned_reps'], rpe=data.get('planned_rpe')),
                         actual={k: actual.get(k) for k in ('weight_kg', 'reps', 'rpe')} if actual else None,
                         reasons=snapshot['reasons'], notes=notes.get(row['id'], []))
        entries.append(entry)
    cohorts = [dict(c, title=names.get(c['exercise_template_id'], 'Movement ' + c['exercise_template_id'])) for c in trial.evaluation()]
    result = dict(entries=entries, cohorts=cohorts)
    shadow_cohorts = smoother.summaries()
    if shadow_cohorts:
        result['shadow_cohorts'] = shadow_cohorts
    return result
