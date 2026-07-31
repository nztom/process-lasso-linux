"""Tests for fitting the main window to the available desktop workspace."""
from __future__ import annotations

import unittest

from gui.main_window import _window_size_for_available


class MainWindowSizingTests(unittest.TestCase):
    def test_keeps_existing_size_policy_when_it_fits(self):
        self.assertEqual(_window_size_for_available(1920, 1080), (1500, 907))

    def test_caps_size_to_small_workspace(self):
        self.assertEqual(_window_size_for_available(800, 600), (800, 600))

    def test_caps_only_the_constrained_dimension(self):
        self.assertEqual(_window_size_for_available(2560, 640), (1500, 640))


if __name__ == "__main__":
    unittest.main()
