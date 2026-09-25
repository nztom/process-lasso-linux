"""Configuration defaults and migration tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config


class MonitorConfigTests(unittest.TestCase):
    @mock.patch("cpu_tools.get_cpu_info")
    def test_load_migrates_legacy_intervals_to_process_scan_value(self, cpu_info):
        cpu_info.return_value.topology.preferred = set()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text(json.dumps({
                "version": 2,
                "monitor": {
                    "rule_enforce_interval_ms": 300,
                    "process_scan_interval_ms": 800,
                    "display_refresh_interval_ms": 1700,
                },
                "game_mode": {
                    "defaults_initialized": True,
                    "wrappers": [],
                    "environment": [],
                },
            }))
            with mock.patch.object(config, "CONFIG_DIR", Path(temp_dir)), \
                    mock.patch.object(config, "CONFIG_FILE", config_file):
                loaded = config.load()
                persisted = json.loads(config_file.read_text())

        self.assertEqual(loaded["monitor"], {"interval_ms": 800})
        self.assertEqual(persisted["monitor"], {"interval_ms": 800})
        cpu_info.assert_not_called()

    def test_unified_interval_takes_precedence_over_legacy_values(self):
        configured = {"monitor": {
            "interval_ms": 600,
            "process_scan_interval_ms": 900,
        }}

        self.assertEqual(config.monitor_interval_ms(configured), 600)

    def test_monitor_interval_is_safely_bounded(self):
        self.assertEqual(
            config.monitor_interval_ms({"monitor": {"interval_ms": 1}}),
            config.MONITOR_INTERVAL_MIN_MS,
        )
        self.assertEqual(
            config.monitor_interval_ms({"monitor": {"interval_ms": "invalid"}}),
            config.MONITOR_INTERVAL_DEFAULT_MS,
        )


if __name__ == "__main__":
    unittest.main()
