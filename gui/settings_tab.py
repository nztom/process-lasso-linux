"""Settings tab: global CPU defaults and monitor intervals."""
from __future__ import annotations

import os
import shlex

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QSpinBox, QMessageBox,
    QFrame, QInputDialog, QComboBox,
)
from PyQt6.QtCore import pyqtSignal
import subprocess

import utils
import app_identity
import cpu_park
from gui.dialogs import AffinityDialog


class SettingsTab(QWidget):
    settings_changed = pyqtSignal(dict)   # emits full updated config dict
    helper_changed = pyqtSignal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._topology = cpu_park.detect_topology()
        self._x3d_supported = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ── Detected CPU topology ─────────────────────────────────────────
        topology_group = QGroupBox("Detected CPU Topology")
        topology_layout = QVBoxLayout(topology_group)
        self._topology_label = QLabel(self._topology.description)
        self._topology_label.setWordWrap(True)
        topology_layout.addWidget(self._topology_label)
        layout.addWidget(topology_group)

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
        self._default_affinity_edit.setReadOnly(True)
        self._default_affinity_edit.setPlaceholderText("e.g. 8-15,24-31")
        self._default_affinity_edit.setMaximumWidth(160)
        row.addWidget(self._default_affinity_edit)

        pick_btn = QPushButton("Pick CPUs…")
        pick_btn.clicked.connect(self._pick_affinity)
        row.addWidget(pick_btn)

        row.addStretch()
        cpu_layout.addLayout(row)

        apply_cpu_btn = QPushButton("Apply — enforce on all running processes now")
        apply_cpu_btn.clicked.connect(self._apply_cpu)
        cpu_layout.addWidget(apply_cpu_btn)

        layout.addWidget(cpu_group)

        # ── AMD X3D scheduler preference ──────────────────────────────────
        # This is a system-wide hardware scheduler setting, not a process mode.
        self._x3d_group = QGroupBox("AMD X3D — Scheduler Preferred CCD")
        x3d_layout = QVBoxLayout(self._x3d_group)
        x3d_desc = QLabel(
            "Select which CCD Linux should fill first. Both CCDs remain online; "
            "this changes scheduler core rankings rather than CPU affinity."
        )
        x3d_desc.setWordWrap(True)
        x3d_layout.addWidget(x3d_desc)

        x3d_row = QHBoxLayout()
        x3d_row.addWidget(QLabel("Prefer:"))
        self._x3d_mode_combo = QComboBox()
        self._x3d_mode_combo.addItem("V-Cache CCD (cache-sensitive / games)", "cache")
        self._x3d_mode_combo.addItem("Frequency CCD (higher clocks / compute)", "frequency")
        x3d_row.addWidget(self._x3d_mode_combo)
        self._x3d_apply_btn = QPushButton("Apply")
        self._x3d_apply_btn.clicked.connect(self._apply_x3d_mode)
        x3d_row.addWidget(self._x3d_apply_btn)
        self._x3d_status = QLabel()
        x3d_row.addWidget(self._x3d_status)
        x3d_row.addStretch()
        x3d_layout.addLayout(x3d_row)
        self._x3d_group.setVisible(False)
        layout.addWidget(self._x3d_group)

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
            "Installs the privileged helper used for negative nice values and AMD X3D controls."
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

        layout.addStretch()

        self._load_config()
        self._update_helper_status()
        self._refresh_x3d_mode()

    def _refresh_x3d_mode(self):
        self._x3d_supported = cpu_park.has_dual_ccd_x3d_control(self._topology)
        self._x3d_group.setVisible(self._x3d_supported)
        if not self._x3d_supported:
            return

        mode = cpu_park.get_x3d_mode()
        index = self._x3d_mode_combo.findData(mode)
        if index >= 0:
            self._x3d_mode_combo.setCurrentIndex(index)
        label = "V-Cache CCD preferred" if mode == "cache" else "Frequency CCD preferred"
        self._x3d_status.setText(f"Current: {label}")

        helper_ready = cpu_park.is_helper_current() and cpu_park.is_sudoers_installed()
        self._x3d_apply_btn.setEnabled(helper_ready)
        self._x3d_apply_btn.setToolTip(
            "" if helper_ready else "Install or update the privileged helper first."
        )

    def _apply_x3d_mode(self):
        mode = self._x3d_mode_combo.currentData()
        ok, message = cpu_park.set_x3d_mode(mode)
        if not ok:
            QMessageBox.warning(self, "AMD X3D Preference", message)
            return
        self._refresh_x3d_mode()
        label = "V-Cache" if mode == "cache" else "Frequency"
        QMessageBox.information(
            self, "AMD X3D Preference", f"Linux now prefers the {label} CCD."
        )

    def _update_helper_status(self):
        if cpu_park.is_helper_current() and cpu_park.is_sudoers_installed():
            self._helper_status.setText("✓ Helper installed — priority and X3D controls available")
            self._helper_status.setStyleSheet("color: #a6e3a1;")
        elif cpu_park.is_helper_installed() and cpu_park.is_sudoers_installed():
            self._helper_status.setText("⚠ Helper needs update — click 'Install / Update Helper'")
            self._helper_status.setStyleSheet("color: #f9e2af;")
        else:
            self._helper_status.setText(
                "✗ Helper not installed — install it to enable priority and X3D controls"
            )
            self._helper_status.setStyleSheet("color: #f38ba8;")

    def refresh_helper_state(self):
        """Refresh the helper status after it changes on another tab."""
        self._update_helper_status()
        self._refresh_x3d_mode()

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

    def _load_config(self):
        default = self._config.get("cpu", {}).get("default_affinity") or ""
        self._default_affinity_cb.setChecked(bool(default))
        self._default_affinity_edit.setText(default)
        self._default_affinity_edit.setEnabled(bool(default))
        self._default_affinity_cb.toggled.connect(self._default_affinity_edit.setEnabled)

        mon = self._config.get("monitor", {})
        self._rule_interval.setValue(mon.get("rule_enforce_interval_ms", 500))
        self._display_interval.setValue(mon.get("display_refresh_interval_ms", 2000))

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

    def _apply_cpu(self):
        if not self._default_affinity_cb.isChecked():
            self._config.setdefault("cpu", {})["default_affinity"] = None
            self.settings_changed.emit(self._config)
            QMessageBox.information(
                self, "Default Affinity",
                "Default affinity disabled. It will no longer be applied; "
                "current process affinities are left unchanged."
            )
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
