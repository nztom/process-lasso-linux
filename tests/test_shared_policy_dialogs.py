"""All policy editors route affinity and nice choices through shared dialogs."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from gui.dialogs import NicePriorityDialog
from gui.game_mode_tab import GameModeTab


class SharedPolicyDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shared_nice_dialog_carries_offset_bounds(self):
        dialog = NicePriorityDialog(
            current_nice=0, initial_mode="offset", initial_offset=4,
            initial_floor=-10, initial_ceiling=15,
        )
        self.assertEqual(dialog.get_mode(), "offset")
        self.assertEqual(dialog.get_offset(), 4)
        self.assertEqual((dialog.get_floor(), dialog.get_ceiling()), (-10, 15))

    @mock.patch("gui.game_mode_tab.AffinityDialog")
    def test_game_mode_default_uses_shared_affinity_dialog(self, dialog_type):
        picker = dialog_type.return_value
        picker.exec.return_value = dialog_type.DialogCode.Accepted
        picker.get_cpulist.return_value = "0-7"
        tab = GameModeTab(
            {"ccd_preference": "cache", "affinity": None,
             "nice": None, "games": []},
            SimpleNamespace(sessions={}),
        )

        tab._pick_default_affinity()

        dialog_type.assert_called_once()
        self.assertEqual(tab._affinity.text(), "0-7")


if __name__ == "__main__":
    unittest.main()
