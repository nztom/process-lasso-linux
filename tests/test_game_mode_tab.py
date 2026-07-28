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

    @mock.patch("gui.game_mode_tab.cpu_tools.get_available_x3d_modes")
    @mock.patch("gui.game_mode_tab.cpu_tools.get_cpu_info")
    def setUp(self, cpu_info, available_modes):
        cpu_info.return_value.features.x3d_mode_control = True
        available_modes.return_value = (
            mock.Mock(value="cache", label="V-Cache CCD"),
            mock.Mock(value="frequency", label="Frequency CCD"),
        )
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
        available_modes.assert_called_once_with()
        self.assertEqual(self.tab._ccd.currentData(), "cache")
        self.assertEqual(self.tab._ccd.currentText(), "cache (recommended)")

    @mock.patch("gui.game_mode_tab.cpu_tools.get_available_x3d_modes", return_value=())
    @mock.patch("gui.game_mode_tab.cpu_tools.get_cpu_info")
    def test_ccd_controls_are_disabled_without_dual_x3d_feature(
        self, cpu_info, _modes
    ):
        cpu_info.return_value.features.x3d_mode_control = False
        tab = GameModeTab(self.config, SimpleNamespace(sessions={}))

        self.assertFalse(tab._ccd.isEnabled())
        self.assertEqual(tab._ccd.placeholderText(), "Not supported by this CPU")

    def test_active_game_list_shows_effective_policy_and_command(self):
        self.assertEqual(
            self.tab._mode_indicator.text(),
            "● Game Mode enabled — 1 active session",
        )
        self.assertIn("#22ff66", self.tab._mode_indicator.styleSheet())
        self.assertTrue(self.tab._session_flash_pending)
        self.assertNotIn("#22ff66", self.tab._active.styleSheet())
        self.assertEqual(self.tab._active.rowCount(), 1)
        self.assertEqual(self.tab._active.item(0, 0).text(), "Space Game")
        self.assertEqual(self.tab._active.item(0, 2).text(), "0-7")
        self.assertEqual(self.tab._active.item(0, 3).text(), "5")
        self.assertEqual(
            self.tab._active.item(0, 4).text(), "gamemoderun SpaceGame.exe"
        )
        self.assertTrue(self.tab._create_running_profile.isEnabled())

    def test_indicator_changes_when_game_mode_becomes_inactive(self):
        self.tab._sessions.sessions.clear()

        self.tab.refresh()

        self.assertEqual(self.tab._mode_indicator.text(), "○ Game Mode inactive")
        self.assertNotIn("#22ff66", self.tab._mode_indicator.styleSheet())

    def test_new_session_flash_only_triggers_once_per_session_token(self):
        initial_generation = self.tab._session_flash_generation

        self.tab.refresh()
        self.assertEqual(self.tab._session_flash_generation, initial_generation)

        second = dict(self.session, token="session-2", root_pid=5678)
        self.tab._sessions.sessions["session-2"] = second
        self.tab.refresh()

        self.assertEqual(
            self.tab._session_flash_generation, initial_generation
        )
        self.assertTrue(self.tab._session_flash_pending)

        with mock.patch.object(
            self.tab, "_can_show_session_flash", return_value=True
        ):
            self.tab._consume_pending_session_flash()

        self.assertFalse(self.tab._session_flash_pending)
        self.assertEqual(self.tab._session_flash_generation, initial_generation + 1)
        self.assertIn("#22ff66", self.tab._active_heading.styleSheet())

        with mock.patch.object(
            self.tab, "_can_show_session_flash", return_value=True
        ):
            self.tab._consume_pending_session_flash()
        self.assertEqual(self.tab._session_flash_generation, initial_generation + 1)

    def test_visible_session_batches_flash_once_and_later_sessions_flash_again(self):
        self.tab._session_flash_pending = False
        initial_generation = self.tab._session_flash_generation
        second = dict(self.session, token="session-2", root_pid=5678)
        third = dict(self.session, token="session-3", root_pid=6789)
        self.tab._sessions.sessions.update({
            "session-2": second,
            "session-3": third,
        })

        with mock.patch.object(
            self.tab, "_can_show_session_flash", return_value=True
        ):
            self.tab.refresh()
            self.tab.refresh()

            fourth = dict(self.session, token="session-4", root_pid=7890)
            self.tab._sessions.sessions["session-4"] = fourth
            self.tab.refresh()

        self.assertEqual(self.tab._session_flash_generation, initial_generation + 2)

    def test_disabled_ccd_option_is_saved_as_none(self):
        self.tab._ccd.setCurrentIndex(self.tab._ccd.findData(None))
        emissions = []
        self.tab.settings_changed.connect(emissions.append)

        self.tab._apply()

        self.assertIsNone(self.config["ccd_preference"])
        self.assertEqual(len(emissions), 1)

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
