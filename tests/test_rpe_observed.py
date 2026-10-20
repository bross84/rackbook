"""Tests for rpe_observed: your own logged sets turned into an RPE table, with estimated cells once there is enough data."""
import os
import shutil
import sys
import tempfile
import unittest
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)

_IMPORT_DIR = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(_IMPORT_DIR, "import.db"))

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import rpe_observed  # noqa: E402
import set_log  # noqa: E402
import training_max  # noqa: E402
from exercise_state import LB_PER_KG  # noqa: E402

DAY1 = "2026-10-16T00:25:31.873Z"
DAY2 = "2026-10-18T00:25:31.873Z"
DAY3 = "2026-10-20T00:10:00.000Z"
DAY4 = "2026-10-23T00:10:00.000Z"
ANCHOR_KG = 160.0
SHAPES = [(1, 7.0), (5, 5.0), (5, 6.5), (5, 7.5), (3, 8.0)]   # k = 4, 10, 8.5, 7.5, 5


def ts(set_at, e1rm_kg=ANCHOR_KG):
    return {"e1rm_lb": e1rm_kg * LB_PER_KG, "set_at": set_at}


def S(weight_kg, reps, rpe, start=DAY1, set_type="normal", is_ts=0):
    return {"weight_kg": weight_kg, "reps": reps, "rpe": rpe, "set_type": set_type, "is_ts": is_ts, "workout_start": start}


def chart(rpe, reps):
    return {(7.0, 5): 0.80}.get((rpe, reps))


def line(slope):
    return lambda k: 1 - slope * (k - 1)


def _synthetic(e1rm_kg, f, shapes, start):
    """Sets that follow the share curve f(k) exactly, one per (reps, rpe)."""
    return [S(round(e1rm_kg * f(reps + 10 - rpe), 4), reps, rpe, start=start) for reps, rpe in shapes]


def _three_workouts(f=line(0.03)):
    return _synthetic(150.0, f, SHAPES, DAY1) + _synthetic(155.0, f, SHAPES, DAY2) + _synthetic(152.0, f, SHAPES, DAY3)


def _cell(out, rpe, reps):
    return next((c for c in out["cells"] if (c["rpe"], c["reps"]) == (rpe, reps)), None)


def _est(out, rpe, reps):
    return next((c for c in out["estimated"] if (c["rpe"], c["reps"]) == (rpe, reps)), None)


class TestBuildObserved(unittest.TestCase):

    def test_a_cell_is_a_set_s_share_of_its_workouts_fitted_e1rm_and_never_uses_the_table(self):
        garbage = lambda rpe, reps: 0.5   # a table that is nonsense: the cells must not care
        out = rpe_observed.build_observed(_synthetic(150.0, line(0.03), SHAPES, DAY1), [], garbage)
        single = _cell(out, 7.0, 1)
        self.assertAlmostEqual(line(0.03)(4), single["observed"], delta=0.005)
        self.assertEqual(0.5, single["chart"])   # only reported beside the value

    def test_sets_at_the_same_rpe_and_reps_are_averaged_and_counted(self):
        sets = _synthetic(150.0, line(0.03), SHAPES, DAY1) + _synthetic(155.0, line(0.03), SHAPES, DAY2)
        cell = _cell(rpe_observed.build_observed(sets, [], chart), 6.5, 5)
        self.assertEqual(2, cell["n"])
        self.assertAlmostEqual(line(0.03)(8.5), cell["observed"], delta=0.005)

    def test_the_ts_is_an_ordinary_set_that_is_counted_and_flagged(self):
        sets = _synthetic(150.0, line(0.03), SHAPES, DAY1)
        sets[0]["is_ts"] = 1   # the 1 @7
        out = rpe_observed.build_observed(sets, [], chart)
        single = _cell(out, 7.0, 1)
        self.assertEqual((1, 1), (single["n"], single["ts"]))
        self.assertEqual((5, 1), (out["sets_used"], out["ts_sets"]))

    def test_warmups_and_dropsets_are_left_out(self):
        sets = _synthetic(150.0, line(0.03), SHAPES, DAY1) + [S(60, 5, 7.0, set_type="warmup"), S(100, 5, 7.0, set_type="dropset")]
        self.assertEqual(5, rpe_observed.build_observed(sets, [], chart)["sets_used"])

    def test_sets_missing_a_weight_reps_or_rpe_are_left_out(self):
        sets = _synthetic(150.0, line(0.03), SHAPES, DAY1) + [S(None, 5, 7.0), S(100, None, 7.0), S(100, 5, None), S(0, 5, 7.0)]
        self.assertEqual(5, rpe_observed.build_observed(sets, [], chart)["sets_used"])

    def test_without_a_workout_that_spans_two_efforts_there_are_no_cells_but_the_gate_still_counts(self):
        out = rpe_observed.build_observed([S(128, 5, 7.0)], [], chart)
        self.assertEqual(([], []), (out["cells"], out["estimated"]))
        self.assertEqual((False, 1, 1), (out["gate"]["passed"], out["gate"]["sets"], out["gate"]["workouts"]))

    def test_cells_run_from_the_highest_rpe_down_then_by_reps(self):
        out = rpe_observed.build_observed(_synthetic(150.0, line(0.03), SHAPES, DAY1), [], chart)
        self.assertEqual([(8.0, 3), (7.5, 5), (7.0, 1), (6.5, 5), (5.0, 5)], [(c["rpe"], c["reps"]) for c in out["cells"]])


