"""Settings behavior for disabling the global default affinity."""
from __future__ import annotations

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import cpu_park
from gui.settings_tab import SettingsTab


class DefaultAffinitySettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @mock.patch("gui.settings_tab.QMessageBox.information")
    @mock.patch("gui.settings_tab.subprocess.run")
    @mock.patch("gui.settings_tab.cpu_park.has_dual_ccd_x3d_control", return_value=False)
    @mock.patch("gui.settings_tab.cpu_park.detect_topology")
    def test_unchecked_apply_saves_disabled_value_and_emits_change(
        self, topology, _supported, _run, _message
    ):
        topology.return_value = cpu_park.CPUTopology(
            kind=cpu_park.TopologyKind.UNIFORM, preferred={0, 1}
        )
        config = {"cpu": {"default_affinity": "0"}, "monitor": {}}
        tab = SettingsTab(config)
        emissions = []
        tab.settings_changed.connect(emissions.append)
        tab._default_affinity_cb.setChecked(False)

        tab._apply_cpu()

        self.assertIsNone(config["cpu"]["default_affinity"])
        self.assertEqual(len(emissions), 1)


if __name__ == "__main__":
    unittest.main()
