"""Tests for cached process identity and dynamic metric sampling."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from monitor import MonitorThread, _safe_proc_identity, _update_proc_metrics
from probalance import ProBalance
from rules import RuleEngine


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

    def test_snapshot_records_are_detached_from_worker_cache(self):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._process_cache = {7: {"pid": 7, "cpu_percent": 1.0}}

        snapshot = monitor._snapshot_records()
        monitor._process_cache[7]["cpu_percent"] = 99.0

        self.assertEqual(snapshot[0]["cpu_percent"], 1.0)

    @mock.patch("monitor._safe_proc_identity")
    def test_pid_reuse_clears_all_old_process_state(self, safe_identity):
        engine = RuleEngine()
        probalance = ProBalance({})
        monitor = MonitorThread(engine, probalance, {})
        monitor._known_pids = {7}
        monitor._process_cache = {
            7: {"pid": 7, "comm": "game", "create_time": 1.0}
        }
        monitor._original_affinities[7] = frozenset({0})
        monitor._gaming_niced[7] = 0
        probalance._states[7] = mock.Mock()
        proc = mock.Mock(pid=7)
        proc.create_time.return_value = 2.0
        proc.name.return_value = "game"
        replacement = {
            "pid": 7, "comm": "game", "name": "game",
            "create_time": 2.0,
        }
        safe_identity.return_value = replacement

        with mock.patch.object(monitor, "_apply_new_pid") as apply_new:
            monitor._sync_processes([proc])

        self.assertIs(monitor._process_cache[7], replacement)
        self.assertNotIn(7, monitor._original_affinities)
        self.assertNotIn(7, monitor._gaming_niced)
        self.assertNotIn(7, probalance._states)
        apply_new.assert_called_once_with(replacement)

    @mock.patch("monitor._safe_proc_identity")
    def test_exec_refreshes_metadata_but_keeps_lifetime_state(self, safe_identity):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._known_pids = {7}
        monitor._process_cache = {
            7: {"pid": 7, "comm": "launcher", "create_time": 1.0}
        }
        original = frozenset({0, 1})
        monitor._original_affinities[7] = original
        proc = mock.Mock(pid=7)
        proc.create_time.return_value = 1.0
        proc.name.return_value = "game"
        replacement = {
            "pid": 7, "comm": "game", "name": "game",
            "create_time": 1.0,
        }
        safe_identity.return_value = replacement

        with mock.patch.object(monitor, "_apply_new_pid") as apply_new:
            monitor._sync_processes([proc])

        self.assertEqual(monitor._original_affinities[7], original)
        self.assertIs(monitor._process_cache[7], replacement)
        apply_new.assert_called_once_with(replacement)


if __name__ == "__main__":
    unittest.main()
