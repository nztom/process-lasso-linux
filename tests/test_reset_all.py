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

    @mock.patch("monitor.utils.get_process_tids", return_value=[101, 102])
    @mock.patch("monitor.os.sched_setaffinity")
    def test_monitor_restores_process_and_thread_affinities(self, set_affinity, _tids):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._original_affinities = {101: frozenset({0, 2})}

        monitor.reset_all_affinities()

        self.assertEqual(
            set_affinity.call_args_list,
            [mock.call(101, frozenset({0, 2})), mock.call(101, frozenset({0, 2})),
             mock.call(102, frozenset({0, 2}))],
        )
        self.assertEqual(monitor._original_affinities, {})


if __name__ == "__main__":
    unittest.main()
