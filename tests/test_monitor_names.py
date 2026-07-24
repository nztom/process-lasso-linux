"""Tests for native, Wine, and sudo process-name resolution."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from monitor import _resolve_name, _resolve_sudo_command


class ProcessNameTests(unittest.TestCase):
    def test_plain_sudo_command(self):
        self.assertEqual(
            _resolve_name("sudo", ["sudo", "/usr/bin/htop"]),
            "htop",
        )

    def test_sudo_options_with_values(self):
        self.assertEqual(
            _resolve_sudo_command(["sudo", "-E", "-u", "root", "/opt/tools/app"]),
            "app",
        )

    def test_sudo_environment_assignment(self):
        self.assertEqual(
            _resolve_sudo_command(["sudo", "DISPLAY=:0", "/usr/bin/gui-app"]),
            "gui-app",
        )

    def test_sudo_env_wrapper(self):
        self.assertEqual(
            _resolve_sudo_command(["sudo", "env", "MODE=fast", "/usr/bin/game"]),
            "game",
        )

    def test_sudo_without_command_stays_sudo(self):
        self.assertEqual(_resolve_sudo_command(["sudo", "-v"]), "sudo")

    def test_wine_name_resolution_is_preserved(self):
        self.assertEqual(
            _resolve_name("Main", [r"Z:\\Games\\BlackDesert64.exe"]),
            "BlackDesert64.exe",
        )


if __name__ == "__main__":
    unittest.main()