class TestTheGate(unittest.TestCase):

    def test_two_workouts_of_five_sets_are_not_enough(self):
        sets = _synthetic(150.0, line(0.03), SHAPES, DAY1) + _synthetic(155.0, line(0.03), SHAPES, DAY2)
        out = rpe_observed.build_observed(sets, [], chart)
        gate = out["gate"]
        self.assertFalse(gate["passed"])
        self.assertEqual((10, 15, 2, 3), (gate["sets"], gate["min_sets"], gate["workouts"], gate["min_workouts"]))
        self.assertEqual([], out["estimated"])

    def test_fifteen_sets_from_three_workouts_spanning_four_reps_of_effort_pass(self):
        gate = rpe_observed.build_observed(_three_workouts(), [], chart)["gate"]
        self.assertTrue(gate["passed"])
        self.assertEqual((15, 3), (gate["sets"], gate["workouts"]))
        self.assertAlmostEqual(6.0, gate["k_span"])

    def test_a_narrow_spread_of_effort_does_not_pass_however_many_sets(self):
        narrow = [(5, 7.0), (5, 7.5), (5, 8.0), (4, 7.0), (6, 8.0)]   # k from 8 to 8.5 or so
        sets = _synthetic(150.0, line(0.03), narrow, DAY1) + _synthetic(155.0, line(0.03), narrow, DAY2) + _synthetic(152.0, line(0.03), narrow, DAY3)
        out = rpe_observed.build_observed(sets, [], chart)
        self.assertEqual(15, out["gate"]["sets"])
        self.assertLess(out["gate"]["k_span"], rpe_observed.MIN_K_SPAN)
        self.assertFalse(out["gate"]["passed"])


