"""Tests for progress: per-session e1RM from Hevy history, joined to smoothed bodyweight and DOTS."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from progress import LIFT_TITLES, build_series, e1rm_by_session  # noqa: E402
from strength_score import dots_score  # noqa: E402

PCT = {(8.0, 5): 0.8, (10.0, 5): 0.86}


def pct(rpe, reps):
    return PCT.get((rpe, reps))


def entry(workout, start, kg, reps, rpe, set_type="normal"):
    return {"workout_id": workout, "workout_start_time": start, "set_type": set_type,
            "weight_kg": kg, "reps": reps, "rpe": rpe}


class E1rmBySessionTest(unittest.TestCase):
    def test_one_point_per_workout_oldest_first(self):
        entries = [  # Hevy sends newest first
            entry("w2", "2026-10-09T17:00:00+00:00", 100, 5, 10),
            entry("w1", "2026-09-30T17:00:00+00:00", 90, 5, 8),
        ]
        out = e1rm_by_session(entries, pct)
        self.assertEqual([p["date"] for p in out], ["2026-09-30", "2026-10-09"])
        self.assertGreater(out[1]["e1rm_lb"], out[0]["e1rm_lb"])

    def test_uses_the_best_working_set_and_ignores_warmups(self):
        entries = [
            entry("w1", "2026-10-09T17:00:00+00:00", 150, 5, 10, "warmup"),
            entry("w1", "2026-10-09T17:00:00+00:00", 90, 5, 8),
            entry("w1", "2026-10-09T17:00:00+00:00", 100, 5, 10),
        ]
        out = e1rm_by_session(entries, pct)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["e1rm_lb"], 100 * 2.2 / 0.86, delta=3)

    def test_sessions_without_an_rpe_are_skipped(self):
        entries = [entry("w1", "2026-10-09T17:00:00+00:00", 100, 5, None)]
        self.assertEqual(e1rm_by_session(entries, pct), [])

    def test_no_history(self):
        self.assertEqual(e1rm_by_session([], pct), [])


class BuildSeriesTest(unittest.TestCase):
    MEASUREMENTS = [{"date": f"2026-10-0{d}", "weight_kg": 80.0} for d in range(1, 8)]

    def test_joins_smoothed_bodyweight_and_dots(self):
        out = build_series([{"date": "2026-10-07", "e1rm_lb": 220.462}], self.MEASUREMENTS)
        self.assertEqual(out[0]["bodyweight_lb"], round(80 * 2.20462, 1))
        self.assertAlmostEqual(out[0]["dots"], round(dots_score(100.0, 80.0), 1), places=1)

    def test_session_before_first_weigh_in_has_no_bodyweight_or_score(self):
        out = build_series([{"date": "2026-09-01", "e1rm_lb": 200.0}], self.MEASUREMENTS)
        self.assertEqual(out[0]["e1rm_lb"], 200.0)
        self.assertIsNone(out[0]["bodyweight_lb"])
        self.assertIsNone(out[0]["dots"])

    def test_session_a_few_days_after_the_last_weigh_in_uses_the_latest_reading(self):
        out = build_series([{"date": "2026-10-10", "e1rm_lb": 200.0}], self.MEASUREMENTS)
        self.assertEqual(out[0]["bodyweight_lb"], round(80 * 2.20462, 1))

    def test_session_long_after_the_last_weigh_in_gets_no_score(self):
        out = build_series([{"date": "2026-11-01", "e1rm_lb": 200.0}], self.MEASUREMENTS)
        self.assertIsNone(out[0]["bodyweight_lb"])
        self.assertIsNone(out[0]["dots"])

    def test_losing_weight_raises_the_score_for_the_same_lift(self):
        heavy = [{"date": "2026-01-01", "weight_kg": 90.0}]
        light = [{"date": "2026-01-01", "weight_kg": 77.0}]
        session = [{"date": "2026-01-02", "e1rm_lb": 250.0}]
        self.assertGreater(build_series(session, light)[0]["dots"], build_series(session, heavy)[0]["dots"])

    def test_provenance_boundaries_and_no_future_measurements(self):
        measurements = [{"date": "2025-07-26", "weight_kg": 80},
                        {"date": "2025-08-01", "weight_kg": 90},
                        {"date": "2025-08-20", "weight_kg": 70}]
        dates = ["2025-07-25", "2025-08-01", "2025-08-12", "2025-08-15", "2025-08-16"]
        out = build_series([{"date": d, "e1rm_lb": 300} for d in dates], measurements)
        for i in [0, 4]:
            for key in ["bodyweight_lb", "dots", "bodyweight_source_date", "bodyweight_age_days", "bodyweight_weigh_in_count"]:
                self.assertIsNone(out[i][key])
        for i, age in [(1, 0), (2, 11), (3, 14)]:
            self.assertEqual(out[i]["bodyweight_source_date"], "2025-08-01")
            self.assertEqual(out[i]["bodyweight_age_days"], age)
            self.assertEqual(out[i]["bodyweight_weigh_in_count"], 2)
            self.assertEqual(out[i]["bodyweight_lb"], round(85 * 2.20462, 1))

    def test_requested_comparison(self):
        measurements = [{"date": "2025-08-01", "weight_kg": 188.5 / 2.20462},
                        {"date": "2026-10-16", "weight_kg": 169.8 / 2.20462}]
        out = build_series([{"date": d, "e1rm_lb": 300} for d in ["2025-08-12", "2026-10-16"]], measurements)
        self.assertEqual([p["bodyweight_lb"] for p in out], [188.5, 169.8])
        self.assertEqual(out[0]["bodyweight_age_days"], 11)
        self.assertEqual(out[1]["bodyweight_age_days"], 0)
        self.assertEqual(round((169.8 / 188.5 - 1) * 100, 1), -9.9)
        self.assertEqual(build_series([], measurements), [])
        self.assertIsNone(build_series([{"date": "2025-01-01", "e1rm_lb": 300}], [])[0]["bodyweight_source_date"])

    def test_the_four_lifts_are_defined(self):
        self.assertEqual(set(LIFT_TITLES), {"squat", "bench", "deadlift", "press"})


if __name__ == "__main__":
    unittest.main()
