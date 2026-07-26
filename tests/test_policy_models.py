"""Tests for immutable effective-policy value objects."""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from policy_models import (
    AbsoluteNicePolicy,
    EffectiveProcessPolicy,
    IoPriorityPolicy,
    OffsetNicePolicy,
    format_io_priority_policy,
    format_nice_policy,
)


class AbsoluteNicePolicyTests(unittest.TestCase):
    def test_accepts_linux_nice_range_boundaries(self):
        self.assertEqual(AbsoluteNicePolicy(-20).value, -20)
        self.assertEqual(AbsoluteNicePolicy(19).value, 19)

    def test_rejects_out_of_range_and_non_integer_values(self):
        for value in (-21, 20, 1.5, "0", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AbsoluteNicePolicy(value)

    def test_is_immutable(self):
        policy = AbsoluteNicePolicy(-8)

        with self.assertRaises(FrozenInstanceError):
            policy.value = 0

    def test_formats_as_absolute_policy(self):
        self.assertEqual(
            format_nice_policy(AbsoluteNicePolicy(-8)),
            "Absolute -8",
        )


class OffsetNicePolicyTests(unittest.TestCase):
    def test_defaults_to_existing_offset_bounds(self):
        self.assertEqual(
            OffsetNicePolicy(-5),
            OffsetNicePolicy(offset=-5, floor=-15, ceiling=19),
        )

    def test_accepts_full_linux_boundaries(self):
        policy = OffsetNicePolicy(offset=39, floor=-20, ceiling=19)

        self.assertEqual((policy.offset, policy.floor, policy.ceiling), (39, -20, 19))

    def test_rejects_invalid_bounds(self):
        for floor, ceiling in ((0, -1), (-21, 19), (-20, 20)):
            with self.subTest(floor=floor, ceiling=ceiling), self.assertRaises(ValueError):
                OffsetNicePolicy(offset=-5, floor=floor, ceiling=ceiling)

    def test_rejects_non_integer_values(self):
        for values in (
            {"offset": -1.5},
            {"offset": True},
            {"offset": -5, "floor": "-15"},
            {"offset": -5, "ceiling": 19.0},
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                OffsetNicePolicy(**values)

    def test_is_immutable(self):
        policy = OffsetNicePolicy(-5)

        with self.assertRaises(FrozenInstanceError):
            policy.offset = 0

    def test_formats_with_signed_offset_and_bounds(self):
        self.assertEqual(
            format_nice_policy(OffsetNicePolicy(5, floor=-10, ceiling=15)),
            "Offset +5 [-10, 15]",
        )

    def test_empty_policy_formats_as_empty_text(self):
        self.assertEqual(format_nice_policy(None), "")


class EffectiveProcessPolicyTests(unittest.TestCase):
    def test_policy_and_io_values_are_immutable(self):
        ionice = IoPriorityPolicy(2, 4)
        policy = EffectiveProcessPolicy(
            affinity="0-3",
            nice=AbsoluteNicePolicy(-8),
            ionice=ionice,
        )

        with self.assertRaises(FrozenInstanceError):
            ionice.level = 0
        with self.assertRaises(FrozenInstanceError):
            policy.affinity = "4-7"

    def test_io_policy_validates_class_and_level(self):
        for io_class, level in ((-1, 0), (4, 0), (2, -1), (2, 8), (True, 0)):
            with self.subTest(io_class=io_class, level=level), self.assertRaises(ValueError):
                IoPriorityPolicy(io_class, level)

    def test_io_policy_formatting_covers_known_custom_and_empty_values(self):
        self.assertEqual(format_io_priority_policy(IoPriorityPolicy(2, 4)), "Normal (2/4)")
        self.assertEqual(format_io_priority_policy(IoPriorityPolicy(3)), "Very Low (3)")
        self.assertEqual(format_io_priority_policy(IoPriorityPolicy(1, 2)), "Custom (1/2)")
        self.assertEqual(format_io_priority_policy(None), "")
