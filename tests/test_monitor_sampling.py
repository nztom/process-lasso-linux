"""Tests for cached process identity and dynamic metric sampling."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from monitor import MonitorThread, _safe_proc_identity, _update_proc_metrics
from process_info import ProcessIdentity, ProcessPolicyView, ProcessSnapshot
from probalance import ProBalance
from rules import Rule, RuleEngine


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
        monitor._process_cache = {7: {
            "pid": 7,
            "create_time": 1.0,
            "comm": "worker",
            "name": "worker",
            "user": "user",
            "sudo": False,
            "cpu_percent": 1.0,
            "mem_rss": 1024,
            "nice": 0,
            "affinity": "0-3",
            "ionice": "2/4",
            "cmdline": "/usr/bin/worker",
        }}

        snapshot = monitor._snapshot_records()
        monitor._process_cache[7]["cpu_percent"] = 99.0
        snapshot.append({"pid": 9})

        self.assertIsInstance(snapshot[0], ProcessPolicyView)
        self.assertIsInstance(snapshot[0].observed, ProcessSnapshot)
        self.assertEqual(snapshot[0]["cpu_percent"], 1.0)
        self.assertEqual(monitor._process_cache[7]["pid"], 7)
        self.assertEqual(monitor._process_cache[7]["cpu_percent"], 99.0)

        with self.assertRaises(FrozenInstanceError):
            snapshot[0].observed.pid = 8
        with self.assertRaises(TypeError):
            snapshot[0]["pid"] = 8

    def test_snapshot_joins_effective_policy_and_manual_override_once(self):
        engine = RuleEngine()
        engine.add_rule(Rule(pattern="worker", nice=-8))
        monitor = MonitorThread(engine, ProBalance({}), {})
        monitor._process_cache = {7: {
            "pid": 7, "create_time": 1.0, "comm": "worker", "name": "worker",
            "user": "user", "sudo": False, "cpu_percent": 1.0,
            "mem_rss": 1024, "nice": 0, "affinity": "0-3",
            "ionice": "2/4", "cmdline": "/usr/bin/worker",
        }}
        monitor._manually_overridden_pids.add(7)

        with mock.patch.object(
            engine, "effective_policy", wraps=engine.effective_policy
        ) as effective_policy:
            views = monitor._snapshot_records()

        effective_policy.assert_called_once_with("worker")
        self.assertEqual(views[0].effective_policy.nice.value, -8)
        self.assertTrue(views[0].manually_overridden)

    def test_process_exit_clears_all_transient_state(self):
        engine = RuleEngine()
        rule = Rule(rule_id="policy", pattern="game", affinity="0-3")
        engine.add_rule(rule)
        engine.suppress_pid(7)
        engine._affinity_seen.add("boot:7:1:7:2:policy")
        engine._affinity_drift_attempts["boot:7:1:7:2:policy"] = 3
        engine._affinity_released.add("boot:7:1:7:2:policy")
        probalance = ProBalance({})
        probalance._states[ProcessIdentity(7, 1.0)] = mock.Mock()
        monitor = MonitorThread(engine, probalance, {})
        monitor._known_pids = {7}
        monitor._process_cache = {
            7: {"pid": 7, "comm": "game", "create_time": 1.0}
        }
        monitor._original_affinities[7] = frozenset({0})
        monitor._gaming_niced[7] = 0
        monitor._known_tids_by_pid[7] = {7, 8}
        monitor._manually_overridden_pids.add(7)

        monitor._sync_processes([])

        self.assertEqual(monitor._known_pids, set())
        self.assertNotIn(7, monitor._process_cache)
        self.assertNotIn(7, monitor._original_affinities)
        self.assertNotIn(7, monitor._gaming_niced)
        self.assertNotIn(7, monitor._known_tids_by_pid)
        self.assertNotIn(7, monitor._manually_overridden_pids)
        self.assertFalse(any(key.pid == 7 for key in probalance._states))
        self.assertNotIn(7, engine._attempts_by_rule[rule.rule_id])
        self.assertNotIn((rule.rule_id, 7), engine._suppressed_rule_pids)
        self.assertFalse(engine._affinity_seen)
        self.assertFalse(engine._affinity_drift_attempts)
        self.assertFalse(engine._affinity_released)

    @mock.patch("monitor.utils.get_process_tids", return_value=[100])
    def test_startup_process_rule_does_not_replace_persisted_nice_baseline(
        self, get_tids
    ):
        engine = RuleEngine()
        monitor = MonitorThread(engine, ProBalance({}), {})
        info = {"pid": 100, "name": "game.exe", "nice": -8}

        with mock.patch.object(engine, "matches_process", return_value=True), \
             mock.patch.object(engine, "apply_to_process") as apply:
            monitor._apply_new_pid(info)
            monitor._apply_new_pid({"pid": 101, "name": "game.exe", "nice": 7})

        self.assertEqual(apply.call_args_list, [
            mock.call(100, "game.exe"),
            mock.call(101, "game.exe"),
        ])

    @mock.patch("monitor._safe_proc_identity")
    def test_pid_reuse_clears_all_old_process_state(self, safe_identity):
        engine = RuleEngine()
        rule = Rule(rule_id="policy", pattern="game", affinity="0-3")
        engine.add_rule(rule)
        engine.suppress_pid(7)
        engine._affinity_seen.add("boot:7:1:7:2:policy")
        engine._affinity_drift_attempts["boot:7:1:7:2:policy"] = 3
        engine._affinity_released.add("boot:7:1:7:2:policy")
        probalance = ProBalance({})
        monitor = MonitorThread(engine, probalance, {})
        monitor._known_pids = {7}
        monitor._process_cache = {
            7: {"pid": 7, "comm": "game", "create_time": 1.0}
        }
        monitor._original_affinities[7] = frozenset({0})
        monitor._gaming_niced[7] = 0
        monitor._known_tids_by_pid[7] = {7, 8}
        monitor._manually_overridden_pids.add(7)
        probalance._states[ProcessIdentity(7, 1.0)] = mock.Mock()
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
        self.assertNotIn(7, monitor._known_tids_by_pid)
        self.assertNotIn(7, monitor._manually_overridden_pids)
        self.assertFalse(any(key.pid == 7 for key in probalance._states))
        self.assertNotIn(7, engine._attempts_by_rule[rule.rule_id])
        self.assertNotIn((rule.rule_id, 7), engine._suppressed_rule_pids)
        self.assertFalse(engine._affinity_seen)
        self.assertFalse(engine._affinity_drift_attempts)
        self.assertFalse(engine._affinity_released)
        apply_new.assert_called_once_with(replacement)

    @mock.patch("monitor.utils.get_process_tids", return_value=[100, 101, 102])
    def test_new_threads_are_applied_once_and_remembered(self, get_tids):
        engine = RuleEngine()
        monitor = MonitorThread(engine, ProBalance({}), {})
        monitor._process_cache = {100: {"pid": 100, "name": "game.exe"}}
        monitor._known_tids_by_pid = {100: {100, 101}}

        with mock.patch.object(engine, "matches_process", return_value=True), \
             mock.patch.object(engine, "apply_to_thread") as apply_thread:
            monitor._sync_new_threads()
            monitor._sync_new_threads()

        apply_thread.assert_called_once_with(100, 102, "game.exe")
        self.assertEqual(monitor._known_tids_by_pid[100], {100, 101, 102})

    @mock.patch("monitor.utils.set_thread_affinity", return_value=True)
    @mock.patch("monitor.utils.get_process_tids", return_value=[200, 201])
    def test_new_threads_receive_default_affinity(self, get_tids, set_affinity):
        monitor = MonitorThread(
            RuleEngine(),
            ProBalance({}),
            {"cpu": {"default_affinity": "0-3"}},
        )
        monitor._process_cache = {200: {"pid": 200, "name": "worker"}}
        monitor._known_tids_by_pid = {200: {200}}

        monitor._sync_new_threads()

        set_affinity.assert_called_once_with(201, "0-3")

    @mock.patch("monitor.utils.set_thread_affinity", return_value=True)
    @mock.patch("monitor.utils.get_process_tids", return_value=[200, 201])
    def test_manual_override_suppresses_default_on_new_threads(
        self, get_tids, set_affinity
    ):
        monitor = MonitorThread(
            RuleEngine(),
            ProBalance({}),
            {"cpu": {"default_affinity": "0-3"}},
        )
        monitor._process_cache = {200: {"pid": 200, "name": "worker"}}
        monitor._known_tids_by_pid = {200: {200}}
        monitor.set_manual_rule_override(200)

        monitor._sync_new_threads()

        set_affinity.assert_not_called()

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
