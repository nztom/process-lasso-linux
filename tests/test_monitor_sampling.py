"""Tests for cached process identity and dynamic metric sampling."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest

import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from monitor import _safe_proc_identity, _update_proc_metrics


class MonitorSamplingTests(unittest.TestCase):
    def test_identity_and_metrics_are_collected_separately(self):
        proc = psutil.Process(os.getpid())

        info = _safe_proc_identity(proc)

        self.assertIsNotNone(info)
        self.assertIn("cmdline", info)
        self.assertEqual(info["mem_rss"], 0)

        self.assertTrue(_update_proc_metrics(proc, info, include_details=True))
        self.assertGreater(info["mem_rss"], 0)
        self.assertTrue(info["affinity"])


if __name__ == "__main__":
    unittest.main()
