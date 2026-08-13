"""PodRacer entry point.

`podracer` from a terminal, or double-click (the onefile bundle).
`--smoke` constructs the window offscreen, runs 300 ms, and exits —
used by tests and CI.
"""

from __future__ import annotations

import shutil
import sys

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox


def _icon_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)  # PyInstaller onefile temp dir
    if meipass:
        return Path(meipass) / "podracer" / "assets" / "podracer_icon.png"
    return Path(__file__).resolve().parent / "assets" / "podracer_icon.png"

# Absolute import: this file also runs as a bare script inside the
# onefile bundle, where relative imports have no parent package.
from podracer.themes import THEMES, apply_theme
from podracer.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PodRacer")
    app.setOrganizationName("PodRacer")
    # Fusion as the style base so the theme QSS paints consistently
    # across desktops; the status-bar Theme button re-skins live.
    app.setStyle("Fusion")
    apply_theme(app, THEMES[0])
    icon = _icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    if not shutil.which("ffmpeg"):
        QMessageBox.critical(
            None, "PodRacer",
            "ffmpeg is not installed, so music cannot be copied or converted.\n"
            "Install it with: sudo zypper install ffmpeg",
        )
        return 1
    if not shutil.which("udisksctl"):
        QMessageBox.critical(
            None, "PodRacer",
            "udisksctl is not installed, so the iPod cannot be mounted.\n"
            "Install it with: sudo zypper install udisks2",
        )
        return 1

    window = MainWindow()
    if "--demo" in app.arguments():
        # Synthetic library + fake music tree; nothing real is read.
        # Screenshots of theme showcases come from this mode.
        window._enter_demo_mode()
    if icon.is_file():
        # The app icon covers the taskbar; the window needs its own
        # copy for the title bar on some window managers.
        window.setWindowIcon(QIcon(str(icon)))
    # The two-pane layout is unusable when small; start maximized.
    window.showMaximized()

    if "--smoke" in app.arguments():
        QTimer.singleShot(300, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
