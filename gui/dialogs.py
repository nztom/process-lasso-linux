"""Dialogs for setting affinity, nice priority, and ionice priority."""
from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QComboBox, QGridLayout, QCheckBox, QWidget,
    QScrollArea, QGroupBox, QDialogButtonBox, QMessageBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QLineEdit,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QTimer
import utils


class AffinityDialog(QDialog):
    """CPU affinity picker: topology-aware checkbox grid."""

    def __init__(self, current_affinity: str = "", parent=None,
                 title_suffix: str = "", current_summary: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Set CPU Affinity{' — ' + title_suffix if title_suffix else ''}")
        # Always use total CPU count (present), not just online count
        import cpu_tools
        self._cpu_info = cpu_tools.get_cpu_info()
        self._cpu_count = self._cpu_info.cpu_count
        self._checkboxes: list[QCheckBox] = []
        self._build_ui(current_affinity, current_summary)
        self.setMinimumWidth(520)
        self.adjustSize()

    def _build_ui(self, current_affinity: str, current_summary: str = ""):
        layout = QVBoxLayout(self)
        selected = self._parse_cpulist(current_affinity)

        if current_summary:
            current = QLabel(f"Current affinity: {current_summary}")
            current.setWordWrap(True)
            layout.addWidget(current)

        # Gather topology info for CCD-aware display
        try:
            import cpu_tools
            offline = self._cpu_info.offline
            topo = self._cpu_info.topology
            smt_siblings = self._cpu_info.smt_siblings
        except Exception:
            offline = set()
            topo = None
            smt_siblings = set()

        preferred   = set(topo.preferred)     if (topo and topo.has_asymmetry) else set()
        non_pref    = set(topo.non_preferred)  if (topo and topo.has_asymmetry) else set()
        self._preferred = preferred
        self._non_pref  = non_pref
        self._smt_siblings = smt_siblings

        # cb_map[cpu] = QCheckBox for that CPU
        cb_map: dict[int, QCheckBox] = {}

        group = QGroupBox("Select CPUs")
        grid = QGridLayout(group)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)

        if preferred and non_pref:
            # ── Topology-aware: group by CCD + physical/HT ──────────────
            pref_phys  = sorted(c for c in preferred if c not in smt_siblings)
            pref_ht    = sorted(c for c in preferred if c in smt_siblings)
            npref_phys = sorted(c for c in non_pref  if c not in smt_siblings)
            npref_ht   = sorted(c for c in non_pref  if c in smt_siblings)

            if self._cpu_info.features.amd_x3d:
                ccd0_name, ccd1_name = "CCD0 (V-Cache — preferred)", "CCD1 (frequency optimized)"
            else:
                ccd0_name, ccd1_name = "Preferred CPUs", "Non-preferred CPUs"

            row = [0]

            def add_section(title: str, cpus: list[int]):
                hdr = QLabel(title)
                hdr.setStyleSheet(
                    "font-size: 11px; font-weight: 600; "
                    "color: rgba(167,139,250,0.9); padding-top: 6px;"
                )
                grid.addWidget(hdr, row[0], 0, 1, 8)
                row[0] += 1
                for col, cpu in enumerate(cpus):
                    cb = QCheckBox(str(cpu))
                    cb.setChecked(cpu in selected)
                    if cpu in offline:
                        cb.setEnabled(False)
                        cb.setToolTip(f"CPU {cpu} is currently offline")
                    grid.addWidget(cb, row[0], col)
                    cb_map[cpu] = cb
                row[0] += 1

            if pref_phys:
                add_section(f"  {ccd0_name} — physical cores", pref_phys)
            if pref_ht:
                add_section(f"  {ccd0_name} — HT siblings", pref_ht)
            if npref_phys:
                add_section(f"  {ccd1_name} — physical cores", npref_phys)
            if npref_ht:
                add_section(f"  {ccd1_name} — HT siblings", npref_ht)

        else:
            # ── Flat grid fallback for uniform / unknown topology ────────
            cols = 8
            for i in range(self._cpu_count):
                cb = QCheckBox(str(i))
                cb.setChecked(i in selected)
                if i in offline:
                    cb.setEnabled(False)
                    cb.setToolTip(f"CPU {i} is currently offline")
                r, c = divmod(i, cols)
                grid.addWidget(cb, r, c)
                cb_map[i] = cb

        # Build ordered list: self._checkboxes[i] = checkbox for CPU i
        self._checkboxes = [cb_map.get(i, QCheckBox(str(i))) for i in range(self._cpu_count)]

        if offline:
            offline_str = utils._cpuset_to_cpulist(offline)
            note = QLabel(f"⚠  CPUs {offline_str} are currently offline and cannot be selected.")
            note.setStyleSheet("color: rgba(249,226,175,0.85); font-size: 11px;")
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addWidget(group)

        btn_row = QHBoxLayout()
        all_btn  = QPushButton("All")
        none_btn = QPushButton("None")
        all_btn.clicked.connect(self._select_all)
        none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)

        if preferred and non_pref:
            if self._cpu_info.features.amd_x3d:
                ccd0_label, ccd1_label = "CCD0 (V-Cache)", "CCD1"
            else:
                ccd0_label, ccd1_label = "Preferred CCD", "Non-preferred CCD"

            sep = QLabel("|")
            sep.setStyleSheet("color: rgba(255,255,255,0.3); margin: 0 4px;")
            btn_row.addWidget(sep)

            ccd0_btn = QPushButton(ccd0_label)
            ccd0_btn.setToolTip(f"Select only {ccd0_label} CPUs: {sorted(preferred)}")
            ccd0_btn.clicked.connect(lambda: self._select_set(preferred))
            btn_row.addWidget(ccd0_btn)

            ccd1_btn = QPushButton(ccd1_label)
            ccd1_btn.setToolTip(f"Select only {ccd1_label} CPUs: {sorted(non_pref)}")
            ccd1_btn.clicked.connect(lambda: self._select_set(non_pref))
            btn_row.addWidget(ccd1_btn)

            ccd0_phys = preferred - smt_siblings
            if ccd0_phys != preferred:
                ccd0p_btn = QPushButton(f"{ccd0_label} (no SMT)")
                ccd0p_btn.setToolTip(f"Select only physical cores of {ccd0_label}: {sorted(ccd0_phys)}")
                ccd0p_btn.clicked.connect(lambda: self._select_set(ccd0_phys))
                btn_row.addWidget(ccd0p_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _parse_cpulist(self, cpulist: str) -> set[int]:
        result = set()
        if not cpulist:
            return set(range(self._cpu_count))
        for part in cpulist.split(","):
            part = part.strip()
            if "-" in part:
                sub = part.split("-")
                try:
                    lo, hi = int(sub[0]), int(sub[1])
                    result.update(range(lo, hi + 1))
                except ValueError:
                    pass
            else:
                try:
                    result.add(int(part))
                except ValueError:
                    pass
        return result

    def _select_all(self):
        for cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(True)

    def _select_none(self):
        for cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(False)

    def _select_set(self, cpus: set[int]):
        for i, cb in enumerate(self._checkboxes):
            if cb.isEnabled():
                cb.setChecked(i in cpus)

    def _validate_and_accept(self):
        selected = [i for i, cb in enumerate(self._checkboxes) if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Invalid", "At least one CPU must be selected.")
            return
        self.accept()

    def get_cpulist(self) -> str:
        """Return compact cpulist string for selected CPUs."""
        selected = sorted(i for i, cb in enumerate(self._checkboxes) if cb.isChecked())
        if not selected:
            return ""
        ranges = []
        start = selected[0]
        end = selected[0]
        for c in selected[1:]:
            if c == end + 1:
                end = c
            else:
                ranges.append(f"{start}-{end}" if start != end else str(start))
                start = end = c
        ranges.append(f"{start}-{end}" if start != end else str(start))
        return ",".join(ranges)


class NicePriorityDialog(QDialog):
    """Absolute or relative nice priority picker (-20 to 19)."""

    def __init__(
        self, current_nice: int = 0, parent=None, title_suffix: str = "",
        initial_mode: str = "absolute", initial_offset: int = 0,
        initial_floor: int = -15, initial_ceiling: int = 19,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Set CPU Priority (nice){' — ' + title_suffix if title_suffix else ''}")
        self._initial_mode = initial_mode if initial_mode == "offset" else "absolute"
        self._initial_offset = max(-39, min(39, initial_offset))
        self._initial_floor = max(-20, min(19, initial_floor))
        self._initial_ceiling = max(self._initial_floor, min(19, initial_ceiling))
        self._build_ui(current_nice)

    def _build_ui(self, current_nice: int):
        self._current_nice = max(-20, min(19, current_nice))
        layout = QVBoxLayout(self)

        info = QLabel(
            "Nice priority: lower = higher priority.\n"
            "Negative values require root (will fail silently if not root)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Mode:"))
        self._mode = QComboBox()
        self._mode.addItem("Absolute", "absolute")
        self._mode.addItem("Offset", "offset")
        row.addWidget(self._mode)
        row.addWidget(QLabel("Value:"))
        self._spin = QSpinBox()
        self._spin.setRange(-20, 19)
        self._spin.setValue(self._current_nice)
        row.addWidget(self._spin)
        self._target = QLabel()
        row.addWidget(self._target)
        row.addStretch()
        layout.addLayout(row)

        self._bounds = QWidget()
        bounds_row = QHBoxLayout(self._bounds)
        bounds_row.setContentsMargins(0, 0, 0, 0)
        bounds_row.addWidget(QLabel("Offset bounds — floor:"))
        self._floor_spin = QSpinBox()
        self._floor_spin.setRange(-20, 19)
        self._floor_spin.setValue(self._initial_floor)
        bounds_row.addWidget(self._floor_spin)
        bounds_row.addWidget(QLabel("ceiling:"))
        self._ceiling_spin = QSpinBox()
        self._ceiling_spin.setRange(-20, 19)
        self._ceiling_spin.setValue(self._initial_ceiling)
        bounds_row.addWidget(self._ceiling_spin)
        bounds_row.addStretch()
        layout.addWidget(self._bounds)

        self._mode.currentIndexChanged.connect(self._update_mode)
        self._spin.valueChanged.connect(self._update_target)
        self._mode.setCurrentIndex(self._mode.findData(self._initial_mode))
        self._update_mode(reset_value=True)

        # Windows Process Lasso calls these CPU Priority Classes. Linux has a
        # continuous nice range, so these are the closest useful equivalents.
        presets_row = QHBoxLayout()
        presets_row.addWidget(QLabel("Priority class:"))
        for label, val in [
            ("Real-time (-20)", -20),
            ("High (-10)", -10),
            ("Above normal (-5)", -5),
            ("Normal (0)", 0),
            ("Below normal (5)", 5),
            ("Idle (19)", 19),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, v=val: self._set_absolute(v))
            presets_row.addWidget(btn)
        presets_row.addStretch()
        layout.addLayout(presets_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_nice(self) -> int:
        if self._mode.currentData() == "offset":
            # If an offset rule produced the live value, adjust relative to that
            # policy so accepting its unchanged offset does not apply it twice.
            baseline_offset = (
                self._initial_offset if self._initial_mode == "offset" else 0
            )
            adjustment = self._spin.value() - baseline_offset
            return max(-20, min(19, self._current_nice + adjustment))
        return self._spin.value()

    def get_mode(self) -> str:
        return self._mode.currentData()

    def get_offset(self) -> int:
        return self._spin.value() if self.get_mode() == "offset" else 0

    def get_floor(self) -> int:
        return self._floor_spin.value()

    def get_ceiling(self) -> int:
        return self._ceiling_spin.value()

    def _validate_and_accept(self):
        if self.get_mode() == "offset" and self.get_floor() > self.get_ceiling():
            QMessageBox.warning(self, "Invalid", "Nice floor cannot exceed ceiling.")
            return
        self.accept()

    def _set_absolute(self, value: int):
        self._mode.setCurrentIndex(self._mode.findData("absolute"))
        self._spin.setValue(value)

    def _update_mode(self, _index=None, *, reset_value: bool = True):
        offset = self._mode.currentData() == "offset"
        if offset:
            self._spin.setRange(-39, 39)
        else:
            self._spin.setRange(-20, 19)
        if reset_value:
            self._spin.setValue(
                self._initial_offset
                if offset and self._initial_mode == "offset"
                else 0 if offset else self._current_nice
            )
        self._update_target()
        self._bounds.setVisible(offset)

    def _update_target(self):
        if self._mode.currentData() == "offset":
            self._target.setText(f"→ nice {self.get_nice()}")
        else:
            self._target.clear()


class IoNiceDialog(QDialog):
    """I/O priority class and level picker."""

    CLASSES = [
        (0, "None (default)"),
        (1, "Realtime (root)"),
        (2, "Best-effort"),
        (3, "Idle"),
    ]

    def __init__(self, current_class: int = 2, current_level: int = 4, parent=None, title_suffix: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"Set I/O Priority{' — ' + title_suffix if title_suffix else ''}")
        self._build_ui(current_class, current_level)

    def _build_ui(self, current_class: int, current_level: int):
        layout = QVBoxLayout(self)

        info = QLabel(
            "Linux mapping for Process Lasso I/O priorities: High = best-effort 0, "
            "Normal = best-effort 4, Low = best-effort 7, and Very Low = idle."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        grid = QGridLayout()
        grid.addWidget(QLabel("I/O Class:"), 0, 0)
        self._class_combo = QComboBox()
        for val, label in self.CLASSES:
            self._class_combo.addItem(label, val)
        idx = next((i for i, (v, _) in enumerate(self.CLASSES) if v == current_class), 2)
        self._class_combo.setCurrentIndex(idx)
        self._class_combo.currentIndexChanged.connect(self._on_class_changed)
        grid.addWidget(self._class_combo, 0, 1)

        grid.addWidget(QLabel("I/O Level (0-7):"), 1, 0)
        self._level_spin = QSpinBox()
        self._level_spin.setRange(0, 7)
        self._level_spin.setValue(current_level)
        grid.addWidget(self._level_spin, 1, 1)
        layout.addLayout(grid)

        presets_row = QHBoxLayout()
        presets_row.addWidget(QLabel("Priority class:"))
        for label, io_class, level in [
            ("High", 2, 0),
            ("Normal", 2, 4),
            ("Low", 2, 7),
            ("Very Low", 3, 0),
        ]:
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked, c=io_class, n=level: self._set_preset(c, n)
            )
            presets_row.addWidget(button)
        presets_row.addStretch()
        layout.addLayout(presets_row)

        self._on_class_changed()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_class_changed(self):
        cls = self._class_combo.currentData()
        self._level_spin.setEnabled(cls in (1, 2))

    def _set_preset(self, io_class: int, level: int):
        index = self._class_combo.findData(io_class)
        if index >= 0:
            self._class_combo.setCurrentIndex(index)
        self._level_spin.setValue(level)

    def get_ionice_class(self) -> int:
        return self._class_combo.currentData()

    def get_ionice_level(self) -> int:
        return self._level_spin.value()


class SteamGamePickerDialog(QDialog):
    """Browse the local Steam library and pick a game to launch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick Steam Game")
        self.setMinimumSize(560, 480)
        self._appid: str = ""
        self._name: str = ""
        self._all_rows: list[tuple[str, str]] = []   # (appid, name)
        self._build_ui()
        QTimer.singleShot(0, self._scan_library)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type to filter games…")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["AppID", "Game Name"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self._table)

        self._status = QLabel("Scanning Steam library…")
        self._status.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _scan_library(self):
        from pathlib import Path
        import re

        games: dict[str, str] = {}

        # Candidate Steam root paths (resolve symlinks to avoid duplicates)
        steam_roots_raw = [
            Path.home() / ".steam" / "steam",
            Path.home() / ".local" / "share" / "Steam",
        ]
        seen = set()
        library_dirs: list[Path] = []
        for root in steam_roots_raw:
            try:
                resolved = root.resolve()
            except Exception:
                continue
            if resolved not in seen and resolved.exists():
                seen.add(resolved)
                library_dirs.append(resolved / "steamapps")

        # Parse libraryfolders.vdf for additional library paths
        for lib_dir in list(library_dirs):
            vdf = lib_dir / "libraryfolders.vdf"
            if not vdf.exists():
                continue
            try:
                text = vdf.read_text(errors="replace")
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    p = Path(m.group(1)).resolve()
                    apps = p / "steamapps"
                    if apps not in seen and apps.exists():
                        seen.add(apps)
                        library_dirs.append(apps)
            except Exception:
                pass

        # Read appmanifest files
        for apps_dir in library_dirs:
            try:
                for fname in apps_dir.iterdir():
                    if not fname.name.startswith("appmanifest_") or not fname.name.endswith(".acf"):
                        continue
                    try:
                        text = fname.read_text(errors="replace")
                        m_id   = re.search(r'"appid"\s+"(\d+)"', text)
                        m_name = re.search(r'"name"\s+"([^"]+)"', text)
                        if m_id and m_name:
                            games[m_id.group(1)] = m_name.group(1)
                    except Exception:
                        pass
            except Exception:
                pass

        rows = sorted(games.items(), key=lambda x: x[1].lower())
        self._all_rows = rows
        self._render_rows(rows)
        self._status.setText(f"{len(rows)} games found")

    def _render_rows(self, rows: list[tuple[str, str]]):
        self._table.setRowCount(len(rows))
        for r, (appid, name) in enumerate(rows):
            self._table.setItem(r, 0, QTableWidgetItem(appid))
            self._table.setItem(r, 1, QTableWidgetItem(name))

    def _filter(self, text: str):
        text = text.lower()
        filtered = [(a, n) for a, n in self._all_rows if text in n.lower() or text in a]
        self._render_rows(filtered)

    def _on_accept(self):
        row = self._table.currentRow()
        if row < 0:
            return
        self._appid = self._table.item(row, 0).text() if self._table.item(row, 0) else ""
        self._name  = self._table.item(row, 1).text() if self._table.item(row, 1) else ""
        self.accept()

    def get_selection(self) -> tuple[str, str]:
        """Return (appid, name) of the selected game."""
        return self._appid, self._name


# ── Lutris game picker ─────────────────────────────────────────────────────────

class LutrisGamePickerDialog(QDialog):
    """Browse the local Lutris game database and pick a game to launch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick Lutris Game")
        self.setMinimumSize(560, 480)
        self._slug: str = ""
        self._name: str = ""
        self._all_rows: list[tuple[str, str]] = []   # (slug, name)
        self._build_ui()
        QTimer.singleShot(0, self._scan_library)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Type to filter games…")
        self._search.textChanged.connect(self._filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Name", "Runner / Slug"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(self._on_accept)
        layout.addWidget(self._table)

        self._status = QLabel("Scanning Lutris database…")
        self._status.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(self._status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _scan_library(self):
        import sqlite3
        db_path = os.path.expanduser("~/.local/share/lutris/pga.db")
        if not os.path.exists(db_path):
            self._status.setText("Lutris database not found — is Lutris installed?")
            return
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT name, slug, runner FROM games WHERE installed=1 ORDER BY name COLLATE NOCASE"
            ).fetchall()
            conn.close()
        except Exception as e:
            self._status.setText(f"Could not read Lutris database: {e}")
            return
        self._all_rows = [(slug, f"{name}  [{runner}]") for name, slug, runner in rows]
        self._render_rows(self._all_rows)
        self._status.setText(f"{len(self._all_rows)} installed games found")

    def _render_rows(self, rows: list[tuple[str, str]]):
        self._table.setRowCount(len(rows))
        for r, (slug, label) in enumerate(rows):
            name = label.split("  [")[0]
            self._table.setItem(r, 0, QTableWidgetItem(name))
            self._table.setItem(r, 1, QTableWidgetItem(label.split("  [")[1].rstrip("]") if "  [" in label else slug))

    def _filter(self, text: str):
        text = text.lower()
        filtered = [(s, l) for s, l in self._all_rows if text in l.lower()]
        self._render_rows(filtered)

    def _on_accept(self):
        row = self._table.currentRow()
        if row < 0:
            return
        # Find slug from filtered list
        name_item = self._table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()
        # Match back to slug
        for slug, label in self._all_rows:
            if label.startswith(name + "  [") or label == name:
                self._slug = slug
                self._name = name
                break
        else:
            self._name = name
            self._slug = name.lower().replace(" ", "-")
        self.accept()

    def get_selection(self) -> tuple[str, str]:
        """Return (slug, name) of the selected game."""
        return self._slug, self._name
