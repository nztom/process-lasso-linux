"""Tests for process-table column defaults."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

from gui.process_table import ProcessTable


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

    def test_columns_are_movable(self):
        table = ProcessTable(None, None)
        self.assertTrue(table.horizontalHeader().sectionsMovable())

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


if __name__ == "__main__":
    unittest.main()
