"""Settings tab: global CPU defaults and monitor intervals."""
from __future__ import annotations

import os
import shlex

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QMessageBox,
    QSlider, QFrame, QInputDialog,
)
from PyQt6.QtCore import pyqtSignal, Qt
import subprocess

import utils
import app_identity
import cpu_park
from gui.dialogs import AffinityDialog


class SettingsTab(QWidget):
    settings_changed = pyqtSignal(dict)   # emits full updated config dict
    helper_changed = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── Default CPU Affinity ────────────────────────────────────────────
        cpu_group = QGroupBox("Default CPU Affinity")
        cpu_layout = QVBoxLayout(cpu_group)

        desc = QLabel(
            "Applied to every process that doesn't match a specific rule.\n"
            "Typical 7950X3D setup:\n"
            "  • Default → CCD1 (8-15,24-31)  — background processes\n"
            "  • Rule: steam (exact) → CCD0 (0-7,16-23)  — game + all children inherit\n"
            "  • Rule: specific game (exact) → further override if needed"
        )
        desc.setWordWrap(True)
        cpu_layout.addWidget(desc)

        row = QHBoxLayout()
        self._default_affinity_cb = QCheckBox("Enable default affinity:")
        row.addWidget(self._default_affinity_cb)

        self._default_affinity_edit = QLineEdit()
        self._default_affinity_edit.setPlaceholderText("e.g. 8-15,24-31")
        self._default_affinity_edit.setMaximumWidth(160)
        row.addWidget(self._default_affinity_edit)

        pick_btn = QPushButton("Pick CPUs…")
        pick_btn.clicked.connect(self._pick_affinity)
        row.addWidget(pick_btn)

        ccd_label = QLabel("Quick:")
        row.addWidget(ccd_label)
        for label, val in [("CCD0 (0-7,16-23)", "0-7,16-23"), ("CCD1 (8-15,24-31)", "8-15,24-31"), ("All", "")]:
            btn = QPushButton(label)
            btn.setMaximumWidth(130)
            btn.clicked.connect(lambda checked, v=val: self._set_quick(v))
            row.addWidget(btn)

        row.addStretch()
        cpu_layout.addLayout(row)

        apply_cpu_btn = QPushButton("Apply — enforce on all running processes now")
        apply_cpu_btn.clicked.connect(self._apply_cpu)
        cpu_layout.addWidget(apply_cpu_btn)

        layout.addWidget(cpu_group)

        # ── Monitor intervals ───────────────────────────────────────────────
        mon_group = QGroupBox("Monitor Intervals")
        mon_form = QFormLayout(mon_group)

        self._rule_interval = QSpinBox()
        self._rule_interval.setRange(100, 10000)
        self._rule_interval.setSuffix(" ms")
        self._rule_interval.setValue(500)
        mon_form.addRow("Rule enforce interval:", self._rule_interval)

        self._display_interval = QSpinBox()
        self._display_interval.setRange(500, 10000)
        self._display_interval.setSuffix(" ms")
        self._display_interval.setValue(2000)
        mon_form.addRow("Display refresh interval:", self._display_interval)

        apply_mon_btn = QPushButton("Apply Monitor Settings")
        apply_mon_btn.clicked.connect(self._apply_monitor)
        mon_form.addRow("", apply_mon_btn)

        layout.addWidget(mon_group)

        # ── Appearance ──────────────────────────────────────────────────────
        appear_group = QGroupBox("Appearance")
        appear_layout = QVBoxLayout(appear_group)

        self._system_theme_cb = QCheckBox("Use system theme (disables Process Lasso theme)")
        self._system_theme_cb.setToolTip(
            "When checked, Process Lasso uses your OS/desktop dark/light theme\n"
            "instead of the built-in Breeze Dark stylesheet."
        )
        appear_layout.addWidget(self._system_theme_cb)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Window opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(100)
        self._opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._opacity_slider.setTickInterval(10)
        self._opacity_label = QLabel("100%")
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_label)
        appear_layout.addLayout(opacity_row)

        layout.addWidget(appear_group)

        # ── Autostart ────────────────────────────────────────────────────────
        auto_group = QGroupBox("Autostart")
        auto_layout = QVBoxLayout(auto_group)
        self._autostart_cb = QCheckBox("Start Process Lasso automatically with your desktop session")
        self._autostart_cb.setToolTip(
            "Installs / removes a systemd user service unit\n"
            "(~/.config/systemd/user/process-lasso.service)"
        )
        auto_layout.addWidget(self._autostart_cb)
        autostart_apply_btn = QPushButton("Apply Autostart Setting")
        autostart_apply_btn.clicked.connect(self._apply_autostart)
        auto_layout.addWidget(autostart_apply_btn)
        layout.addWidget(auto_group)

        # ── Privileged helper ──────────────────────────────────────────────
        helper_group = QGroupBox("Root Helper")
        helper_layout = QVBoxLayout(helper_group)
        helper_desc = QLabel(
            "Installs the privileged helper used for CPU parking and negative nice values."
        )
        helper_desc.setWordWrap(True)
        helper_layout.addWidget(helper_desc)

        helper_frame = QFrame()
        helper_frame.setFrameShape(QFrame.Shape.StyledPanel)
        helper_row = QHBoxLayout(helper_frame)
        self._helper_status = QLabel()
        helper_row.addWidget(self._helper_status)
        install_btn = QPushButton("Install / Update Helper (root)")
        install_btn.clicked.connect(self._install_helper)
        helper_row.addWidget(install_btn)
        helper_row.addStretch()
        helper_layout.addWidget(helper_frame)
        layout.addWidget(helper_group)

        # ── Reset All Changes ──────────────────────────────────────────────
        reset_group = QGroupBox("Reset All Changes")
        reset_layout = QVBoxLayout(reset_group)
        reset_desc = QLabel(
            "Restores all per-process CPU affinities and priority changes made by "
            "Process Lasso, then unparks any parked CPUs."
        )
        reset_desc.setWordWrap(True)
        reset_layout.addWidget(reset_desc)
        reset_btn = QPushButton("↩  Reset All Changes")
        reset_btn.setMinimumHeight(36)
        reset_btn.clicked.connect(self._reset_all)
        reset_layout.addWidget(reset_btn)
        layout.addWidget(reset_group)

        layout.addStretch()

        self._load_config()
        self._update_helper_status()

    def _update_helper_status(self):
        if cpu_park.is_helper_current() and cpu_park.is_sudoers_installed():
            self._helper_status.setText("✓ Helper installed — parking + nice -1 available")
            self._helper_status.setStyleSheet("color: #a6e3a1;")
        elif cpu_park.is_helper_installed() and cpu_park.is_sudoers_installed():
            self._helper_status.setText("⚠ Helper needs update — click 'Install / Update Helper'")
            self._helper_status.setStyleSheet("color: #f9e2af;")
        else:
            self._helper_status.setText(
                "✗ Helper not installed — install it to enable CPU parking and nice -1"
            )
            self._helper_status.setStyleSheet("color: #f38ba8;")

    def refresh_helper_state(self):
        """Refresh the helper status after it changes on another tab."""
        self._update_helper_status()

    def _install_helper(self):
        password, ok = QInputDialog.getText(
            self, "Root Authentication",
            "Enter root password to install the privileged sysfs helper:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not password:
            return
        ok, msg = cpu_park.install_helper_as_root(password=password)
        self._update_helper_status()
        if ok:
            self.helper_changed.emit()
        QMessageBox.information(self, "Install Helper", msg)

    def _reset_all(self):
        ans = QMessageBox.question(
            self, "Reset All Changes",
            "This will:\n"
            "  • Restore all per-process CPU affinities and priority changes\n"
            "  • Disable Gaming Mode and unpark any parked CPUs\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.reset_requested.emit()

    def _load_config(self):
        default = self._config.get("cpu", {}).get("default_affinity") or ""
        self._default_affinity_cb.setChecked(bool(default))
        self._default_affinity_edit.setText(default)
        self._default_affinity_edit.setEnabled(bool(default))
        self._default_affinity_cb.toggled.connect(self._default_affinity_edit.setEnabled)

        mon = self._config.get("monitor", {})
        self._rule_interval.setValue(mon.get("rule_enforce_interval_ms", 500))
        self._display_interval.setValue(mon.get("display_refresh_interval_ms", 2000))

        self._system_theme_cb.setChecked(
            self._config.get("ui", {}).get("use_system_theme", False)
        )

        opacity = self._config.get("ui", {}).get("opacity", 100)
        self._opacity_slider.setValue(int(opacity))
        self._opacity_label.setText(f"{int(opacity)}%")

        # Autostart: check if systemd user service is enabled
        try:
            r = subprocess.run(
                ["systemctl", "--user", "is-enabled", "process-lasso.service"],
                capture_output=True, text=True
            )
            self._autostart_cb.setChecked(r.stdout.strip() == "enabled")
        except Exception:
            self._autostart_cb.setChecked(False)

    def _pick_affinity(self):
        current = self._default_affinity_edit.text().strip()
        dlg = AffinityDialog(current, self, "Default")
        if dlg.exec() == AffinityDialog.DialogCode.Accepted:
            cpulist = dlg.get_cpulist()
            self._default_affinity_edit.setText(cpulist)
            self._default_affinity_cb.setChecked(bool(cpulist))

    def _set_quick(self, val: str):
        self._default_affinity_edit.setText(val)
        self._default_affinity_cb.setChecked(bool(val))

    def _apply_cpu(self):
        if not self._default_affinity_cb.isChecked():
            QMessageBox.information(self, "Default Affinity", "Default affinity is disabled — nothing applied.")
            return
        cpulist = self._default_affinity_edit.text().strip()
        if cpulist and not utils.validate_cpulist(cpulist):
            QMessageBox.warning(self, "Invalid", f"Invalid CPU list: {cpulist!r}")
            return
        self._config.setdefault("cpu", {})["default_affinity"] = cpulist or None
        self.settings_changed.emit(self._config)
        QMessageBox.information(
            self, "Default Affinity",
            f"Default affinity set to {cpulist or 'disabled'}.\n"
            "Enforcing on all running processes now…"
        )

    def _apply_monitor(self):
        self._config.setdefault("monitor", {})["rule_enforce_interval_ms"] = self._rule_interval.value()
        self._config.setdefault("monitor", {})["display_refresh_interval_ms"] = self._display_interval.value()
        self._config.setdefault("ui", {})["use_system_theme"] = self._system_theme_cb.isChecked()
        self._config.setdefault("ui", {})["opacity"] = self._opacity_slider.value()
        # Apply opacity to main window immediately
        from PyQt6.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            from PyQt6.QtWidgets import QMainWindow
            if isinstance(widget, QMainWindow):
                widget.setWindowOpacity(self._opacity_slider.value() / 100.0)
        self.settings_changed.emit(self._config)
        QMessageBox.information(self, "Monitor Settings", "Settings applied.")

    def _apply_autostart(self):
        enable = self._autostart_cb.isChecked()
        service_dir = os.path.expanduser("~/.config/systemd/user")
        service_file = os.path.join(service_dir, "process-lasso.service")
        if enable:
            os.makedirs(service_dir, exist_ok=True)
            # Find the main.py location
            main_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), "main.py")
            launch_command = "exec -a {} /usr/bin/python3 {}".format(
                shlex.quote(app_identity.PROCESS_NAME), shlex.quote(main_py)
            )
            unit = (
                "[Unit]\n"
                "Description=Process Lasso Linux\n"
                "After=graphical-session.target\n\n"
                "[Service]\n"
                f"ExecStart=/usr/bin/bash -c {shlex.quote(launch_command)}\n"
                "Restart=on-failure\n\n"
                "[Install]\n"
                "WantedBy=graphical-session.target\n"
            )
            try:
                with open(service_file, "w") as f:
                    f.write(unit)
                subprocess.run(["systemctl", "--user", "enable", "process-lasso.service"], check=True)
                QMessageBox.information(self, "Autostart", "Autostart enabled.")
            except Exception as e:
                QMessageBox.warning(self, "Autostart", f"Failed to enable: {e}")
        else:
            try:
                subprocess.run(["systemctl", "--user", "disable", "process-lasso.service"], check=False)
                QMessageBox.information(self, "Autostart", "Autostart disabled.")
            except Exception as e:
                QMessageBox.warning(self, "Autostart", f"Failed to disable: {e}")

    def update_config(self, config: dict):
        self._config = config
        self._load_config()
