"""PodRacer UI: two-pane midnight-commander-style shell.

Left pane browses the local filesystem (QFileSystemModel), right pane
is the iPod library. Drag files from anywhere onto the right pane to
add them; select and press Delete to remove; Sync writes the DB
without ejecting (adds/deletes only reach the device on sync); Sync &
Eject writes and unmounts. A 3-second timer watches for the iPod
appearing/disappearing.

Theme support lands after the layout (themes.py): the window only
ships a stylesheet hook today.
"""

from __future__ import annotations

import html
import tempfile
import time
from datetime import date
from pathlib import Path

from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSettings,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFileSystemModel,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from . import device
from .fonts import (
    FONT_OPTIONS,
    LINE_SPACINGS,
    MAX_SIZE,
    MIN_SIZE,
    apply_font,
    register_fonts,
)
from .icons import tinted_icon
from .pipeline import ACCEPTED_EXTENSIONS, AddResult, collect_audio
from .sync import SyncSession
from .themes import THEMES, apply_theme, is_dark, theme_by_name, theme_label
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

    def track_changed(self, row: int) -> None:
        """Repaint one row after a metadata edit (keeps selection/scroll)."""
        if 0 <= row < self.rowCount():
            top = self.index(row, 0)
            bottom = self.index(row, self.columnCount() - 1)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DisplayRole])


class LibraryView(QTableView):
    """Library table with drop and Delete wiring.

    Subclassing is required: PySide6 dispatches virtual methods through
    the class, so instance-attribute assignments (view.dragEnterEvent =
    ...) never fire. Signals keep the view free of session logic.
    """

    filesDropped = Signal(object)   # list[Path] from a drop
    deleteRequested = Signal()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            Path(u.toLocalFile())
            for u in event.mimeData().urls()
            if u.isLocalFile() and Path(u.toLocalFile()).exists()
        ]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)


