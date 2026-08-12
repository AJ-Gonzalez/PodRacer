"""UI widget tests: LibraryView drop/delete dispatch, column resizing.

These pin the PySide6 virtual-override behavior: instance-attribute
assignments never fire, so the drop/Delete wiring must live in a real
subclass with signals.
"""

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QHeaderView

from podracer.ui import LibraryView, MainWindow


class _QtCase(unittest.TestCase):
    """Closes every leaked widget so Qt teardown does not segfault."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        # deleteLater() destroys the widgets while the QApplication is
        # still alive; bare close() leaves C++ objects that crash at
        # interpreter exit (seen: accepted-drop views holding mime state).
        for widget in self.app.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        self.app.processEvents()


class LibraryViewTests(_QtCase):
    def test_drop_emits_local_paths(self):
        view = LibraryView()
        received: list = []
        view.filesDropped.connect(received.append)
        with tempfile.TemporaryDirectory() as tmp:
            song = Path(tmp) / "song.mp3"
            song.write_bytes(b"x")
            # Keep mime + event alive across dropEvent: PySide6 GCs the
            # mime data when its wrapper goes out of scope, leaving the
            # event with a dangling pointer (segfault on urls()).
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(song))])
            event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                               Qt.MouseButton.LeftButton,
                               Qt.KeyboardModifier.NoModifier)
            view.dropEvent(event)
            del event, mime
        self.assertEqual(received, [[song]])  # payload is the path list

    def test_drop_ignores_non_local_urls(self):
        view = LibraryView()
        received: list = []
        view.filesDropped.connect(received.append)
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/song.mp3")])
        event = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        view.dropEvent(event)
        self.assertEqual(received, [])

    def test_delete_key_emits_request(self):
        view = LibraryView()
        fired: list = []
        view.deleteRequested.connect(lambda: fired.append(True))
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete,
                          Qt.KeyboardModifier.NoModifier)
        view.keyPressEvent(event)
        self.assertEqual(fired, [True])

    def test_other_keys_pass_through(self):
        view = LibraryView()
        fired: list = []
        view.deleteRequested.connect(lambda: fired.append(True))
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                          Qt.KeyboardModifier.NoModifier)
        view.keyPressEvent(event)
        self.assertEqual(fired, [])


class LeftPaneTests(_QtCase):
    def test_left_columns_resizable(self):
        win = MainWindow()
        header = win.fs_view.header()
        for col in range(header.count()):
            self.assertEqual(header.sectionResizeMode(col),
                             QHeaderView.ResizeMode.Interactive, col)
        self.assertTrue(header.stretchLastSection())
        win.close()


if __name__ == "__main__":
    unittest.main()
