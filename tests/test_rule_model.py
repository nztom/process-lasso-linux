"""Characterization tests for matching and merging persistent rules."""
from __future__ import annotations

import unittest

from policy_models import (
    AbsoluteNicePolicy,
    EffectiveProcessPolicy,
    IoPriorityPolicy,
    OffsetNicePolicy,
)
from rules import Rule, RuleEngine


class EffectiveSettingsMergeTests(unittest.TestCase):
    def test_later_matching_rules_win_independently_per_field(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            name="Base game policy",
            pattern="game.exe",
            match_type="exact",
            affinity="0-3",
            nice=-8,
            ionice_class=2,
            ionice_level=4,
        ))
        engine.add_rule(Rule(
            name="Priority override",
            pattern="game",
            match_type="contains",
            nice=-4,
        ))
        engine.add_rule(Rule(
            name="Affinity and I/O override",
            pattern=r"^game\.exe$",
            match_type="regex",
            affinity="4-7",
            ionice_class=3,
            ionice_level=None,
        ))

        self.assertEqual(engine.effective_settings("game.exe"), {
            "affinity": "4-7",
            "nice": -4,
            "ionice_class": 3,
            "ionice_level": None,
        })

    def test_typed_policy_uses_last_matching_value_per_field(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game.exe",
            match_type="exact",
            affinity="0-3",
            nice=-8,
            ionice_class=2,
            ionice_level=4,
        ))
        engine.add_rule(Rule(
            pattern="game",
            match_type="contains",
            nice=0,
            nice_mode="offset",
            nice_offset=-5,
            nice_floor=-10,
            nice_ceiling=15,
        ))
        engine.add_rule(Rule(
            pattern=r"^game\.exe$",
            match_type="regex",
            affinity="4-7",
            ionice_class=3,
        ))

        self.assertEqual(engine.effective_policy("game.exe"),
            EffectiveProcessPolicy(
                affinity="4-7",
                nice=OffsetNicePolicy(-5, floor=-10, ceiling=15),
                ionice=IoPriorityPolicy(3),
            )
        )

    def test_later_absolute_policy_replaces_offset_as_a_complete_value(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game", nice=0, nice_mode="offset", nice_offset=-5
        ))
        engine.add_rule(Rule(pattern="game", nice=-8))

        self.assertEqual(
            engine.effective_policy("game"),
            EffectiveProcessPolicy(nice=AbsoluteNicePolicy(-8)),
        )
        self.assertEqual(engine.effective_settings("game"), {
            "affinity": None,
            "nice": -8,
            "ionice_class": None,
            "ionice_level": None,
        })

    def test_disabled_rules_are_absent_from_typed_policy(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game", affinity="0-3", nice=-8,
            ionice_class=2, ionice_level=4, enabled=False,
        ))

        self.assertEqual(engine.effective_policy("game"), EffectiveProcessPolicy())

    def test_disabled_matching_rules_do_not_contribute_settings(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            name="Enabled policy",
            pattern="game.exe",
            match_type="exact",
            affinity="0-3",
            nice=-8,
            ionice_class=2,
            ionice_level=4,
        ))
        engine.add_rule(Rule(
            name="Disabled override",
            pattern="game.exe",
            match_type="exact",
            affinity="4-7",
            nice=10,
            ionice_class=3,
            ionice_level=None,
            enabled=False,
        ))

        self.assertEqual(engine.effective_settings("game.exe"), {
            "affinity": "0-3",
            "nice": -8,
            "ionice_class": 2,
            "ionice_level": 4,
        })

    def test_only_disabled_matches_produce_empty_effective_settings(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game.exe",
            match_type="exact",
            affinity="0-3",
            nice=-8,
            ionice_class=2,
            ionice_level=4,
            enabled=False,
        ))

        self.assertFalse(engine.matches_process("game.exe"))
        self.assertEqual(engine.effective_settings("game.exe"), {
            "affinity": None,
            "nice": None,
            "ionice_class": None,
            "ionice_level": None,
        })


if __name__ == "__main__":
    unittest.main()
