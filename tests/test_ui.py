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


class StatusBarTests(_QtCase):
    def test_status_uses_label_not_showmessage(self):
        # Qt 6.11 paints QStatusBar.showMessage at the far-left edge,
        # ON TOP of the normal widgets — the overlap seen when the iPod
        # connects ("Mounted HYPERPINK." over the device/track buttons).
        # Status text must live in a real, layout-participating label.
        win = MainWindow()
        win._status("Mounted HYPERPINK.")
        self.assertEqual(win.status_label.text(), "Mounted HYPERPINK.")
        self.assertEqual(win.statusBar().currentMessage(), "")
        win.show()
        self.app.processEvents()
        # The label sits between the left buttons and the permanent
        # widgets, never over them.
        self.assertGreater(win.status_label.geometry().x(),
                           win.device_label.geometry().right())
        self.assertLess(win.status_label.geometry().x(),
                        win.remove_button.geometry().x())
        win.close()

    def test_status_auto_clears_after_timeout(self):
        win = MainWindow()
        win._status("Transient")
        self.assertEqual(win.status_label.text(), "Transient")
        win._status_timer.timeout.emit()
        self.assertEqual(win.status_label.text(), "")
        win.close()


class QuitGuardTests(_QtCase):
    def test_clean_session_closes(self):
        win = MainWindow()
        self.assertEqual(win._quit_action(), "close")
        win.close()

    def test_dirty_requires_decision(self):
        win = MainWindow()
        win.session = object()  # a connected session is required
        win._dirty = True
        self.assertEqual(win._quit_action(), "unsynced")
        # Reset before close: closeEvent on a dirty window opens the
        # modal quit-guard dialog, which would block the test.
        win._dirty = False
        win.session = None
        win.close()

    def test_running_transfer_blocks_close(self):
        win = MainWindow()
        class _FakeWorker:
            def isRunning(self) -> bool:
                return True
        win._worker = _FakeWorker()
        self.assertEqual(win._quit_action(), "transfer")
        win._worker = None
        win.close()

    def test_sync_clears_dirty_and_writes_db(self):
        import tempfile
        from pathlib import Path

        from podracer import device
        from podracer.sync import SyncSession

        with tempfile.TemporaryDirectory() as tmp:
            ipod_dir = Path(tmp) / "HYPERPINK"
            (ipod_dir / "iPod_Control" / "iTunes").mkdir(parents=True)
            (ipod_dir / "iPod_Control" / "Music").mkdir(parents=True)
            ipod = device.IPod(
                mountpoint=ipod_dir, label="HYPERPINK", block_device="sdb1",
                guid="000A27001BB9E492", serial="YM825HUD13F",
                family_id=12, db_version=3,
            )
            win = MainWindow()
            win.session = SyncSession(ipod, sidecar=Path(tmp) / "lib.sqlite")
            win._dirty = True
            win._sync()
            self.assertFalse(win._dirty)
            self.assertTrue((ipod_dir / "iPod_Control/iTunes/iTunesDB").is_file())
            win.session.close()
            win.close()


if __name__ == "__main__":
    unittest.main()