class TestEstimatedCells(unittest.TestCase):

    def setUp(self):
        self.out = rpe_observed.build_observed(_three_workouts(), [], chart)

    def test_a_cell_you_have_not_hit_is_estimated_from_sets_at_nearby_efforts(self):
        # 5 @8 is k = 7: nobody logged it, but k = 5 (3 @8) and k = 7.5 (5 @7.5) bracket it
        est = _est(self.out, 8.0, 5)
        self.assertIsNotNone(est)
        low, high = _cell(self.out, 7.5, 5)["observed"], _cell(self.out, 8.0, 3)["observed"]
        self.assertGreater(est["estimated"], low)
        self.assertLess(est["estimated"], high)
        self.assertAlmostEqual(line(0.03)(7), est["estimated"], delta=0.01)

    def test_a_cell_that_shares_an_effort_with_logged_sets_is_estimated_from_them(self):
        # 8 @10 is also k = 8, the same effort as 5 @7: nothing logged there, but the effort is measured
        est = _est(self.out, 10.0, 8)
        self.assertIsNotNone(est)
        self.assertAlmostEqual(line(0.03)(8), est["estimated"], delta=0.01)

    def test_cells_with_logged_sets_are_not_estimated_too(self):
        observed = {(c["rpe"], c["reps"]) for c in self.out["cells"]}
        self.assertFalse(observed & {(c["rpe"], c["reps"]) for c in self.out["estimated"]})

    def test_nothing_is_estimated_beyond_the_hardest_or_easiest_effort_logged(self):
        self.assertIsNone(_est(self.out, 5.0, 6))      # k = 11, past the easiest logged (10)
        self.assertIsNone(_est(self.out, 5.0, 12))
        self.assertIsNotNone(_est(self.out, 10.0, 1))  # k = 1: the RPE 10 single, pinned at 100%

    def test_the_rpe_10_single_is_pinned_at_100_percent(self):
        self.assertAlmostEqual(1.0, _est(self.out, 10.0, 1)["estimated"])

    def test_estimates_never_rise_as_the_effort_gets_easier(self):
        by_k = sorted((c["reps"] + 10 - c["rpe"], c["estimated"]) for c in self.out["estimated"])
        values = [v for _, v in by_k]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_the_table_in_use_has_no_say_in_the_estimates(self):
        a = rpe_observed.build_observed(_three_workouts(), [], lambda rpe, reps: 0.1)
        b = rpe_observed.build_observed(_three_workouts(), [], lambda rpe, reps: 0.99)
        self.assertEqual([(c["rpe"], c["reps"], c["estimated"]) for c in a["estimated"]],
                         [(c["rpe"], c["reps"], c["estimated"]) for c in b["estimated"]])

    def test_a_curve_that_is_not_a_straight_line_is_followed_not_flattened(self):
        # steep over the first three reps of effort, gentler after: 100% at k=1, 85% at k=4, 82% at k=5, 67% at k=10
        bent = lambda k: 1 - 0.05 * (k - 1) if k <= 4 else 0.85 - 0.03 * (k - 4)
        out = rpe_observed.build_observed(_three_workouts(bent), [], chart)
        k4, k5, k10 = _cell(out, 7.0, 1)["observed"], _cell(out, 8.0, 3)["observed"], _cell(out, 5.0, 5)["observed"]
        # the scale is only fixed up to a constant, so check the ratios between cells, which it cannot touch
        self.assertAlmostEqual(0.82 / 0.85, k5 / k4, delta=0.01)
        self.assertAlmostEqual(0.67 / 0.85, k10 / k4, delta=0.01)

    def test_no_estimates_until_the_gate_is_passed(self):
        out = rpe_observed.build_observed(_synthetic(150.0, line(0.03), SHAPES, DAY1), [], chart)
        self.assertEqual([], out["estimated"])


class TestFitCurve(unittest.TestCase):

    def test_it_recovers_the_slope_and_each_workouts_e1rm_without_using_the_table(self):
        sets = _synthetic(150.0, line(0.03), SHAPES[:4], DAY1) + _synthetic(155.0, line(0.03), SHAPES[:4], DAY3)
        out = rpe_observed.fit_curve(sets, [ts(DAY1), ts(DAY3)], chart)
        self.assertAlmostEqual(0.03, out["slope"], places=3)
        by = {s["workout_start"]: s for s in out["sessions"]}
        self.assertAlmostEqual(150.0 * LB_PER_KG, by[DAY1]["e1rm_lb"], delta=1.0)
        self.assertAlmostEqual(155.0 * LB_PER_KG, by[DAY3]["e1rm_lb"], delta=1.0)
        self.assertEqual((2, 8), (out["informative_sessions"], out["sets_fitted"]))
        self.assertLess(out["rms_error"], 0.001)

    def test_the_ts_single_counts_like_any_other_set(self):
        sets = _synthetic(150.0, line(0.03), SHAPES[:4], DAY1)
        sets[0]["is_ts"] = 1   # the 1 @7
        self.assertEqual(4, rpe_observed.fit_curve(sets, [ts(DAY1)], chart)["sets_fitted"])

    def test_a_workout_with_every_set_at_one_k_does_not_pin_the_slope_but_still_gets_an_e1rm(self):
        same_k = _synthetic(150.0, line(0.03), [(5, 7.0), (3, 5.0), (7, 9.0)], DAY1)   # k is 8 for all three
        varied = _synthetic(150.0, line(0.03), SHAPES[:4], DAY3)
        out = rpe_observed.fit_curve(same_k + varied, [], chart)
        self.assertEqual(1, out["informative_sessions"])
        self.assertAlmostEqual(0.03, out["slope"], places=3)
        self.assertEqual(2, len(out["sessions"]))

    def test_no_workout_with_two_different_k_means_no_fit(self):
        self.assertIsNone(rpe_observed.fit_curve([S(128, 5, 7.0)], [], chart))
        self.assertIsNone(rpe_observed.fit_curve([], [], chart))

    def test_warmups_and_dropsets_do_not_enter_the_fit(self):
        sets = _synthetic(150.0, line(0.03), SHAPES[:4], DAY1) + [S(30, 12, 3.0, set_type="warmup"), S(60, 12, 4.0, set_type="dropset")]
        self.assertEqual(4, rpe_observed.fit_curve(sets, [ts(DAY1)], chart)["sets_fitted"])

    def test_the_table_in_use_is_reported_beside_the_fit(self):
        sets = _synthetic(150.0, line(0.03), SHAPES[:4], DAY1)
        full = lambda rpe, reps: {(10.0, 2): 0.96, (10.0, 10): 0.746}.get((rpe, reps))
        out = rpe_observed.fit_curve(sets, [ts(DAY1, 148.0)], full)
        self.assertAlmostEqual((0.96 - 0.746) / 8, out["table_slope"])
        self.assertAlmostEqual(148.0 * LB_PER_KG, out["sessions"][0]["table_e1rm_lb"], places=3)


