import unittest
from datetime import datetime, timedelta

from fatigue import analyze
from tests.test_fatigue import NOW, data


def related(at, count=4, exercise="leg", workout=None, kind="normal"):
    return [dict(workout_start=at.isoformat(), exercise_template_id=exercise,
                 exercise_title=exercise.title(), hevy_workout_id=workout or exercise + at.isoformat(),
                 set_type=kind, reps=10, rpe=8) for _ in range(count)]


class FatigueContextCase(unittest.TestCase):
    def assess(self, args, extra=(), *, now=NOW, links=None):
        return analyze(*args, now=now, pattern="squat", exercise_template_id="target",
                       all_sets=[dict(row, exercise_template_id="target") for row in args[1]] + list(extra),
                       relationships=links if links is not None else {"target": ["squat"], "leg": ["squat"]})

    def test_regular_spacing_and_zero_known_related_work_preserves_trial(self):
        result = self.assess(data([300] * 12))
        self.assertEqual(result["action"], "try_set")
        self.assertTrue(result["context"]["extra_sets_eligible"])
        self.assertEqual(result["context"]["reference_exercise_days"], 3)
        self.assertEqual(result["context"]["reference_related_sets_7"], 0)
        self.assertIsNone(result["points"][0]["days_since_exercise"])

    def test_weekly_movement_has_its_own_reference(self):
        result = self.assess(data([300] * 12, spacing=7))
        self.assertEqual(result["action"], "try_set")
        self.assertEqual(result["context"]["reference_exercise_days"], 7)

    def test_unchanged_confirmed_related_work_preserves_trial(self):
        args = data([300] * 12)
        extra = []
        for point in args[0]:
            extra += related(datetime.fromisoformat(point["set_at"]) - timedelta(days=1))
        result = self.assess(args, extra)
        self.assertEqual(result["action"], "try_set")
        self.assertEqual(result["context"]["reference_pattern_days"], 1)
        self.assertEqual(result["context"]["reference_related_sets_7"], result["context"]["recent_related_sets_7"])

    def test_single_eight_day_gap_blocks_even_with_normal_recent_median(self):
        args = data([300] * 12)
        later = NOW + timedelta(days=5)
        args[0][-1]["set_at"] = later.isoformat()
        for row in args[1][-4:]:
            row["workout_start"] = later.isoformat()
        args[3].extend(dict(date=(NOW + timedelta(days=d)).date().isoformat(), weight_kg=90) for d in range(1, 6))
        result = self.assess(args, now=later)
        self.assertEqual(result["status"], "stable")
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["context"]["latest_exercise_days"], 8)
        self.assertEqual(result["context"]["recent_exercise_days"], 3)
        self.assertTrue(any("Exact-exercise" in reason for reason in result["context"]["block_reasons"]))

    def test_current_break_prevents_stale_add_advice(self):
        result = self.assess(data([300] * 12), now=NOW + timedelta(days=8))
        self.assertEqual(result["action"], "hold")
        self.assertTrue(result["collection"]["ready"])
        self.assertTrue(any("current break" in reason for reason in result["context"]["block_reasons"]))

    def test_recent_group_spacing_change_is_checked_when_latest_gap_is_normal(self):
        args = data([300] * 12)
        intervals = [3] * 5 + [5] * 5 + [3]
        times = [NOW]
        for gap in reversed(intervals):
            times.append(times[-1] - timedelta(days=gap))
        times.reverse()
        replacements = {row["set_at"]: at.isoformat() for row, at in zip(args[0], times)}
        for row in args[0]:
            row["set_at"] = replacements[row["set_at"]]
        for row in args[1]:
            row["workout_start"] = replacements[row["workout_start"]]
        args[3][:] = [dict(date=(NOW-timedelta(days=d)).date().isoformat(), weight_kg=90) for d in range(51)]
        result = self.assess(args)
        self.assertEqual(result["context"]["latest_exercise_days"], 3)
        self.assertEqual(result["context"]["recent_exercise_days"], 5)
        self.assertEqual(result["action"], "hold")

    def test_current_tolerance_is_strict_and_exact(self):
        args = data([300] * 12)
        self.assertEqual(self.assess(args, now=NOW + timedelta(days=4))["action"], "try_set")
        self.assertEqual(self.assess(args, now=NOW + timedelta(days=4, seconds=1))["action"], "hold")

    def test_one_related_exposure_changes_latest_context_not_ts(self):
        result = self.assess(data([300] * 12), related(NOW - timedelta(days=1)))
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["context"]["latest_pattern_days"], 1)
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 4)
        self.assertEqual(result["points"][-1]["related_workouts_7_before"], 1)
        self.assertEqual(result["e1rm_change_pct"], 0)
        self.assertEqual(len(result["points"]), 12)

    def test_related_workload_drop_is_also_changed_context(self):
        args = data([300] * 12)
        extra = []
        for point in args[0][:6]:
            extra += related(datetime.fromisoformat(point["set_at"]) - timedelta(days=1))
        result = self.assess(args, extra)
        self.assertEqual(result["action"], "hold")
        self.assertGreater(result["context"]["reference_related_sets_7"], result["context"]["recent_related_sets_7"])
        self.assertTrue(any("workload differs" in reason for reason in result["context"]["block_reasons"]))

    def test_unreviewed_is_unknown_and_explicit_empty_is_not_related(self):
        args = data([300] * 12)
        extra = related(NOW - timedelta(days=1), exercise="unknown")
        result = self.assess(args, extra)
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["context"]["pending_mappings"], [dict(exercise_template_id="unknown", title="Unknown")])
        self.assertIsNone(result["points"][-1]["related_sets_7_before"])
        self.assertIsNone(result["points"][-1]["days_since_pattern"])
        result = self.assess(args, extra, links={"target": ["squat"], "unknown": []})
        self.assertEqual(result["action"], "try_set")
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 0)

    def test_main_lift_mapping_is_not_automatically_confirmed(self):
        result = self.assess(data([300] * 12), links={})
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["context"]["pending_mappings"][0]["exercise_template_id"], "target")

    def test_multi_pattern_assignment_counts_each_row_once(self):
        result = self.assess(data([300] * 12), related(NOW - timedelta(days=1)),
                             links={"target": ["squat"], "leg": ["squat", "deadlift"]})
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 4)
        self.assertEqual(result["points"][-1]["related_workouts_7_before"], 1)

    def test_two_related_exercises_in_one_workout_count_one_exposure(self):
        at = NOW - timedelta(days=1)
        extra = related(at, exercise="leg", workout="shared") + related(at, exercise="other", workout="shared")
        result = self.assess(data([300] * 12), extra,
                             links={"target": ["squat"], "leg": ["squat"], "other": ["squat"]})
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 8)
        self.assertEqual(result["points"][-1]["related_workouts_7_before"], 1)

    def test_new_related_work_after_latest_ts_blocks_trial(self):
        result = self.assess(data([300] * 12), related(NOW + timedelta(days=1)), now=NOW + timedelta(days=1))
        self.assertEqual(result["action"], "hold")
        self.assertTrue(result["context"]["additional_work_since_ts"])
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 0)

    def test_new_target_work_without_ts_also_blocks_trial(self):
        args = data([300] * 12)
        later = NOW + timedelta(days=1)
        args[1].extend(related(later, exercise="target", workout="new-target"))
        args[2].append(dict(hevy_workout_id="new-target", squat=0, squat_pain=0))
        result = self.assess(args, now=later)
        self.assertTrue(result["context"]["additional_work_since_ts"])
        self.assertEqual(result["action"], "hold")

    def test_future_warmup_and_assessed_workout_do_not_leak(self):
        extra = related(NOW + timedelta(days=1), exercise="future")
        extra += related(NOW - timedelta(days=1), exercise="warmup", kind="warmup")
        extra += related(NOW, exercise="leg")
        result = self.assess(data([300] * 12), extra)
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 0)
        self.assertEqual(result["points"][-1]["days_since_pattern"], 3)
        self.assertEqual(result["context"]["pending_mappings"], [])
        self.assertEqual(result["action"], "try_set")

    def test_exact_seven_day_boundary_is_counted_without_future_leakage(self):
        extra = related(NOW - timedelta(days=7), count=2)
        extra += related(NOW - timedelta(days=7, seconds=1), count=3)
        result = self.assess(data([300] * 12), extra)
        self.assertEqual(result["points"][-1]["related_sets_7_before"], 2)

    def test_decline_and_pain_actions_are_not_overridden(self):
        result = self.assess(data([300] * 6 + [280] * 6, soreness=3), links={})
        self.assertEqual(result["action"], "reduce_set")
        args = data([300] * 12)
        args[2][-1]["squat_pain"] = 1
        self.assertEqual(self.assess(args, links={})["action"], "review_pain")

    def test_unrelated_history_far_outside_comparison_does_not_block(self):
        extra = related(NOW - timedelta(days=100), exercise="old")
        self.assertEqual(self.assess(data([300] * 12), extra)["action"], "try_set")

    def test_initial_collection_and_gap_reset_still_work(self):
        result = self.assess(data([300]))
        self.assertFalse(result["collection"]["ready"])
        self.assertIsNone(result["context"]["reference_exercise_days"])
        self.assertEqual(result["action"], "collect")
        result = self.assess(data([300] * 12), now=NOW + timedelta(days=21))
        self.assertTrue(result["gap_reset"])
        self.assertEqual(result["action"], "collect")
