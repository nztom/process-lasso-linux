"""Tests for mutable worker records and immutable observed snapshots."""
from __future__ import annotations

import unittest

from dataclasses import FrozenInstanceError

from policy_models import AbsoluteNicePolicy, EffectiveProcessPolicy
from process_info import ProcessPolicyView, ProcessSnapshot


class ProcessSnapshotTests(unittest.TestCase):
    @staticmethod
    def _snapshot() -> ProcessSnapshot:
        return ProcessSnapshot(
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

    def test_mapping_compatibility_is_read_only(self):
        snapshot = self._snapshot()

        self.assertEqual(snapshot["pid"], 7)
        self.assertEqual(snapshot.get("cpu_percent"), 12.5)
        self.assertEqual(dict(snapshot)["name"], "worker")
        with self.assertRaises(KeyError):
            _ = snapshot["missing"]

    def test_joined_view_is_immutable_and_delegates_observed_fields(self):
        view = ProcessPolicyView(
            observed=self._snapshot(),
            effective_policy=EffectiveProcessPolicy(
                nice=AbsoluteNicePolicy(-8)
            ),
            manually_overridden=True,
        )

        self.assertEqual(view["pid"], 7)
        self.assertEqual(view.get("name"), "worker")
        self.assertEqual(view.effective_policy.nice, AbsoluteNicePolicy(-8))
        self.assertTrue(view.manually_overridden)
        with self.assertRaises(FrozenInstanceError):
            view.manually_overridden = False
