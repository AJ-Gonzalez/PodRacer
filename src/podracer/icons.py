"""Theme-tinted icons: bundled Lucide SVGs recolored per theme.

Lucide (ISC license, Feather-derived icons MIT — see
assets/icons/LICENSE-Lucide.txt) ships monochrome stroke icons with
stroke="currentColor". Qt renders currentColor as black, so to make the
icons ride each theme's text color we render the SVG and recolor every
opaque pixel with SourceIn composition against the target color.

The color comes from the caller: buttons sit on the accent gradient, so
they use text_on_accent; menu items sit on panels, so they use
panel_text. Both are WCAG-AA-checked pairs, so icons inherit the
theme's contrast discipline for free.

Rendered pixmaps are cached per (icon, color, size); theme switches
just hit new cache keys. HiDPI-aware: renders at the screen's device
pixel ratio so icons stay crisp on scaled displays.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}


def icon_path(name: str) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller onefile temp dir
    if meipass:
        return Path(meipass) / "podracer" / "assets" / "icons" / f"{name}.svg"
    return Path(__file__).resolve().parent / "assets" / "icons" / f"{name}.svg"


def _tinted_pixmap(name: str, color: str, size: int) -> QPixmap:
    """Render the SVG once, recolor every opaque pixel with `color`."""
    path = icon_path(name)
    if not path.is_file():
        return QPixmap()
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer = QSvgRenderer(str(path))
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    _ = painter.fillRect(pm.rect(), QColor(color))
    painter.end()
    return pm


def tinted_icon(name: str, color: str, size: int = 16) -> QIcon:
    """The bundled icon `name`, rendered in `color` at `size` px.

    A missing SVG degrades to an empty QIcon (text-only), never a
    crash — the bundle and the source tree both ship the icons, so
    this is a belt-and-braces guard.
    """
    key = (name, color, size)
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    pm = _tinted_pixmap(name, color, size)
    icon = QIcon(pm)
    _ICON_CACHE[key] = icon
    return icon


def menu_icon(name: str, panel_text: str, text_on_accent: str,
              checked: bool = False, size: int = 16) -> QIcon:
    """Two-mode menu icon: visible on every menu-item background.

    Qt renders a highlighted menu row in QIcon.Selected mode, so the
    Selected pixmap carries text_on_accent (the highlight's text
    color, AA-checked against the accent). The Normal pixmap carries
    the resting text color: panel_text for plain items, or
    text_on_accent for the checked/current item, which sits on the
    darkened accent (its label already switches to text_on_accent).
    """
    resting = text_on_accent if checked else panel_text
    icon = QIcon()
    icon.addPixmap(_tinted_pixmap(name, resting, size),
                   QIcon.Mode.Normal)
    icon.addPixmap(_tinted_pixmap(name, text_on_accent, size),
                   QIcon.Mode.Selected)
    return icon
