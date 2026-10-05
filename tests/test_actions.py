import math
import unittest

from gpt64.actions import Segment, validate_sequence


class ActionsTest(unittest.TestCase):
    def test_valid_combination_and_release(self):
        self.assertEqual(Segment(3, -1, 0.5, ("A", "Z")).wire(), "3 -80 40 5")
        self.assertEqual(Segment(1).wire(), "1 0 0 0")

    def test_reject_unsafe_values(self):
        for args in ({"frames": 0}, {"frames": 121}, {"frames": True},
                     {"frames": 1, "x": math.nan}, {"frames": 1, "y": 1.1},
                     {"frames": 1, "x": True}, {"frames": 1, "buttons": ("Power",)},
                     {"frames": 1, "buttons": ("A", "A")}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Segment(**args)

    def test_sequence_limits(self):
        for segments in ([], [Segment(1)] * 17, [Segment(120)] * 3):
            with self.assertRaises(ValueError):
                validate_sequence(segments)
        self.assertEqual(len(validate_sequence([Segment(120)] * 2)), 2)
