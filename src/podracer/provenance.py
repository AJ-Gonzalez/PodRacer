"""Provenance sidecar: host-side memory of what went onto the iPod.

`~/.local/share/podracer/library.sqlite` (or an injected path) keeps
two tables:

- `provenance`: SHA-256 of every source file we have hashed, keyed by
  (path, size, mtime). Re-dragging the same source is caught even when
  its tags changed — as long as the file itself did not.
- `device_files`: sha256 -> iPod path for files we wrote to the
  device. Content-level duplicate detection without re-hashing the
  device.

Tracks that predate PodRacer have no provenance; those fall back to a
metadata match (artist+title+album+duration) against the library state
parsed from the DB. Skips are reported in the UI, never silent.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from podracer_db.model import Track

# Duration (ms) tolerated when matching pre-PodRacer tracks by
# artist+title+album+duration.
DURATION_TOLERANCE_MS = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS provenance (
    source_path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL,
    added INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS device_files (
    ipod_path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    added INTEGER NOT NULL
);
"""


class ProvenanceDB:
    """Thin wrapper over the sidecar sqlite file.

    Thread-safe: the connection is created with check_same_thread=False
    because the add pipeline runs in a worker thread while the UI
    thread owns the session; a lock serializes all access.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "ProvenanceDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _execute(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def _commit(self) -> None:
        with self._lock:
            self.conn.commit()

    # -- sources --------------------------------------------------------

    def source_digest(self, source_path: str, size: int, mtime: float) -> str | None:
        """The cached sha256 of @source_path, or None if the file is
        unknown or changed (size/mtime no longer match)."""
        row = self._execute(
            "SELECT sha256, size, mtime FROM provenance WHERE source_path = ?",
            (source_path,),
        ).fetchone()
        if row is None:
            return None
        if (row[1], row[2]) != (size, mtime):
            return None
        return row[0]

    def remember_source(
        self, source_path: str, size: int, mtime: float, sha256: str
    ) -> None:
        self._execute(
            "INSERT OR REPLACE INTO provenance (source_path, size, mtime, sha256, added)"
            " VALUES (?, ?, ?, ?, ?)",
            (source_path, size, mtime, sha256, int(time.time())),
        )
        self._commit()

    # -- device files ---------------------------------------------------

    def device_has_digest(self, sha256: str) -> bool:
        row = self._execute(
            "SELECT 1 FROM device_files WHERE sha256 = ?", (sha256,)
        ).fetchone()
        return row is not None

    def remember_device_file(self, ipod_path: str, sha256: str) -> None:
        self._execute(
            "INSERT OR REPLACE INTO device_files (ipod_path, sha256, added)"
            " VALUES (?, ?, ?)",
            (ipod_path, sha256, int(time.time())),
        )
        self._commit()

    def forget_device_file(self, ipod_path: str) -> None:
        self._execute(
            "DELETE FROM device_files WHERE ipod_path = ?", (ipod_path,)
        )
        self._commit()

    def device_files_count(self) -> int:
        return self._execute("SELECT COUNT(*) FROM device_files").fetchone()[0]


def default_db_path() -> Path:
    """The sidecar location: $XDG_DATA_HOME/podracer/library.sqlite."""
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "podracer" / "library.sqlite"


def hash_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's content, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


@dataclass(frozen=True)
class MetadataKey:
    """The fallback identity for tracks without provenance."""

    artist: str
    title: str
    album: str
    duration_ms: int


def metadata_key(track: Track) -> MetadataKey:
    return MetadataKey(
        artist=_norm(track.artist),
        title=_norm(track.title),
        album=_norm(track.album),
        duration_ms=track.tracklen,
    )


def find_metadata_duplicate(
    track: Track, library_tracks: list[Track]
) -> Track | None:
    """A library track matching @track by artist+title+album+duration
    (duration within DURATION_TOLERANCE_MS)."""
    key = metadata_key(track)
    for other in library_tracks:
        if key.title and key.title != _norm(other.title):
            continue
        if key.artist and key.artist != _norm(other.artist):
            continue
        if key.album and key.album != _norm(other.album):
            continue
        if abs(key.duration_ms - other.tracklen) <= DURATION_TOLERANCE_MS:
            return other
    return None


def check_duplicate(
    db: ProvenanceDB,
    source_path: str | Path,
    probe: Track,
    library_tracks: list[Track],
) -> str | None:
    """Why @source_path would be a duplicate, or None if it is new.

    @probe: the source file's tags as a Track (title/artist/album/
    tracklen filled by the pipeline's tag reader). Returns "content"
    when the file's sha256 is already on the device (cached provenance
    or a fresh hash), "metadata" when a pre-PodRacer track matches by
    artist+title+album+duration.
    """
    path = Path(source_path)
    stat = path.stat()
    digest = db.source_digest(str(path), stat.st_size, stat.st_mtime)
    if digest is None:
        digest = hash_file(path)
        db.remember_source(str(path), stat.st_size, stat.st_mtime, digest)
    if db.device_has_digest(digest):
        return "content"
    if find_metadata_duplicate(probe, library_tracks) is not None:
        return "metadata"
    return None
