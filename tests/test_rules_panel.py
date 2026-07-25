"""Tests for the saved-rules table layout."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QHeaderView

from gui.rules_panel import RulesPanel
from rules import RuleEngine


class RulesPanelLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_columns_have_stable_interactive_widths(self):
        panel = RulesPanel(RuleEngine())
        header = panel._table.horizontalHeader()

        self.assertFalse(header.stretchLastSection())
        for column, width in panel.DEFAULT_COLUMN_WIDTHS.items():
            self.assertEqual(
                header.sectionResizeMode(column),
                QHeaderView.ResizeMode.Interactive,
            )
            self.assertEqual(header.sectionSize(column), width)

    def test_wide_table_uses_smooth_horizontal_scrolling(self):
        panel = RulesPanel(RuleEngine())

        self.assertEqual(
            panel._table.horizontalScrollMode(),
            panel._table.ScrollMode.ScrollPerPixel,
        )
        self.assertEqual(panel._table.horizontalScrollBar().singleStep(), 24)

    def test_columns_are_clickable_and_movable(self):
        panel = RulesPanel(RuleEngine())
        header = panel._table.horizontalHeader()

        self.assertTrue(header.sectionsClickable())
        self.assertTrue(header.sectionsMovable())

    def test_reset_restores_column_order_visibility_and_widths(self):
        panel = RulesPanel(RuleEngine())
        header = panel._table.horizontalHeader()
        header.moveSection(header.visualIndex(2), 0)
        header.setSectionHidden(3, True)
        header.resizeSection(2, 500)

        panel._reset_column_layout()

        self.assertEqual(
            [header.visualIndex(i) for i in range(len(panel.COLUMNS))],
            list(range(len(panel.COLUMNS))),
        )
        for column, width in panel.DEFAULT_COLUMN_WIDTHS.items():
            self.assertFalse(header.isSectionHidden(column))
            self.assertEqual(header.sectionSize(column), width)


if __name__ == "__main__":
    unittest.main()
