"""Entry point for podracer.

Opens the application shell. The two-pane UI lands in M3; this exists so the
app can be launched and smoke-tested end to end from day one.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


class MainWindow(QMainWindow):
    """Application shell. Left pane (local files) and right pane (iPod library) replace the placeholder in M3."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PodRacer")
        self.setCentralWidget(
            QLabel("Left: your music folder. Right: what goes on the iPod. UI lands in M3.")
        )


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
