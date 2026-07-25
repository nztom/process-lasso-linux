"""Shared interactive table-column configuration and reset helpers."""
from __future__ import annotations

from collections.abc import Collection, Mapping

from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget


def configure_columns(
    table: QTableWidget,
    widths: Mapping[int, int],
    *,
    hidden: Collection[int] = (),
) -> None:
    """Configure stable, movable columns with smooth horizontal scrolling."""
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.horizontalScrollBar().setSingleStep(24)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setMinimumSectionSize(44)
    header.setStretchLastSection(False)
    header.setSectionsClickable(True)
    header.setSectionsMovable(True)
    reset_columns(table, widths, hidden=hidden)


def reset_columns(
    table: QTableWidget,
    widths: Mapping[int, int],
    *,
    hidden: Collection[int] = (),
) -> None:
    """Restore logical order, default visibility, and configured widths."""
    header = table.horizontalHeader()
    hidden_columns = set(hidden)
    for logical_index in range(table.columnCount()):
        visual_index = header.visualIndex(logical_index)
        if visual_index != logical_index:
            header.moveSection(visual_index, logical_index)
        header.setSectionHidden(logical_index, logical_index in hidden_columns)
    for column, width in widths.items():
        header.resizeSection(column, width)
