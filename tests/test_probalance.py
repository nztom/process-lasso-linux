"""Tests for ProBalance safety behavior."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from probalance import ProBalance


class ProBalanceTests(unittest.TestCase):
    @mock.patch("probalance.utils.set_nice")
    def test_never_throttles_its_own_process(self, set_nice):
        probalance = ProBalance({
            "enabled": True,
            "cpu_threshold_percent": 1.0,
            "consecutive_seconds": 0,
            "nice_adjustment": 10,
            "nice_floor": 15,
        })

        probalance.tick([{
            "pid": os.getpid(),
            "name": "python3",
            "cpu_percent": 100.0,
            "nice": 0,
        }], 10.0)

        set_nice.assert_not_called()
        self.assertEqual(probalance.get_throttled_pids(), set())

    @mock.patch("probalance.utils.set_nice", return_value=True)
    def test_disabling_restores_all_throttled_processes(self, set_nice):
        config = {
            "enabled": True,
            "cpu_threshold_percent": 1.0,
            "consecutive_seconds": 0,
            "nice_adjustment": 10,
            "nice_floor": 15,
        }
        probalance = ProBalance(config)
        snapshot = [
            {"pid": 101, "name": "worker-a", "cpu_percent": 100.0, "nice": 0},
            {"pid": 202, "name": "worker-b", "cpu_percent": 100.0, "nice": 5},
        ]
        probalance.tick(snapshot, 1.0)
        self.assertEqual(probalance.get_throttled_pids(), {101, 202})

        probalance.update_config({**config, "enabled": False})

        self.assertEqual(
            set_nice.call_args_list,
            [
                mock.call(101, 10),
                mock.call(202, 15),
                mock.call(101, 0),
                mock.call(202, 5),
            ],
        )
        self.assertEqual(probalance.get_throttled_pids(), set())

    @mock.patch("probalance.utils.set_nice", side_effect=[True, False, True])
    def test_disabled_tick_retries_failed_restore(self, set_nice):
        config = {
            "enabled": True,
            "cpu_threshold_percent": 1.0,
            "consecutive_seconds": 0,
        }
        probalance = ProBalance(config)
        probalance.tick([
            {"pid": 101, "name": "worker", "cpu_percent": 100.0, "nice": 0},
        ], 1.0)

        probalance.update_config({**config, "enabled": False})
        self.assertEqual(probalance.get_throttled_pids(), {101})

        probalance.tick([], 1.0)

        self.assertEqual(probalance.get_throttled_pids(), set())


if __name__ == "__main__":
    unittest.main()
