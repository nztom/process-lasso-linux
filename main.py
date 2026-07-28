#!/usr/bin/env python3
"""Process Lasso — Linux KDE process manager with ProBalance.

Entry point: configures Qt and starts the main window.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys

from PyQt6.QtWidgets import QApplication

import app_identity
import config
from gui.main_window import MainWindow
from windows_theme import WINDOWS_DARK_THEME


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _set_process_name(name: str) -> None:
    """Set Linux's task name (limited by the kernel to 15 bytes)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(15, name[:15].encode("utf-8"), 0, 0, 0)  # PR_SET_NAME
    except (AttributeError, OSError):
        # The display name is cosmetic; startup must not fail on other platforms.
        logging.getLogger(__name__).debug("Could not set process name", exc_info=True)


def main():
    _set_process_name(app_identity.PROCESS_NAME)

    # Required before QApplication on some platforms.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("Process Lasso")
    app.setApplicationDisplayName("Process Lasso")
    app.setOrganizationName("process-lasso")

    config.load()
    app.setStyleSheet(WINDOWS_DARK_THEME)
    app.setProperty("pl_dark_theme_css", WINDOWS_DARK_THEME)

    # Closing the main window hides it to the system tray.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
