import unittest
from unittest import mock

from monitor import MonitorThread
from probalance import ProBalance
from rules import RuleEngine
from runtime_cleanup import ProcessRuntimeCleanup


class ProcessRuntimeCleanupTests(unittest.TestCase):
    def test_forget_pid_notifies_every_owner_once(self):
        rule_engine = mock.Mock()
        probalance = mock.Mock()
        forget_monitor_state = mock.Mock()
        cleanup = ProcessRuntimeCleanup(
            rule_engine, probalance, forget_monitor_state
        )

        cleanup.forget_pid(73)

        rule_engine.forget_pid.assert_called_once_with(73)
        probalance.forget_pid.assert_called_once_with(73)
        forget_monitor_state.assert_called_once_with(73)

    def test_process_exit_routes_once_through_coordinator(self):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._known_pids = {73}
        monitor._process_cache = {
            73: {"pid": 73, "create_time": 1.0, "comm": "old"}
        }
        monitor._runtime_cleanup = mock.Mock()

        monitor._sync_processes([])

        monitor._runtime_cleanup.forget_pid.assert_called_once_with(73)

    @mock.patch("monitor._safe_proc_identity")
    def test_pid_reuse_routes_once_through_coordinator(self, safe_identity):
        monitor = MonitorThread(RuleEngine(), ProBalance({}), {})
        monitor._known_pids = {73}
        monitor._process_cache = {
            73: {"pid": 73, "create_time": 1.0, "comm": "same"}
        }
        proc = mock.Mock(pid=73)
        proc.create_time.return_value = 2.0
        proc.name.return_value = "same"
        safe_identity.return_value = None
        monitor._runtime_cleanup = mock.Mock()

        monitor._sync_processes([proc])

        monitor._runtime_cleanup.forget_pid.assert_called_once_with(73)


if __name__ == "__main__":
    unittest.main()
