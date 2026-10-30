"""Append-only shadow arm for HF's pinned recovery-confirmation-v1 daily model.

Daily action is context alongside movement performance, not a movement prediction.
No legacy rows/results are updated, and no shadow output is revealed before save.
"""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from database import get_db
import hevy_recovery_model as model

VERSION = 'hf-recovery-shadow-v1'
SOURCE_HASH = hashlib.sha256(Path(model.__file__).read_bytes()).hexdigest()


def unavailable(day, now):
    return dict(model_version=VERSION, source_model_version=model.MODEL_VERSION,
                source_sha256=SOURCE_HASH, assessed_at=now.isoformat(), as_of_date=day,
                status='unavailable', data_sufficient=False, recommendation='insufficient_data',
                recommendation_label=model.FALLBACK_LABEL,
                recommendation_detail='Hevy Fatigue model inputs are unavailable. Insufficient data to recommend a change.')


def capture(day, now):
    result = unavailable(day, now)
    source = os.environ.get('HEVY_FATIGUE_DB_PATH')
    if not source:
        return result
    try:
        target = date.fromisoformat(day)
        with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True, timeout=1)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN')
            checkins = [dict(r) for r in conn.execute('''SELECT date, tiredness, perceived_recovery,
                sore_quad_dom, sore_posterior, sore_upper_push, sore_upper_pull
                FROM daily_readiness WHERE date <= ? ORDER BY date''', (day,))]
            earliest = checkins[0]['date'] if checkins else day
            from datetime import timedelta
            floor = (date.fromisoformat(earliest)-timedelta(days=180)).isoformat()
            rows = conn.execute('''SELECT s.workout_date, SUM(COALESCE(l.weight_lbs,0)*COALESCE(l.reps,0)) AS volume
                FROM workout_sessions s JOIN workout_logs l ON l.workout_id=s.hevy_workout_id
                WHERE s.workout_date >= ? AND s.workout_date < ? GROUP BY s.workout_date ORDER BY s.workout_date''', (floor,day)).fetchall()
        volumes = {date.fromisoformat(r['workout_date']):float(r['volume'] or 0) for r in rows}
        inputs = dict(checkins=checkins, daily_volumes=[dict(date=d.isoformat(),volume=v) for d,v in volumes.items()])
        encoded = json.dumps(inputs,sort_keys=True,separators=(',',':'))
        daily = model.build_history(checkins,volumes,target)[-1]
        result.update(daily)
        result.update(model_version=VERSION, source_model_version=model.MODEL_VERSION,
                      status='available' if daily['data_sufficient'] else 'insufficient_data',
                      input_sha256=hashlib.sha256(encoded.encode()).hexdigest(), inputs=inputs,
                      interpretation='Daily training action; not a movement-performance prediction. Target-day workouts excluded; source check-ins have date-only timing.')
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return unavailable(day,now)
    return result


def store(trial_id, snapshot):
    with closing(get_db()) as conn, conn:
        conn.execute('INSERT OR IGNORE INTO fatigue_trial_shadow(trial_id,model_version,snapshot) VALUES (?,?,?)',
                     (trial_id,VERSION,json.dumps(snapshot,sort_keys=True)))


def read(trial_id):
    with closing(get_db()) as conn:
        row = conn.execute('SELECT snapshot FROM fatigue_trial_shadow WHERE trial_id=? ORDER BY model_version LIMIT 1', (trial_id,)).fetchone()
    if not row:
        return None
    return public(json.loads(row[0]))


def public(snapshot):
    # Keep large frozen source inputs server-side; retain identity/version hashes.
    return {k:v for k,v in snapshot.items() if k != 'inputs'}


def summaries():
    groups = defaultdict(list)
    with closing(get_db()) as conn:
        rows = conn.execute('''SELECT s.snapshot AS shadow, t.exercise_template_id, t.snapshot, t.completion, t.prospective
            FROM fatigue_trial_shadow s JOIN fatigue_trial_snapshots t ON t.id=s.trial_id''').fetchall()
    for row in rows:
        if not row['completion'] or not row['prospective']:
            continue
        snapshot = json.loads(row['shadow'])
        mode = json.loads(row['snapshot'])['input']['mode']
        key = (snapshot['model_version'],row['exercise_template_id'],mode)
        groups[key].append((snapshot,json.loads(row['completion'])['observed']))
    result=[]
    for (version,exercise,mode),items in groups.items():
        actions=defaultdict(Counter)
        for snapshot,observed in items:
            actions[snapshot['recommendation_label']][observed]+=1
        result.append(dict(model_version=version,exercise_template_id=exercise,mode=mode,
            completed_prospective=len(items),data_sufficient=sum(s['data_sufficient'] for s,_ in items),
            classified_outcomes=sum(o!='unclassified' for _,o in items),
            by_recommendation={k:dict(v) for k,v in actions.items()},
            interpretation='Descriptive daily-action versus movement-outcome counts. No movement prediction or accuracy claim.'))
    return result
