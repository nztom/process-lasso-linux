"""Game Mode identity, launch policy, and wrapper regression tests."""
from __future__ import annotations

import os
import unittest
from unittest import mock

import game_identity
import game_mode
import process_lasso_game
import config


class GameIdentityTests(unittest.TestCase):
    def test_wrapper_command_resolves_proton_game_executable(self):
        argv = ["gamemoderun", "/steam/proton", "waitforexitandrun",
                "Z:\\Games\\SpaceGame.exe"]
        self.assertEqual(game_identity.executable_alias(argv), "spacegame.exe")

    def test_native_identity_is_reused_by_safe_executable_alias(self):
        config = {"games": []}
        catalog = game_identity.GameCatalog(config)
        first, warning = catalog.resolve(["/games/Foo"], {}, None)
        second, _ = catalog.resolve(["/other/foo"], {}, None)
        self.assertIsNone(warning)
        self.assertEqual(first.game_id, second.game_id)
        self.assertEqual(config["games"][0]["executable_aliases"], ["foo"])

    def test_ambiguous_alias_uses_defaults(self):
        config = {"games": [
            {"id": "1", "name": "One", "executable_aliases": ["game.exe"]},
            {"id": "2", "name": "Two", "executable_aliases": ["game.exe"]},
        ]}
        identity, warning = game_identity.GameCatalog(config).resolve(["game.exe"], {}, None)
        self.assertIsNone(identity)
        self.assertIn("ambiguous", warning)

    def test_profile_fields_independently_inherit_disable_and_override(self):
        cfg = {"affinity": "0-7", "nice": {"type": "absolute", "value": 5}}
        identity = game_identity.LaunchIdentity("id", "Game", (), (), "disabled",
                                                {"type": "offset", "offset": 2})
        self.assertEqual(game_identity.effective_policy(cfg, identity), {
            "affinity": None, "nice": {"type": "offset", "offset": 2},
        })


class GameModeDefaultTests(unittest.TestCase):
    @mock.patch("cpu_tools.get_cpu_info")
    def test_initial_defaults_use_preferred_cores_and_absolute_minus_one(self, cpu_info):
        cpu_info.return_value.topology.preferred = {0, 1, 4, 5}
        loaded = config._initialize_game_mode_defaults({"game_mode": {}})
        game_mode_config = loaded["game_mode"]
        self.assertEqual(game_mode_config["affinity"], "0-1,4-5")
        self.assertEqual(game_mode_config["nice"], {
            "type": "absolute", "value": -1,
        })
        self.assertTrue(game_mode_config["defaults_initialized"])

    @mock.patch("cpu_tools.get_cpu_info")
    def test_initialized_defaults_preserve_explicitly_disabled_fields(self, cpu_info):
        loaded = config._initialize_game_mode_defaults({"game_mode": {
            "defaults_initialized": True, "affinity": None, "nice": None,
        }})
        self.assertIsNone(loaded["game_mode"]["affinity"])
        self.assertIsNone(loaded["game_mode"]["nice"])
        cpu_info.assert_not_called()


class LaunchPolicyTests(unittest.TestCase):
    @mock.patch("game_mode.utils.set_nice", return_value=True)
    @mock.patch("game_mode.utils.set_affinity", return_value=True)
    @mock.patch("game_mode.os.getpriority", return_value=7)
    def test_offset_composes_with_current_nice_and_is_bounded(self, _priority, affinity, nice):
        errors = game_mode.apply_launch_policy(42, {
            "affinity": "0-3", "nice": {"type": "offset", "offset": 20,
                                          "floor": -15, "ceiling": 19},
        })
        self.assertEqual(errors, [])
        affinity.assert_called_once_with(42, "0-3")
        nice.assert_called_once_with(42, 19)


class GameSessionPreferenceTests(unittest.TestCase):
    @mock.patch.object(game_mode.GameSessionManager, "_load_state")
    @mock.patch.object(game_mode.GameSessionManager, "_persist")
    @mock.patch("game_mode.cpu_tools.set_x3d_mode", return_value=(True, "ok"))
    def test_disabling_ccd_switching_restores_mode_during_active_session(
        self, set_mode, _persist, _load_state
    ):
        manager = game_mode.GameSessionManager({"game_mode": {}})
        manager.sessions = {"session": {"token": "session"}}
        manager._saved_ccd = "frequency"
        manager._active_ccd = "cache"

        manager.set_ccd_preference(None)

        set_mode.assert_called_once_with("frequency")
        self.assertIsNone(manager._saved_ccd)
        self.assertIsNone(manager._active_ccd)
        self.assertIsNone(manager.config["game_mode"]["ccd_preference"])

    @mock.patch("process_lasso_game.os.execvp")
    @mock.patch("process_lasso_game.apply_launch_policy", return_value=[])
    @mock.patch("process_lasso_game._request")
    def test_wrapper_preserves_exact_argv_and_existing_environment(self, request, apply, execvp):
        request.return_value = {"ok": True, "token": "abc", "policy": {}}
        with mock.patch.dict(os.environ, {"LD_PRELOAD": "libexample.so"}, clear=True):
            process_lasso_game.main(["--", "command", "a b", "--flag"])
            self.assertEqual(os.environ["LD_PRELOAD"], "libexample.so")
            self.assertEqual(os.environ[game_mode.MARKER_ENV], "abc")
        execvp.assert_called_once_with("command", ["command", "a b", "--flag"])
        apply.assert_called_once_with(os.getpid(), {})


if __name__ == "__main__":
    unittest.main()
