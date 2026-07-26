"""Tests for per-rule, per-process bounded enforcement."""
from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from rules import Rule, RuleEngine, RULE_APPLY_ATTEMPTS
from policy_models import AbsoluteNicePolicy, EffectiveProcessPolicy, IoPriorityPolicy
from thread_priority_state import ThreadPriorityState


class RuleAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        priority_state = ThreadPriorityState(
            pathlib.Path(self.temp.name) / "priority-state.json"
        )
        priority_state.boot_id = "boot"
        self.engine = RuleEngine(priority_state)
        self.rule = Rule(name="Game", pattern="game.exe", match_type="exact", affinity="0-3")
        self.engine.add_rule(self.rule)
        self.tids = mock.patch("rules.utils.get_process_tids", side_effect=lambda pid: [pid])
        self.identity = mock.patch(
            "rules.thread_identity",
            side_effect=lambda pid, tid, rule_id, boot: f"{boot}:{pid}:1:{tid}:2:{rule_id}",
        )
        self.current_affinity = mock.patch(
            "rules.os.sched_getaffinity", return_value={8}
        )
        self.tids.start()
        self.identity.start()
        self.current_affinity.start()

    def tearDown(self):
        mock.patch.stopall()
        self.temp.cleanup()

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_rule_stops_after_ten_attempts(self, set_affinity):
        logs = []
        self.engine.set_log_callback(logs.append)
        for _ in range(20):
            self.engine.apply_to_process(100, "game.exe")

        self.assertEqual(set_affinity.call_count, RULE_APPLY_ATTEMPTS + 1)
        self.assertEqual(
            len([message for message in logs if "Released affinity drift" in message]),
            1,
        )

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_attempts_are_independent_per_pid(self, set_affinity):
        for _ in range(20):
            self.engine.apply_to_process(100, "game.exe")
            self.engine.apply_to_process(200, "game.exe")

        self.assertEqual(set_affinity.call_count, (RULE_APPLY_ATTEMPTS + 1) * 2)

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_forgetting_pid_allows_rule_to_apply_again(self, set_affinity):
        for _ in range(RULE_APPLY_ATTEMPTS):
            self.engine.apply_to_process(100, "game.exe")
        self.engine.forget_pid(100)
        self.engine.apply_to_process(100, "game.exe")

        self.assertEqual(set_affinity.call_count, RULE_APPLY_ATTEMPTS + 1)

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_manual_suppression_stops_rule(self, set_affinity):
        self.engine.apply_to_process(100, "game.exe")
        self.engine.suppress_pid(100)
        self.engine.apply_to_process(100, "game.exe")

        set_affinity.assert_called_once_with(100, "0-3")

    @mock.patch("rules.utils.set_nice", return_value=True)
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_edit_resets_only_edited_rule(self, set_affinity, set_nice):
        nice_rule = Rule(name="Nice", pattern="game.exe", match_type="exact", nice=-1)
        self.engine.add_rule(nice_rule)
        for _ in range(RULE_APPLY_ATTEMPTS):
            self.engine.apply_to_process(100, "game.exe")

        edited = Rule(
            rule_id=self.rule.rule_id,
            name="Game",
            pattern="game.exe",
            match_type="exact",
            affinity="4-7",
        )
        self.engine.update_rule(edited)
        self.engine.apply_to_process(100, "game.exe")

        self.assertEqual(set_affinity.call_count, RULE_APPLY_ATTEMPTS + 1)
        self.assertEqual(set_nice.call_count, RULE_APPLY_ATTEMPTS)
        set_affinity.assert_called_with(100, "4-7")

    def test_attempt_state_is_not_serialized(self):
        self.engine.apply_to_process(100, "game.exe")
        self.assertNotIn("_attempts_by_pid", vars(self.rule))
        self.assertNotIn("_attempts_by_pid", self.rule.to_dict())

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_force_apply_bypasses_attempt_limit_and_suppression(self, set_affinity):
        self.rule.force_apply = True
        self.engine.suppress_pid(100)
        for _ in range(RULE_APPLY_ATTEMPTS + 5):
            self.engine.apply_to_process(100, "game.exe")

        self.assertEqual(set_affinity.call_count, RULE_APPLY_ATTEMPTS + 5)

    def test_force_apply_round_trips_through_config(self):
        self.rule.force_apply = True

        restored = Rule.from_dict(self.rule.to_dict())

        self.assertTrue(restored.force_apply)

    def test_existing_config_defaults_force_apply_off(self):
        restored = Rule.from_dict({"name": "Legacy", "pattern": "legacy"})

        self.assertFalse(restored.force_apply)

    def test_exact_process_name_match_is_case_insensitive(self):
        rule = Rule(
            pattern="blackdesert64.exe",
            match_type="exact",
            affinity="0-7",
        )

        self.assertTrue(rule.matches("BlackDesert64.exe"))

    def test_effective_policy_uses_last_matching_value_per_field(self):
        self.engine.add_rule(Rule(
            name="Priority",
            pattern="game.exe",
            match_type="exact",
            nice=-10,
            ionice_class=2,
            ionice_level=4,
        ))
        self.engine.add_rule(Rule(
            name="Affinity override",
            pattern="game",
            match_type="contains",
            affinity="4-7",
            ionice_class=3,
        ))

        self.assertEqual(
            self.engine.effective_policy("game.exe"),
            EffectiveProcessPolicy(
                affinity="4-7",
                nice=AbsoluteNicePolicy(-10),
                ionice=IoPriorityPolicy(3),
            ),
        )

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_new_thread_receives_matching_affinity_rule(self, set_affinity):
        self.engine.apply_to_thread(100, 123, "game.exe")

        set_affinity.assert_called_once_with(123, "0-3")

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_manual_override_suppresses_new_thread_rules(self, set_affinity):
        self.engine.suppress_pid(100)

        self.engine.apply_to_thread(100, 123, "game.exe")

        set_affinity.assert_not_called()

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_editing_rule_clears_its_manual_suppression(self, set_affinity):
        self.engine.suppress_pid(100)
        edited = Rule(
            rule_id=self.rule.rule_id,
            name="Game",
            pattern="game.exe",
            match_type="exact",
            affinity="4-7",
        )
        self.engine.update_rule(edited)

        self.engine.apply_to_thread(100, 123, "game.exe")

        set_affinity.assert_called_once_with(123, "4-7")

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_forced_rule_places_new_thread_once(self, set_affinity):
        self.rule.force_apply = True

        self.engine.apply_to_thread(100, 123, "game.exe")

        set_affinity.assert_called_once_with(123, "0-3")

    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_matching_affinity_is_never_rewritten(self, set_affinity):
        with mock.patch("rules.os.sched_getaffinity", return_value={0, 1, 2, 3}):
            for _ in range(20):
                self.engine.apply_to_process(100, "game.exe")

        set_affinity.assert_not_called()

    @mock.patch("rules.utils.get_online_cpus", return_value={0, 1})
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_parked_rule_cpus_do_not_count_as_affinity_drift(
        self, set_affinity, _online
    ):
        self.rule.affinity = "0-3"
        with mock.patch("rules.os.sched_getaffinity", return_value={0, 1}):
            for _ in range(RULE_APPLY_ATTEMPTS + 5):
                self.engine.apply_to_process(100, "game.exe")

        set_affinity.assert_not_called()
        self.assertEqual(self.engine._affinity_drift_attempts, {})
        self.assertEqual(self.engine._affinity_released, set())

    @mock.patch("rules.utils.get_online_cpus", return_value={0, 1})
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_rule_with_only_parked_cpus_waits_without_drift_attempts(
        self, set_affinity, _online
    ):
        self.rule.affinity = "2-3"

        for _ in range(RULE_APPLY_ATTEMPTS + 5):
            self.engine.apply_to_process(100, "game.exe")

        set_affinity.assert_not_called()
        self.assertEqual(self.engine._affinity_drift_attempts, {})
        self.assertEqual(self.engine._affinity_released, set())


if __name__ == "__main__":
    unittest.main()
