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
import utils
from gui.main_window import MainWindow
from windows_theme import WINDOWS_DARK_THEME


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STARTUP_NICE = 15


def _set_process_name(name: str) -> None:
    """Set Linux's task name (limited by the kernel to 15 bytes)."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(15, name[:15].encode("utf-8"), 0, 0, 0)  # PR_SET_NAME
    except (AttributeError, OSError):
        # The display name is cosmetic; startup must not fail on other platforms.
        logging.getLogger(__name__).debug("Could not set process name", exc_info=True)


def _apply_startup_nice() -> bool:
    """Apply a one-time responsiveness boost that later rules may override."""
    applied = utils.set_nice(os.getpid(), STARTUP_NICE)
    if not applied:
        logging.getLogger(__name__).warning(
            "Could not apply startup nice priority %d", STARTUP_NICE
        )
    return applied


def main():
    _set_process_name(app_identity.PROCESS_NAME)
    _apply_startup_nice()

    # Required before QApplication on some platforms.
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("Process Lasso")
    app.setApplicationDisplayName("Process Lasso")
    app.setOrganizationName("process-lasso")
    app.setDesktopFileName("processlasso")

    config.load()
    app.setStyleSheet(WINDOWS_DARK_THEME)
    app.setProperty("pl_dark_theme_css", WINDOWS_DARK_THEME)

    # Closing the main window hides it to the system tray.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
