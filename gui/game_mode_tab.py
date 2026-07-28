"""Thin Qt editor/view over the shared Game Mode configuration model."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QComboBox, QLineEdit, QTableWidget,
    QTableWidgetItem, QLabel, QPushButton, QHBoxLayout, QDialog,
    QDialogButtonBox, QMessageBox, QAbstractItemView,
)
from gui.dialogs import AffinityDialog, NicePriorityDialog
import cpu_tools


class RunningGameProfileDialog(QDialog):
    """Edit the canonical profile backing one active Game Mode session."""

    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Game Mode Profile — {game.get('name', 'Game')}")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(game.get("name", ""))
        self.affinity_mode = QComboBox()
        self.affinity_mode.addItems(["Inherit default", "Disabled", "Custom"])
        self.affinity = QLineEdit()
        self.affinity.setReadOnly(True)
        self.affinity.setPlaceholderText("Example: 0-7,16-23")
        self.affinity_pick = QPushButton("Pick CPUs…")
        self.affinity_pick.clicked.connect(self._pick_affinity)
        affinity = game.get("affinity", "inherit")
        if affinity == "inherit":
            self.affinity_mode.setCurrentIndex(0)
        elif affinity in ("disabled", None, ""):
            self.affinity_mode.setCurrentIndex(1)
        else:
            self.affinity_mode.setCurrentIndex(2)
            self.affinity.setText(str(affinity))

        self.nice_mode = QComboBox()
        self.nice_mode.addItems(["Inherit default", "Disabled", "Absolute", "Offset"])
        self.nice_value = QLineEdit()
        self.nice_value.setReadOnly(True)
        self.nice_value.setPlaceholderText("No custom nice policy")
        self.nice_pick = QPushButton("Pick priority…")
        self.nice_pick.clicked.connect(self._pick_nice)
        nice = game.get("nice", "inherit")
        self._nice_policy = (
            nice if isinstance(nice, dict)
            else {"type": "absolute", "value": nice} if isinstance(nice, int)
            else None
        )
        if nice == "inherit":
            self.nice_mode.setCurrentIndex(0)
        elif nice in ("disabled", None, ""):
            self.nice_mode.setCurrentIndex(1)
        elif isinstance(nice, dict) and nice.get("type") == "offset":
            self.nice_mode.setCurrentIndex(3)
            self.nice_value.setText(GameModeTab._nice_text(nice))
        else:
            self.nice_mode.setCurrentIndex(2)
            value = nice.get("value", 0) if isinstance(nice, dict) else nice
            self.nice_value.setText(GameModeTab._nice_text(
                nice if isinstance(nice, dict) else {"type": "absolute", "value": value}
            ))

        self.source_aliases = QLineEdit(", ".join(game.get("source_aliases", [])))
        self.executable_aliases = QLineEdit(", ".join(game.get("executable_aliases", [])))
        form.addRow("Profile name", self.name)
        form.addRow("Affinity policy", self.affinity_mode)
        affinity_row = QHBoxLayout()
        affinity_row.addWidget(self.affinity)
        affinity_row.addWidget(self.affinity_pick)
        form.addRow("Custom affinity", affinity_row)
        form.addRow("Nice policy", self.nice_mode)
        nice_row = QHBoxLayout()
        nice_row.addWidget(self.nice_value)
        nice_row.addWidget(self.nice_pick)
        form.addRow("Nice value", nice_row)
        form.addRow("Source aliases", self.source_aliases)
        form.addRow("Executable aliases", self.executable_aliases)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.affinity_mode.currentIndexChanged.connect(self._update_picker_state)
        self.nice_mode.currentIndexChanged.connect(self._update_picker_state)
        self._update_picker_state()

    def _update_picker_state(self):
        self.affinity.setEnabled(self.affinity_mode.currentIndex() == 2)
        self.affinity_pick.setEnabled(self.affinity_mode.currentIndex() == 2)
        custom_nice = self.nice_mode.currentIndex() in (2, 3)
        self.nice_value.setEnabled(custom_nice)
        self.nice_pick.setEnabled(custom_nice)

    def _pick_affinity(self):
        dialog = AffinityDialog(self.affinity.text(), self, self.name.text().strip())
        if dialog.exec() == AffinityDialog.DialogCode.Accepted:
            self.affinity.setText(dialog.get_cpulist())

    def _pick_nice(self):
        policy = self._nice_policy or {"type": "absolute", "value": 0}
        mode = "offset" if self.nice_mode.currentIndex() == 3 else "absolute"
        dialog = NicePriorityDialog(
            current_nice=int(policy.get("value", 0)), parent=self,
            title_suffix=self.name.text().strip(), initial_mode=mode,
            initial_offset=int(policy.get("offset", 0)),
            initial_floor=int(policy.get("floor", -15)),
            initial_ceiling=int(policy.get("ceiling", 19)),
        )
        if dialog.exec() != NicePriorityDialog.DialogCode.Accepted:
            return
        if dialog.get_mode() == "offset":
            self._nice_policy = {"type": "offset", "offset": dialog.get_offset(),
                                 "floor": dialog.get_floor(),
                                 "ceiling": dialog.get_ceiling()}
            self.nice_mode.setCurrentIndex(3)
        else:
            self._nice_policy = {"type": "absolute", "value": dialog.get_nice()}
            self.nice_mode.setCurrentIndex(2)
        self.nice_value.setText(GameModeTab._nice_text(self._nice_policy))

    def update_game(self, game):
        name = self.name.text().strip()
        if not name:
            raise ValueError("Profile name cannot be empty")
        affinity_mode = self.affinity_mode.currentIndex()
        if affinity_mode == 0:
            affinity = "inherit"
        elif affinity_mode == 1:
            affinity = "disabled"
        else:
            affinity = self.affinity.text().strip()
            if not affinity:
                raise ValueError("Enter a custom CPU affinity")

        nice_mode = self.nice_mode.currentIndex()
        if nice_mode == 0:
            nice = "inherit"
        elif nice_mode == 1:
            nice = "disabled"
        else:
            if self._nice_policy is None:
                raise ValueError("Choose a nice priority")
            nice = self._nice_policy
        game.update({
            "name": name,
            "affinity": affinity,
            "nice": nice,
            "source_aliases": [x.strip() for x in self.source_aliases.text().split(",") if x.strip()],
            "executable_aliases": [x.strip().casefold() for x in self.executable_aliases.text().split(",") if x.strip()],
        })


class GameModeTab(QWidget):
    settings_changed = pyqtSignal(dict)

    def __init__(self, game_config, sessions, parent=None):
        super().__init__(parent)
        self._config = game_config
        self._sessions = sessions
        self._known_session_tokens: set[str] = set()
        self._session_flash_generation = 0
        self._session_flash_pending = False
        layout = QVBoxLayout(self)
        self._mode_indicator = QLabel()
        self._mode_indicator.setObjectName("gameModeIndicator")
        layout.addWidget(self._mode_indicator)
        layout.addWidget(QLabel(
            "Usage: processlasso-game %command%"
        ))
        form = QFormLayout()
        self._ccd = QComboBox()
        self._ccd.addItem("Disabled", None)
        configured_mode = game_config.get("ccd_preference", "cache")
        for mode in cpu_tools.get_available_x3d_modes():
            label = (
                f"{mode.value} (recommended)"
                if mode.value == "cache" else mode.value
            )
            self._ccd.addItem(label, mode.value)
        configured_index = self._ccd.findData(configured_mode)
        if configured_index >= 0:
            self._ccd.setCurrentIndex(configured_index)
        x3d_enabled = cpu_tools.get_cpu_info().features.x3d_mode_control
        self._ccd.setEnabled(x3d_enabled and self._ccd.count() > 0)
        if not x3d_enabled or not self._ccd.count():
            self._ccd.setPlaceholderText("Not supported by this CPU")
        self._affinity = QLineEdit(game_config.get("affinity") or "")
        self._affinity.setReadOnly(True)
        self._affinity.setPlaceholderText("Disabled (example: 0-7,16-23)")
        self._nice = QLineEdit(self._nice_text(game_config.get("nice")))
        self._nice.setReadOnly(True)
        self._nice.setPlaceholderText("Disabled; integer or offset:+5")
        affinity_row = QHBoxLayout()
        affinity_row.addWidget(self._affinity)
        affinity_pick = QPushButton("Pick CPUs…")
        affinity_pick.clicked.connect(self._pick_default_affinity)
        affinity_clear = QPushButton("Disable")
        affinity_clear.clicked.connect(self._affinity.clear)
        affinity_row.addWidget(affinity_pick)
        affinity_row.addWidget(affinity_clear)
        nice_row = QHBoxLayout()
        nice_row.addWidget(self._nice)
        nice_pick = QPushButton("Pick priority…")
        nice_pick.clicked.connect(self._pick_default_nice)
        nice_clear = QPushButton("Disable")
        nice_clear.clicked.connect(self._nice.clear)
        nice_row.addWidget(nice_pick)
        nice_row.addWidget(nice_clear)
        form.addRow("Game Mode CCD preference", self._ccd)
        form.addRow("Default game affinity", affinity_row)
        form.addRow("Default nice policy", nice_row)
        layout.addLayout(form)
        save = QPushButton("Apply Game Mode defaults")
        save.clicked.connect(self._apply)
        layout.addWidget(save)

        layout.addWidget(QLabel("Game profiles and aliases"))
        self._games = QTableWidget(0, 5)
        self._games.setHorizontalHeaderLabels(["Name", "Source aliases", "Executable aliases", "Affinity", "Nice"])
        self._games.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._games.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._games.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._games.cellDoubleClicked.connect(
            lambda selected_row, _column: self._edit_selected_profile(selected_row)
        )
        layout.addWidget(self._games)
        row = QHBoxLayout()
        edit_profile = QPushButton("Edit Selected Profile…")
        edit_profile.clicked.connect(lambda: self._edit_selected_profile())
        merge = QPushButton("Merge selected identities")
        merge.setToolTip(
            "Keep the first selected profile and its settings, combine aliases "
            "from the other selected profiles into it, then remove those profiles."
        )
        merge.clicked.connect(self._merge_selected)
        row.addWidget(edit_profile)
        row.addWidget(merge)
        row.addStretch()
        layout.addLayout(row)
        self._active_heading = QLabel("Games currently running with Game Mode")
        layout.addWidget(self._active_heading)
        self._active = QTableWidget(0, 5)
        self._active.setHorizontalHeaderLabels(
            ["Game", "Root PID", "Affinity", "Nice", "Command"]
        )
        self._active.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._active.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._active.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._active.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._active.horizontalScrollBar().setSingleStep(12)
        self._active.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._active.verticalScrollBar().setSingleStep(12)
        layout.addWidget(self._active)
        active_actions = QHBoxLayout()
        self._create_running_profile = QPushButton(
            "Create / Edit Profile for Selected Game"
        )
        self._create_running_profile.clicked.connect(self._profile_for_running_game)
        active_actions.addWidget(self._create_running_profile)
        active_actions.addStretch()
        layout.addLayout(active_actions)
        self.refresh()

    @staticmethod
    def _nice_text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, int):
            return str(value)
        if value.get("type") == "offset":
            return f"offset:{value.get('offset', 0)}"
        return str(value.get("value", ""))

    @staticmethod
    def _parse_nice(text):
        text = text.strip()
        if not text:
            return None
        if text.startswith("offset:"):
            return {"type": "offset", "offset": int(text.split(":", 1)[1]),
                    "floor": -15, "ceiling": 19}
        return {"type": "absolute", "value": int(text)}

    def _apply(self):
        self._config["ccd_preference"] = self._ccd.currentData()
        self._config["affinity"] = self._affinity.text().strip() or None
        try:
            self._config["nice"] = self._parse_nice(self._nice.text())
        except ValueError:
            return
        self.settings_changed.emit(self._config)

    def _pick_default_affinity(self):
        dialog = AffinityDialog(self._affinity.text(), self, "Game Mode Default")
        if dialog.exec() == AffinityDialog.DialogCode.Accepted:
            self._affinity.setText(dialog.get_cpulist())

    def _pick_default_nice(self):
        policy = self._config.get("nice") or {"type": "absolute", "value": 0}
        if isinstance(policy, int):
            policy = {"type": "absolute", "value": policy}
        dialog = NicePriorityDialog(
            current_nice=int(policy.get("value", 0)), parent=self,
            title_suffix="Game Mode Default",
            initial_mode=policy.get("type", "absolute"),
            initial_offset=int(policy.get("offset", 0)),
            initial_floor=int(policy.get("floor", -15)),
            initial_ceiling=int(policy.get("ceiling", 19)),
        )
        if dialog.exec() != NicePriorityDialog.DialogCode.Accepted:
            return
        if dialog.get_mode() == "offset":
            policy = {"type": "offset", "offset": dialog.get_offset(),
                      "floor": dialog.get_floor(), "ceiling": dialog.get_ceiling()}
        else:
            policy = {"type": "absolute", "value": dialog.get_nice()}
        self._config["nice"] = policy
        self._nice.setText(self._nice_text(policy))

    def refresh(self):
        selected_token = None
        selected = self._active.selectedItems()
        if selected:
            selected_token = selected[0].data(256)
        games = self._config.get("games", [])
        self._games.setRowCount(len(games))
        for row, game in enumerate(games):
            values = [game.get("name", ""), ", ".join(game.get("source_aliases", [])),
                      ", ".join(game.get("executable_aliases", [])),
                      str(game.get("affinity", "inherit")), self._nice_text(game.get("nice", "inherit"))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (3, 4):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._games.setItem(row, column, item)
        sessions = list(self._sessions.sessions.values())
        session_tokens = {session["token"] for session in sessions}
        if session_tokens - self._known_session_tokens:
            self._queue_or_flash_new_game_session()
        self._known_session_tokens = session_tokens
        if sessions:
            count = len(sessions)
            suffix = "session" if count == 1 else "sessions"
            self._mode_indicator.setText(
                f"● Game Mode enabled — {count} active {suffix}"
            )
            self._mode_indicator.setStyleSheet(
                "color: #22ff66; font-weight: 800; padding: 4px 0;"
            )
        else:
            self._mode_indicator.setText("○ Game Mode inactive")
            self._mode_indicator.setStyleSheet(
                "color: rgba(205,214,244,0.65); font-weight: 600; padding: 4px 0;"
            )
        self._active.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            policy = session.get("policy", {})
            values = [session["game_name"], str(session["root_pid"]),
                      str(policy.get("affinity") or "Disabled"),
                      self._nice_text(policy.get("nice")) or "Disabled",
                      " ".join(session.get("argv", []))]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(256, session["token"])
                self._active.setItem(row, column, item)
            if selected_token == session["token"]:
                self._active.selectRow(row)
        self._create_running_profile.setEnabled(bool(sessions))

    def _can_show_session_flash(self):
        window = self.window()
        return (
            self.isVisible()
            and window.isVisible()
            and not window.isMinimized()
        )

    def _queue_or_flash_new_game_session(self):
        if self._can_show_session_flash():
            self._session_flash_pending = False
            self._flash_new_game_session()
        else:
            self._session_flash_pending = True

    def _consume_pending_session_flash(self):
        if self._session_flash_pending and self._can_show_session_flash():
            self._session_flash_pending = False
            self._flash_new_game_session()

    def showEvent(self, event):
        super().showEvent(event)
        # Run after Qt finishes making the tab/window visible.
        QTimer.singleShot(0, self._consume_pending_session_flash)

    def _flash_new_game_session(self):
        """Briefly highlight the active-session area for each new session."""
        self._session_flash_generation += 1
        generation = self._session_flash_generation
        self._active_heading.setStyleSheet(
            "color: #22ff66; font-weight: 800; "
            "background: rgba(34,255,102,0.18); padding: 5px;"
        )
        self._active.setStyleSheet(
            "QTableWidget { border: 2px solid #22ff66; "
            "background: rgba(34,255,102,0.08); }"
        )

        def clear_flash():
            if generation != self._session_flash_generation:
                return
            self._active_heading.setStyleSheet("")
            self._active.setStyleSheet("")

        QTimer.singleShot(1200, clear_flash)

    def _profile_for_running_game(self):
        row = self._active.currentRow()
        if row < 0:
            QMessageBox.information(self, "Game Mode Profile",
                                    "Select a running game first.")
            return
        token = self._active.item(row, 0).data(256)
        session = self._sessions.sessions.get(token)
        if not session or not session.get("game_id"):
            QMessageBox.warning(
                self, "Game Mode Profile",
                "This session has an ambiguous identity. Edit or merge its aliases first.",
            )
            return
        game = next((game for game in self._config.get("games", [])
                     if game.get("id") == session["game_id"]), None)
        if game is None:
            QMessageBox.warning(self, "Game Mode Profile",
                                "The canonical game profile could not be found.")
            return
        dialog = RunningGameProfileDialog(game, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dialog.update_game(game)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Game Mode Profile", str(exc))
            return
        self.settings_changed.emit(self._config)
        self.refresh()

    def _edit_selected_profile(self, selected_row=None):
        row = self._games.currentRow() if selected_row is None else selected_row
        games = self._config.get("games", [])
        if row < 0 or row >= len(games):
            QMessageBox.information(self, "Game Mode Profile",
                                    "Select a game profile first.")
            return
        game = games[row]
        dialog = RunningGameProfileDialog(game, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dialog.update_game(game)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Game Mode Profile", str(exc))
            return
        self.settings_changed.emit(self._config)
        self.refresh()
        self._games.selectRow(row)

    def _merge_selected(self):
        rows = sorted({index.row() for index in self._games.selectedIndexes()})
        if len(rows) < 2:
            return
        games = self._config.get("games", [])
        target = games[rows[0]]
        for row in reversed(rows[1:]):
            source = games.pop(row)
            for field in ("source_aliases", "executable_aliases"):
                target[field] = list(dict.fromkeys(target.get(field, []) + source.get(field, [])))
        self.settings_changed.emit(self._config)
        self.refresh()
