"""Tests for process-table column defaults."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QSignalSpy

from gui.process_table import ProcessTable
from rules import Rule, RuleEngine


class ProcessTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_command_column_is_hidden_by_default(self):
        table = ProcessTable(None, None)

        self.assertEqual(table.COLUMNS[table.COMMAND_COLUMN], "Command")
        self.assertTrue(table.isColumnHidden(table.COMMAND_COLUMN))

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
        self.assertEqual(table.item(0, table.NICE_ALWAYS_COLUMN).text(), "High (-10)")
        self.assertEqual(table.item(0, table.AFFINITY_CURRENT_COLUMN).text(), "0-7")
        self.assertEqual(table.item(0, table.AFFINITY_ALWAYS_COLUMN).text(), "4-7")
        self.assertEqual(table.item(0, table.IONICE_CURRENT_COLUMN).text(), "2/4")
        self.assertEqual(table.item(0, table.IONICE_ALWAYS_COLUMN).text(), "Very Low (3)")

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


if __name__ == "__main__":
    unittest.main()
