"""Tests for bounded per-process rule enforcement."""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from monitor import MonitorThread, RULE_APPLY_BURST_ATTEMPTS


class RuleBurstTests(unittest.TestCase):
    def setUp(self):
        self.rules = mock.Mock()
        self.rules.matches_process.return_value = True
        self.probalance = mock.Mock()
        self.monitor = MonitorThread(self.rules, self.probalance, {})
        self.monitor._capture_original = mock.Mock()
        self.info = {"pid": 1234, "name": "BlackDesert64.exe", "nice": 0}

    def test_new_process_gets_exactly_ten_attempts(self):
        self.monitor._apply_new_pid(self.info)
        for _ in range(20):
            self.monitor._continue_rule_bursts([self.info])

        self.assertEqual(self.rules.apply_to_process.call_count, RULE_APPLY_BURST_ATTEMPTS)
        self.assertEqual(
            self.monitor._rule_apply_attempts[1234],
            RULE_APPLY_BURST_ATTEMPTS,
        )

    def test_manual_change_stops_remaining_attempts(self):
        self.monitor._apply_new_pid(self.info)
        self.monitor.set_manual_rule_override(1234)
        self.monitor._continue_rule_bursts([self.info])

        self.rules.apply_to_process.assert_called_once_with(1234, "BlackDesert64.exe")

    def test_rule_edit_clears_completion_flags(self):
        self.monitor.set_manual_rule_override(1234)
        self.monitor.invalidate_rule_applications()

        self.assertEqual(self.monitor._rule_apply_attempts, {})


if __name__ == "__main__":
    unittest.main()
