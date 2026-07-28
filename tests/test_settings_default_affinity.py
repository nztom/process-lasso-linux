"""Settings behavior for disabling the global default affinity."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import cpu_tools
from gui.settings_tab import SettingsTab


class DefaultAffinitySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @mock.patch("gui.settings_tab.QMessageBox.information")
    @mock.patch("gui.settings_tab.subprocess.run")
    @mock.patch("gui.settings_tab.cpu_tools.get_cpu_info")
    def test_unchecked_apply_saves_disabled_value_and_emits_change(
        self, cpu_info, _run, _message
    ):
        topology = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.UNIFORM, preferred={0, 1}
        )
        cpu_info.return_value = cpu_tools.CPUInfo(
            topology=topology, present={0, 1}, online={0, 1}, offline=set(),
            smt_siblings=set(), features=cpu_tools.CPUFeatures(),
        )
        config = {"cpu": {"default_affinity": "0"}, "monitor": {}}
        tab = SettingsTab(config)
        self.assertFalse(tab._x3d_group.isEnabled())
        emissions = []
        tab.settings_changed.connect(emissions.append)
        tab._default_affinity_cb.setChecked(False)

        tab._apply_cpu()

        self.assertIsNone(config["cpu"]["default_affinity"])
        self.assertEqual(len(emissions), 1)

    @mock.patch("gui.settings_tab.cpu_tools.is_sudoers_installed", return_value=True)
    @mock.patch("gui.settings_tab.cpu_tools.is_helper_current", return_value=True)
    @mock.patch("gui.settings_tab.cpu_tools.get_x3d_mode", return_value="frequency")
    @mock.patch("gui.settings_tab.subprocess.run")
    @mock.patch("gui.settings_tab.cpu_tools.get_cpu_info")
    def test_x3d_status_shows_current_and_configured_default(
        self, cpu_info, _run, _mode, _helper, _sudoers
    ):
        topology = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1}, non_preferred={2, 3},
        )
        cpu_info.return_value = cpu_tools.CPUInfo(
            topology=topology, present={0, 1, 2, 3},
            online={0, 1, 2, 3}, offline=set(), smt_siblings=set(),
            features=cpu_tools.CPUFeatures(
                asymmetric=True, amd_x3d=True, dual_ccd_x3d=True,
                x3d_mode_control=True,
            ),
        )
        tab = SettingsTab({
            "cpu": {}, "monitor": {},
            "game_mode": {"ccd_preference": "cache"},
        })

        self.assertEqual(
            tab._x3d_status.text(),
            "Current scheduler preference: frequency\n"
            "Configured Game Mode default: cache",
        )
        self.assertEqual(tab._x3d_mode_combo.currentData(), "frequency")
        self.assertEqual(
            tab._x3d_mode_combo.currentText(), "frequency (recommended)"
        )

    @mock.patch("gui.settings_tab.cpu_tools.is_sudoers_installed", return_value=True)
    @mock.patch("gui.settings_tab.cpu_tools.is_helper_current", return_value=True)
    @mock.patch(
        "gui.settings_tab.cpu_tools.get_x3d_mode",
        side_effect=["frequency", "frequency", "future-mode"],
    )
    @mock.patch("gui.settings_tab.subprocess.run")
    @mock.patch("gui.settings_tab.cpu_tools.get_cpu_info")
    def test_poll_refreshes_live_mode_without_redetecting_topology(
        self, cpu_info, _run, _mode, _helper, _sudoers
    ):
        topology = cpu_tools.CPUTopology(
            kind=cpu_tools.TopologyKind.AMD_X3D,
            preferred={0, 1}, non_preferred={2, 3},
        )
        cpu_info.return_value = cpu_tools.CPUInfo(
            topology=topology, present={0, 1, 2, 3},
            online={0, 1, 2, 3}, offline=set(), smt_siblings=set(),
            features=cpu_tools.CPUFeatures(
                asymmetric=True, amd_x3d=True, dual_ccd_x3d=True,
                x3d_mode_control=True,
            ),
        )
        tab = SettingsTab({"cpu": {}, "monitor": {}, "game_mode": {}})
        topology_reads = cpu_info.call_count

        tab.refresh_current_x3d_mode()

        self.assertIn("Current scheduler preference: future-mode", tab._x3d_status.text())
        self.assertEqual(cpu_info.call_count, topology_reads)


if __name__ == "__main__":
    unittest.main()
