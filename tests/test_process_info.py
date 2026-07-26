"""Tests for mutable worker records and immutable observed snapshots."""
from __future__ import annotations

import unittest

from process_info import ProcessSnapshot


class ProcessSnapshotTests(unittest.TestCase):
    def test_mapping_compatibility_is_read_only(self):
        snapshot = ProcessSnapshot(
            pid=7,
            create_time=1.0,
            comm="worker",
            name="worker",
            user="user",
            sudo=False,
            cpu_percent=12.5,
            mem_rss=1024,
            nice=0,
            affinity="0-3",
            ionice="2/4",
            cmdline="/usr/bin/worker",
        )

        self.assertEqual(snapshot["pid"], 7)
        self.assertEqual(snapshot.get("cpu_percent"), 12.5)
        self.assertEqual(dict(snapshot)["name"], "worker")
        with self.assertRaises(KeyError):
            _ = snapshot["missing"]
