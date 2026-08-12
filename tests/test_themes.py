"""Theme tests: palette sanity, contrast discipline, live switching."""

import unittest

from PySide6.QtWidgets import QApplication

from podracer.themes import (
    THEMES,
    Theme,
    apply_theme,
    contrast_ratio,
    theme_by_name,
)


class PaletteTests(unittest.TestCase):
    def test_all_colors_are_valid_hex(self):
        for theme in THEMES:
            for key, value in theme.colors.items():
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", f"{theme.name}.{key}")
            for value in (
                theme.window_gradient + theme.header_gradient
                + (theme.accent, theme.accent2, theme.panel_bg, theme.panel_text,
                   theme.text_on_accent)
            ):
                self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", theme.name)

    def test_body_text_contrast_aa(self):
        # WCAG AA: body text needs >= 4.5:1 against its background.
        for theme in THEMES:
            self.assertGreaterEqual(
                contrast_ratio(theme.panel_text, theme.panel_bg), 4.5, theme.name
            )
            self.assertGreaterEqual(
                contrast_ratio(theme.text_on_accent, theme.accent), 4.5, theme.name
            )
            self.assertGreaterEqual(
                contrast_ratio(theme.status_text, theme.window_gradient[0]), 4.5,
                theme.name,
            )

    def test_theme_registry(self):
        names = [t.name for t in THEMES]
        self.assertEqual(len(names), len(set(names)), "theme names must be unique")
        self.assertEqual(theme_by_name(THEMES[0].name), THEMES[0])
        with self.assertRaises(KeyError):
            theme_by_name("No Such Theme")


class ApplyThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_apply_theme_sets_stylesheet_and_palette(self):
        app = self.app
        app.setStyle("Fusion")
        for theme in THEMES:
            apply_theme(app, theme)
            self.assertIn("QMainWindow", app.styleSheet())
            self.assertEqual(app.palette().highlight().color().name().lower(),
                             theme.accent.lower())
            apply_theme(app, THEMES[0])  # back to default, stays consistent
        self.assertIn(THEMES[0].accent, app.styleSheet())

    def test_qss_covers_required_widgets(self):
        qss = THEMES[0].qss()
        for selector in ("QMainWindow", "QTreeView, QTableView", "QHeaderView::section",
                         "QPushButton", "QProgressBar", "QStatusBar", "QMenu",
                         "QLineEdit", "QToolTip", "QScrollBar"):
            self.assertIn(selector, qss)


if __name__ == "__main__":
    unittest.main()
