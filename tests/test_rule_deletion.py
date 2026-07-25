"""Tests for deleting saved process rules."""
from __future__ import annotations

import os
import pathlib
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QMessageBox

from gui.rules_panel import RulesPanel
from rules import Rule, RuleEngine


class RuleDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.engine = RuleEngine()
        self.first_rule = Rule(name="First", pattern="first")
        self.second_rule = Rule(name="Second", pattern="second")
        self.engine.add_rule(self.first_rule)
        self.engine.add_rule(self.second_rule)

    def test_engine_removes_only_rule_with_matching_id(self):
        self.engine.remove_rule(self.first_rule.rule_id)

        self.assertEqual(self.engine.get_rules(), [self.second_rule])

    def test_engine_ignores_unknown_rule_id(self):
        self.engine.remove_rule("missing-rule-id")

        self.assertEqual(
            self.engine.get_rules(),
            [self.first_rule, self.second_rule],
        )

    @mock.patch(
        "gui.rules_panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    )
    def test_confirmed_delete_removes_selected_rule_and_refreshes_panel(
        self,
        question,
    ):
        panel = RulesPanel(self.engine)
        panel._table.setCurrentCell(0, 0)
        changed = QSignalSpy(panel.rules_changed)

        panel._delete_selected()

        self.assertEqual(self.engine.get_rules(), [self.second_rule])
        self.assertEqual(panel._table.rowCount(), 1)
        self.assertEqual(panel._table.item(0, 2).text(), "Second")
        self.assertEqual(len(changed), 1)
        question.assert_called_once()

    @mock.patch(
        "gui.rules_panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    )
    def test_cancelled_delete_keeps_rule_and_emits_no_change(self, question):
        panel = RulesPanel(self.engine)
        panel._table.setCurrentCell(0, 0)
        changed = QSignalSpy(panel.rules_changed)

        panel._delete_selected()

        self.assertEqual(
            self.engine.get_rules(),
            [self.first_rule, self.second_rule],
        )
        self.assertEqual(panel._table.rowCount(), 2)
        self.assertEqual(len(changed), 0)
        question.assert_called_once()

    def test_delete_without_selection_does_nothing(self):
        panel = RulesPanel(self.engine)
        panel._table.clearSelection()
        panel._table.setCurrentCell(-1, -1)
        changed = QSignalSpy(panel.rules_changed)

        panel._delete_selected()

        self.assertEqual(
            self.engine.get_rules(),
            [self.first_rule, self.second_rule],
        )
        self.assertEqual(len(changed), 0)


if __name__ == "__main__":
    unittest.main()
