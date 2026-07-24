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


if __name__ == "__main__":
    unittest.main()
