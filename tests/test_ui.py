"""UI widget tests: LibraryView drop/delete dispatch, column resizing.

These pin the PySide6 virtual-override behavior: instance-attribute
assignments never fire, so the drop/Delete wiring must live in a real
subclass with signals.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
)

from podracer_db.model import Track
from podracer.fonts import FONT_OPTIONS, LINE_SPACINGS, MAX_SIZE, MIN_SIZE
from podracer.themes import (
    HIDDEN_THEMES,
    SYSTEM_THEME,
    THEMES,
    theme_label,
)
from podracer.ui import (
    BulkMetadataDialog,
    LibraryView,
    MainWindow,
    MetadataDialog,
    TracksModel,
)


def _synthetic_db_with_track(count=1) -> bytes:
    """A real iTunesDB with tagged tracks (no gitignored fixture)."""
    from podracer_db import write_db
    from podracer_db.model import Library, Playlist, Track

    tracks = []
    for i in range(count):
        title = "Orig Title" if i == 0 else f"Song {i + 1}"
        tracks.append(Track(
            title=title, artist="Orig Artist",
            album="Orig Album", genre="Orig Genre",
            ipod_path=f":iPod_Control:Music:F00:AB{i:02X}.mp3",
        ))
    lib = Library(tracks=tracks)
    lib.playlists = [
        Playlist(name="Hyperpink", ptype=1, id=0x1234, members=tracks)
    ]
    return write_db(lib, firewire_guid="0011223344556677")


class _FakeSession:
    """Duck-typed SyncSession: enough tracks for selection tests."""

    tracks = [Track(title="A"), Track(title="B"), Track(title="C")]


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

    def test_ctrl_click_selects_multiple_rows(self):
        view = LibraryView()
        model = TracksModel()
        model.set_session(_FakeSession())
        view.setModel(model)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        view.resize(400, 200)
        view.show()
        self.app.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         view.visualRect(model.index(0, 0)).center())
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         view.visualRect(model.index(2, 0)).center())
        rows = sorted(i.row() for i in view.selectionModel().selectedRows())
        self.assertEqual(rows, [0, 2])


class LeftPaneTests(_QtCase):
    def test_left_columns_resizable(self):
        win = MainWindow()
        header = win.fs_view.header()
        for col in range(header.count()):
            self.assertEqual(header.sectionResizeMode(col),
                             QHeaderView.ResizeMode.Interactive, col)
        self.assertTrue(header.stretchLastSection())
        win.close()

    def test_left_pane_multi_select_enabled(self):
        # The default selection mode is SingleSelection, which silently
        # disables Ctrl+click; the left pane must allow multi-select so
        # several folders can be dragged to the iPod at once.
        win = MainWindow()
        self.assertEqual(
            win.fs_view.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
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
                guid="0011223344556677", serial="AB12CD34EF56",
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


class MetadataEditTests(_QtCase):
    """Tag editing: dialog prefill + dialog-free apply path."""

    def _make_window_with_session(self, count=1):
        from podracer import device
        from podracer.sync import SyncSession

        tmp = tempfile.TemporaryDirectory()
        ipod_dir = Path(tmp.name) / "HYPERPINK"
        (ipod_dir / "iPod_Control" / "iTunes").mkdir(parents=True)
        (ipod_dir / "iPod_Control" / "Music").mkdir(parents=True)
        (ipod_dir / "iPod_Control" / "iTunes" / "iTunesDB").write_bytes(
            _synthetic_db_with_track(count)
        )
        ipod = device.IPod(
            mountpoint=ipod_dir, label="HYPERPINK", block_device="sdb1",
            guid="0011223344556677", serial="AB12CD34EF56",
            family_id=12, db_version=3,
        )
        win = MainWindow()
        win.session = SyncSession(ipod, sidecar=Path(tmp.name) / "lib.sqlite")
        win.tracks_model.set_session(win.session)
        return win, tmp

    def test_dialog_prefills_track_fields(self):
        win, tmp = self._make_window_with_session()
        try:
            track = win.session.tracks[0]
            dialog = MetadataDialog(track, win)
            self.assertEqual(dialog.values(), {
                "title": "Orig Title", "artist": "Orig Artist",
                "album": "Orig Album", "genre": "Orig Genre",
            })
            dialog._edits["Title"].setText("New")
            self.assertEqual(dialog.values()["title"], "New")
        finally:
            win._dirty = False  # closeEvent would open the quit-guard modal
            win.session.close()
            win.close()
            tmp.cleanup()

    def test_apply_metadata_edits_track_and_marks_dirty(self):
        win, tmp = self._make_window_with_session()
        try:
            win._apply_metadata(0, {
                "title": "New Title", "artist": "New Artist",
                "album": "New Album", "genre": "New Genre",
            })
            track = win.session.tracks[0]
            self.assertEqual(track.title, "New Title")
            self.assertEqual(track.artist, "New Artist")
            self.assertEqual(track.album, "New Album")
            self.assertEqual(track.genre, "New Genre")
            self.assertTrue(win._dirty)
            # The model cell reflects the edit (dataChanged fired).
            self.assertEqual(
                win.tracks_model.data(win.tracks_model.index(0, 0)),
                "New Title",
            )
        finally:
            win._dirty = False  # closeEvent would open the quit-guard modal
            win.session.close()
            win.close()
            tmp.cleanup()

    def test_apply_metadata_noop_stays_clean(self):
        win, tmp = self._make_window_with_session()
        try:
            win._apply_metadata(0, {
                "title": "Orig Title", "artist": "Orig Artist",
                "album": "Orig Album", "genre": "Orig Genre",
            })
            self.assertFalse(win._dirty)
        finally:
            win.session.close()
            win.close()
            tmp.cleanup()

    def test_bulk_dialog_empty_values(self):
        dialog = BulkMetadataDialog(3)
        self.assertEqual(dialog.values(), {})
        dialog.deleteLater()

    def test_bulk_dialog_only_filled_fields(self):
        dialog = BulkMetadataDialog(3)
        dialog._edits["Artist"].setText("  New Artist  ")
        dialog._edits["Genre"].setText("")
        self.assertEqual(dialog.values(), {"artist": "New Artist"})
        dialog.deleteLater()

    def test_bulk_dialog_title_protected_by_default(self):
        dialog = BulkMetadataDialog(3)
        guard = dialog._title_guard
        self.assertTrue(guard.isChecked())
        self.assertFalse(dialog._edits["Title"].isEnabled())
        # A stray value in the disabled field must never apply.
        dialog._edits["Title"].setText("Clobbered")
        self.assertEqual(dialog.values(), {})
        dialog.deleteLater()

    def test_bulk_dialog_title_guard_releases_field(self):
        dialog = BulkMetadataDialog(3)
        dialog._title_guard.setChecked(False)
        self.assertTrue(dialog._edits["Title"].isEnabled())
        dialog._edits["Title"].setText("Same Title")
        self.assertEqual(dialog.values(), {"title": "Same Title"})
        dialog.deleteLater()

    def test_apply_bulk_metadata_edits_all_and_dirty(self):
        win, tmp = self._make_window_with_session(count=2)
        try:
            rows = [win.tracks_model.index(0, 0), win.tracks_model.index(1, 0)]
            win._apply_bulk_metadata(rows, {
                "artist": "Bulk Artist", "album": "Bulk Album",
            })
            tracks = win.session.tracks
            self.assertEqual([t.artist for t in tracks],
                             ["Bulk Artist", "Bulk Artist"])
            self.assertEqual([t.album for t in tracks],
                             ["Bulk Album", "Bulk Album"])
            self.assertTrue(win._dirty)
            # The untouched title still shows in the model.
            self.assertEqual(
                win.tracks_model.data(win.tracks_model.index(1, 0)),
                "Song 2",
            )
        finally:
            win._dirty = False  # closeEvent would open the quit-guard modal
            win.session.close()
            win.close()
            tmp.cleanup()

    def test_apply_bulk_metadata_empty_values_noop(self):
        win, tmp = self._make_window_with_session(count=2)
        try:
            rows = [win.tracks_model.index(0, 0), win.tracks_model.index(1, 0)]
            win._apply_bulk_metadata(rows, {})
            self.assertFalse(win._dirty)
        finally:
            win.session.close()
            win.close()
            tmp.cleanup()

    def test_apply_rename_renames_session_and_label(self):
        from podracer import device as device_mod

        win, tmp = self._make_window_with_session()
        try:
            with mock.patch.object(
                device_mod, "rename_label"
            ) as rename_label:
                win._apply_rename("STONER")
            self.assertEqual(win.session.device_name, "STONER")
            self.assertTrue(win._dirty)
            rename_label.assert_called_once_with(
                win.session.ipod, "STONER")
            self.assertEqual(win.device_label.text(), "STONER")
        finally:
            win._dirty = False  # closeEvent would open the quit-guard modal
            win.session.close()
            win.close()
            tmp.cleanup()


class MusicHomeTests(_QtCase):
    def setUp(self):
        # Isolate QSettings so tests never touch the real config.
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self._tmp.cleanup()
        super().tearDown()

    def test_set_top_level_navigates_without_persisting(self):
        with tempfile.TemporaryDirectory() as folder:
            win = MainWindow()
            # Pin a known default; set-top-level must leave it untouched
            # (session-only, unlike the persistent default action).
            win.settings.setValue("fs/home", "sentinel")
            win._set_top_level(Path(folder))
            self.assertEqual(
                Path(win.fs_model.filePath(
                    win.fs_proxy.mapToSource(win.fs_view.rootIndex()))),
                Path(folder),
            )
            self.assertEqual(
                win.settings.value("fs/home", "", str), "sentinel")
            win.close()

    def test_set_music_home_persists_and_navigates(self):
        with tempfile.TemporaryDirectory() as folder:
            win = MainWindow()
            win._set_music_home(Path(folder))
            self.assertEqual(win.settings.value("fs/home", "", str), folder)
            self.assertEqual(Path(win.fs_model.filePath(win.fs_proxy.mapToSource(win.fs_view.rootIndex()))),
                             Path(folder))
            win.close()

    def test_startup_uses_saved_music_home(self):
        with tempfile.TemporaryDirectory() as folder:
            win = MainWindow()
            win._set_music_home(Path(folder))
            win.close()
            win2 = MainWindow()
            self.assertEqual(Path(win2.fs_model.filePath(win2.fs_proxy.mapToSource(win2.fs_view.rootIndex()))),
                             Path(folder))
            win2.close()

    def test_clear_music_home_returns_to_home(self):
        with tempfile.TemporaryDirectory() as folder:
            win = MainWindow()
            win._set_music_home(Path(folder))
            win._clear_music_home()
            self.assertEqual(win.settings.value("fs/home", "", str), "")
            self.assertEqual(Path(win.fs_model.filePath(win.fs_proxy.mapToSource(win.fs_view.rootIndex()))),
                             Path.home())
            win.close()

    def test_stale_saved_home_falls_back(self):
        # A saved folder that no longer exists must not break startup.
        gone = Path(self._tmp.name) / "does-not-exist"
        win = MainWindow()
        win.settings.setValue("fs/home", str(gone))
        win.close()
        win2 = MainWindow()
        self.assertEqual(win2._music_home(), str(Path.home()))
        win2.close()


class AppearanceMenuTests(_QtCase):
    def setUp(self):
        # Isolate QSettings so switching themes in a test never touches
        # the real saved appearance.
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self._tmp.cleanup()
        super().tearDown()

    def test_appearance_is_one_button_with_four_submenus(self):
        win = MainWindow()
        submenus = [a.text() for a in win.appearance_menu.actions() if a.menu()]
        self.assertEqual(
            submenus, ["Theme", "Font", "Font size", "Line spacing"]
        )
        self.assertEqual(len(win._theme_actions), len(THEMES))
        self.assertEqual(len(win._font_actions), len(FONT_OPTIONS))
        self.assertEqual(len(win._size_actions), MAX_SIZE - MIN_SIZE + 1)
        self.assertEqual(len(win._line_spacing_actions), len(LINE_SPACINGS))
        win.close()

    def test_line_spacing_applies_and_checks(self):
        win = MainWindow()
        baseline = win.lib_view.verticalHeader().defaultSectionSize()
        label, factor = LINE_SPACINGS[-1]
        text = f"{label} ({int(round(factor * 100))}%)"
        target = next(
            a for a in win._line_spacing_actions if a.text() == text
        )
        target.trigger()
        self.assertEqual(win._line_spacing, factor)
        self.assertEqual(
            float(win.settings.value("font/line_spacing", 1.0, float)),
            factor,
        )
        self.assertGreater(
            win.lib_view.verticalHeader().defaultSectionSize(), baseline
        )
        self.assertEqual(win._fs_delegate.factor, factor)
        checked = [a for a in win._line_spacing_actions if a.isChecked()]
        self.assertEqual([a.text() for a in checked], [text])
        win.close()

    def test_theme_switch_moves_checkmark(self):
        win = MainWindow()
        win._apply_theme(THEMES[1])
        checked = [a for a in win._theme_actions if a.isChecked()]
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0].text(), theme_label(THEMES[1]))
        win.close()

    def test_theme_menu_shows_dark_light_with_moon_sun(self):
        win = MainWindow()
        for action, theme in zip(win._theme_actions, THEMES):
            self.assertEqual(action.text(), theme_label(theme))
            self.assertFalse(action.icon().isNull())
        win.close()

    def test_system_theme_action_present_and_applies(self):
        win = MainWindow()
        action = win._system_theme_action
        self.assertIsNotNone(action)
        self.assertEqual(action.text(), f"{SYSTEM_THEME}\t(Boring)")
        self.assertFalse(action.icon().isNull())
        action.trigger()
        self.assertEqual(win._theme_name, SYSTEM_THEME)
        self.assertEqual(
            win.settings.value("theme/name", "", str), SYSTEM_THEME
        )
        # While following, the rendered theme is always a real one and
        # the checkmark stays on the system action.
        self.assertIn(win._current_theme().name,
                      [t.name for t in THEMES + HIDDEN_THEMES])
        checked = [a for a in win._theme_actions if a.isChecked()]
        self.assertEqual(checked, [])
        self.assertTrue(action.isChecked())
        # Picking a real theme leaves system mode. The menu rebuilds,
        # so the action reference must be re-fetched.
        win._apply_theme(THEMES[1])
        self.assertFalse(win._system_theme_action.isChecked())
        win.close()

    def test_size_action_applies_and_checks(self):
        win = MainWindow()
        target = win._size_actions[0]
        target.trigger()
        self.assertEqual(win._font_size, MIN_SIZE)
        checked = [a for a in win._size_actions if a.isChecked()]
        self.assertEqual([a.text() for a in checked], [f"{MIN_SIZE} pt"])
        win.close()


class FsFilterTests(_QtCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self._tmp.cleanup()
        super().tearDown()

    def test_browser_hides_album_junk(self):
        # Covers and scene NFOs must not be visible (or draggable) in
        # the left pane; directories and real media stay.
        import time

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "song.mp3").write_bytes(b"x")
            (root / "clip.m4v").write_bytes(b"x")
            (root / "cover.jpg").write_bytes(b"x")
            (root / "info.nfo").write_bytes(b"x")
            (root / "subdir").mkdir()
            win = MainWindow()
            win._set_music_home(root)
            # QFileSystemModel populates asynchronously.
            deadline = time.monotonic() + 5
            while (win.fs_proxy.rowCount(win.fs_view.rootIndex()) == 0
                   and time.monotonic() < deadline):
                self.app.processEvents()
                time.sleep(0.01)
            names = sorted(
                win.fs_model.fileName(
                    win.fs_proxy.mapToSource(
                        win.fs_proxy.index(row, 0, win.fs_view.rootIndex())
                    )
                )
                for row in range(win.fs_proxy.rowCount(win.fs_view.rootIndex()))
            )
            self.assertEqual(names, ["clip.m4v", "song.mp3", "subdir"])
            win.close()


if __name__ == "__main__":
    unittest.main()
