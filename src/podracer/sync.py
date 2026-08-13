"""SyncSession: the state and operations behind the UI.

Qt-free on purpose — every piece of sync logic is testable without a
display. The widgets own a SyncSession and call its methods; the
session owns the parsed library, the provenance sidecar, and the
device handle.

Lifecycle: connect() when the iPod appears, disconnect() when it
disappears, add()/remove() while connected, sync() to write the DB
without unmounting, eject() to write and unmount.
"""

from __future__ import annotations

from pathlib import Path

from podracer_db import parse_db
from podracer_db.model import Library, Playlist, Track
from .device import IPod
from .eject import eject_ipod as _eject_ipod, sync_ipod as _sync_ipod

from .pipeline import AddResult, add_file, ipod_path_parts
from .provenance import ProvenanceDB, default_db_path


class SyncSession:
    """One connected iPod: library state + sidecar + operations."""

    def __init__(self, ipod: IPod, sidecar: str | Path | None = None) -> None:
        self.ipod = ipod
        self.sidecar = ProvenanceDB(sidecar or default_db_path())
        self.music_dir = ipod.ipod_control / "Music"
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self._load_library()

    def _load_library(self) -> None:
        db_path = self.ipod.db_path
        if db_path.is_file():
            self.lib = parse_db(db_path.read_bytes())
        else:
            # Fresh device: start an empty library named after the volume.
            self.lib = Library()
            mpl = Playlist(name=self.ipod.label or "iPod", ptype=1)
            self.lib.playlists = [mpl]

    @property
    def tracks(self) -> list[Track]:
        mpl = self.lib.master_playlist()
        return list(mpl.members) if mpl else []

    @property
    def device_name(self) -> str:
        mpl = self.lib.master_playlist()
        return mpl.name if mpl else self.ipod.label or "iPod"

    def add(self, source: str | Path) -> AddResult:
        """Stage one file; appends to the master playlist when added."""
        result = add_file(self.lib.tracks, self.sidecar, source, self.music_dir)
        if result.status == "added" and result.track is not None:
            mpl = self.lib.master_playlist()
            if mpl is not None:
                mpl.members.append(result.track)
        return result

    def remove(self, track: Track) -> None:
        """Delete a track from the library and the device tree."""
        if track.ipod_path:
            parts = ipod_path_parts(track.ipod_path)
            if len(parts) == 4:  # iPod_Control:Music:F0X:name
                file_on_device = self.music_dir / parts[2] / parts[3]
                file_on_device.unlink(missing_ok=True)
            self.sidecar.forget_device_file(track.ipod_path)
        self.lib.tracks.remove(track)
        mpl = self.lib.master_playlist()
        if mpl is not None and track in mpl.members:
            mpl.members.remove(track)

    def set_metadata(
        self,
        track: Track,
        *,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        genre: str | None = None,
    ) -> bool:
        """Edit a track's tags in library state.

        Keyword arguments mirror the four editable tag fields; None
        leaves a field untouched, "" clears it (the device then falls
        back to the file name for the title). Edits reach the device
        DB only on sync(), like adds and deletes. Returns True when at
        least one field changed.
        """
        changed = False
        for field, value in (
            ("title", title),
            ("artist", artist),
            ("album", album),
            ("genre", genre),
        ):
            if value is None:
                continue
            # Empty/whitespace-only input clears the tag; normalized to
            # None so memory matches a parsed DB (writer omits falsy).
            value = value.strip() or None
            if getattr(track, field) == value:
                continue
            setattr(track, field, value)
            changed = True
        return changed

    def set_metadata_bulk(
        self,
        tracks: list[Track],
        *,
        title: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        genre: str | None = None,
    ) -> int:
        """Apply the same tag values to many tracks at once.

        Same semantics as set_metadata: None leaves a field untouched,
        "" clears it. The bulk dialog keeps empty fields as None so a
        bulk edit never wipes a tag by accident. Returns how many
        tracks actually changed.
        """
        changed = 0
        for track in tracks:
            if self.set_metadata(
                track, title=title, artist=artist, album=album, genre=genre
            ):
                changed += 1
        return changed

    def sync(self) -> None:
        """Write the library to the device now; keep it mounted.

        The commit step for adds/deletes — use before quitting or
        unplugging so changes survive. Eject() is this plus unmount.
        """
        _sync_ipod(self.ipod, self.lib)

    def eject(self, unmount: bool = True) -> None:
        """Write the library to the device; unmount unless told not to."""
        _eject_ipod(self.ipod, self.lib, unmount=unmount)

    def free_bytes(self) -> int | None:
        import shutil

        try:
            return shutil.disk_usage(self.ipod.mountpoint).free
        except OSError:
            return None

    def close(self) -> None:
        self.sidecar.close()
