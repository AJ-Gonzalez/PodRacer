"""Icon tests: theme tinting, cache reuse, graceful degradation."""

import unittest

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from podracer.icons import tinted_icon


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


if __name__ == "__main__":
    unittest.main()
