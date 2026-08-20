"""Theme tests: palette sanity, contrast discipline, live switching."""

import unittest

from PySide6.QtWidgets import QApplication

from podracer.themes import (
    HIDDEN_THEMES,
    SYSTEM_THEME,
    THEMES,
    apply_theme,
    contrast_checks,
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

    def test_all_aa_pairs_pass(self):
        # Every rendered text pair (incl. derived pressed/checked and
        # the button gradient stop) must clear WCAG-AA. contrast_checks
        # is the single source shared with scripts/check_contrast.py.
        for theme in THEMES + HIDDEN_THEMES:
            for label, _fg, _bg, ratio in contrast_checks(theme):
                self.assertGreaterEqual(
                    ratio, 4.5, f"{theme.name}: {label}"
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
        self.assertIn(resolved, THEMES + HIDDEN_THEMES)

    def test_hidden_system_themes_are_flat(self):
        # Identical gradient stops mean no sweeps anywhere. Their
        # contrast is covered by test_all_aa_pairs_pass (which iterates
        # THEMES + HIDDEN_THEMES).
        for theme in HIDDEN_THEMES:
            self.assertEqual(theme.window_gradient[0], theme.window_gradient[1],
                             f"{theme.name} window gradient")
            self.assertEqual(theme.header_gradient[0], theme.header_gradient[1],
                             f"{theme.name} header gradient")
            self.assertEqual(theme.button_to, theme.accent,
                             f"{theme.name} button flat")


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
