#!/usr/bin/env python3
"""Process Lasso — Linux KDE process manager with ProBalance.

Entry point: configures Qt and starts the main window.
"""
from __future__ import annotations

import logging
import os
import sys

from PyQt6.QtWidgets import QApplication

import config
from gui.main_window import MainWindow
from windows_theme import WINDOWS_DARK_THEME


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main():
    # Required before QApplication on some platforms.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("Process Lasso")
    app.setApplicationDisplayName("Process Lasso")
    app.setOrganizationName("process-lasso")

    startup_config = config.load()
    if not startup_config.get("ui", {}).get("use_system_theme", False):
        app.setStyleSheet(WINDOWS_DARK_THEME)
    app.setProperty("pl_dark_theme_css", WINDOWS_DARK_THEME)

    # Closing the main window hides it to the system tray.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
