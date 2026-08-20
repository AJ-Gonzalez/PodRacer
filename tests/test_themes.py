"""Theme tests: palette sanity, contrast discipline, live switching."""

import unittest

from PySide6.QtWidgets import QApplication

from podracer.themes import (
    SYSTEM_THEME,
    THEMES,
    Theme,
    apply_theme,
    contrast_ratio,
    resolved_button_to,
    resolved_pressed,
    system_resolved_theme,
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

    def test_pressed_and_header_contrast_aa(self):
        # Derived states the base test misses: the checked/pressed
        # background (darken of the accent) must still read against
        # text_on_accent, and header text against both gradient stops.
        for theme in THEMES:
            self.assertGreaterEqual(
                contrast_ratio(resolved_pressed(theme), theme.text_on_accent),
                4.5,
                f"{theme.name} pressed/checked",
            )
            self.assertGreaterEqual(
                contrast_ratio(resolved_button_to(theme), theme.text_on_accent),
                4.5,
                f"{theme.name} button gradient stop",
            )
            for stop in theme.header_gradient:
                self.assertGreaterEqual(
                    contrast_ratio(stop, theme.header_text),
                    4.5,
                    f"{theme.name} header {stop}",
                )

    def test_theme_registry(self):
        names = [t.name for t in THEMES]
        self.assertEqual(len(names), len(set(names)), "theme names must be unique")
        self.assertEqual(theme_by_name(THEMES[0].name), THEMES[0])
        with self.assertRaises(KeyError):
            theme_by_name("No Such Theme")

    def test_system_theme_resolves_to_a_real_theme(self):
        # The sentinel is not a theme itself; the resolver always lands
        # on a bundled one (offscreen reports Light/Unknown).
        self.assertNotIn(SYSTEM_THEME, [t.name for t in THEMES])
        resolved = system_resolved_theme()
        self.assertIn(resolved, THEMES)


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
                         "QPushButton", "QPushButton:disabled", "QProgressBar",
                         "QStatusBar", "QMenu", "QLineEdit", "QToolTip",
                         "QScrollBar"):
            self.assertIn(selector, qss)

    def test_disabled_button_is_visible(self):
        # The disabled state must stay readable on any background:
        # accent-tinted fill with faded accent text (not white-on-white).
        qss = THEMES[0].qss()
        self.assertIn("rgba(183, 9, 76, 0.35)", qss)   # accent fill
        self.assertIn("rgba(255, 255, 255, 0.6)", qss)  # faded text


if __name__ == "__main__":
    unittest.main()
