"""Process table widget with live data and right-click context menu."""
from __future__ import annotations

import os

import psutil

from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QAbstractItemView,
    QMenu, QHeaderView, QMessageBox, QApplication, QStyle,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence

import utils
from process_info import ProcessInfo
from gui.dialogs import AffinityDialog, NicePriorityDialog, IoNiceDialog, RuleEditDialog
from gui.table_layout import configure_columns, reset_columns


def _read_threads(pid: int) -> list[dict]:
    """Read display details for the threads currently owned by ``pid``."""
    threads = []
    for tid in sorted(utils.get_process_tids(pid)):
        try:
            with open(f"/proc/{pid}/task/{tid}/comm") as comm_file:
                name = comm_file.read().strip()
            thread = psutil.Process(tid)
            affinity = utils._cpuset_to_cpulist(set(thread.cpu_affinity()))
            ionice = thread.ionice()
            threads.append({
                "tid": tid,
                "name": name or str(tid),
                "nice": thread.nice(),
                "affinity": affinity,
                "ionice": f"{ionice.ioclass}/{ionice.value}",
            })
        except (OSError, psutil.Error):
            continue
    return threads


class ProcessTable(QTableWidget):
    """Sortable process table with right-click context menu."""

    rule_add_requested = pyqtSignal(object)  # emits Rule
    rule_value_manually_changed = pyqtSignal(int)  # pid — stop its startup rule burst
    available_users_changed = pyqtSignal(list)

    COLUMNS = [
        "PID", "Name", "User", "Sudo", "CPU%", "Mem(MB)",
        "CPU Priority (current)", "CPU Priority (always)",
        "CPU Affinity (current)", "CPU Affinity (always)",
        "I/O Priority (current)", "I/O Priority (always)",
        "Status", "Command",
    ]
    SUDO_COLUMN = 3
    NICE_CURRENT_COLUMN = 6
    NICE_ALWAYS_COLUMN = 7
    AFFINITY_CURRENT_COLUMN = 8
    AFFINITY_ALWAYS_COLUMN = 9
    IONICE_CURRENT_COLUMN = 10
    IONICE_ALWAYS_COLUMN = 11
    STATUS_COLUMN = 12
    COMMAND_COLUMN = 13
    DEFAULT_HIDDEN_COLUMNS = {SUDO_COLUMN, COMMAND_COLUMN}
    DEFAULT_COLUMN_WIDTHS = {
        0: 72,    # PID
        1: 220,   # Name
        2: 100,   # User
        3: 60,    # Sudo
        4: 70,    # CPU%
        5: 85,    # Mem(MB)
        6: 145,   # CPU Priority (current)
        7: 145,   # CPU Priority (always)
        8: 145,   # CPU Affinity (current)
        9: 145,   # CPU Affinity (always)
        10: 135,  # I/O Priority (current)
        11: 135,  # I/O Priority (always)
        12: 110,  # Status
        13: 360,  # Command
    }

    def __init__(self, rule_engine, log_callback, parent=None, thread_provider=None):
        super().__init__(0, len(self.COLUMNS), parent)
        self._rule_engine = rule_engine
        self._log_callback = log_callback
        self._snapshot: list[ProcessInfo] = []
        self._throttled_pids: set[int] = set()
        self._sort_col = 4   # CPU%
        self._sort_asc = False
        self._filter_text: str = ""
        self._user_filter: str = ""
        self._hide_root: bool = True
        self._available_users: list[str] = []
        self._expanded_pids: set[int] = set()
        self._thread_provider = thread_provider or _read_threads
        self._col_visible: list[bool] = [True] * len(self.COLUMNS)
        self._setup()

    def _setup(self):
        self.setHorizontalHeaderLabels(self.COLUMNS)
        for column in self.DEFAULT_HIDDEN_COLUMNS:
            self.setColumnHidden(column, True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.cellDoubleClicked.connect(self._toggle_threads_for_row)
        hdr = self.horizontalHeader()
        configure_columns(
            self,
            self.DEFAULT_COLUMN_WIDTHS,
            hidden=self.DEFAULT_HIDDEN_COLUMNS,
        )
        hdr.sectionClicked.connect(self._on_header_click)
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._show_header_menu)
        self.setSortingEnabled(False)  # Manual sorting

    def _show_header_menu(self, pos):
        """Right-click on header — toggle column visibility."""
        menu = QMenu(self)
        hdr = self.horizontalHeader()
        for i, name in enumerate(self.COLUMNS):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not hdr.isSectionHidden(i))
            action.setData(i)
        menu.addSeparator()
        reset_action = menu.addAction("Reset columns to default")
        chosen = menu.exec(hdr.mapToGlobal(pos))
        if chosen == reset_action:
            self._reset_column_layout()
        elif chosen:
            col = chosen.data()
            hidden = hdr.isSectionHidden(col)
            hdr.setSectionHidden(col, not hidden)

    def _reset_column_layout(self):
        """Restore default column order and visibility."""
        reset_columns(
            self,
            self.DEFAULT_COLUMN_WIDTHS,
            hidden=self.DEFAULT_HIDDEN_COLUMNS,
        )

    def _restore_default_column_widths(self):
        """Restore predictable widths without any auto-stretching sections."""
        for column, width in self.DEFAULT_COLUMN_WIDTHS.items():
            self.horizontalHeader().resizeSection(column, width)

    def _update_header_labels(self):
        """Re-set header labels (called after sort to add/remove arrow indicators)."""
        labels = []
        for i, name in enumerate(self.COLUMNS):
            if i == self._sort_col:
                labels.append(f"{name} {'▲' if self._sort_asc else '▼'}")
            else:
                labels.append(name)
        self.setHorizontalHeaderLabels(labels)

    def _on_header_click(self, col: int):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = col not in (4, 5)  # CPU/Mem default desc
        self._update_header_labels()
        self._refresh_display()

    def update_throttled(self, throttled_pids: set[int]):
        self._throttled_pids = throttled_pids

    def update_snapshot(self, snapshot: list[ProcessInfo]):
        self._snapshot = snapshot
        self._expanded_pids.intersection_update(proc["pid"] for proc in snapshot)
        users = sorted(
            {proc.get("user", "") for proc in snapshot if proc.get("user", "")},
            key=str.casefold,
        )
        if users != self._available_users:
            self._available_users = users
            self.available_users_changed.emit(users)
        self._refresh_display()

    def set_filter(self, text: str):
        """Filter displayed processes by name or PID (case-insensitive substring)."""
        self._filter_text = text.strip().lower()
        self._refresh_display()

    def set_user_filter(self, user: str):
        """Show only processes owned by ``user``; an empty value shows all."""
        self._user_filter = user.strip()
        self._refresh_display()

    def set_hide_root(self, hide: bool):
        self._hide_root = hide
        self._refresh_display()

    def _refresh_display(self):
        def always_settings(proc: dict) -> dict:
            if self._rule_engine is None:
                return {}
            return self._rule_engine.effective_settings(proc["name"])

        key_map = {
            0: lambda p: p["pid"],
            1: lambda p: p["name"].lower(),
            2: lambda p: p.get("user", "").lower(),
            3: lambda p: p.get("sudo", False),
            4: lambda p: p["cpu_percent"],
            5: lambda p: p["mem_rss"],
            6: lambda p: p["nice"],
            7: lambda p: self._format_nice(always_settings(p).get("nice")),
            8: lambda p: p["affinity"],
            9: lambda p: always_settings(p).get("affinity") or "",
            10: lambda p: p["ionice"],
            11: lambda p: self._format_ionice_rule(always_settings(p)),
            12: lambda p: "",
            13: lambda p: p.get("cmdline", "").lower(),
        }
        key_fn = key_map.get(self._sort_col, lambda p: 0)
        try:
            sorted_snap = sorted(self._snapshot, key=key_fn, reverse=not self._sort_asc)
        except Exception:
            sorted_snap = self._snapshot

        # Root processes are intentionally hidden on first launch, but remain
        # available through the filter controls.
        if self._hide_root:
            sorted_snap = [p for p in sorted_snap if p.get("user", "") != "root"]
        if self._user_filter:
            sorted_snap = [
                p for p in sorted_snap
                if p.get("user", "") == self._user_filter
            ]

        # Apply text filter
        if self._filter_text:
            ft = self._filter_text
            sorted_snap = [
                p for p in sorted_snap
                if ft in p["name"].lower()
                or ft in p.get("user", "").lower()
                or ft in str(p["pid"])
            ]

        threads_by_pid = {
            proc["pid"]: self._thread_provider(proc["pid"])
            for proc in sorted_snap
            if proc["pid"] in self._expanded_pids
        }
        self.setRowCount(
            len(sorted_snap) + sum(len(threads) for threads in threads_by_pid.values())
        )
        row = 0
        for proc in sorted_snap:
            pid = proc["pid"]
            cpu = proc["cpu_percent"]
            throttled = pid in self._throttled_pids
            persistent = always_settings(proc)
            items = [
                str(pid),
                proc["name"],
                proc.get("user", ""),
                "Yes" if proc.get("sudo", False) else "",
                f"{cpu:.1f}",
                f"{proc['mem_rss'] / 1_048_576:.1f}",
                str(proc["nice"]),
                self._format_nice(persistent.get("nice")),
                proc.get("affinity", ""),
                persistent.get("affinity") or "",
                proc.get("ionice", ""),
                self._format_ionice_rule(persistent),
                "⏸ Throttled" if throttled else "",
                proc.get("cmdline", ""),
            ]
            # Pick row text color based on CPU usage or throttle state
            if throttled:
                row_color = QColor("#fab387")   # orange
            elif cpu >= 80:
                row_color = QColor("#f38ba8")   # red
            elif cpu >= 40:
                row_color = QColor("#f9e2af")   # yellow
            elif cpu >= 10:
                row_color = QColor("#a6e3a1")   # green
            else:
                row_color = None                # default text color

            cmdline = proc.get("cmdline", "")
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item.setData(Qt.ItemDataRole.UserRole, "process")
                if col == 1 and cmdline:
                    item.setToolTip(cmdline)
                if col == 0:
                    arrow = (
                        QStyle.StandardPixmap.SP_ArrowDown
                        if pid in self._expanded_pids
                        else QStyle.StandardPixmap.SP_ArrowRight
                    )
                    item.setIcon(self.style().standardIcon(arrow))
                    hint = (
                        "Double-click to collapse threads"
                        if pid in self._expanded_pids
                        else "Double-click to expand threads"
                    )
                    item.setToolTip(hint)
                if row_color is not None:
                    item.setForeground(row_color)
                self.setItem(row, col, item)
            row += 1
            for thread in threads_by_pid.get(pid, []):
                self._render_thread_row(row, proc, thread)
                row += 1

    def _render_thread_row(self, row: int, proc: ProcessInfo, thread: dict):
        """Render a display-only child row beneath its owning process."""
        items = [
            str(thread["tid"]),
            f"    ↳ {thread['name']}",
            proc.get("user", ""),
            "", "", "",
            str(thread.get("nice", "")),
            "",
            thread.get("affinity", ""),
            "",
            thread.get("ionice", ""),
            "",
            "Thread",
            f"Thread of {proc['name']} ({proc['pid']})",
        ]
        for column, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
            )
            item.setData(Qt.ItemDataRole.UserRole, "thread")
            item.setData(Qt.ItemDataRole.UserRole + 1, proc["pid"])
            item.setForeground(QColor("#8b949e"))
            self.setItem(row, column, item)

    def _toggle_threads_for_row(self, row: int, _column: int):
        pid_item = self.item(row, 0)
        if pid_item is None or pid_item.data(Qt.ItemDataRole.UserRole) != "process":
            return
        pid = int(pid_item.text())
        if pid in self._expanded_pids:
            self._expanded_pids.remove(pid)
        else:
            self._expanded_pids.add(pid)
        self._refresh_display()

    @staticmethod
    def _format_nice(value) -> str:
        if value is None:
            return ""
        labels = {
            -20: "Real-time",
            -10: "High",
            -5: "Above normal",
            0: "Normal",
            5: "Below normal",
            19: "Idle",
        }
        label = labels.get(value)
        return f"{label} ({value})" if label else str(value)

    @staticmethod
    def _format_ionice_rule(settings: dict) -> str:
        io_class = settings.get("ionice_class")
        level = settings.get("ionice_level")
        if io_class is None:
            return ""
        labels = {
            (2, 0): "High",
            (2, 4): "Normal",
            (2, 7): "Low",
            (3, None): "Very Low",
        }
        lookup_level = None if io_class == 3 else level
        label = labels.get((io_class, lookup_level), "Custom")
        raw = str(io_class) if level is None else f"{io_class}/{level}"
        return f"{label} ({raw})"

    def _selected_proc(self) -> dict | None:
        rows = self.selectedItems()
        if not rows:
            return None
        row = self.currentRow()
        pid_item = self.item(row, 0)
        name_item = self.item(row, 1)
        nice_item = self.item(row, self.NICE_CURRENT_COLUMN)
        affinity_item = self.item(row, self.AFFINITY_CURRENT_COLUMN)
        ionice_item = self.item(row, self.IONICE_CURRENT_COLUMN)
        if not pid_item or pid_item.data(Qt.ItemDataRole.UserRole) != "process":
            return None
        return {
            "pid": int(pid_item.text()),
            "name": name_item.text() if name_item else "",
            "nice": int(nice_item.text()) if nice_item else 0,
            "affinity": affinity_item.text() if affinity_item else "",
            "ionice": ionice_item.text() if ionice_item else "",
        }

    def _selected_procs(self) -> list[dict]:
        """Return all selected rows as proc dicts."""
        selected_rows = sorted({idx.row() for idx in self.selectedIndexes()})
        procs = []
        for row in selected_rows:
            pid_item = self.item(row, 0)
            name_item = self.item(row, 1)
            if not pid_item or pid_item.data(Qt.ItemDataRole.UserRole) != "process":
                continue
            procs.append({
                "pid": int(pid_item.text()),
                "name": name_item.text() if name_item else "",
            })
        return procs

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            procs = self._selected_procs()
            if procs:
                self._do_kill_many(procs, force=False)
                return
        super().keyPressEvent(event)

    def _show_context_menu(self, pos):
        proc = self._selected_proc()
        procs = self._selected_procs()
        if not proc:
            return
        menu = QMenu(self)
        if len(procs) > 1:
            menu.addAction(
                f"Kill {len(procs)} selected processes",
                lambda: self._do_kill_many(procs, force=False)
            )
            menu.addAction(
                f"Force Kill {len(procs)} selected processes",
                lambda: self._do_kill_many(procs, force=True)
            )
            menu.addSeparator()
        else:
            menu.addAction(
                f"Kill {proc['name']} ({proc['pid']})",
                lambda: self._do_kill(proc, force=False)
            )
            menu.addAction(
                f"Force Kill {proc['name']} ({proc['pid']})",
                lambda: self._do_kill(proc, force=True)
            )
            menu.addSeparator()
        affinity_menu = menu.addMenu("CPU Affinity")
        affinity_menu.addAction("Current…", lambda: self._do_set_affinity(proc))
        affinity_menu.addAction("Always…", lambda: self._do_add_affinity_rule(proc))

        priority_menu = menu.addMenu("CPU Priority")
        priority_menu.addAction("Current…", lambda: self._do_set_nice(proc))
        priority_menu.addAction("Always…", lambda: self._do_add_priority_rule(proc))

        io_menu = menu.addMenu("I/O Priority")
        io_menu.addAction("Current…", lambda: self._do_set_ionice(proc))
        io_menu.addAction("Always…", lambda: self._do_add_ionice_rule(proc))
        menu.addSeparator()
        menu.addAction(
            f"Add Rule for '{proc['name']}'...",
            lambda: self._do_add_rule(proc)
        )
        menu.exec(self.viewport().mapToGlobal(pos))

    def _do_kill(self, proc: dict, force: bool):
        import signal
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            import os
            os.kill(proc["pid"], sig)
            msg = f"{'Force k' if force else 'K'}illed {proc['name']} ({proc['pid']})"
        except OSError as e:
            msg = f"Kill failed for {proc['name']} ({proc['pid']}): {e}"
        if self._log_callback:
            self._log_callback(msg)

    def _do_kill_many(self, procs: list[dict], force: bool):
        if not procs:
            return
        names = ", ".join(f"{p['name']}({p['pid']})" for p in procs[:4])
        if len(procs) > 4:
            names += f" and {len(procs) - 4} more"
        ans = QMessageBox.question(
            self, "Confirm Kill",
            f"{'Force kill' if force else 'Kill'} {len(procs)} processes?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        for p in procs:
            self._do_kill(p, force)

    def _do_set_affinity(self, proc: dict):
        dlg = AffinityDialog(proc.get("affinity", ""), self, proc["name"])
        if dlg.exec() == AffinityDialog.DialogCode.Accepted:
            cpulist = dlg.get_cpulist()
            if utils.set_affinity(proc["pid"], cpulist):
                msg = f"Set affinity={cpulist} on {proc['name']}({proc['pid']})"
                self.rule_value_manually_changed.emit(proc["pid"])
            else:
                msg = f"Failed to set affinity on {proc['name']}({proc['pid']})"
            if self._log_callback:
                self._log_callback(msg)

    def _do_set_nice(self, proc: dict):
        dlg = NicePriorityDialog(proc.get("nice", 0), self, proc["name"])
        if dlg.exec() == NicePriorityDialog.DialogCode.Accepted:
            nice = dlg.get_nice()
            if utils.set_nice(proc["pid"], nice):
                msg = f"Set nice={nice} on {proc['name']}({proc['pid']})"
                self.rule_value_manually_changed.emit(proc["pid"])
            else:
                msg = f"Failed to set nice={nice} on {proc['name']}({proc['pid']}) (root needed?)"
            if self._log_callback:
                self._log_callback(msg)

    def _do_set_ionice(self, proc: dict):
        current_class, current_level = self._parse_ionice(proc.get("ionice", ""))
        dlg = IoNiceDialog(current_class, current_level, self, proc["name"])
        if dlg.exec() == IoNiceDialog.DialogCode.Accepted:
            cls = dlg.get_ionice_class()
            lvl = dlg.get_ionice_level()
            if utils.set_ionice(proc["pid"], cls, lvl):
                msg = f"Set ionice class={cls} level={lvl} on {proc['name']}({proc['pid']})"
                self.rule_value_manually_changed.emit(proc["pid"])
            else:
                msg = f"Failed to set ionice on {proc['name']}({proc['pid']})"
            if self._log_callback:
                self._log_callback(msg)

    @staticmethod
    def _parse_ionice(value: str) -> tuple[int, int]:
        """Parse the process-table ``class/level`` representation."""
        try:
            io_class, level = value.split("/", 1)
            return int(io_class), int(level)
        except (AttributeError, ValueError):
            return 2, 4

    def _emit_always_rule(self, proc: dict, label: str, **settings):
        """Create a Windows-style ``Always`` rule for an exact process name."""
        from rules import Rule

        rule_name = f"{proc['name']} — {label}"
        existing = None
        if self._rule_engine is not None:
            existing = next(
                (
                    rule for rule in self._rule_engine.get_rules()
                    if rule.name == rule_name
                    and rule.pattern == proc["name"]
                    and rule.match_type == "exact"
                ),
                None,
            )
        rule = Rule(
            name=rule_name,
            pattern=proc["name"],
            match_type="exact",
            enabled=existing.enabled if existing else True,
            force_apply=existing.force_apply if existing else False,
            **settings,
        )
        if existing:
            rule.rule_id = existing.rule_id
        self.rule_add_requested.emit(rule)

    def _do_add_affinity_rule(self, proc: dict):
        dlg = AffinityDialog(proc.get("affinity", ""), self, proc["name"])
        if dlg.exec() == AffinityDialog.DialogCode.Accepted:
            self._emit_always_rule(
                proc, "CPU Affinity", affinity=dlg.get_cpulist()
            )

    def _do_add_priority_rule(self, proc: dict):
        dlg = NicePriorityDialog(proc.get("nice", 0), self, proc["name"])
        if dlg.exec() == NicePriorityDialog.DialogCode.Accepted:
            self._emit_always_rule(
                proc, "CPU Priority", nice=dlg.get_nice()
            )

    def _do_add_ionice_rule(self, proc: dict):
        current_class, current_level = self._parse_ionice(proc.get("ionice", ""))
        dlg = IoNiceDialog(current_class, current_level, self, proc["name"])
        if dlg.exec() == IoNiceDialog.DialogCode.Accepted:
            self._emit_always_rule(
                proc,
                "I/O Priority",
                ionice_class=dlg.get_ionice_class(),
                ionice_level=dlg.get_ionice_level(),
            )

    def _do_add_rule(self, proc: dict):
        from rules import Rule
        # Pre-populate with process name
        template = Rule(name=proc["name"], pattern=proc["name"], match_type="contains")
        dlg = RuleEditDialog(rule=template, parent=self)
        if dlg.exec() == RuleEditDialog.DialogCode.Accepted:
            rule = dlg.get_rule()
            self.rule_add_requested.emit(rule)
