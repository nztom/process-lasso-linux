"""Tests for the global Reset All Changes action."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QMessageBox

from gui.gaming_mode_tab import GamingModeTab
from gui.settings_tab import SettingsTab
from monitor import MonitorThread
from probalance import ProBalance
from rules import RuleEngine


class ResetAllTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @mock.patch("gui.settings_tab.subprocess.run")
    @mock.patch("gui.settings_tab.cpu_park.is_sudoers_installed", return_value=True)
    @mock.patch("gui.settings_tab.cpu_park.is_helper_current", return_value=True)
    def test_settings_confirmation_emits_reset_request(self, _current, _sudoers, _run):
        tab = SettingsTab({})
        spy = QSignalSpy(tab.reset_requested)

        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            tab._reset_all()

        self.assertEqual(len(spy), 1)

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

    @mock.patch("gui.gaming_mode_tab.cpu_park.unpark_all", return_value=True)
    @mock.patch("gui.gaming_mode_tab.cpu_park.get_offline_cpus", return_value={4, 5})
    def test_gaming_reset_restores_priority_and_unparks_cpus(self, _offline, unpark):
        tab = mock.Mock()
        tab._parked = True

        GamingModeTab.reset_all_changes(tab)

        tab.gaming_mode_changed.emit.assert_called_once_with(False, False)
        unpark.assert_called_once_with(log_cb=tab._append_log)
        tab._update_cpu_status.assert_called_once_with()
        tab._detect_topology.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
