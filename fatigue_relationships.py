"""Explicitly reviewed workload relationships; suggestions never confirm themselves."""
import json
from contextlib import closing
from datetime import datetime, timezone

from database import get_db
from soreness import patterns as main_patterns

PATTERNS = ("squat", "bench_press", "deadlift")
MUSCLE_SUGGESTIONS = {
    "quadriceps": ["squat"],
    "hamstrings": ["deadlift"],
    "lower_back": ["deadlift"],
    "glutes": ["squat", "deadlift"],
    "chest": ["bench_press"],
    "shoulders": ["bench_press"],
    "triceps": ["bench_press"],
}


def confirmed(conn):
    return {r["exercise_template_id"]: json.loads(r["patterns_json"])
            for r in conn.execute("SELECT exercise_template_id, patterns_json FROM fatigue_relationships")}


def list_relationships():
    with closing(get_db()) as conn:
        rows = conn.execute("""
            SELECT ids.exercise_template_id, cache.title AS cached_title, cache.primary_muscle,
                (SELECT exercise_title FROM logged_sets s
                 WHERE s.exercise_template_id = ids.exercise_template_id AND s.exercise_title IS NOT NULL
                 ORDER BY s.id DESC LIMIT 1) AS logged_title,
                links.patterns_json, links.reviewed_at
            FROM (SELECT DISTINCT exercise_template_id FROM logged_sets) ids
            LEFT JOIN hevy_exercise_cache cache ON cache.id = ids.exercise_template_id
            LEFT JOIN fatigue_relationships links ON links.exercise_template_id = ids.exercise_template_id
        """).fetchall()
    mains = main_patterns()
    result = []
    for row in rows:
        title = row["cached_title"] or row["logged_title"] or row["exercise_template_id"]
        muscle = (row["primary_muscle"] or "").lower().replace(" ", "_")
        suggested = [mains[title]] if title in mains else MUSCLE_SUGGESTIONS.get(muscle, [])
        result.append(dict(exercise_template_id=row["exercise_template_id"], title=title,
            suggested_patterns=list(suggested), patterns=json.loads(row["patterns_json"]) if row["reviewed_at"] else [],
            reviewed=row["reviewed_at"] is not None, reviewed_at=row["reviewed_at"]))
    return sorted(result, key=lambda item: (item["title"].casefold(), item["exercise_template_id"]))


def save(exercise_id, patterns):
    if len(set(patterns)) != len(patterns) or any(p not in PATTERNS for p in patterns):
        raise ValueError("Choose each supported pattern at most once.")
    ordered = [p for p in PATTERNS if p in patterns]
    with closing(get_db()) as conn, conn:
        if not conn.execute("SELECT 1 FROM logged_sets WHERE exercise_template_id = ? LIMIT 1", (exercise_id,)).fetchone():
            raise LookupError("This exercise has no local set history.")
        conn.execute("""INSERT INTO fatigue_relationships (exercise_template_id, patterns_json, reviewed_at)
            VALUES (?, ?, ?) ON CONFLICT(exercise_template_id) DO UPDATE SET
            patterns_json=excluded.patterns_json, reviewed_at=excluded.reviewed_at""",
            (exercise_id, json.dumps(ordered), datetime.now(timezone.utc).isoformat()))
    return next(item for item in list_relationships() if item["exercise_template_id"] == exercise_id)
