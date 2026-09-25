"""Tests for the privileged negative-nice wrapper."""
from __future__ import annotations

import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import nice_helper


class NiceHelperTests(unittest.TestCase):
    @mock.patch("nice_helper.utils.get_thread_nice", return_value=0)
    @mock.patch("nice_helper.subprocess.run")
    def test_sets_every_requested_thread(self, run, getpriority):
        run.return_value.returncode = 0

        self.assertEqual(
            nice_helper.set_negative_nice_threads([1234, 1235], -1),
            {1234, 1235},
        )

        run.assert_called_once_with(
            ["sudo", nice_helper.HELPER, "renice-pids", "-1", "1234", "1235"],
            capture_output=True, text=True, timeout=10,
        )

    @mock.patch("nice_helper.utils.get_thread_nice", return_value=-1)
    @mock.patch("nice_helper.subprocess.run")
    def test_skips_threads_already_at_target(self, run, getpriority):
        self.assertEqual(
            nice_helper.set_negative_nice_threads([1234, 1235], -1),
            {1234, 1235},
        )
        run.assert_not_called()

    @mock.patch("nice_helper.subprocess.run")
    def test_rejects_non_negative_nice(self, run):
        self.assertEqual(nice_helper.set_negative_nice_threads([1234], 0), set())
        run.assert_not_called()

    @mock.patch("nice_helper.subprocess.run")
    def test_rejects_invalid_tid(self, run):
        self.assertEqual(nice_helper.set_negative_nice_threads([0], -1), set())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
