"""Tests for process-table column defaults."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QSignalSpy

from gui.dialogs import NicePriorityDialog
from gui.process_table import ProcessTable, _CLOCK_TICKS, _parse_thread_cpu_stat
from process_info import ProcessPolicyView, ProcessSnapshot
from rules import Rule, RuleEngine


class ProcessTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_command_column_is_hidden_by_default(self):
        table = ProcessTable(None, None)

        self.assertEqual(table.COLUMNS[table.COMMAND_COLUMN], "Command")
        self.assertTrue(table.isColumnHidden(table.COMMAND_COLUMN))

    def test_thread_cpu_stat_uses_task_specific_ticks(self):
        fields = ["S"] + ["0"] * 19
        fields[11] = "3"
        fields[12] = "2"
        fields[19] = "99"

        created, cpu_seconds = _parse_thread_cpu_stat(
            "123 (worker thread) " + " ".join(fields)
        )

        self.assertEqual(created, 99)
        self.assertEqual(cpu_seconds, 5 / _CLOCK_TICKS)

    def test_sudo_column_is_hidden_by_default(self):
        table = ProcessTable(None, None)

        self.assertEqual(table.COLUMNS[table.SUDO_COLUMN], "Sudo")
        self.assertTrue(table.isColumnHidden(table.SUDO_COLUMN))

    def test_command_column_contains_full_command_line(self):
        table = ProcessTable(None, None)
        table.set_hide_root(False)
        command = "sudo -n /usr/bin/sleep 10"
        table.update_snapshot([{
            "pid": 1234,
            "name": "sleep",
            "user": "root",
            "sudo": True,
            "cpu_percent": 0.0,
            "mem_rss": 1024,
            "nice": 0,
            "affinity": "0-3",
            "ionice": "2/4",
            "cmdline": command,
        }])

        self.assertEqual(table.item(0, table.COMMAND_COLUMN).text(), command)

    def test_all_column_data_is_left_aligned(self):
        table = ProcessTable(None, None)
        table.set_hide_root(False)
        table.update_snapshot([{
            "pid": 1234,
            "name": "sleep",
            "user": "user",
            "sudo": False,
            "cpu_percent": 12.3,
            "mem_rss": 1_048_576,
            "nice": 0,
            "affinity": "0-3",
            "ionice": "2/4",
            "cmdline": "/usr/bin/sleep 10",
        }])

        for column in range(table.columnCount()):
            alignment = table.item(0, column).textAlignment()
            self.assertTrue(alignment & Qt.AlignmentFlag.AlignLeft, column)
            self.assertFalse(alignment & Qt.AlignmentFlag.AlignRight, column)

    def test_columns_are_movable(self):
        table = ProcessTable(None, None)
        self.assertTrue(table.horizontalHeader().sectionsMovable())

    def test_horizontal_scrolling_is_smooth(self):
        table = ProcessTable(None, None)

        self.assertEqual(
            table.horizontalScrollMode(),
            table.ScrollMode.ScrollPerPixel,
        )
        self.assertEqual(table.horizontalScrollBar().singleStep(), 24)

    def test_columns_use_stable_interactive_widths(self):
        table = ProcessTable(None, None)
        header = table.horizontalHeader()

        for column, width in table.DEFAULT_COLUMN_WIDTHS.items():
            self.assertEqual(
                header.sectionResizeMode(column),
                header.ResizeMode.Interactive,
            )
            if column not in table.DEFAULT_HIDDEN_COLUMNS:
                self.assertEqual(header.sectionSize(column), width)

    def test_reset_restores_default_order_and_visibility(self):
        table = ProcessTable(None, None)
        header = table.horizontalHeader()
        header.moveSection(header.visualIndex(2), 0)
        table.setColumnHidden(1, True)
        table.setColumnHidden(table.COMMAND_COLUMN, False)
        header.resizeSection(1, 500)

        table._reset_column_layout()

        self.assertEqual(
            [header.visualIndex(i) for i in range(len(table.COLUMNS))],
            list(range(len(table.COLUMNS))),
        )
        for column in range(len(table.COLUMNS)):
            self.assertEqual(
                table.isColumnHidden(column),
                column in table.DEFAULT_HIDDEN_COLUMNS,
            )
            if column not in table.DEFAULT_HIDDEN_COLUMNS:
                self.assertEqual(
                    header.sectionSize(column),
                    table.DEFAULT_COLUMN_WIDTHS[column],
                )

    def test_always_rule_uses_exact_process_name(self):
        table = ProcessTable(None, None)
        spy = QSignalSpy(table.rule_add_requested)

        table._emit_always_rule(
            {"pid": 1234, "name": "blackdesert64.exe"},
            "CPU Priority",
            nice=-10,
        )

        self.assertEqual(len(spy), 1)
        rule = spy[0][0]
        self.assertEqual(rule.pattern, "blackdesert64.exe")
        self.assertEqual(rule.match_type, "exact")
        self.assertEqual(rule.nice, -10)
        self.assertIsNone(rule.affinity)
        self.assertIsNone(rule.ionice_class)

    def test_parse_ionice_display_value(self):
        self.assertEqual(ProcessTable._parse_ionice("2/7"), (2, 7))
        self.assertEqual(ProcessTable._parse_ionice(""), (2, 4))

    def test_non_preset_always_priority_omits_custom_label(self):
        self.assertEqual(ProcessTable._format_nice(-8), "-8")

    def test_current_priority_dialog_supports_nice_offsets(self):
        dialog = NicePriorityDialog(current_nice=5)
        dialog._mode.setCurrentIndex(dialog._mode.findData("offset"))
        dialog._spin.setValue(-8)

        self.assertEqual(dialog._mode.currentText(), "Offset")
        self.assertEqual(dialog.get_mode(), "offset")
        self.assertEqual(dialog.get_offset(), -8)
        self.assertEqual(dialog.get_nice(), -3)
        self.assertEqual(dialog._target.text(), "→ nice -3")

    def test_current_priority_dialog_shows_applied_offset_without_compounding(self):
        dialog = NicePriorityDialog(
            current_nice=-6, initial_mode="offset", initial_offset=-5,
        )

        self.assertEqual(dialog.get_mode(), "offset")
        self.assertEqual(dialog.get_offset(), -5)
        self.assertEqual(dialog.get_nice(), -6)
        self.assertEqual(dialog._target.text(), "→ nice -6")

        dialog._spin.setValue(-4)
        self.assertEqual(dialog.get_nice(), -5)

    def test_current_priority_offset_is_clamped_to_linux_nice_range(self):
        dialog = NicePriorityDialog(current_nice=18)
        dialog._mode.setCurrentIndex(dialog._mode.findData("offset"))
        dialog._spin.setValue(10)

        self.assertEqual(dialog.get_nice(), 19)

    def test_current_priority_negative_offset_is_clamped_to_linux_nice_range(self):
        dialog = NicePriorityDialog(current_nice=-18)
        dialog._mode.setCurrentIndex(dialog._mode.findData("offset"))
        dialog._spin.setValue(-10)

        self.assertEqual(dialog.get_nice(), -20)
        self.assertEqual(dialog._target.text(), "→ nice -20")

    @mock.patch("gui.process_table.utils.set_nice", return_value=True)
    @mock.patch("gui.process_table.NicePriorityDialog")
    def test_current_priority_action_applies_offset_target(
        self, dialog_class, set_nice
    ):
        dialog = dialog_class.return_value
        dialog.exec.return_value = dialog_class.DialogCode.Accepted
        dialog.get_nice.return_value = -3
        dialog.get_mode.return_value = "offset"
        dialog.get_offset.return_value = -8
        messages = []
        table = ProcessTable(None, messages.append)
        changed = QSignalSpy(table.rule_value_manually_changed)

        table._do_set_nice(self._process(42, "game.exe", "user") | {"nice": 5})

        dialog_class.assert_called_once_with(
            5, table, "game.exe", initial_mode="absolute", initial_offset=0,
        )
        set_nice.assert_called_once_with(42, -3)
        self.assertEqual(list(changed[0]), [42])
        self.assertEqual(
            messages,
            ["Set nice offset=-8 (target=-3) on game.exe(42)"],
        )

    @mock.patch("gui.process_table.NicePriorityDialog")
    def test_current_priority_action_initializes_from_effective_offset_rule(
        self, dialog_class
    ):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game.exe", match_type="exact", nice=-6,
            nice_mode="offset", nice_offset=-5,
        ))
        dialog_class.return_value.exec.return_value = (
            dialog_class.DialogCode.Rejected
        )
        table = ProcessTable(engine, None)

        table._do_set_nice(self._process(42, "game.exe", "user") | {"nice": -6})

        dialog_class.assert_called_once_with(
            -6, table, "game.exe", initial_mode="offset", initial_offset=-5,
        )

    @mock.patch("gui.process_table.utils.set_nice", return_value=False)
    @mock.patch("gui.process_table.NicePriorityDialog")
    def test_failed_current_priority_offset_does_not_emit_manual_change(
        self, dialog_class, set_nice
    ):
        dialog = dialog_class.return_value
        dialog.exec.return_value = dialog_class.DialogCode.Accepted
        dialog.get_nice.return_value = -3
        dialog.get_mode.return_value = "offset"
        dialog.get_offset.return_value = -8
        messages = []
        table = ProcessTable(None, messages.append)
        changed = QSignalSpy(table.rule_value_manually_changed)

        table._do_set_nice(self._process(42, "game.exe", "user") | {"nice": 5})

        set_nice.assert_called_once_with(42, -3)
        self.assertEqual(len(changed), 0)
        self.assertEqual(
            messages,
            ["Failed to set nice offset=-8 (target=-3) on game.exe(42) (root needed?)"],
        )

    def test_process_table_shows_current_and_always_rule_values(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            name="Game",
            pattern="game.exe",
            match_type="exact",
            affinity="4-7",
            nice=-10,
            ionice_class=3,
        ))
        table = ProcessTable(engine, None)
        table.update_snapshot([{
            "pid": 42,
            "name": "game.exe",
            "user": "user",
            "sudo": False,
            "cpu_percent": 1.0,
            "mem_rss": 1024,
            "nice": 0,
            "affinity": "0-7",
            "ionice": "2/4",
            "cmdline": "game.exe",
        }])

        self.assertEqual(table.item(0, table.NICE_CURRENT_COLUMN).text(), "0")
        self.assertEqual(table.item(0, table.NICE_ALWAYS_COLUMN).text(), "Absolute -10")
        self.assertEqual(table.item(0, table.AFFINITY_CURRENT_COLUMN).text(), "0-7")
        self.assertEqual(table.item(0, table.AFFINITY_ALWAYS_COLUMN).text(), "4-7")
        self.assertEqual(table.item(0, table.IONICE_CURRENT_COLUMN).text(), "2/4")
        self.assertEqual(table.item(0, table.IONICE_ALWAYS_COLUMN).text(), "Very Low (3)")

    def test_always_columns_refresh_immediately_after_rule_edit(self):
        engine = RuleEngine()
        rule = Rule(pattern="game.exe", match_type="exact", affinity="0-3", nice=-8)
        engine.add_rule(rule)
        table = ProcessTable(engine, None)
        table.update_snapshot([self._process(42, "game.exe", "user")])

        rule.affinity = "4-7"
        rule.nice = -5
        engine.update_rule(rule)
        table.refresh_rule_columns()

        self.assertEqual(table.item(0, table.AFFINITY_ALWAYS_COLUMN).text(), "4-7")
        self.assertEqual(table.item(0, table.NICE_ALWAYS_COLUMN).text(), "Absolute -5")

    def test_rule_refresh_rebuilds_policy_without_new_metrics_snapshot(self):
        engine = RuleEngine()
        rule = Rule(pattern="game.exe", match_type="exact", nice=-8)
        engine.add_rule(rule)
        observed = ProcessSnapshot(
            pid=42, create_time=1.0, comm="game.exe", name="game.exe",
            user="user", sudo=False, cpu_percent=10.0, mem_rss=1024,
            nice=0, affinity="0-3", ionice="2/4", cmdline="game.exe",
        )
        view = ProcessPolicyView(
            observed=observed,
            effective_policy=engine.effective_policy(observed.name),
        )
        table = ProcessTable(engine, None)
        table.set_hide_root(False)
        table.update_snapshot([view])

        rule.nice = -5
        engine.update_rule(rule)
        table.refresh_rule_columns()

        rebuilt = table._snapshot[0]
        self.assertIsInstance(rebuilt, ProcessPolicyView)
        self.assertIs(rebuilt.observed, observed)
        self.assertEqual(rebuilt.effective_policy.nice.value, -5)

    def test_offset_always_column_shows_policy_not_internal_nice_marker(self):
        engine = RuleEngine()
        engine.add_rule(Rule(
            pattern="game.exe", match_type="exact", nice=-8,
            nice_mode="offset", nice_offset=-5, nice_floor=-15, nice_ceiling=19,
        ))
        table = ProcessTable(engine, None)
        table.update_snapshot([self._process(42, "game.exe", "user")])

        self.assertEqual(
            table.item(0, table.NICE_ALWAYS_COLUMN).text(),
            "Offset -5 [-15, 19]",
        )

    def test_root_processes_are_hidden_by_default_and_can_be_shown(self):
        table = ProcessTable(None, None)
        snapshot = [
            self._process(pid=1, name="root-task", user="root"),
            self._process(pid=2, name="user-task", user="user"),
        ]

        table.update_snapshot(snapshot)
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 1).text(), "user-task")

        table.set_hide_root(False)
        self.assertEqual(table.rowCount(), 2)

    def test_processes_can_be_filtered_by_user(self):
        table = ProcessTable(None, None)
        table.set_hide_root(False)
        table.update_snapshot([
            self._process(pid=1, name="one", user="alice"),
            self._process(pid=2, name="two", user="bob"),
        ])

        table.set_user_filter("bob")

        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 2).text(), "bob")

    def test_process_row_expands_to_display_its_threads(self):
        threads = [{
            "tid": 101,
            "name": "worker",
            "cpu_percent": 12.3,
            "nice": 5,
            "affinity": "0-1",
            "ionice": "2/4",
        }]
        table = ProcessTable(None, None, thread_provider=lambda pid: threads)
        table.set_hide_root(False)
        table.update_snapshot([self._process(100, "server", "user")])

        table._toggle_threads_for_row(0, 1)

        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(table.item(1, 0).text(), "101")
        self.assertEqual(table.item(1, 1).text().strip(), "↳ worker")
        self.assertEqual(table.item(1, 4).text(), "12.3")
        self.assertEqual(table.item(1, 5).text(), "")
        self.assertEqual(table.item(1, table.NICE_CURRENT_COLUMN).text(), "5")
        self.assertEqual(table.item(1, table.AFFINITY_CURRENT_COLUMN).text(), "0-1")
        self.assertEqual(table.item(1, table.STATUS_COLUMN).text(), "Thread")

    def test_expand_arrow_is_on_pid_cell_only(self):
        table = ProcessTable(None, None, thread_provider=lambda pid: [])
        table.set_hide_root(False)
        table.update_snapshot([self._process(100, "server", "user")])

        self.assertFalse(table.item(0, 0).icon().isNull())
        self.assertTrue(table.item(0, 1).icon().isNull())

    def test_thread_expansion_persists_across_snapshots_and_collapses(self):
        calls = []

        def threads(pid):
            calls.append(pid)
            return [{
                "tid": 101, "name": "worker", "nice": 0,
                "affinity": "0-3", "ionice": "2/4",
            }]

        table = ProcessTable(None, None, thread_provider=threads)
        table.set_hide_root(False)
        snapshot = [self._process(100, "server", "user")]
        table.update_snapshot(snapshot)
        table._toggle_threads_for_row(0, 1)
        table.update_snapshot(snapshot)

        self.assertEqual(table.rowCount(), 2)
        self.assertEqual(calls, [100, 100])

        table._toggle_threads_for_row(0, 1)
        self.assertEqual(table.rowCount(), 1)

    def test_thread_rows_are_excluded_from_process_actions(self):
        thread = {
            "tid": 101, "name": "worker", "nice": 0,
            "affinity": "0-3", "ionice": "2/4",
        }
        table = ProcessTable(None, None, thread_provider=lambda pid: [thread])
        table.set_hide_root(False)
        table.update_snapshot([self._process(100, "server", "user")])
        table._toggle_threads_for_row(0, 1)
        table.setCurrentCell(1, 0)
        table.selectRow(1)

        self.assertIsNone(table._selected_proc())
        self.assertEqual(table._selected_procs(), [])

    def test_expansion_is_forgotten_when_process_exits(self):
        table = ProcessTable(None, None, thread_provider=lambda pid: [])
        table.set_hide_root(False)
        table.update_snapshot([self._process(100, "server", "user")])
        table._toggle_threads_for_row(0, 1)
        table.update_snapshot([])

        self.assertNotIn(100, table._expanded_pids)

    @staticmethod
    def _process(pid: int, name: str, user: str) -> dict:
        return {
            "pid": pid,
            "name": name,
            "user": user,
            "sudo": user == "root",
            "cpu_percent": 0.0,
            "mem_rss": 1024,
            "nice": 0,
            "affinity": "0-3",
            "ionice": "2/4",
            "cmdline": name,
        }

    def test_always_rule_reuses_existing_rule_id(self):
        engine = RuleEngine()
        existing = Rule(
            name="game.exe — CPU Affinity",
            pattern="game.exe",
            match_type="exact",
            affinity="0-3",
            force_apply=True,
        )
        engine.add_rule(existing)
        table = ProcessTable(engine, None)
        spy = QSignalSpy(table.rule_add_requested)

        table._emit_always_rule(
            {"pid": 42, "name": "game.exe"},
            "CPU Affinity",
            affinity="4-7",
        )

        updated = spy[0][0]
        self.assertEqual(updated.rule_id, existing.rule_id)
        self.assertEqual(updated.affinity, "4-7")
        self.assertTrue(updated.force_apply)

    @mock.patch(
        "gui.process_table.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    )
    def test_clear_process_rule_requests_removal_without_applying_changes(self, question):
        engine = RuleEngine()
        matching = Rule(name="Game priority", pattern="game.exe", match_type="exact", nice=-5)
        unrelated = Rule(name="Other", pattern="other.exe", match_type="exact", nice=5)
        engine.add_rule(matching)
        engine.add_rule(unrelated)
        table = ProcessTable(engine, None)
        spy = QSignalSpy(table.rule_remove_requested)

        table._do_clear_rules({"pid": 42, "name": "game.exe"}, [matching.rule_id])

        self.assertEqual(spy[0][0], [matching.rule_id])
        self.assertEqual(engine.get_rules(), [matching, unrelated])
        question.assert_called_once()

    def test_clear_process_rule_only_lists_matching_rules(self):
        engine = RuleEngine()
        matching = Rule(name="Game", pattern="game.exe", match_type="exact")
        engine.add_rule(matching)
        engine.add_rule(Rule(name="Other", pattern="other.exe", match_type="exact"))

        table = ProcessTable(engine, None)

        self.assertEqual(table._matching_rules("game.exe"), [matching])


if __name__ == "__main__":
    unittest.main()
