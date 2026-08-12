"""Bundled font tests: registration, application scaling, clamps."""

import unittest

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from podracer.fonts import MAX_SIZE, MIN_SIZE, apply_font, register_fonts


class FontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_fonts_register(self):
        register_fonts()
        families = set(QFontDatabase.families())
        for family in ("Comic Neue", "OpenDyslexic3", "IBM Plex Mono"):
            self.assertIn(family, families, family)

    def test_apply_font_sets_family_and_size(self):
        register_fonts()
        apply_font(self.app, "Comic Neue", 13)
        font = self.app.font()
        self.assertEqual(font.family(), "Comic Neue")
        self.assertEqual(font.pointSize(), 13)

    def test_size_clamped(self):
        register_fonts()
        apply_font(self.app, "OpenDyslexic3", 999)
        self.assertEqual(self.app.font().pointSize(), MAX_SIZE)
        apply_font(self.app, "OpenDyslexic3", 1)
        self.assertEqual(self.app.font().pointSize(), MIN_SIZE)

    def test_system_family_restores_real_system_font(self):
        # Regression: QFont() copies the CURRENT app font, so switching
        # back to System must come from QFontDatabase.systemFont().
        apply_font(self.app, "Comic Neue", 14)
        self.assertEqual(self.app.font().family(), "Comic Neue")
        apply_font(self.app, "", 11)
        self.assertEqual(self.app.font().pointSize(), 11)
        self.assertNotEqual(self.app.font().family(), "Comic Neue")

    def test_font_change_reaches_styled_widgets(self):
        # Regression: with a stylesheet active, QApplication.setFont
        # alone leaves styled widgets stale; apply_font must re-polish.
        from PySide6.QtWidgets import QTableView
        from podracer.themes import THEMES, apply_theme

        apply_theme(self.app, THEMES[0])
        view = QTableView()
        view.show()
        self.app.processEvents()
        apply_font(self.app, "Comic Neue", 17)
        self.app.processEvents()
        self.assertEqual(view.font().pointSize(), 17)
        self.assertEqual(view.font().family(), "Comic Neue")
        view.close()


if __name__ == "__main__":
    unittest.main()
