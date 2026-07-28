"""Tests for running-game profile controls in the Game Mode tab."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog

from gui.game_mode_tab import GameModeTab, RunningGameProfileDialog


class GameModeTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.game = {
            "id": "game-1", "name": "Space Game",
            "source_aliases": ["steam:123"],
            "executable_aliases": ["spacegame.exe"],
            "affinity": "inherit", "nice": "inherit",
        }
        self.session = {
            "token": "session-1", "game_id": "game-1",
            "game_name": "Space Game", "root_pid": 1234,
            "policy": {"affinity": "0-7", "nice": {"type": "absolute", "value": 5}},
            "argv": ["gamemoderun", "SpaceGame.exe"],
        }
        self.config = {"ccd_preference": "cache", "affinity": None,
                       "nice": None, "games": [self.game]}
        self.tab = GameModeTab(
            self.config, SimpleNamespace(sessions={"session-1": self.session})
        )

    def test_active_game_list_shows_effective_policy_and_command(self):
        self.assertEqual(self.tab._active.rowCount(), 1)
        self.assertEqual(self.tab._active.item(0, 0).text(), "Space Game")
        self.assertEqual(self.tab._active.item(0, 2).text(), "0-7")
        self.assertEqual(self.tab._active.item(0, 3).text(), "5")
        self.assertEqual(
            self.tab._active.item(0, 4).text(), "gamemoderun SpaceGame.exe"
        )
        self.assertTrue(self.tab._create_running_profile.isEnabled())

    def test_running_game_dialog_writes_canonical_profile_overrides(self):
        dialog = RunningGameProfileDialog(self.game)
        dialog.name.setText("Custom Space Game")
        dialog.affinity_mode.setCurrentIndex(2)
        dialog.affinity.setText("8-15")
        dialog.nice_mode.setCurrentIndex(3)
        dialog._nice_policy = {"type": "offset", "offset": 4,
                               "floor": -15, "ceiling": 19}
        dialog.nice_value.setText("Offset +4 [-15, 19]")

        dialog.update_game(self.game)

        self.assertEqual(self.game["name"], "Custom Space Game")
        self.assertEqual(self.game["affinity"], "8-15")
        self.assertEqual(self.game["nice"]["type"], "offset")
        self.assertEqual(self.game["nice"]["offset"], 4)

    @mock.patch("gui.game_mode_tab.RunningGameProfileDialog")
    def test_selected_saved_profile_can_be_opened_for_editing(self, dialog_type):
        dialog = dialog_type.return_value
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        self.tab._games.selectRow(0)

        self.tab._edit_selected_profile()

        dialog_type.assert_called_once_with(self.game, self.tab)
        dialog.update_game.assert_called_once_with(self.game)


if __name__ == "__main__":
    unittest.main()
