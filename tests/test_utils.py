"""Tests for process priority helpers."""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import utils


class SetNiceTests(unittest.TestCase):
    @mock.patch("utils.os.listdir", side_effect=FileNotFoundError)
    def test_missing_process_has_no_threads(self, listdir):
        self.assertEqual(utils.get_process_tids(1234), [])

    @mock.patch("nice_helper.set_negative_nice", return_value=True)
    @mock.patch("utils.subprocess.run")
    def test_negative_nice_uses_privileged_helper(self, run, helper):
        self.assertTrue(utils.set_nice(1234, -1))

        helper.assert_called_once_with(1234, -1)
        run.assert_not_called()

    @mock.patch("nice_helper.set_negative_nice", return_value=False)
    @mock.patch("utils.subprocess.run")
    def test_negative_nice_propagates_helper_failure(self, run, helper):
        self.assertFalse(utils.set_nice(1234, -5))

        helper.assert_called_once_with(1234, -5)
        run.assert_not_called()

    @mock.patch("utils.subprocess.run")
    @mock.patch("utils.get_process_tids", return_value=[1234, 1235])
    def test_non_negative_nice_sets_all_threads_unprivileged(self, get_tids, run):
        run.return_value.returncode = 0

        self.assertTrue(utils.set_nice(1234, 5))

        run.assert_called_once_with(
            ["renice", "-n", "5", "-p", "1234", "1235"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @mock.patch("utils.get_online_cpus", return_value={0, 1, 2, 3})
    @mock.patch("utils.os.sched_setaffinity")
    def test_thread_affinity_targets_only_requested_tid(
        self, set_affinity, _online
    ):
        self.assertTrue(utils.set_thread_affinity(1235, "0-3"))

        set_affinity.assert_called_once_with(1235, {0, 1, 2, 3})

    @mock.patch("utils.get_online_cpus", return_value={0, 1})
    @mock.patch("utils.os.sched_setaffinity")
    def test_thread_affinity_excludes_parked_cpus(self, set_affinity, _online):
        self.assertTrue(utils.set_thread_affinity(1235, "0-3"))

        set_affinity.assert_called_once_with(1235, {0, 1})

    @mock.patch("utils.get_online_cpus", return_value={0, 1})
    @mock.patch("utils.os.sched_setaffinity")
    def test_thread_affinity_fails_when_every_requested_cpu_is_parked(
        self, set_affinity, _online
    ):
        self.assertFalse(utils.set_thread_affinity(1235, "2-3"))

        set_affinity.assert_not_called()

    @mock.patch("nice_helper.set_negative_nice_thread", return_value=True)
    def test_negative_thread_nice_uses_single_thread_helper(self, helper):
        self.assertTrue(utils.set_thread_nice(1235, -8))

        helper.assert_called_once_with(1235, -8)


if __name__ == "__main__":
    unittest.main()
