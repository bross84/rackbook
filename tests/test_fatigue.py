import unittest
from datetime import datetime, timedelta, timezone
from fatigue import analyze

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def data(values, *, soreness=0, sets=4, bodyweight=True, spacing=3):
    ts, rows, obs, weights = [], [], [], []
    first = NOW - timedelta(days=spacing * (len(values)-1))
    for i, value in enumerate(values):
        at = first + timedelta(days=spacing*i)
        stamp = at.isoformat()
        ts.append(dict(set_at=stamp, e1rm_lb=value, reps=1, rpe=8))
        count = sets[i] if isinstance(sets, list) else sets
        for j in range(count):
            rows.append(dict(workout_start=stamp, hevy_workout_id=str(i), set_type="normal", reps=1 if j==0 else 5, rpe=8 if j==0 else 7))
        obs.append(dict(hevy_workout_id=str(i), squat=soreness, squat_pain=0))
    if bodyweight:
        for days in range(-6, spacing*(len(values)-1)+1):
            weights.append(dict(date=(first+timedelta(days=days)).date().isoformat(), weight_kg=90))
    return ts, rows, obs, weights


class FatigueRulesCase(unittest.TestCase):
    def assess(self, args):
        return analyze(*args, pattern="squat", now=NOW, relationships={"__target__":["squat"]})

    def test_need_twelve_comparable_ts_not_best_sets(self):
        args = data([300]*11)
        self.assertEqual(self.assess(args)["action"], "collect")
        args[0].clear()
        self.assertEqual(self.assess(args)["comparable_sessions"], 0)

    def test_stable_low_soreness_can_trial_one_set(self):
        result = self.assess(data([300]*12))
        self.assertEqual((result["status"], result["action"]), ("stable", "try_set"))
        self.assertEqual(result["e1rm_change_pct"], 0)

    def test_improving_holds_volume(self):
        self.assertEqual(self.assess(data([300]*6+[315]*6))["action"], "hold")

    def test_single_bad_session_does_not_trigger_decline(self):
        self.assertNotEqual(self.assess(data([300]*11+[270]))["status"], "declining")

    def test_repeated_decline_and_soreness_reduces_backoff(self):
        result = self.assess(data([300]*6+[285]*6, soreness=2))
        self.assertEqual((result["status"], result["action"]), ("declining", "reduce_set"))
        self.assertAlmostEqual(result["e1rm_change_pct"], -5)

    def test_decline_low_soreness_reviews_reps_not_extra_sets(self):
        self.assertEqual(self.assess(data([300]*6+[285]*6))["action"], "review_reps")

    def test_no_backoff_to_remove(self):
        self.assertEqual(self.assess(data([300]*6+[285]*6, soreness=3, sets=1))["action"], "review_reps")

    def test_missing_bw_keeps_raw_history_without_interpretation(self):
        result = self.assess(data([300]*6+[285]*6, bodyweight=False))
        self.assertEqual((result["status"], result["action"]), ("building_baseline", "collect"))
        self.assertIsNone(result["bw_change_pct"])

    def test_stale_and_future_bw_not_carried_forward(self):
        args = data([300]*12, bodyweight=False)
        args[3].extend([dict(date=(NOW-timedelta(days=100)).date().isoformat(),weight_kg=90),
                        dict(date=(NOW+timedelta(days=1)).date().isoformat(),weight_kg=90)])
        self.assertTrue(all(p["bodyweight_kg"] is None for p in self.assess(args)["points"]))

    def test_bw_loss_context_does_not_erase_absolute_decline(self):
        args = data([300]*6+[285]*6)
        cutoff = (NOW-timedelta(days=18)).date().isoformat()
        for row in args[3]:
            if row["date"] > cutoff:
                row["weight_kg"] = 80
        result = self.assess(args)
        self.assertEqual((result["status"],result["action"]),("declining","review_bw"))
        self.assertGreater(result["relative_change_pct"],0)

    def test_missing_soreness_not_zero(self):
        args = data([300]*12); args[2].clear()
        self.assertEqual(self.assess(args)["action"], "collect")
        self.assertIsNone(self.assess(args)["recent_soreness"])

    def test_pain_separate_and_blocks_progression(self):
        args = data([300]*12); args[2][-1]["squat_pain"] = 1
        self.assertEqual(self.assess(args)["action"], "review_pain")
        args[2][-1]["squat_pain"] = 0; args[2][-2]["squat_pain"] = 1
        self.assertEqual(self.assess(args)["action"], "review_pain")

    def test_21_day_gap_resets_baseline_even_without_ts(self):
        args = data([300]*12)
        args[1].append(dict(workout_start=(NOW+timedelta(days=21)).isoformat(),hevy_workout_id="new",set_type="normal",reps=5,rpe=7))
        result = analyze(*args, pattern="squat", now=NOW+timedelta(days=21))
        self.assertTrue(result["gap_reset"])
        self.assertEqual(result["comparable_sessions"],0)
        self.assertEqual(len(result["points"]),13)

    def test_current_inactivity_resets(self):
        result = analyze(*data([300]*12),pattern="squat",now=NOW+timedelta(days=21))
        self.assertTrue(result["gap_reset"])
        self.assertEqual(result["comparable_sessions"],0)

    def test_changed_ts_rep_range_not_pooled(self):
        args = data([300]*12); args[0][-1]["reps"] = 3
        self.assertEqual(self.assess(args)["comparable_sessions"],1)

    def test_changed_ts_effort_not_pooled(self):
        args = data([300]*12); args[0][-1]["rpe"] = 6
        self.assertEqual(self.assess(args)["comparable_sessions"],1)

    def test_persistent_decline_after_set_reduction_can_flag_block(self):
        result = self.assess(data([320]*6+[300]*6+[280]*6, sets=[5]*12+[4]*6))
        self.assertEqual(result["action"],"consider_block")

    def test_persistent_decline_without_changes_reviews_reps_first(self):
        self.assertEqual(self.assess(data([320]*6+[300]*6+[280]*6))["action"],"review_reps")

    def test_unknown_mapping_no_soreness_inference(self):
        self.assertEqual(analyze(*data([300]*12),pattern=None,now=NOW)["action"],"collect")

    def test_unknown_set_history_blocks_suggestions(self):
        args=data([300]*12); args[1].clear()
        self.assertEqual(self.assess(args)["action"],"collect")

    def test_warmups_future_sessions_and_duplicate_ts_excluded(self):
        args=data([300]*12)
        args[0].append(args[0][-1].copy())
        args[0].append(dict(set_at=(NOW+timedelta(days=1)).isoformat(),e1rm_lb=600,reps=1,rpe=8))
        args[1].append(dict(workout_start=NOW.isoformat(),set_type="warmup",reps=5,rpe=5))
        result=self.assess(args)
        self.assertEqual(result["comparable_sessions"],12)
        self.assertEqual(result["recent_sets"],4)

    def test_extra_set_trial_requires_stable_reps_effort_and_frequency(self):
        for kind in ("reps", "rpe"):
            args=data([300]*12)
            for row in args[1][-24:]:
                row[kind] = 10 if kind=="reps" else 9
            self.assertEqual(self.assess(args)["action"],"hold")
        args=data([300]*12)
        args[1].append(dict(workout_start=(NOW-timedelta(days=1)).isoformat(),hevy_workout_id="extra",set_type="normal",reps=5,rpe=7))
        # Missing new-session soreness blocks any progression as well.
        self.assertNotEqual(self.assess(args)["action"],"try_set")

    def test_latest_pattern_pain_on_another_workout_blocks_progression(self):
        args=data([300]*12)
        args[2].append(dict(hevy_workout_id="other",workout_start=(NOW+timedelta(hours=1)).isoformat(),squat_pain=1,squat=None))
        result=analyze(*args,pattern="squat",now=NOW+timedelta(hours=2))
        self.assertEqual(result["action"],"review_pain")

    def test_six_sessions_have_charts_but_no_verdict_or_suggestion(self):
        result=self.assess(data([300]*3+[270]*3, soreness=3))
        self.assertEqual(result["status"],"building_baseline")
        self.assertEqual(result["action"],"collect")
        self.assertIsNone(result["e1rm_change_pct"])
        self.assertIsNone(result["bw_change_pct"])
        self.assertFalse(result["collection"]["ready"])
        self.assertEqual(result["collection"]["sessions"],6)
        self.assertEqual(result["collection"]["required_sessions"],12)
        self.assertEqual(len(result["points"]),6)
        self.assertTrue(all(p["e1rm_lb"] is not None for p in result["points"]))

    def test_no_minimum_week_wait_when_twelve_sessions_are_complete(self):
        result=self.assess(data([300]*12,spacing=1))
        self.assertTrue(result["collection"]["ready"])
        self.assertEqual(result["action"],"try_set")

    def test_long_elapsed_time_does_not_replace_session_count(self):
        result=self.assess(data([300]*6,spacing=10))
        self.assertEqual(result["action"],"collect")
        self.assertFalse(result["collection"]["ready"])

    def test_old_ts_with_only_recent_soreness_does_not_unlock(self):
        args=data([300]*12)
        del args[2][:-3]
        result=self.assess(args)
        self.assertEqual(result["status"],"building_baseline")
        self.assertFalse(result["collection"]["ready"])
        self.assertEqual(result["collection"]["previous_paired"],0)
        self.assertEqual(result["collection"]["recent_paired"],3)

    def test_five_paired_in_each_half_required(self):
        args=data([300]*12)
        args[2][0]["squat"]=None
        args[2][6]["squat"]=None
        result=self.assess(args)
        self.assertTrue(result["collection"]["ready"])
        self.assertEqual(result["collection"]["previous_paired"],5)
        self.assertEqual(result["collection"]["recent_paired"],5)
        args[2][1]["squat"]=None
        result=self.assess(args)
        self.assertFalse(result["collection"]["ready"])
        self.assertEqual(result["status"],"building_baseline")

    def test_partial_set_rpe_is_not_complete_observation(self):
        args=data([300]*12)
        args[1][0]["rpe"]=None
        args[1][4]["rpe"]=None
        result=self.assess(args)
        self.assertEqual(result["collection"]["previous_paired"],4)
        self.assertFalse(result["collection"]["ready"])

    def test_first_session_pain_flag_is_not_delayed_by_collection(self):
        args=data([300])
        args[2][0]["squat_pain"]=1
        result=self.assess(args)
        self.assertEqual(result["action"],"review_pain")
        self.assertFalse(result["collection"]["ready"])
        self.assertIsNone(result["e1rm_change_pct"])

    def test_return_after_gap_restarts_count_but_keeps_chart_points(self):
        args=data([300]*12)
        stamp=(NOW+timedelta(days=21)).isoformat()
        args[0].append(dict(set_at=stamp,e1rm_lb=280,reps=1,rpe=8))
        result=analyze(*args,pattern="squat",now=NOW+timedelta(days=21))
        self.assertEqual(result["collection"]["sessions"],1)
        self.assertEqual(len(result["points"]),13)
        self.assertFalse(result["collection"]["ready"])
