"""Bundled fonts: registration + application-wide font control.

Comic Neue and OpenDyslexic are the dyslexia-friendly options
(AGENTS.md), IBM Plex Mono is the monospace option, Macondo and
Amarante are the display/art options. All are SIL OFL and shipped
inside the app bundle; Qt loads them from disk or from the PyInstaller
onefile temp dir.

`apply_font()` re-scales the whole UI live: Qt propagates the
application font to every widget, and layouts recompute from font
metrics, so larger text genuinely grows the interface.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

# (regular, bold) — bold may be None for single-weight families.
FONTS = {
    "OpenDyslexic3": ("OpenDyslexic3Regular.ttf", "OpenDyslexic3Bold.ttf"),
    "Comic Neue": ("ComicNeue-Regular.ttf", "ComicNeue-Bold.ttf"),
    "IBM Plex Mono": ("IBMPlexMono-Regular.ttf", "IBMPlexMono-Bold.ttf"),
    "Macondo": ("Macondo-Regular.ttf", None),
    "Amarante": ("Amarante-Regular.ttf", None),
}

# Order shown in the switcher; "" = the platform's system font.
FONT_OPTIONS = [("System Font", ""), ("Comic Neue", "Comic Neue"),
                ("OpenDyslexic3", "OpenDyslexic3"),
                ("IBM Plex Mono", "IBM Plex Mono"),
                ("Macondo", "Macondo"),
                ("Amarante", "Amarante")]

MIN_SIZE = 9
MAX_SIZE = 24


def _fonts_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller onefile temp dir
    if meipass:
        return Path(meipass) / "podracer" / "fonts"
    return Path(__file__).resolve().parent / "fonts"

def register_fonts() -> None:
    """Load every bundled font weight once; safe to call repeatedly."""
    for _family, (regular, bold) in FONTS.items():
        for name in (regular, bold):
            if name is None:
                continue
            path = _fonts_dir() / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
def apply_font(app, family: str, size_pt: int) -> None:
    """Set the application font; the whole UI re-scales instantly.

    family "" means the platform's real system font: a bare QFont()
    copies the CURRENT application font (so 'back to system' would
    stay on the previous family), hence QFontDatabase.systemFont().
    """
    if family:
        font = QFont()
        font.setFamily(family)
    else:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setPointSize(max(MIN_SIZE, min(MAX_SIZE, size_pt)))
    app.setFont(font)
    # Qt's stylesheet engine caches each widget's font at polish time
    # and ignores the application-font change for styled widgets.
    # Re-setting the sheet re-polishes everything against the new font.
    sheet = app.styleSheet()
    if sheet:
        app.setStyleSheet(sheet)
