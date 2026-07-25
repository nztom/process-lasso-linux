from __future__ import annotations

import json
import stat
import pathlib
import tempfile
import unittest
from unittest import mock

from rules import Rule, RuleEngine
from thread_priority_state import ThreadPriorityState, parse_proc_stat_start_time


class RuleModelOffsetTests(unittest.TestCase):
    def test_old_rule_defaults_to_absolute(self):
        rule = Rule.from_dict({"pattern": "game", "nice": -8})
        self.assertEqual(rule.nice_mode, "absolute")

    def test_offset_defaults_and_serialization(self):
        rule = Rule.from_dict({"pattern": "game", "nice": 0, "nice_mode": "offset"})
        self.assertEqual((rule.nice_floor, rule.nice_ceiling), (-15, 19))
        self.assertEqual(rule.to_dict()["nice_mode"], "offset")

    def test_invalid_bounds_are_rejected(self):
        for floor, ceiling in ((0, -1), (-21, 19), (-15, 20)):
            with self.subTest(floor=floor, ceiling=ceiling), self.assertRaises(ValueError):
                Rule.from_dict({"nice_mode": "offset", "nice_floor": floor,
                                "nice_ceiling": ceiling})

    def test_proc_stat_parser_handles_parentheses(self):
        tail = ["S"] + [str(i) for i in range(4, 23)]
        tail[19] = "987654"
        self.assertEqual(parse_proc_stat_start_time("12 (odd ) name) " + " ".join(tail)), 987654)


class OffsetApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name) / "state.json"
        self.state = ThreadPriorityState(self.path, debounce_seconds=0.5)
        self.state.boot_id = "boot"
        self.engine = RuleEngine(self.state)
        self.rule = Rule(rule_id="rule", name="Game", pattern="game", nice=0,
                         nice_mode="offset", nice_offset=-5,
                         nice_floor=-15, nice_ceiling=19)
        self.engine.add_rule(self.rule)

    def tearDown(self):
        self.temp.cleanup()

    @mock.patch("rules.thread_identity", side_effect=lambda p, t, r, b: f"boot:{p}:1:{t}:2:{r}")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=10)
    def test_applies_once_and_ignores_later_changes(self, get_nice, set_nice, identity):
        self.engine._apply_offset_threads(self.rule, 100, [101], "game")
        self.engine._apply_offset_threads(self.rule, 100, [101], "game")
        set_nice.assert_called_once_with([101], 5)
        get_nice.assert_called_once_with(101)

    @mock.patch("rules.thread_identity", return_value="boot:100:1:102:3:rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=-5)
    def test_new_thread_inheriting_applied_target_does_not_compound(
        self, get_nice, set_nice, identity
    ):
        self.state.entries["boot:100:1:101:2:rule"] = {
            "original_nice": 0, "target_nice": -5, "status": "applied",
        }

        self.engine._apply_offset_threads(self.rule, 100, [102], "game")

        entry = self.state.get("boot:100:1:102:3:rule")
        self.assertEqual(entry["original_nice"], 0)
        self.assertEqual(entry["original_source"], "inherited_target")
        set_nice.assert_called_once_with([102], -5)

    @mock.patch("rules.thread_identity", return_value="boot:100:1:103:4:rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    def test_inherited_worker_target_preserves_worker_original(
        self, get_nice, set_nice, identity
    ):
        self.state.entries["boot:100:1:101:2:rule"] = {
            "original_nice": 5, "target_nice": 0, "status": "applied",
        }

        self.engine._apply_offset_threads(self.rule, 100, [103], "game")

        self.assertEqual(
            self.state.get("boot:100:1:103:4:rule")["original_nice"], 5
        )
        set_nice.assert_called_once_with([103], 0)

    def test_ambiguous_target_tie_prefers_process_leader(self):
        self.state.entries = {
            "boot:100:1:100:2:rule": {
                "original_nice": 0, "target_nice": -5, "status": "applied",
            },
            "boot:100:1:101:3:rule": {
                "original_nice": 5, "target_nice": -5, "status": "applied",
            },
        }

        self.assertEqual(
            self.state.inferred_original_for_process_target(
                "boot:100:1:102:4:rule", -5
            ),
            0,
        )

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=-14)
    def test_bounds_and_rule_edit_use_saved_original(self, get_nice, set_nice, identity):
        self.engine._apply_offset_threads(self.rule, 100, [101], "game")
        self.rule.nice_offset = 10
        self.rule.nice_ceiling = -10
        self.engine._apply_offset_threads(self.rule, 100, [101], "game")
        self.assertEqual(set_nice.call_args_list, [mock.call([101], -15), mock.call([101], -10)])
        get_nice.assert_called_once()

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:rule")
    @mock.patch("rules.utils.set_nice_threads", return_value=set())
    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    def test_failed_update_is_not_marked_applied(self, get_nice, set_nice, identity):
        self.engine._apply_offset_threads(self.rule, 100, [101], "game")
        entry = next(iter(self.state.entries.values()))
        self.assertEqual(entry["status"], "failed")

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=-8)
    def test_startup_hint_records_zero_instead_of_current_clamped_value(
        self, get_nice, set_nice, identity
    ):
        self.engine._apply_offset_threads(
            self.rule, 100, [101], "game", original_nice_hint=0
        )

        entry = self.state.get("boot:100:1:101:2:rule")
        self.assertEqual(entry["original_nice"], 0)
        set_nice.assert_called_once_with([101], -5)
        get_nice.assert_not_called()

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:offset-rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=-13)
    def test_startup_hint_repairs_existing_absolute_plus_offset_baseline(
        self, get_nice, set_nice, identity
    ):
        self.state.entries = {
            "boot:100:1:101:2:absolute-rule": {
                "original_nice": -8, "mode": "absolute",
                "target_nice": -8, "status": "applied",
            },
            "boot:100:1:101:2:offset-rule": {
                "original_nice": -8, "offset": -5, "floor": -15,
                "ceiling": 19, "target_nice": -13, "status": "applied",
            },
        }
        offset = Rule(rule_id="offset-rule", pattern="game", nice=0,
                      nice_mode="offset", nice_offset=-5)

        self.engine._apply_offset_threads(
            offset, 100, [101], "game", original_nice_hint=0
        )

        self.assertEqual(
            {entry["original_nice"] for entry in self.state.entries.values()}, {0}
        )
        set_nice.assert_called_once_with([101], -5)
        get_nice.assert_not_called()

    def test_pending_batch_is_one_atomic_write_and_applied_is_debounced(self):
        with mock.patch.object(self.state, "_write", wraps=self.state._write) as write:
            self.state.set_pending_many({"a": {"original_nice": 0}, "b": {"original_nice": 1}})
            self.assertEqual(write.call_count, 1)
            self.state.set_applied("a", -5)
            self.state.set_applied("b", -4)
            self.assertEqual(write.call_count, 1)
            self.state.flush_if_due(float("inf"))
            self.assertEqual(write.call_count, 2)
        self.assertEqual(set(json.loads(self.path.read_text())["entries"]), {"a", "b"})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:absolute-rule")
    @mock.patch("rules.utils.get_thread_nice", return_value=0)
    def test_absolute_records_original_before_clamping(self, get_nice, identity):
        absolute = Rule(rule_id="absolute-rule", pattern="game", nice=-8)
        keyed = self.engine._prepare_absolute_threads(absolute, 100, [101])
        self.engine._finish_absolute_threads(keyed, -8, True)

        entry = self.state.get("boot:100:1:101:2:absolute-rule")
        self.assertEqual(entry["original_nice"], 0)
        self.assertEqual(entry["target_nice"], -8)
        self.assertEqual(entry["status"], "applied")

    @mock.patch("rules.thread_identity", side_effect=lambda p, t, r, b: f"boot:{p}:1:{t}:2:{r}")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", side_effect=[0])
    def test_absolute_to_offset_reuses_original_across_rule_ids(
        self, get_nice, set_nice, identity
    ):
        absolute = Rule(rule_id="absolute-rule", pattern="game", nice=-8)
        keyed = self.engine._prepare_absolute_threads(absolute, 100, [101])
        self.engine._finish_absolute_threads(keyed, -8, True)

        offset = Rule(rule_id="offset-rule", pattern="game", nice=0,
                      nice_mode="offset", nice_offset=-5)
        self.engine._apply_offset_threads(offset, 100, [101], "game")

        set_nice.assert_called_once_with([101], -5)
        get_nice.assert_called_once_with(101)

    @mock.patch("rules.thread_identity", return_value="boot:100:1:101:2:rule")
    @mock.patch("rules.utils.set_nice_threads", side_effect=lambda tids, target: set(tids))
    @mock.patch("rules.utils.get_thread_nice", return_value=-8)
    def test_restart_uses_persisted_original_not_absolute_target(
        self, get_nice, set_nice, identity
    ):
        self.state.set_pending_many({
            "boot:100:1:101:2:rule": {
                "original_nice": 0, "mode": "absolute", "target_nice": -8,
            }
        })
        self.state.set_applied("boot:100:1:101:2:rule", -8)
        self.state.flush()

        with mock.patch("thread_priority_state.read_boot_id", return_value="boot"):
            restarted = RuleEngine(ThreadPriorityState(self.path))
        restarted._apply_offset_threads(self.rule, 100, [101], "game")

        set_nice.assert_called_once_with([101], -5)
        get_nice.assert_not_called()


if __name__ == "__main__":
    unittest.main()
