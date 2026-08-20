"""Icon tests: theme tinting, cache reuse, graceful degradation."""

import unittest

from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

from podracer.icons import menu_icon, tinted_icon


def _opaque_colors(icon, mode, size=16):
    """The set of fully-opaque pixel colors of one icon mode."""
    pm = icon.pixmap(size, size, mode)
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    colors = set()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 255:
                colors.add((c.red(), c.green(), c.blue()))
    return colors


class TintedIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tint_fills_opaque_pixels_with_target_color(self):
        icon = tinted_icon("moon", "#00ff41", 24)
        self.assertFalse(icon.isNull())
        img = icon.pixmap(24, 24).toImage().convertToFormat(
            QImage.Format.Format_ARGB32
        )
        # Every fully-opaque pixel must be exactly the tint (0, 255, 65).
        # Semi-transparent edge pixels carry antialiasing + premultiply
        # rounding (65 * alpha / 255 lands off-by-one at alpha 254), so
        # only alpha == 255 is compared exactly.
        for y in range(img.height()):
            for x in range(img.width()):
                c = img.pixelColor(x, y)
                if c.alpha() == 255:
                    self.assertEqual((c.red(), c.green(), c.blue()),
                                     (0, 255, 65))

    def test_icons_cache_per_name_color_size(self):
        a = tinted_icon("sun", "#ffffff")
        b = tinted_icon("sun", "#ffffff")
        c = tinted_icon("sun", "#000000")
        self.assertIs(a, b)          # same key, same object
        self.assertIsNot(a, c)       # different tint, different render

    def test_missing_icon_degrades_to_text_only(self):
        icon = tinted_icon("no-such-icon", "#000000")
        self.assertTrue(icon.isNull())

    def test_menu_icon_has_resting_and_selected_modes(self):
        # Normal rides the item's resting text color; Selected rides
        # text_on_accent so the icon stays visible on the highlight.
        panel, accent_text = "#c0c0c0", "#0000ff"
        icon = menu_icon("sun", panel, accent_text)
        self.assertEqual(_opaque_colors(icon, QIcon.Mode.Normal),
                         {(192, 192, 192)})
        self.assertEqual(_opaque_colors(icon, QIcon.Mode.Selected),
                         {(0, 0, 255)})

    def test_menu_icon_checked_uses_accent_text(self):
        # The checked/current item sits on the darkened accent, so its
        # resting icon carries text_on_accent, matching its label.
        panel, accent_text = "#c0c0c0", "#0000ff"
        icon = menu_icon("sun", panel, accent_text, checked=True)
        self.assertEqual(_opaque_colors(icon, QIcon.Mode.Normal),
                         {(0, 0, 255)})


if __name__ == "__main__":
    unittest.main()