class TestObservedRoutes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["DB_PATH"] = os.path.join(self.tmp, "test.db")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def _log(self, template, title, sets, start=DAY1):
        entry = {"title": "Day", "start_time": start, "end_time": start,
                 "exercises": [{"exercise_template_id": template, "title": title, "sets": sets}]}
        set_log.record(set_log.rows_from_entry(entry, "h1"))
        if title == "Squat, Low Bar w/ Belt":
            from contextlib import closing
            from database import get_db
            with closing(get_db()) as conn, conn:
                conn.execute("INSERT INTO rpe_chart_assignments VALUES (?, 'squat', 1) ON CONFLICT DO NOTHING", (template,))

    def test_lists_squat_bench_and_deadlift_with_what_is_logged_for_each(self):
        self._log("tpl-squat", "Squat, Low Bar w/ Belt", [
            {"type": "warmup", "weight_kg": 60, "reps": 5, "rpe": None},
            {"type": "normal", "weight_kg": 120, "reps": 5, "rpe": 5},
            {"type": "normal", "weight_kg": 128, "reps": 5, "rpe": 7},
        ])
        self._log("tpl-row", "Pendlay Row (Barbell)", [{"type": "normal", "weight_kg": 80, "reps": 5, "rpe": 7}])   # not a main lift: not listed
        got = self.client.get("/rpe-observed").json()
        self.assertEqual(["squat", "bench", "deadlift", "general"], [l["key"] for l in got])
        self.assertEqual(("tpl-squat", 2, 1), (got[0]["exercise_template_id"], got[0]["sets"], got[0]["sessions"]))
        self.assertEqual((None, 0, 0), (got[1]["exercise_template_id"], got[1]["sets"], got[1]["sessions"]))   # nothing logged yet

    def test_a_squat_logged_without_an_rpe_does_not_count(self):
        self._log("tpl-squat", "Squat, Low Bar w/ Belt", [{"type": "normal", "weight_kg": 120, "reps": 5, "rpe": None}])
        self.assertIsNone(self.client.get("/rpe-observed").json()[0]["exercise_template_id"])

    def test_the_table_for_a_movement_has_cells_the_gate_and_the_fit(self):
        self._log("tpl-squat", "Squat", [
            {"type": "normal", "weight_kg": 145, "reps": 1, "rpe": 7, "ts": True},
            {"type": "normal", "weight_kg": 130, "reps": 5, "rpe": 7.5},
            {"type": "normal", "weight_kg": 120, "reps": 5, "rpe": 5},
        ])
        r = self.client.get("/rpe-observed/tpl-squat")
        self.assertEqual(200, r.status_code, r.text)
        body = r.json()
        self.assertEqual(("Squat", 3, 1), (body["title"], body["sets_used"], body["ts_sets"]))
        self.assertEqual(3, len(body["cells"]))
        self.assertIsNotNone(next(c["chart"] for c in body["cells"] if (c["rpe"], c["reps"]) == (7.5, 5)))   # the table in use, beside it
        self.assertEqual((False, 3, 1), (body["gate"]["passed"], body["gate"]["sets"], body["gate"]["workouts"]))
        self.assertEqual([], body["estimated"])
        self.assertIsNotNone(body["fit"])

    def test_an_unknown_movement_is_just_empty(self):
        body = self.client.get("/rpe-observed/nope").json()
        self.assertEqual((None, 0, [], False, None), (body["title"], body["sets_used"], body["cells"], body["gate"]["passed"], body["fit"]))


if __name__ == "__main__":
    unittest.main()