class SpacedRowDelegate(QStyledItemDelegate):
    """Scale a view's row height by the line-spacing factor.

    Factor 1.0 returns the stock sizeHint untouched (identity), so the
    default renders exactly as before. Used on the filesystem tree,
    which has no verticalHeader to drive row height directly.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.factor = 1.0

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        if self.factor == 1.0:
            return hint
        return QSize(hint.width(), max(hint.height(), int(hint.height() * self.factor)))


def _spaced_para(text: str, factor: float) -> str:
    """Plain text -> one rich-text paragraph with CSS line-height.

    Qt's stylesheets ignore `line-height`, but rich text honors it, so
    wrapping dialog bodies is the only way to space wrapped lines. The
    text is HTML-escaped so a track title can never inject markup.
    """
    pct = int(round(factor * 100))
    body = html.escape(text).replace("\n", "<br>")
    return f'<p style="line-height:{pct}%">{body}</p>'


class MetadataDialog(QDialog):
    """Edit one track's title/artist/album/genre.

    Thin widget: pre-fills from the track, returns the four strings via
    values(). The apply decision lives in MainWindow._apply_metadata so
    tests never need a modal dialog.
    """

    FIELDS = ("Title", "Artist", "Album", "Genre")

    def __init__(self, track: Track, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit metadata — {track.display_title}")
        self.setMinimumWidth(360)
        form = QVBoxLayout(self)
        self._edits: dict[str, QLineEdit] = {}
        for field in self.FIELDS:
            label = QLabel(field, self)
            edit = QLineEdit(getattr(track, field.lower()) or "", self)
            self._edits[field] = edit
            form.addWidget(label)
            form.addWidget(edit)
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save", self)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addLayout(buttons)
        # Enter in any field saves; Esc cancels (QDialog default).

    def values(self) -> dict:
        return {field.lower(): edit.text() for field, edit in self._edits.items()}


class BulkMetadataDialog(QDialog):
    """Edit title/artist/album/genre on many tracks at once.

    Empty fields mean "leave unchanged", never "clear": clearing a tag
    is a per-track action and must not happen by accident across a
    selection. Thin widget, like MetadataDialog; the apply decision
    lives in MainWindow.
    """

    FIELDS = ("Title", "Artist", "Album", "Genre")

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit metadata for {count} tracks")
        self.setMinimumWidth(360)
        form = QVBoxLayout(self)
        note = QLabel("Empty fields are left unchanged.", self)
        note.setWordWrap(True)
        form.addWidget(note)
        self._edits: dict[str, QLineEdit] = {}
        for field in self.FIELDS:
            label = QLabel(field, self)
            edit = QLineEdit(self)
            edit.setPlaceholderText("leave unchanged")
            self._edits[field] = edit
            form.addWidget(label)
            form.addWidget(edit)
        buttons = QHBoxLayout()
        cancel = QPushButton("Cancel", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save", self)
        save.setDefault(True)
        save.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addLayout(buttons)

    def values(self) -> dict:
        """Only the filled fields, ready for set_metadata_bulk (None = leave)."""
        out = {}
        for field, edit in self._edits.items():
            text = edit.text().strip()
            if text:
                out[field.lower()] = text
        return out


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


class BackupWorker(QThread):
    """Extracts the library to a folder in the background.

    Signals carry (done, total) so the bar can tick per file; total 0
    means the phase length is unknown yet.
    """

    fileStarted = Signal(str)
    progressMade = Signal(int, int)
    finishedAll = Signal(object)   # BackupResult

    def __init__(self, session: SyncSession, dest: Path) -> None:
        super().__init__()
        self.session = session
        self.dest = dest
        self.cancelled = False

    def run(self) -> None:
        from .backup import backup_collection

        result = backup_collection(
            self.session.lib, self.session.music_dir, self.dest,
            guid=self.session.ipod.guid,
            progress=self._on_progress,
            cancel=lambda: self.cancelled,
        )
        self.finishedAll.emit(result)

    def _on_progress(self, done: int, total: int) -> None:
        self.progressMade.emit(done, total)


class CheckWorker(QThread):
    """Scans the device tree for untracked files (hidden duplicates)."""

    fileStarted = Signal(str)
    progressMade = Signal(int, int)
    finishedAll = Signal(object)   # OrphanScan

    def __init__(self, session: SyncSession) -> None:
        super().__init__()
        self.session = session
        self.cancelled = False

    def run(self) -> None:
        from .orphans import scan_orphans

        scan = scan_orphans(
            self.session.lib, self.session.music_dir,
            progress=self._on_progress,
            cancel=lambda: self.cancelled,
        )
        self.finishedAll.emit(scan)

    def _on_progress(self, done: int, total: int) -> None:
        self.progressMade.emit(done, total)


class _FileFilterProxy(QSortFilterProxyModel):
    """Hides album-folder junk (covers, scene NFOs) from the browser.

    Files that cannot reach the iPod are still shown (this is a file
    browser), but the noise that lives inside album folders — cover
    scans and metadata NFOs — is hidden so it cannot be dragged onto
    the iPod by accident. Directories always pass through.
    """

    HIDDEN_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".nfo"})

    def filterAcceptsRow(self, source_row, source_parent) -> bool:  # noqa: N802
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if model.isDir(index):
            return True
        suffix = Path(model.fileName(index)).suffix.lower()
        return suffix not in self.HIDDEN_SUFFIXES


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.session: SyncSession | None = None
        self._device_key: str | None = None
        self._worker: AddWorker | None = None
        self._backup_worker: BackupWorker | None = None
        self._check_worker: CheckWorker | None = None
        self._last_mount_attempt = 0.0
        # True while the in-memory library differs from what is on the
        # device (adds/deletes since the last Sync / Sync & Eject).
        self._dirty = False
        self.settings = QSettings("PodRacer", "PodRacer")

        # -- left pane: filesystem -------------------------------------
        # The app starts on the saved music home (right-click a folder
        # to set it), falling back to the user's home directory.
        start = self._music_home()
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath(start)
        self.fs_proxy = _FileFilterProxy(self)
        self.fs_proxy.setSourceModel(self.fs_model)
        self.fs_view = QTreeView(self)
        self.fs_view.setModel(self.fs_proxy)
        self.fs_view.setRootIndex(
            self.fs_proxy.mapFromSource(self.fs_model.index(start))
        )
        # Row height is driven by the delegate's sizeHint (a QTreeView
        # has no verticalHeader); the line-spacing factor scales it.
        self._fs_delegate = SpacedRowDelegate(self.fs_view)
        self.fs_view.setItemDelegate(self._fs_delegate)
        self.fs_view.setDragEnabled(True)
        self.fs_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        # Multi-select (Ctrl+click / Shift+click): the default is
        # SingleSelection, which silently disables it.
        self.fs_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.fs_view.setHeaderHidden(False)
        # All columns manually resizable (no Stretch lock); the date
        # column absorbs leftover space instead.
        self.fs_view.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.fs_view.header().setStretchLastSection(True)
        self.fs_view.setColumnWidth(0, 280)
        self.fs_view.setColumnWidth(1, 80)
        self.fs_view.setColumnWidth(2, 90)
        self.fs_view.setColumnWidth(3, 130)
        # Right-click: send a folder to the iPod, or pin it as the
        # folder the app opens on (product tenet — no hunting for it).
        self.fs_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.fs_view.customContextMenuRequested.connect(
            self._show_fs_context_menu
        )

        self.path_bar = QLineEdit(self)
        self.path_bar.setText(start)
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
        self.lib_view = LibraryView(self)
        self.lib_view.setModel(self.tracks_model)
        self.lib_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lib_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.lib_view.setAcceptDrops(True)
        self.lib_view.setDropIndicatorShown(True)
        self.lib_view.filesDropped.connect(self._files_dropped)
        self.lib_view.deleteRequested.connect(self._remove_selected)
        # Double-click opens the metadata editor; the context menu and
        # tooltip make the affordance discoverable (product tenet).
        self.lib_view.doubleClicked.connect(
            lambda index: self._edit_track(index.row())
        )
        # Discoverability: the Delete key alone is invisible. Right-click
        # opens a context menu; a status-bar Remove button enables with
        # the selection. Both say what they do (product tenet).
        self.lib_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.lib_view.customContextMenuRequested.connect(
            self._show_lib_context_menu
        )
        self.lib_view.setToolTip(
            "Drag songs here to add them to the iPod.\n"
            "Double-click a song, or right-click, to edit its metadata.\n"
            "Select several songs and right-click to edit them all at once.\n"
            "Press Delete to remove the selection."
        )
        self.lib_view.selectionModel().selectionChanged.connect(
            self._selection_changed
        )
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
        self.device_label.setToolTip(
            "Click to find and mount the iPod.\n"
            "Right-click to rename it."
        )
        self.device_label.clicked.connect(self._find_ipod)
        self.device_label.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.device_label.customContextMenuRequested.connect(
            self._show_device_menu
        )
        self.track_count = QPushButton("", self)
        self.track_count.setFlat(True)
        self.track_count.setEnabled(False)
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.clicked.connect(self._cancel_add)
        self.cancel_button.hide()
        # '&' is Qt's mnemonic marker; '&&' renders a literal ampersand.
        self.eject_button = QPushButton("Sync && Eject", self)
        self.eject_button.clicked.connect(self._eject)
        self.eject_button.setEnabled(False)
        self.eject_button.setToolTip(
            "Write the library to the iPod, then unmount it. "
            "Safe to unplug after this."
        )
        self.sync_button = QPushButton("Sync", self)
        self.sync_button.clicked.connect(self._sync)
        self.sync_button.setEnabled(False)
        self.sync_button.setToolTip(
            "Write the library to the iPod now, without ejecting. "
            "Adds and removes only reach the device when you sync."
        )
        self.backup_button = QPushButton("Backup…", self)
        self.backup_button.clicked.connect(self._start_backup)
        self.backup_button.setEnabled(False)
        self.backup_button.setToolTip(
            "Copy the music off the iPod into a folder, "
            "organized by artist and album."
        )
        self.check_button = QPushButton("Check duplicates…", self)
        self.check_button.clicked.connect(self._check_hidden_duplicates)
        self.check_button.setEnabled(False)
        self.check_button.setToolTip(
            "Find files on the iPod that aren't in the library. "
            "Hidden duplicates (same song twice) can be removed to "
            "free space."
        )
        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self._remove_selected)
        self.remove_button.setEnabled(False)
        self.remove_button.setToolTip(
            "Remove the selected songs from the iPod (keyboard: Delete)."
        )
        self.appearance_button = QPushButton("Appearance", self)
        self.appearance_button.setToolTip(
            "The look of PodRacer: theme, font, text size, and line "
            "spacing (text-size shortcuts: Ctrl+ / Ctrl−)."
        )
        self.appearance_button.clicked.connect(self._show_appearance_menu)
        self.appearance_menu = QMenu(self)
        self._theme_actions: list = []
        self._font_actions: list = []
        self._size_actions: list = []
        self._line_spacing_actions: list = []
        self.statusBar().addWidget(self.device_label)
        self.statusBar().addWidget(self.track_count)
        # Status messages go in a real label, never QStatusBar.showMessage:
        # Qt 6.11 paints showMessage text at the far-left edge, ON TOP of
        # the normal widgets, so "Mounted HYPERPINK." overlapped the
        # device/track buttons. A stretch-1 label lays out properly.
        self.status_label = QLabel("", self)
        self.statusBar().addWidget(self.status_label, 1)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(8000)
        self._status_timer.timeout.connect(self.status_label.clear)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.cancel_button)
        self.statusBar().addPermanentWidget(self.remove_button)
        self.statusBar().addPermanentWidget(self.sync_button)
        self.statusBar().addPermanentWidget(self.eject_button)
        self.statusBar().addPermanentWidget(self.backup_button)
        self.statusBar().addPermanentWidget(self.check_button)
        self.statusBar().addPermanentWidget(self.appearance_button)
        self._load_settings()
        self._refresh_icons()
        # Font size stays one keystroke away even behind the menu.
        QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomIn), self,
                  lambda: self._bump_font(1))
        QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self,
                  lambda: self._bump_font(-1))

        # -- device watcher ----------------------------------------------
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._poll_device)
        self._timer.start()
        self._poll_device()


    # -- appearance ------------------------------------------------------

    def _rebuild_appearance_menu(self) -> None:
        """Theme, font, size, and line-spacing submenus, checkmark current."""
        self.appearance_menu.clear()
        self._theme_actions = []
        self._font_actions = []
        self._size_actions = []
        self._line_spacing_actions = []
        try:
            menu_tint = theme_by_name(self._theme_name).panel_text
        except KeyError:
            menu_tint = THEMES[0].panel_text

        theme_menu = self.appearance_menu.addMenu("Theme")
        theme_menu.setIcon(tinted_icon("palette", menu_tint))
        for theme in THEMES:
            action = theme_menu.addAction(theme_label(theme))
            action.setIcon(tinted_icon(
                "moon" if is_dark(theme) else "sun", menu_tint
            ))
            action.setCheckable(True)
            action.setChecked(theme.name == self._theme_name)
            action.triggered.connect(
                lambda _=False, t=theme: self._apply_theme(t)
            )
            self._theme_actions.append(action)

        font_menu = self.appearance_menu.addMenu("Font")
        font_menu.setIcon(tinted_icon("type", menu_tint))
        for label, family in FONT_OPTIONS:
            action = font_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(label == self._font_label())
            action.triggered.connect(
                lambda _=False, f=family: self._apply_font_family(f)
            )
            self._font_actions.append(action)

        size_menu = self.appearance_menu.addMenu("Font size")
        size_menu.setIcon(tinted_icon("a-large-small", menu_tint))
        for size in range(MIN_SIZE, MAX_SIZE + 1):
            action = size_menu.addAction(f"{size} pt")
            action.setCheckable(True)
            action.setChecked(size == self._font_size)
            action.triggered.connect(
                lambda _=False, s=size: self._set_font(self._font_family, s)
            )
            self._size_actions.append(action)

        line_menu = self.appearance_menu.addMenu("Line spacing")
        line_menu.setIcon(tinted_icon("rows-3", menu_tint))
        for label, factor in LINE_SPACINGS:
            action = line_menu.addAction(
                f"{label} ({int(round(factor * 100))}%)"
            )
            action.setCheckable(True)
            action.setChecked(factor == self._line_spacing)
            action.triggered.connect(
                lambda _=False, f=factor: self._set_line_spacing(f)
            )
            self._line_spacing_actions.append(action)

    def _font_label(self) -> str:
        return next(
            (label for label, fam in FONT_OPTIONS if fam == self._font_family),
            self._font_family,
        )

    def _show_appearance_menu(self) -> None:
        self.appearance_menu.exec(self.appearance_button.mapToGlobal(
            self.appearance_button.rect().bottomLeft()
        ))

    def _apply_theme(self, theme) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        self._theme_name = theme.name
        self.settings.setValue("theme/name", theme.name)
        self._rebuild_appearance_menu()
        self._refresh_icons()
        self._status(f"Theme: {theme.name}")

    def _refresh_icons(self) -> None:
        """Re-tint the status-bar/button icons for the current theme.

        Buttons sit on the accent gradient, so their icons use
        text_on_accent (the same AA-checked pair as the label text).
        """
        try:
            theme = theme_by_name(self._theme_name)
        except KeyError:
            return
        color = theme.text_on_accent
        for button, name in (
            (self.up_button, "arrow-up"),
            (self.sync_button, "refresh-cw"),
            (self.eject_button, "eject"),
            (self.remove_button, "trash-2"),
            (self.backup_button, "hard-drive-download"),
            (self.check_button, "search-check"),
            (self.cancel_button, "x"),
            (self.appearance_button, "paintbrush"),
        ):
            button.setIcon(tinted_icon(name, color))

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
        self.settings.setValue("font/family", family)
        self.settings.setValue("font/size", self._font_size)
        self._apply_row_heights()
        self._rebuild_appearance_menu()
        self._status(f"Text: {self._font_label()}, {self._font_size} pt")

    def _set_line_spacing(self, factor: float) -> None:
        self._line_spacing = factor
        self.settings.setValue("font/line_spacing", factor)
        self._apply_row_heights()
        self._rebuild_appearance_menu()
        label, pct = next(
            (l, int(round(f * 100))) for l, f in LINE_SPACINGS if f == factor
        )
        self._status(f"Line spacing: {label} ({pct}%)")

    def _apply_row_heights(self) -> None:
        """Re-derive pane row heights from the font and spacing factor.

        Both panes scale from the current font's line height so the
        setting tracks the user's chosen font size instead of fighting
        it. The table's rows are pinned by the header default (Qt's 30
        is already roomier than a 10pt line); the tree's by the
        delegate sizeHint. Factor 1.0 reproduces the current layout.
        """
        app = QApplication.instance()
        if app is None or self.lib_view is None or self.fs_view is None:
            return
        base = max(30, QFontMetrics(app.font()).lineSpacing())
        row = max(base, int(base * self._line_spacing))
        self.lib_view.verticalHeader().setDefaultSectionSize(row)
        self._fs_delegate.factor = self._line_spacing

    def _load_settings(self) -> None:
        theme_name = self.settings.value("theme/name", THEMES[0].name, str)
        try:
            from .themes import theme_by_name
            theme = theme_by_name(theme_name)
        except KeyError:
            theme = THEMES[0]
        self._theme_name = theme.name
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)

        family = self.settings.value("font/family", "", str)
        if app is not None and app.font().pointSize() > 0:
            default_size = app.font().pointSize()
        else:
            default_size = 10
        size = int(self.settings.value("font/size", default_size, int))
        self._line_spacing = float(
            self.settings.value("font/line_spacing", 1.0, float)
        )
        self._font_family = family
        self._font_size = size
        if app is not None:
            register_fonts()
            apply_font(app, family, size)
        self._apply_row_heights()
        self._rebuild_appearance_menu()


    # -- device ---------------------------------------------------------

    def _poll_device(self) -> None:
        now = time.monotonic()
        # Cooldown after a failed mount: do not hammer udisksctl.
        if self._device_key is None and now - self._last_mount_attempt < 15:
            return
        try:
            ipod = device.auto_mount()
        except device.DeviceError as exc:
            ipod = None
            self._last_mount_attempt = now
            self._status(f"Could not mount the iPod: {exc}")
        key = str(ipod.mountpoint) if ipod else None
        if key == self._device_key:
            return
        self._device_key = key
        if self.session is not None:
            self.session.close()
            self.session = None
        # A fresh session starts from what is on the device — clean.
        self._dirty = False
        if ipod is not None:
            try:
                self.session = SyncSession(ipod)
                self._status(f"Mounted {ipod.label or ipod.mountpoint.name}.")
            except Exception as exc:  # corrupt DB etc.
                self._status(f"Could not read the iPod: {exc}")
                self.session = None
        self._refresh_after_change()

    def _show_device_menu(self, pos) -> None:
        menu = QMenu(self)
        rename = menu.addAction("Rename device…")
        rename.setEnabled(self.session is not None)
        rename.triggered.connect(self._rename_device)
        menu.exec(self.device_label.mapToGlobal(pos))

    def _rename_device(self) -> None:
        if self.session is None or self._transfer_running():
            return
        name, ok = QInputDialog.getText(
            self, "Rename device",
            "New device name (11 characters max, the FAT volume "
            "label limit):",
            text=self.session.device_name,
        )
        if not ok:
            return
        name = name.strip()
        if not name or len(name) > 11:
            self._status("Device name must be 1-11 characters.")
            return
        self._apply_rename(name)

    def _apply_rename(self, name: str) -> None:
        """Dialog-free rename: master playlist title + FAT volume label."""
        if self.session is None:
            return
        self.session.rename_device(name)
        self._dirty = True
        try:
            device.rename_label(self.session.ipod, name)
        except device.DeviceError as exc:
            self._status(
                f"Renamed in the library, but the volume label "
                f"failed: {exc}"
            )
        else:
            self._status(
                f"Renamed to '{name}' — Sync writes it; the folder "
                "name changes on the next plug-in."
            )
        self._refresh_after_change()

    def _find_ipod(self) -> None:
        """Immediate scan + mount (the device label is the button)."""
        self._last_mount_attempt = 0.0
        self._status("Looking for the iPod…")
        self._poll_device()

    def _refresh_after_change(self) -> None:
        self.tracks_model.set_session(self.session)
        if self.session is not None:
            self.device_label.setText(f"{self.session.device_name}")
            free = self.session.free_bytes()
            suffix = f"  ·  {free / 2**30:.1f} GiB free" if free else ""
            self.track_count.setText(f"{len(self.session.tracks)} tracks{suffix}")
            self.eject_button.setEnabled(True)
            self.sync_button.setEnabled(True)
            self.backup_button.setEnabled(True)
            self.check_button.setEnabled(True)
            self.setWindowTitle(f"PodRacer — {self.session.device_name}")
        else:
            self.device_label.setText("No iPod — click to find")
            self.track_count.setText("")
            self.eject_button.setEnabled(False)
            self.sync_button.setEnabled(False)
            self.backup_button.setEnabled(False)
            self.check_button.setEnabled(False)
            self.setWindowTitle("PodRacer")

    # -- filesystem pane -------------------------------------------------

    def _music_home(self) -> str:
        """The folder the app opens on: the saved default, else Home."""
        start = self.settings.value("fs/home", str(Path.home()), str)
        return start if Path(start).is_dir() else str(Path.home())

    def _goto_path(self) -> None:
        path = self.path_bar.text().strip()
        if Path(path).is_dir():
            self.fs_view.setRootIndex(
                self.fs_proxy.mapFromSource(self.fs_model.index(path))
            )
            self.path_bar.setText(str(Path(path)))

    def _go_up(self) -> None:
        index = self.fs_view.rootIndex()
        parent = index.parent()
        if parent.isValid():
            self.fs_view.setRootIndex(parent)
            source = self.fs_proxy.mapToSource(parent)
            self.path_bar.setText(self.fs_model.filePath(source))

    def _show_fs_context_menu(self, pos) -> None:
        index = self.fs_view.indexAt(pos)
        if not index.isValid():
            return
        source = self.fs_proxy.mapToSource(index)
        path = Path(self.fs_model.filePath(source))
        menu = QMenu(self)
        is_music = path.is_dir() or path.suffix.lower() in ACCEPTED_EXTENSIONS
        send = menu.addAction("Send to iPod")
        send.setEnabled(is_music)
        send.setToolTip("Add every music or video file in this folder to the iPod.")
        send.triggered.connect(lambda: self._files_dropped([str(path)]))
        if path.is_dir():
            set_home = menu.addAction("Set as default music folder")
            set_home.setToolTip("The app opens on this folder next time.")
            set_home.triggered.connect(lambda: self._set_music_home(path))
            if self.settings.value("fs/home", "", str):
                reset = menu.addAction("Clear default — start at Home")
                reset.triggered.connect(self._clear_music_home)
        menu.exec(self.fs_view.viewport().mapToGlobal(pos))

    def _set_music_home(self, path: Path) -> None:
        self.settings.setValue("fs/home", str(path))
        self.fs_view.setRootIndex(
            self.fs_proxy.mapFromSource(self.fs_model.index(str(path)))
        )
        self.path_bar.setText(str(path))
        self._status(f"Default music folder: {path}")

    def _clear_music_home(self) -> None:
        self.settings.remove("fs/home")
        home = self._music_home()
        self.fs_view.setRootIndex(
            self.fs_proxy.mapFromSource(self.fs_model.index(home))
        )
        self.path_bar.setText(home)
        self._status("Default cleared — the app starts at Home.")

    # -- add / remove ----------------------------------------------------

    def _transfer_running(self) -> bool:
        """An add, backup, or check worker is mid-flight."""
        if self._worker is not None and self._worker.isRunning():
            return True
        if self._backup_worker is not None and self._backup_worker.isRunning():
            return True
        if self._check_worker is not None and self._check_worker.isRunning():
            return True
        return False

    def _files_dropped(self, paths: list) -> None:
        if self.session is None:
            self._status("Plug in the iPod first.")
            return
        sources = collect_audio([Path(p) for p in paths])
        if not sources:
            self._status("No music files in that drop.")
            return
        self._start_add(sources)

    def _start_add(self, sources: list[Path]) -> None:
        if self._transfer_running():
            self._status("Already adding files.")
            return
        self._worker = AddWorker(self.session, sources)
        self._worker.fileStarted.connect(self._on_file_started)
        self._worker.fileDone.connect(self._on_file_done)
        self._worker.finishedAll.connect(self._on_add_finished)
        self._add_total = len(sources)
        self._add_done = 0
        # Indeterminate: a single flac transcode can take minutes, and
        # a determinate bar sitting at 0/N reads as hung.
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.show()
        self.eject_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self._worker.start()

    def _on_file_started(self, path: str) -> None:
        self._status(
            f"Adding {Path(path).name} ({self._add_done + 1}/{self._add_total}) …"
        )

    def _on_file_done(self, _result) -> None:
        self._add_done += 1
        self._status(f"{self._add_done}/{self._add_total} files done.")

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
        if added:
            self._dirty = True
        self.progress.hide()
        self.cancel_button.hide()
        self.eject_button.setEnabled(self.session is not None)
        self.sync_button.setEnabled(self.session is not None)
        self.backup_button.setEnabled(self.session is not None)
        self.check_button.setEnabled(self.session is not None)
        self.tracks_model.set_session(self.session)
        self._refresh_after_change()
        self._worker = None

    def _cancel_add(self) -> None:
        if self._worker is not None:
            self._worker.cancelled = True
        if self._backup_worker is not None:
            self._backup_worker.cancelled = True
        if self._check_worker is not None:
            self._check_worker.cancelled = True
        self._status("Finishing the current file…")


    def _remove_selected(self) -> None:
        if self.session is None or self._transfer_running():
            return
        rows = sorted({i.row() for i in self.lib_view.selectionModel().selectedRows()})
        tracks = [self.tracks_model.track_at(r) for r in rows]
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Remove tracks")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(_spaced_para(
            f"Remove {len(tracks)} track(s) from the iPod?",
            self._line_spacing,
        ))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        for track in tracks:
            self.session.remove(track)
        self._dirty = True
        self.tracks_model.set_session(self.session)
        self._refresh_after_change()

    def _selection_changed(self) -> None:
        has_selection = bool(self.lib_view.selectionModel().selectedRows())
        self.remove_button.setEnabled(has_selection)

    def _show_lib_context_menu(self, pos) -> None:
        index = self.lib_view.indexAt(pos)
        if index.isValid():
            row = index.row()
            selected = self.lib_view.selectionModel().selectedRows()
            if row not in {i.row() for i in selected}:
                self.lib_view.clearSelection()
                self.lib_view.selectRow(row)
        menu = QMenu(self)
        edit = menu.addAction("Edit metadata…")
        edit.setToolTip("Change title, artist, album, or genre. "
                        "With several songs selected, edits all of them.")
        edit.setEnabled(bool(self.lib_view.selectionModel().selectedRows()))
        edit.triggered.connect(self._edit_selected)
        remove = menu.addAction("Remove from iPod")
        remove.setEnabled(bool(self.lib_view.selectionModel().selectedRows()))
        remove.triggered.connect(self._remove_selected)
        menu.exec(self.lib_view.viewport().mapToGlobal(pos))

    # -- metadata editing -------------------------------------------------

    def _edit_selected(self) -> None:
        """Open the metadata editor: one track, or a bulk edit for many."""
        rows = self.lib_view.selectionModel().selectedRows()
        if not rows:
            return
        if len(rows) == 1:
            self._edit_track(rows[0].row())
            return
        tracks = [self.tracks_model.track_at(r.row()) for r in rows]
        tracks = [t for t in tracks if t is not None]
        if not tracks or self.session is None or self._transfer_running():
            return
        dialog = BulkMetadataDialog(len(tracks), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_bulk_metadata(rows, dialog.values())

    def _edit_track(self, row: int) -> None:
        """Open the editor for one track; apply on Save (no-op on Cancel)."""
        track = self.tracks_model.track_at(row)
        if track is None or self.session is None or self._transfer_running():
            return
        dialog = MetadataDialog(track, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_metadata(row, dialog.values())

    def _apply_metadata(self, row: int, values: dict) -> None:
        """Dialog-free apply of edited tag values to one track.

        Lives outside _edit_track so tests never open a modal dialog.
        """
        track = self.tracks_model.track_at(row)
        if track is None or self.session is None:
            return
        if self.session.set_metadata(track, **values):
            self._dirty = True
            self.tracks_model.track_changed(row)
            self._status(
                f"Updated metadata for '{track.display_title}' — "
                "Sync to write it to the iPod."
            )

    def _apply_bulk_metadata(self, rows: list, values: dict) -> None:
        """Dialog-free bulk apply; empty fields are untouched."""
        if self.session is None or not values:
            return
        tracks = [self.tracks_model.track_at(r.row()) for r in rows]
        tracks = [t for t in tracks if t is not None]
        if not tracks:
            return
        changed = self.session.set_metadata_bulk(tracks, **values)
        if not changed:
            self._status("No metadata changes.")
            return
        self._dirty = True
        for r in rows:
            self.tracks_model.track_changed(r.row())
        self._status(
            f"Updated {changed} track(s) — Sync to write it to the iPod."
        )

    # -- eject ------------------------------------------------------------

    def _sync(self) -> None:
        if self.session is None or self._transfer_running():
            return
        self._status("Writing library…")
        try:
            self.session.sync()
        except device.DeviceError as exc:
            self._status(f"Sync problem: {exc}")
            return
        self._dirty = False
        self._status("Synced. iPod stays mounted.")

    def _eject(self) -> None:
        if self.session is None or self._transfer_running():
            return
        self._status("Writing library…")
        try:
            self.session.eject(unmount=True)
        except device.DeviceError as exc:
            self._status(f"Eject problem: {exc}")
            return
        self._dirty = False
        self._status("Written. Safe to unplug.")

    def _start_backup(self) -> None:
        if self.session is None or self._transfer_running():
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Back up the iPod to…", str(Path.home())
        )
        if not folder:
            return
        dest = Path(folder) / f"PodRacer Backup {date.today():%Y-%m-%d}"
        self._backup_worker = BackupWorker(self.session, dest)
        self._backup_worker.progressMade.connect(self._on_backup_progress)
        self._backup_worker.finishedAll.connect(self._on_backup_finished)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.show()
        self.eject_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self._status(f"Backing up to {dest}…")
        self._backup_worker.start()

    def _on_backup_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self._status(f"Backup {done}/{total or '…'}.")

    def _on_backup_finished(self, result) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        self.eject_button.setEnabled(self.session is not None)
        self.sync_button.setEnabled(self.session is not None)
        self.backup_button.setEnabled(self.session is not None)
        self.check_button.setEnabled(self.session is not None)
        self._backup_worker = None
        parts = [f"{result.copied} songs"]
        if result.orphans_copied:
            parts.append(f"{result.orphans_copied} orphans")
        if result.orphan_duplicates:
            parts.append(f"{result.orphan_duplicates} duplicates skipped")
        if result.duplicate_songs:
            parts.append(f"{len(result.duplicate_songs)} duplicate songs")
        if result.missing:
            parts.append(f"{len(result.missing)} files missing")
        if result.failed_verify:
            parts.append(f"{len(result.failed_verify)} checksum FAILED")
        if result.errors:
            parts.append(f"{len(result.errors)} errors")
        self._status("Backup: " + ", ".join(parts) + ".")

    def _check_hidden_duplicates(self) -> None:
        if self.session is None or self._transfer_running():
            return
        self._check_worker = CheckWorker(self.session)
        self._check_worker.progressMade.connect(self._on_check_progress)
        self._check_worker.finishedAll.connect(self._on_check_finished)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.show()
        self.eject_button.setEnabled(False)
        self.sync_button.setEnabled(False)
        self.backup_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self._status("Scanning the iPod for hidden files…")
        self._check_worker.start()

    def _on_check_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _on_check_finished(self, scan) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        self.eject_button.setEnabled(self.session is not None)
        self.sync_button.setEnabled(self.session is not None)
        self.backup_button.setEnabled(self.session is not None)
        self.check_button.setEnabled(self.session is not None)
        self._check_worker = None
        if scan.errors:
            self._status("Scan problem: " + "; ".join(scan.errors[:2]))
            return
        if not scan.duplicates and not scan.unique:
            self._status("No hidden files — everything is in the library.")
            return
        dup_mb = sum(d.size for d in scan.duplicates) / 2**20
        uniq_mb = sum(u.size for u in scan.unique) / 2**20
        box = QDialog(self)
        box.setWindowTitle("Hidden duplicates")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel(
            f"{len(scan.duplicates)} hidden duplicate(s) ({dup_mb:.1f} MiB) — "
            "copies of songs already in your library."
        ))
        if scan.duplicates:
            listing = QListWidget()
            for d in scan.duplicates:
                listing.addItem(
                    f"{d.path.parent.name}/{d.path.name}  ({d.size / 2**20:.1f} MiB)"
                    f"  →  \"{d.duplicate_of}\""
                )
            layout.addWidget(listing)
        if scan.unique:
            layout.addWidget(QLabel(
                f"{len(scan.unique)} other untracked file(s) ({uniq_mb:.1f} MiB) "
                "are not duplicates — left alone."
            ))
        buttons = QHBoxLayout()
        remove_btn = QPushButton(f"Remove {len(scan.duplicates)} duplicates")
        remove_btn.setEnabled(bool(scan.duplicates))
        remove_btn.clicked.connect(
            lambda: self._remove_hidden_duplicates(box, scan, remove_btn)
        )
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(box.accept)
        buttons.addWidget(remove_btn)
        buttons.addWidget(close_btn)
        if scan.duplicates:
            layout.addWidget(QLabel(
                "Removal is one pass — a large set can take a few "
                "seconds, and the window pauses while it works."
            ))
        layout.addLayout(buttons)
        box.exec()

    def _remove_hidden_duplicates(self, box, scan, remove_btn) -> None:
        from .orphans import delete_orphans

        # The delete loop blocks the UI thread (one synchronous pass);
        # flip the button before it so a multi-GB set does not read as
        # a crash. The repaint forces the change out immediately.
        remove_btn.setEnabled(False)
        remove_btn.setText("Removing…")
        remove_btn.repaint()
        deleted, freed, errors = delete_orphans(scan.duplicates)
        box.accept()
        self._status(
            f"Removed {deleted} hidden duplicate(s), freed {freed / 2**20:.1f} MiB."
        )
        if errors:
            self._status("Removal problem: " + "; ".join(errors[:2]))
        self._refresh_after_change()

    # -- demo mode ---------------------------------------------------------

    def _enter_demo_mode(self) -> None:
        """Render with a synthetic library and fake music tree (--demo).

        Nothing real is touched: the session is a fake device seeded
        with invented tracks, the left pane shows a fabricated album
        tree, and device polling is stopped so a plugged-in iPod can
        not take over the showcase.
        """
        self._timer.stop()
        if self.session is not None:
            self.session.close()
            self.session = None
        from . import demo

        root = Path(tempfile.mkdtemp(prefix="podracer-demo-"))
        ipod, music = demo.build_demo(root)
        self.session = SyncSession(ipod, sidecar=root / "lib.sqlite")
        self._refresh_after_change()
        self.fs_view.setRootIndex(
            self.fs_proxy.mapFromSource(self.fs_model.index(str(music)))
        )
        self.path_bar.setText(str(music))
        self._status("Demo mode — sample library, nothing real.")

    # -- helpers -----------------------------------------------------------

    def _status(self, text: str) -> None:
        self.status_label.setText(text)
        # Auto-clear like showMessage's timeout, so transient messages
        # ("Adding 3/3…") do not linger forever.
        self._status_timer.start()

    def _quit_action(self) -> str:
        """What closing the window should do: 'close', 'cancel', or
        'sync-then-close'. Kept dialog-free so it is unit-testable."""
        if self._transfer_running():
            return "transfer"
        if self._dirty and self.session is not None:
            return "unsynced"
        return "close"

    def closeEvent(self, event) -> None:  # noqa: N802
        action = self._quit_action()
        if action == "transfer":
            box = QMessageBox(self)
            box.setWindowTitle("Transfer in progress")
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(_spaced_para(
                "A transfer is still running. Cancel it first, then close.",
                self._line_spacing,
            ))
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
            event.ignore()
            return
        if action == "unsynced":
            box = QMessageBox(self)
            box.setWindowTitle("Unsynced changes")
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(_spaced_para(
                "Changes have not been written to the iPod yet.",
                self._line_spacing,
            ))
            box.setInformativeText(_spaced_para(
                "Sync writes them now. Quitting without syncing loses them.",
                self._line_spacing,
            ))
            sync_quit = box.addButton(
                "Sync && Quit", QMessageBox.ButtonRole.AcceptRole
            )
            quit_anyway = box.addButton(
                "Quit anyway", QMessageBox.ButtonRole.DestructiveRole
            )
            cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel:
                event.ignore()
                return
            if clicked is sync_quit:
                try:
                    self.session.sync()
                except device.DeviceError as exc:
                    self._status(f"Sync problem: {exc}")
                    event.ignore()
                    return
                self._dirty = False
            event.accept()
            return
        event.accept()
