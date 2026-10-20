"""User-owned movement assignments, edited and saved through the microcycle builder."""
from contextlib import closing
from typing import Literal

from pydantic import BaseModel, Field

from database import get_db

ChartGroup = Literal['squat', 'bench', 'deadlift', 'general']
LABELS = {'squat': 'Squat', 'bench': 'Bench', 'deadlift': 'Deadlift', 'general': 'General'}


class Assignment(BaseModel):
    group: ChartGroup | None = None
    revision: int = Field(default=0, ge=0)


def read(conn, template_ids=None):
    values = {r['exercise_template_id']: {'group': r['chart_group'], 'revision': r['revision']}
              for r in conn.execute('SELECT * FROM rpe_chart_assignments')}
    if template_ids is None:
        return values
    return {key: values.get(key, {'group': None, 'revision': 0}) for key in template_ids}


def all_assignments():
    with closing(get_db()) as conn:
        return read(conn)


def save(conn, changes):
    current = read(conn)
    for template, change in changes.items():
        old = current.get(template, {'group': None, 'revision': 0})
        if change.group == old['group']:
            continue
        if change.revision != old['revision']:
            raise ValueError('An RPE chart assignment changed on another device or plan. Reload before saving.')
        conn.execute('''INSERT INTO rpe_chart_assignments (exercise_template_id, chart_group, revision)
            VALUES (?, ?, ?) ON CONFLICT(exercise_template_id) DO UPDATE SET
            chart_group=excluded.chart_group, revision=excluded.revision''',
            (template, change.group, old['revision'] + 1))


def migrate_legacy(conn):
    """One-time preservation of the four assignments already approved before the builder setting existed."""
    key = 'rpe_builder_assignments_v1'
    if conn.execute('SELECT 1 FROM app_settings WHERE key = ?', (key,)).fetchone():
        return
    legacy = {'Squat, Low Bar w/ Belt': 'squat', 'Squat, High Bar, Paused': 'squat',
              'Bench Press - Close Grip (Barbell)': 'bench', 'Deadlift, Conv. w/ Belt': 'deadlift'}
    rows = conn.execute('''SELECT exercise_template_id, exercise_title FROM logged_sets
        UNION SELECT exercise_template_id, exercise_title FROM rpe_history_imports''').fetchall()
    for row in rows:
        group = legacy.get(row['exercise_title'])
        if group:
            conn.execute('''INSERT INTO rpe_chart_assignments (exercise_template_id, chart_group, revision)
                VALUES (?, ?, 1) ON CONFLICT DO NOTHING''', (row['exercise_template_id'], group))
    conn.execute('INSERT INTO app_settings (key, value) VALUES (?, ?)', (key, 'done'))
