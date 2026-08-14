"""Orphan scan: untracked files on the device, classified by content.

Files dropped straight into iPod_Control/Music bypass the iTunesDB, so
the device ignores them while they still eat storage. A sha256 pass
over the tree classifies every untracked file:

- duplicates: content identical to a library track — the same song
  under a different name, pure waste;
- unique: content that matches nothing — invisible songs (or junk) the
  user has to judge by hand.

Qt-free so it is testable headless; backup.py uses the same scan for
its Orphans/ folder.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from podracer_db.model import Library, Track

Progress = Callable[[int, int], None]   # (done, total)
Cancel = Callable[[], bool]


@dataclass
class OrphanFile:
    path: Path
    size: int
    duplicate_of: str | None   # label of the library track it duplicates


@dataclass
class OrphanScan:
    duplicates: list[OrphanFile] = field(default_factory=list)
    unique: list[OrphanFile] = field(default_factory=list)
    hashes: dict[Path, str] = field(default_factory=dict)      # every file
    library_hashes: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _track_path(track: Track, music_dir: Path) -> Path | None:
    if not track.ipod_path:
        return None
    parts = [p for p in track.ipod_path.split(":") if p]
    if len(parts) != 4:  # iPod_Control:Music:F0X:name
        return None
    return music_dir / parts[2] / parts[3]


def scan_orphans(
    lib: Library,
    music_dir: Path,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> OrphanScan:
    """Classify every file in @music_dir that no library track references.

    @progress receives (done, total) once per file; @cancel aborts the
    scan between files.
    """
    scan = OrphanScan()
    files = sorted(p for p in music_dir.rglob("*") if p.is_file())

    for i, path in enumerate(files):
        if cancel and cancel():
            scan.errors.append("Cancelled during scan.")
            return scan
        try:
            scan.hashes[path] = _hash_file(path)
        except OSError as exc:
            scan.errors.append(f"{path.name}: {exc}")
        if progress:
            progress(i + 1, len(files))

    # Actual on-disk files, indexed case-insensitively. FAT is a
    # case-insensitive filesystem: PodRacer records the folder it
    # generated ("F04") while the file may have landed in a
    # pre-existing lowercase folder ("f04"), so "does a library track
    # reference this file" must not depend on Path equality (which is
    # case-sensitive on Linux).
    on_disk = {
        str(p.relative_to(music_dir)).casefold(): p for p in files
    }

    # Content of every library track, with a label for the report.
    content_label: dict[str, str] = {}
    referenced: set[Path] = set()
    for track in lib.tracks:
        src = _track_path(track, music_dir)
        if src is None:
            continue
        actual = on_disk.get(str(src.relative_to(music_dir)).casefold())
        if actual is None:
            continue  # DB entry whose file is gone — tolerated, not an orphan
        referenced.add(actual)
        digest = scan.hashes.get(actual)
        if digest is None:
            digest = _hash_file(actual)
            scan.hashes[actual] = digest
        scan.library_hashes.add(digest)
        content_label.setdefault(digest, track.title or actual.stem)

    for path in files:
        if path in referenced:
            continue
        digest = scan.hashes[path]
        item = OrphanFile(path=path, size=path.stat().st_size,
                          duplicate_of=content_label.get(digest))
        if item.duplicate_of is not None:
            scan.duplicates.append(item)
        else:
            scan.unique.append(item)
    return scan


def stale_entries(lib: Library, music_dir: Path) -> list[Track]:
    """Library tracks whose device file no longer exists on disk.

    The inverse of the orphan scan: the DB references a file that is
    gone (deleted out from under the DB, or never written), so the
    track lists on the device but can never play. Resolution is
    case-insensitive — a file that exists under a differently-cased
    folder is not stale.
    """
    files = [p for p in music_dir.rglob("*") if p.is_file()]
    on_disk = {str(p.relative_to(music_dir)).casefold() for p in files}
    stale = []
    for track in lib.tracks:
        src = _track_path(track, music_dir)
        if src is None:
            continue
        if str(src.relative_to(music_dir)).casefold() not in on_disk:
            stale.append(track)
    return stale


def delete_orphans(files: list[OrphanFile]) -> tuple[int, int, list[str]]:
    """Delete the files; returns (deleted, bytes_freed, errors)."""
    deleted = 0
    freed = 0
    errors: list[str] = []
    for item in files:
        try:
            item.path.unlink(missing_ok=True)
            deleted += 1
            freed += item.size
        except OSError as exc:
            errors.append(f"{item.path.name}: {exc}")
    return deleted, freed, errors
