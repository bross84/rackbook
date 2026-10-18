"""Tests for workout_payload.build_hevy_workout — logged workout -> Hevy POST /v1/workouts body."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from workout_payload import build_hevy_workout


def _entry(**overrides):
    base = {
        "title": "BS-Bridge 1.3.3",
        "start_time": "2026-10-09T17:00:00Z",
        "end_time": "2026-10-09T18:00:00Z",
        "exercises": [
            {
                "exercise_template_id": "tpl-squat",
                "title": "Squat, Low Bar w/ Belt",
                "sets": [
                    {"type": "warmup", "weight_kg": 50, "reps": 5, "rpe": None},
                    {"type": "normal", "weight_kg": 120, "reps": 5, "rpe": 6},
                    {"type": "normal", "weight_kg": 127.5, "reps": 5, "rpe": 7},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


class TestWeight(unittest.TestCase):

    def _kg(self, typed):
        entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"weight_kg": typed, "reps": 5}]}])
        return build_hevy_workout(entry)["workout"]["exercises"][0]["sets"][0]["weight_kg"]

    def test_the_kg_you_enter_is_posted_as_it_is(self):
        # every step the app can plan: 0.5 kg for micro-loaded lifts up to 5 kg
        for kg in (0.5, 1, 1.25, 2.5, 5, 46.25, 47.5, 100, 0):
            self.assertEqual(float(kg), self._kg(kg), kg)

    def test_upload_preserves_precision_including_converted_pounds(self):
        for kg in (46.2500001,47.499,132.34 / 2.20462262185):
            self.assertEqual(kg,self._kg(kg))

    def test_rounds_whole_weights_in_selected_unit_with_half_up(self):
        factor=2.20462262185
        for unit in ('lb','kg'):
            for entered,expected in ((132.34,132),(132.49,132),(132.5,133),(132.51,133),(0,0),(2.5,3)):
                with self.subTest(unit=unit,entered=entered):
                    kg=entered/factor if unit=='lb' else entered
                    entry=_entry(weight_unit=unit,exercises=[{'exercise_template_id':'t','sets':[{'weight_kg':kg,'reps':5}]}])
                    actual=build_hevy_workout(entry)['workout']['exercises'][0]['sets'][0]['weight_kg']
                    self.assertAlmostEqual(expected,actual*factor if unit=='lb' else actual)
                    self.assertEqual(kg,entry['exercises'][0]['sets'][0]['weight_kg'],'Local input must retain its original value')

    def test_unit_rounding_preserves_missing_weights(self):
        entry=_entry(weight_unit='lb',exercises=[{'exercise_template_id':'t','sets':[{'weight_kg':None,'reps':8}]}])
        self.assertIsNone(build_hevy_workout(entry)['workout']['exercises'][0]['sets'][0]['weight_kg'])


class TestBody(unittest.TestCase):

    def test_wrapped_in_workout_with_snake_case_keys(self):
        body = build_hevy_workout(_entry())
        self.assertEqual(["workout"], list(body))
        w = body["workout"]
        self.assertEqual("BS-Bridge 1.3.3", w["title"])
        self.assertEqual("2026-10-09T17:00:00Z", w["start_time"])
        self.assertEqual("2026-10-09T18:00:00Z", w["end_time"])
        self.assertEqual("tpl-squat", w["exercises"][0]["exercise_template_id"])

    def test_sets_carry_type_kg_reps_rpe(self):
        sets = build_hevy_workout(_entry())["workout"]["exercises"][0]["sets"]
        self.assertEqual(
            [
                {"type": "warmup", "weight_kg": 50.0, "reps": 5, "rpe": None},
                {"type": "normal", "weight_kg": 120.0, "reps": 5, "rpe": 6.0},
                {"type": "normal", "weight_kg": 127.5, "reps": 5, "rpe": 7.0},
            ],
            sets,
        )

    def test_bodyweight_set_has_null_weight(self):
        entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"weight_kg": None, "reps": 8}]}])
        s = build_hevy_workout(entry)["workout"]["exercises"][0]["sets"][0]
        self.assertIsNone(s["weight_kg"])
        self.assertEqual("normal", s["type"])

    def test_notes_and_description_only_when_present(self):
        body = build_hevy_workout(_entry())["workout"]
        self.assertNotIn("description", body)
        self.assertNotIn("notes", body["exercises"][0])
        entry = _entry(description="felt good")
        entry["exercises"][0]["notes"] = " belt on "
        body = build_hevy_workout(entry)["workout"]
        self.assertEqual("felt good", body["description"])
        self.assertEqual("belt on", body["exercises"][0]["notes"])

    def test_exercise_with_no_sets_is_dropped(self):
        entry = _entry()
        entry["exercises"].append({"exercise_template_id": "tpl-bench", "sets": []})
        body = build_hevy_workout(entry)["workout"]
        self.assertEqual(["tpl-squat"], [e["exercise_template_id"] for e in body["exercises"]])


class TestRpe(unittest.TestCase):

    def test_every_hevy_rpe_value_is_kept(self):
        for rpe in (6, 7, 7.5, 8, 8.5, 9, 9.5, 10):
            entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"weight_kg": 45, "reps": 5, "rpe": rpe}]}])
            body = build_hevy_workout(entry)
            self.assertEqual(float(rpe), body["workout"]["exercises"][0]["sets"][0]["rpe"])

    def test_rpe_hevy_cannot_store_leaves_the_field_blank_with_no_note(self):
        entry = _entry(
            exercises=[
                {"exercise_template_id": "t", "title": "Squat", "sets": [{"weight_kg": 45, "reps": 8, "rpe": 5}]}
            ]
        )
        exercise = build_hevy_workout(entry)["workout"]["exercises"][0]
        self.assertIsNone(exercise["sets"][0]["rpe"])
        self.assertNotIn("notes", exercise)

    def test_every_unstorable_rpe_is_blank_and_the_users_own_note_is_untouched(self):
        entry = _entry(
            exercises=[
                {
                    "exercise_template_id": "t",
                    "title": "Squat",
                    "notes": "belt on",
                    "sets": [
                        {"type": "warmup", "weight_kg": 45, "reps": 5, "rpe": 4},
                        {"type": "normal", "weight_kg": 90, "reps": 5, "rpe": 5.5},
                        {"type": "normal", "weight_kg": 100, "reps": 5, "rpe": 7},
                        {"type": "failure", "weight_kg": 100, "reps": 3, "rpe": 6.5},
                    ],
                }
            ]
        )
        exercise = build_hevy_workout(entry)["workout"]["exercises"][0]
        self.assertEqual("belt on", exercise["notes"])
        self.assertEqual([None, None, 7.0, None], [s["rpe"] for s in exercise["sets"]])

    def test_rpe_outside_0_to_10_is_rejected(self):
        for bad in (-1, 10.5, 11):
            entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"reps": 5, "rpe": bad}]}])
            with self.assertRaisesRegex(ValueError, "between 0 and 10"):
                build_hevy_workout(entry)

    def test_rpe_6_5_is_not_storable_either(self):
        entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"reps": 5, "rpe": 6.5}]}])
        self.assertIsNone(build_hevy_workout(entry)["workout"]["exercises"][0]["sets"][0]["rpe"])


class TestRejections(unittest.TestCase):

    def test_blank_title(self):
        with self.assertRaisesRegex(ValueError, "title"):
            build_hevy_workout(_entry(title="  "))

    def test_end_before_start(self):
        with self.assertRaisesRegex(ValueError, "before"):
            build_hevy_workout(_entry(start_time="2026-10-09T18:00:00Z", end_time="2026-10-09T17:00:00Z"))

    def test_bad_timestamp(self):
        with self.assertRaisesRegex(ValueError, "timestamp"):
            build_hevy_workout(_entry(start_time="yesterday"))

    def test_no_completed_sets(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_hevy_workout(_entry(exercises=[]))

    def test_unknown_set_type(self):
        entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [{"type": "amrap", "reps": 5}]}])
        with self.assertRaisesRegex(ValueError, "set type"):
            build_hevy_workout(entry)

    def test_missing_exercise_id(self):
        entry = _entry(exercises=[{"exercise_template_id": "", "title": "Mystery", "sets": [{"reps": 5}]}])
        with self.assertRaisesRegex(ValueError, "Mystery"):
            build_hevy_workout(entry)

    def test_negative_values(self):
        for bad in ({"weight_kg": -5, "reps": 5}, {"weight_kg": 45, "reps": -1}):
            entry = _entry(exercises=[{"exercise_template_id": "t", "sets": [bad]}])
            with self.assertRaises(ValueError):
                build_hevy_workout(entry)


if __name__ == "__main__":
    unittest.main()
