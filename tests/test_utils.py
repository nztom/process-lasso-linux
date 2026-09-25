"""Tests for process priority helpers."""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import utils


class SetNiceTests(unittest.TestCase):
    @mock.patch("utils.os.sched_getaffinity")
    @mock.patch("utils.get_process_tids", return_value=[100, 101, 102])
    def test_aggregate_affinity_unions_all_live_thread_masks(
        self, _get_tids, get_affinity
    ):
        get_affinity.side_effect = [{0}, {0, 1, 2}, {6, 7}]

        aggregate = utils.get_aggregate_affinity_str(100, "0")

        self.assertEqual(aggregate, "0-2,6-7")

    @mock.patch("utils.os.sched_getaffinity")
    @mock.patch("utils.get_process_tids", return_value=[100, 101])
    def test_aggregate_affinity_ignores_threads_that_exit_during_read(
        self, _get_tids, get_affinity
    ):
        get_affinity.side_effect = [{0, 1}, ProcessLookupError]

        self.assertEqual(utils.get_aggregate_affinity_str(100, "4-7"), "0-1")

    @mock.patch("utils.get_process_tids", return_value=[])
    def test_aggregate_affinity_falls_back_when_process_has_exited(self, _get_tids):
        self.assertEqual(utils.get_aggregate_affinity_str(100, "4-7"), "4-7")

    @mock.patch("utils.os.listdir", side_effect=FileNotFoundError)
    def test_missing_process_has_no_threads(self, listdir):
        self.assertEqual(utils.get_process_tids(1234), [])

    @mock.patch("nice_helper.set_negative_nice_threads", return_value={1234, 1235})
    @mock.patch("utils.get_process_tids", return_value=[1234, 1235])
    @mock.patch("utils.subprocess.run")
    def test_negative_nice_uses_privileged_helper(self, run, _get_tids, helper):
        self.assertTrue(utils.set_nice(1234, -1))

        helper.assert_called_once_with([1234, 1235], -1)
        run.assert_not_called()

    @mock.patch("nice_helper.set_negative_nice_threads", return_value=set())
    @mock.patch("utils.get_process_tids", return_value=[1234])
    @mock.patch("utils.subprocess.run")
    def test_negative_nice_propagates_helper_failure(self, run, _get_tids, helper):
        self.assertFalse(utils.set_nice(1234, -5))

        helper.assert_called_once_with([1234], -5)
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
    def test_thread_affinity_excludes_offline_cpus(self, set_affinity, _online):
        self.assertTrue(utils.set_thread_affinity(1235, "0-3"))

        set_affinity.assert_called_once_with(1235, {0, 1})

    @mock.patch("utils.get_online_cpus", return_value={0, 1})
    @mock.patch("utils.os.sched_setaffinity")
    def test_thread_affinity_fails_when_every_requested_cpu_is_offline(
        self, set_affinity, _online
    ):
        self.assertFalse(utils.set_thread_affinity(1235, "2-3"))

        set_affinity.assert_not_called()

    @mock.patch("utils.get_process_tids", return_value=[1234, 1235])
    @mock.patch("utils.get_online_cpus", return_value={0, 1, 2, 3})
    @mock.patch("utils._set_thread_affinity_set", return_value=True)
    def test_process_affinity_uses_shared_thread_setter(
        self, set_thread, _online, _tids
    ):
        self.assertTrue(utils.set_affinity(1234, "0-3"))

        self.assertEqual(set_thread.call_args_list, [
            mock.call(1234, {0, 1, 2, 3}),
            mock.call(1235, {0, 1, 2, 3}),
        ])

    @mock.patch("nice_helper.set_negative_nice_threads", return_value={1235})
    def test_negative_thread_nice_uses_shared_batch_helper(self, helper):
        self.assertTrue(utils.set_thread_nice(1235, -8))

        helper.assert_called_once_with([1235], -8)

    @mock.patch("utils._set_thread_nice_batch", return_value={1234, 1235})
    @mock.patch("utils.get_process_tids", return_value=[1234, 1235])
    def test_process_nice_uses_shared_batch_setter(self, _get_tids, set_batch):
        self.assertTrue(utils.set_process_nice(1234, 5))

        set_batch.assert_called_once_with([1234, 1235], 5)

    @mock.patch("utils._set_thread_nice_batch", return_value={1235})
    def test_thread_nice_uses_shared_batch_setter(self, set_batch):
        self.assertTrue(utils.set_thread_nice(1235, 5))

        set_batch.assert_called_once_with([1235], 5)

    @mock.patch("utils._set_thread_nice_batch", return_value={1234, 1235})
    def test_nice_thread_batch_uses_shared_batch_setter(self, set_batch):
        self.assertEqual(utils.set_nice_threads([1235, 1234], 5), {1234, 1235})

        set_batch.assert_called_once_with([1235, 1234], 5)


if __name__ == "__main__":
    unittest.main()
