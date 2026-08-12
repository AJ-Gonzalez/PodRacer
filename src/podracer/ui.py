"""PodRacer UI: two-pane midnight-commander-style shell.

Left pane browses the local filesystem (QFileSystemModel), right pane
is the iPod library. Drag files from anywhere onto the right pane to
add them; select and press Delete to remove; Eject writes the DB and
unmounts. A 3-second timer watches for the iPod appearing/disappearing.

Theme support lands after the layout (themes.py): the window only
ships a stylesheet hook today.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSettings,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from . import device
from .fonts import FONT_OPTIONS, MAX_SIZE, MIN_SIZE, apply_font, register_fonts
from .pipeline import AddResult
from .sync import SyncSession
from .themes import THEMES, apply_theme
from podracer_db.model import Track

def _fmt_ms(ms: int) -> str:
    ms = max(0, ms)
    return f"{ms // 60000}:{ms % 60000 // 1000:02d}"


class TracksModel(QAbstractTableModel):
    """Flat library list over a SyncSession's tracks."""

    HEADERS = ("Title", "Artist", "Album", "Time")

    def __init__(self, session: SyncSession | None = None) -> None:
        super().__init__()
        self.session = session

    def set_session(self, session: SyncSession | None) -> None:
        self.beginResetModel()
        self.session = session
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid() or self.session is None:
            return 0
        return len(self.session.tracks)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return len(self.HEADERS) if not parent.isValid() else 0

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.session is None:
            return None
        track = self.session.tracks[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                0: track.title or "",
                1: track.artist or "",
                2: track.album or "",
                3: _fmt_ms(track.tracklen),
            }[index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def track_at(self, row: int) -> Track | None:
        if self.session is None or not (0 <= row < len(self.session.tracks)):
            return None
        return self.session.tracks[row]


class AddWorker(QThread):
    """Adds dropped files in the background; cancel between files."""

    fileStarted = Signal(str)
    fileDone = Signal(object)      # AddResult
    finishedAll = Signal(object)   # list[AddResult]

    def __init__(self, session: SyncSession, sources: list[Path]) -> None:
        super().__init__()
        self.session = session
        self.sources = sources
        self.cancelled = False

    def run(self) -> None:
        results: list[AddResult] = []
        for source in self.sources:
            if self.cancelled:
                break
            self.fileStarted.emit(str(source))
            result = self.session.add(source)
            results.append(result)
            self.fileDone.emit(result)
        self.finishedAll.emit(results)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session: SyncSession | None = None
        self._device_key: str | None = None
        self._worker: AddWorker | None = None

        self.setWindowTitle("PodRacer")
        self.resize(1100, 640)

        # -- left pane: filesystem -------------------------------------
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath(str(Path.home()))
        self.fs_view = QTreeView(self)
        self.fs_view.setModel(self.fs_model)
        self.fs_view.setRootIndex(self.fs_model.index(str(Path.home())))
        self.fs_view.setDragEnabled(True)
        self.fs_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.fs_view.setHeaderHidden(False)
        self.fs_view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.path_bar = QLineEdit(self)
        self.path_bar.setText(str(Path.home()))
        self.path_bar.returnPressed.connect(self._goto_path)
        self.up_button = QPushButton("Up", self)
        self.up_button.clicked.connect(self._go_up)
        left_bar = QHBoxLayout()
        left_bar.addWidget(self.up_button)
        left_bar.addWidget(self.path_bar, 1)

        left_pane = QWidget(self)
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(left_bar)
        left_layout.addWidget(self.fs_view, 1)
        left_pane.setMinimumWidth(280)

        # -- right pane: library ---------------------------------------
        self.tracks_model = TracksModel()
        self.lib_view = QTableView(self)
        self.lib_view.setModel(self.tracks_model)
        self.lib_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lib_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lib_view.setAcceptDrops(True)
        self.lib_view.setDropIndicatorShown(True)
        self.lib_view.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for col in (1, 2):
            self.lib_view.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.lib_view.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Fixed
        )
        self.lib_view.setColumnWidth(3, 64)

        right_pane = QWidget(self)
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.lib_view, 1)
        right_pane.setMinimumWidth(420)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(left_pane)
        self.splitter.addWidget(right_pane)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.setCentralWidget(self.splitter)

        # -- status bar --------------------------------------------------
        # addWidget() returns None in PySide6: build the widgets first.
        self.device_label = QPushButton("No iPod", self)
        self.device_label.setFlat(True)
        self.device_label.setEnabled(False)
        self.device_label.setToolTip("Plug in the iPod and it shows up here.")
        self.track_count = QPushButton("", self)
        self.track_count.setFlat(True)
        self.track_count.setEnabled(False)
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self._cancel_add)
        self.cancel_button.hide()
        self.eject_button = QPushButton("Eject", self)
        self.eject_button.clicked.connect(self._eject)
        self.eject_button.setEnabled(False)
        self.eject_button.setToolTip("Write the library to the iPod and unmount it.")
        self.theme_button = QPushButton("Theme", self)
        self.theme_button.setToolTip("Switch the look of PodRacer (instant).")
        self.theme_button.clicked.connect(self._show_theme_menu)
        self.theme_menu = QMenu(self)
        self._theme_actions: list = []
        self.font_button = QPushButton("Font", self)
        self.font_button.setToolTip("Choose the text font.")
        self.font_button.clicked.connect(self._show_font_menu)
        self.font_menu = QMenu(self)
        self._font_actions: list = []
        self.size_down = QPushButton("Aa−", self)
        self.size_down.setToolTip("Smaller text")
        self.size_down.clicked.connect(lambda: self._bump_font(-1))
        self.size_up = QPushButton("Aa+", self)
        self.size_up.setToolTip("Larger text")
        self.size_up.clicked.connect(lambda: self._bump_font(1))
        self.statusBar().addWidget(self.device_label)
        self.statusBar().addWidget(self.track_count)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().addPermanentWidget(self.eject_button)
        self.statusBar().addPermanentWidget(self.theme_button)
        self.statusBar().addPermanentWidget(self.font_button)
        self.statusBar().addPermanentWidget(self.size_down)
        self.statusBar().addPermanentWidget(self.size_up)
        self._rebuild_theme_menu()
        self._rebuild_font_menu()
        self._load_settings()

        # -- device watcher ----------------------------------------------
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll_device)
        self._timer.start()
        self._poll_device()

        # drag & drop and keyboard wiring
        self.lib_view.dragEnterEvent = self._drag_enter
        self.lib_view.dropEvent = self._drop
        self.lib_view.keyPressEvent = self._lib_key

    # -- theme ----------------------------------------------------------

    def _rebuild_theme_menu(self) -> None:
        self.theme_menu.clear()
        self._theme_actions = []
        current = self.theme_button.text()
        for theme in THEMES:
            action = self.theme_menu.addAction(theme.name)
            action.setCheckable(True)
            action.setChecked(theme.name == current)
            action.triggered.connect(
                lambda _=False, t=theme: self._apply_theme(t)
            )
            self._theme_actions.append(action)

    # -- font / size / persistence --------------------------------------

    def _rebuild_font_menu(self) -> None:
        self.font_menu.clear()
        self._font_actions = []
        current = self.font_button.text()
        for label, family in FONT_OPTIONS:
            action = self.font_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(label == current)
            action.triggered.connect(
                lambda _=False, f=family: self._apply_font_family(f)
            )
            self._font_actions.append(action)

    def _show_font_menu(self) -> None:
        self.font_menu.exec(self.font_button.mapToGlobal(
            self.font_button.rect().bottomLeft()
        ))

    def _apply_font_family(self, family: str) -> None:
        self._set_font(family, self._font_size)

    def _bump_font(self, delta: int) -> None:
        self._set_font(self._font_family, self._font_size + delta)

    def _set_font(self, family: str, size: int) -> None:
        app = QApplication.instance()
        if app is None:
            return
        register_fonts()
        self._font_family = family
        self._font_size = max(MIN_SIZE, min(MAX_SIZE, size))
        apply_font(app, family, self._font_size)
        label = next((l for l, f in FONT_OPTIONS if f == family), family)
        self.font_button.setText(label)
        self.settings.setValue("font/family", family)
        self.settings.setValue("font/size", self._font_size)
        self._rebuild_font_menu()
        self._status(f"Text: {label}, {self._font_size} pt")

    def _load_settings(self) -> None:
        self.settings = QSettings("PodRacer", "PodRacer")
        theme_name = self.settings.value("theme/name", THEMES[0].name, str)
        try:
            from .themes import theme_by_name
            theme = theme_by_name(theme_name)
        except KeyError:
            theme = THEMES[0]
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        self.theme_button.setText(theme.name)
        self._rebuild_theme_menu()

        family = self.settings.value("font/family", "", str)
        if app is not None and app.font().pointSize() > 0:
            default_size = app.font().pointSize()
        else:
            default_size = 10
        size = int(self.settings.value("font/size", default_size, int))
        self._font_family = family
        self._font_size = size
        if app is not None:
            register_fonts()
            apply_font(app, family, size)
        label = next((l for l, f in FONT_OPTIONS if f == family), family)
        self.font_button.setText(label)
        self._rebuild_font_menu()

    def _show_theme_menu(self) -> None:
        self.theme_menu.exec(self.theme_button.mapToGlobal(
            self.theme_button.rect().bottomLeft()
        ))

    def _apply_theme(self, theme) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        self.theme_button.setText(theme.name)
        self.settings.setValue("theme/name", theme.name)
        self._rebuild_theme_menu()
        self._status(f"Theme: {theme.name}")


    # -- device ---------------------------------------------------------

    def _poll_device(self) -> None:
        try:
            ipod = device.current_ipod()
        except device.DeviceError:
            ipod = None
        key = str(ipod.mountpoint) if ipod else None
        if key == self._device_key:
            return
        self._device_key = key
        if self.session is not None:
            self.session.close()
            self.session = None
        if ipod is not None:
            try:
                self.session = SyncSession(ipod)
            except Exception as exc:  # corrupt DB etc.
                self._status(f"Could not read the iPod: {exc}")
                self.session = None
        self._refresh_after_change()

    def _refresh_after_change(self) -> None:
        self.tracks_model.set_session(self.session)
        if self.session is not None:
            self.device_label.setText(f"{self.session.device_name}")
            free = self.session.free_bytes()
            suffix = f"  ·  {free / 2**30:.1f} GiB free" if free else ""
            self.track_count.setText(f"{len(self.session.tracks)} tracks{suffix}")
            self.eject_button.setEnabled(True)
            self.setWindowTitle(f"PodRacer — {self.session.device_name}")
        else:
            self.device_label.setText("No iPod")
            self.track_count.setText("")
            self.eject_button.setEnabled(False)
            self.setWindowTitle("PodRacer")

    # -- filesystem pane -------------------------------------------------

    def _goto_path(self) -> None:
        path = self.path_bar.text().strip()
        if Path(path).is_dir():
            self.fs_view.setRootIndex(self.fs_model.index(path))
            self.path_bar.setText(str(Path(path)))

    def _go_up(self) -> None:
        index = self.fs_view.rootIndex()
        parent = index.parent()
        if parent.isValid():
            self.fs_view.setRootIndex(parent)
            self.path_bar.setText(self.fs_model.filePath(parent))

    # -- add / remove ----------------------------------------------------

    def _drag_enter(self, event) -> None:
        if self.session is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop(self, event) -> None:
        if self.session is None:
            self._status("Plug in the iPod first.")
            return
        sources = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                   if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if not sources:
            return
        self._start_add(sources)

    def _start_add(self, sources: list[Path]) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._status("Already adding files.")
            return
        self._worker = AddWorker(self.session, sources)
        self._worker.fileStarted.connect(self._on_file_started)
        self._worker.finishedAll.connect(self._on_add_finished)
        self.progress.setRange(0, len(sources))
        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.eject_button.setEnabled(False)
        self._worker.start()

    def _on_file_started(self, path: str) -> None:
        self._status(f"Adding {Path(path).name} …")

    def _on_add_finished(self, results: list[AddResult]) -> None:
        added = sum(1 for r in results if r.status == "added")
        content = sum(1 for r in results if r.status == "content")
        metadata = sum(1 for r in results if r.status == "metadata")
        errors = sum(1 for r in results if r.status == "error")
        parts = [f"{added} added"]
        if content:
            parts.append(f"{content} duplicate (same file)")
        if metadata:
            parts.append(f"{metadata} duplicate (same song)")
        if errors:
            parts.append(f"{errors} failed")
        self._status(", ".join(parts) + ".")
        self.progress.hide()
        self.cancel_button.hide()
        self.eject_button.setEnabled(self.session is not None)
        self.tracks_model.set_session(self.session)
        self._refresh_after_change()
        self._worker = None

    def _cancel_add(self) -> None:
        if self._worker is not None:
            self._worker.cancelled = True
            self._status("Finishing the current file…")

    def _lib_key(self, event) -> None:
        if event.key() == Qt.Key.Key_Delete:
            self._remove_selected()
            return
        super(QTableView, self.lib_view).keyPressEvent(event)

    def _remove_selected(self) -> None:
        if self.session is None or self._worker is not None:
            return
        rows = sorted({i.row() for i in self.lib_view.selectionModel().selectedRows()})
        tracks = [self.tracks_model.track_at(r) for r in rows]
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        reply = QMessageBox.question(
            self, "Remove tracks",
            f"Remove {len(tracks)} track(s) from the iPod?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for track in tracks:
            self.session.remove(track)
        self.tracks_model.set_session(self.session)
        self._refresh_after_change()

    # -- eject ------------------------------------------------------------

    def _eject(self) -> None:
        if self.session is None or self._worker is not None:
            return
        self._status("Writing library…")
        try:
            self.session.eject(unmount=True)
        except device.DeviceError as exc:
            self._status(f"Eject problem: {exc}")
            return
        self._status("Written. Safe to unplug.")

    # -- helpers -----------------------------------------------------------

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text, 8000)
