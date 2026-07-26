"""Characterization tests for manual rule suppression."""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from rules import Rule, RuleEngine
from thread_priority_state import ThreadPriorityState


class RuleSuppressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        state = ThreadPriorityState(
            pathlib.Path(self.temp.name) / "priority-state.json"
        )
        state.boot_id = "boot"
        self.engine = RuleEngine(state)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _rule(**changes) -> Rule:
        values = {
            "rule_id": "policy",
            "name": "Game policy",
            "pattern": "game.exe",
            "match_type": "exact",
        }
        values.update(changes)
        return Rule(**values)

    @mock.patch("rules.utils.set_ionice", return_value=True)
    @mock.patch("rules.utils.set_nice", return_value=True)
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    @mock.patch("rules.utils.get_process_tids", return_value=[100])
    def test_suppression_blocks_absolute_nice_affinity_and_io_on_process(
        self, get_tids, set_affinity, set_nice, set_ionice
    ):
        self.engine.add_rule(self._rule(
            affinity="0-3", nice=-8, ionice_class=2, ionice_level=4
        ))
        self.engine.suppress_pid(100)

        actions = self.engine.apply_to_process(100, "game.exe", original_nice_hint=0)

        self.assertEqual(actions, [])
        get_tids.assert_not_called()
        set_affinity.assert_not_called()
        set_nice.assert_not_called()
        set_ionice.assert_not_called()

    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    @mock.patch("rules.utils.set_nice_threads", return_value={100})
    @mock.patch("rules.utils.get_process_tids", return_value=[100])
    def test_suppression_blocks_offset_nice_on_process(
        self, get_tids, set_nice_threads, get_nice
    ):
        self.engine.add_rule(self._rule(
            nice=0, nice_mode="offset", nice_offset=-5
        ))
        self.engine.suppress_pid(100)

        actions = self.engine.apply_to_process(100, "game.exe")

        self.assertEqual(actions, [])
        get_tids.assert_not_called()
        get_nice.assert_not_called()
        set_nice_threads.assert_not_called()

    @mock.patch("rules.utils.set_ionice", return_value=True)
    @mock.patch("rules.utils.set_thread_nice", return_value=True)
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    def test_suppression_blocks_rules_on_new_threads(
        self, set_affinity, set_nice, set_ionice
    ):
        self.engine.add_rule(self._rule(
            affinity="0-3", nice=-8, ionice_class=2, ionice_level=4
        ))
        self.engine.suppress_pid(100)

        actions = self.engine.apply_to_thread(100, 101, "game.exe")

        self.assertEqual(actions, [])
        set_affinity.assert_not_called()
        set_nice.assert_not_called()
        set_ionice.assert_not_called()

    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    @mock.patch("rules.utils.set_nice_threads", return_value={101})
    def test_suppression_blocks_offset_nice_on_new_threads(
        self, set_nice_threads, get_nice
    ):
        self.engine.add_rule(self._rule(
            nice=0, nice_mode="offset", nice_offset=-5
        ))
        self.engine.suppress_pid(100)

        actions = self.engine.apply_to_thread(100, 101, "game.exe")

        self.assertEqual(actions, [])
        get_nice.assert_not_called()
        set_nice_threads.assert_not_called()

    @mock.patch("rules.thread_identity", return_value="boot:100:1:100:2:policy")
    @mock.patch("rules.os.sched_getaffinity", return_value={8})
    @mock.patch("rules.utils.set_ionice", return_value=True)
    @mock.patch("rules.utils.set_nice", return_value=True)
    @mock.patch("rules.utils.set_thread_affinity", return_value=True)
    @mock.patch("rules.utils.get_process_tids", return_value=[100])
    def test_forced_absolute_rule_bypasses_suppression_for_every_setting(
        self, get_tids, set_affinity, set_nice, set_ionice, _get_affinity, _identity
    ):
        self.engine.add_rule(self._rule(
            affinity="0-3",
            nice=-8,
            ionice_class=2,
            ionice_level=4,
            force_apply=True,
        ))
        self.engine.suppress_pid(100)

        self.engine.apply_to_process(100, "game.exe", original_nice_hint=0)

        set_affinity.assert_called_once_with(100, "0-3")
        set_nice.assert_called_once_with(100, -8)
        set_ionice.assert_called_once_with(100, 2, 4)

    @mock.patch("rules.thread_identity", return_value="boot:100:1:100:2:policy")
    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    @mock.patch("rules.utils.set_nice_threads", return_value={100})
    @mock.patch("rules.utils.get_process_tids", return_value=[100])
    def test_forced_offset_rule_bypasses_suppression(
        self, get_tids, set_nice_threads, get_nice, _identity
    ):
        self.engine.add_rule(self._rule(
            nice=0, nice_mode="offset", nice_offset=-5, force_apply=True
        ))
        self.engine.suppress_pid(100)

        self.engine.apply_to_process(100, "game.exe")

        get_nice.assert_called_once_with(100)
        set_nice_threads.assert_called_once_with([100], -5)


if __name__ == "__main__":
    unittest.main()
