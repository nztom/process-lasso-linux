"""Startup priority behavior for the Process Lasso application itself."""
from __future__ import annotations

import unittest
from unittest import mock

import main
import app_identity


class MainStartupTests(unittest.TestCase):
    def test_public_process_and_command_names(self):
        self.assertEqual(app_identity.PROCESS_NAME, "processlasso")
        self.assertEqual(app_identity.APP_COMMAND, "processlasso")
        self.assertEqual(app_identity.GAME_COMMAND, "processlasso-game")

    @mock.patch("main.os.getpid", return_value=4321)
    @mock.patch("main.utils.set_nice", return_value=True)
    def test_startup_nice_is_applied_once_without_rule_suppression(
        self, set_nice, _pid
    ):
        self.assertTrue(main._apply_startup_nice())
        set_nice.assert_called_once_with(4321, main.STARTUP_NICE)


if __name__ == "__main__":
    unittest.main()
