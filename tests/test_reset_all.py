"""Tests for internal affinity restoration."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from monitor import MonitorThread
from probalance import ProBalance
from rules import RuleEngine


class ResetAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @mock.patch("monitor.utils.set_process_affinity_set", return_value=True)
    def test_monitor_restores_process_and_thread_affinities(self, set_affinity):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._original_affinities = {101: frozenset({0, 2})}

        monitor.reset_all_affinities()

        set_affinity.assert_called_once_with(101, {0, 2})
        self.assertEqual(monitor._original_affinities, {})

    @mock.patch("monitor.utils.set_affinity")
    @mock.patch("builtins.open", new_callable=mock.mock_open, read_data="worker\n")
    def test_disabled_default_stops_enforcement_without_changing_affinity(
        self, _open, set_affinity
    ):
        monitor = MonitorThread(
            RuleEngine(), ProBalance({}), {"cpu": {"default_affinity": None}}
        )
        monitor._known_pids = {101}

        monitor.reapply_all_defaults()

        set_affinity.assert_not_called()



if __name__ == "__main__":
    unittest.main()
