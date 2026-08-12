"""Backup: extract the iPod library into a readable folder tree.

Qt-free so it is testable headless. The device's file names are
meaningless (iPod_Control/Music/F00/ABCD.mp3), so the iTunesDB is the
map: every track is written as Artist/Album/NN - Title.ext, sanitized
and collision-free.

The sha256 pass and orphan classification live in orphans.py and are
shared with the "hidden duplicates" check; backup adds the copying:
- library tracks are extracted and every copy is checksum-verified;
- orphan duplicates (content identical to a library track) are skipped;
- content-unique orphans land in an Orphans/ folder;

A regenerated iTunesDB lands next to the music so the backup is also a
restorable snapshot (play counts, ratings, device state).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from podracer_db import write_db
from podracer_db.model import Library

from .orphans import _track_path, scan_orphans
from .pipeline import read_tags

_UNKNOWN = "Unknown"

Progress = Callable[[int, int], None]   # (done, total)
Cancel = Callable[[], bool]


@dataclass
class BackupResult:
    copied: int = 0
    verified: int = 0
    failed_verify: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)      # DB tracks w/o a file
    duplicate_songs: list[str] = field(default_factory=list)
    orphan_duplicates: int = 0                            # skipped as dupes
    orphans_copied: int = 0
    errors: list[str] = field(default_factory=list)


def _sanitize(part: str) -> str:
    """A filesystem-safe single path component."""
    cleaned = "".join(
        ch if ch not in "/\\:\0" and ord(ch) >= 32 else "_"
        for ch in part
    ).strip(" .")
    return cleaned[:150] or _UNKNOWN


def _next_free(dest_dir: Path, name: str) -> Path:
    """A non-colliding path: 'Song.mp3' -> 'Song (2).mp3' -> ..."""
    candidate = dest_dir / name
    stem, suffix = candidate.stem, candidate.suffix
    n = 2
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def _copy_verified(src: Path, out: Path, digest: str,
                   result: BackupResult) -> bool:
    """Copy @src to @out and verify the bytes; report failures."""
    try:
        shutil.copyfile(src, out)
    except OSError as exc:
        result.errors.append(f"{src.name}: {exc}")
        return False
    from .orphans import _hash_file
    if _hash_file(out) != digest:
        result.failed_verify.append(str(out))
    else:
        result.verified += 1
    return True


def _orphan_name(src: Path) -> str:
    """Name an orphan from its own tags, else its device name."""
    try:
        probe = read_tags(src)
        return (
            f"{_sanitize(probe.artist or _UNKNOWN)}"
            f" - {_sanitize(probe.title or src.stem)}{src.suffix.lower()}"
        )
    except Exception:  # unreadable/untaggable: keep the device name
        return src.name


def backup_collection(
    lib: Library,
    music_dir: Path,
    dest_root: Path,
    guid: str | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> BackupResult:
    """Extract @lib to @dest_root as Artist/Album/NN - Title.ext.

    Orphans (files not referenced by the library) land in an Orphans/
    folder when their content is unique; orphans that duplicate a
    library track are skipped. A regenerated iTunesDB is written next
    to the music so the backup is restorable.
    """
    result = BackupResult()
    scan = scan_orphans(lib, music_dir, progress=progress, cancel=cancel)
    result.errors = list(scan.errors)
    hashes = scan.hashes
    library_hashes = scan.library_hashes

    # Copy the library tracks.
    dest_root.mkdir(parents=True, exist_ok=True)
    seen_content: dict[str, str] = {}  # first title per hash (dup report)
    for index, track in enumerate(lib.tracks):
        if cancel and cancel():
            result.errors.append("Cancelled during copy.")
            return result
        src = _track_path(track, music_dir)
        if src is None or not src.is_file():
            result.missing.append(track.title or track.ipod_path)
            continue
        digest = hashes.get(src)
        if digest is None:  # not in the hash map; hash on demand
            from .orphans import _hash_file
            digest = _hash_file(src)
            hashes[src] = digest
        library_hashes.add(digest)
        label = track.title or src.stem
        if digest in seen_content:
            result.duplicate_songs.append(f"{seen_content[digest]} / {label}")
        else:
            seen_content[digest] = label

        artist = _sanitize(track.artist or _UNKNOWN)
        album = _sanitize(track.album or _UNKNOWN)
        title = _sanitize(label)
        num = f"{track.track_nr:02d} " if track.track_nr > 0 else ""
        name = f"{num}{title}{src.suffix.lower()}"
        dest = dest_root / artist / album
        dest.mkdir(parents=True, exist_ok=True)
        out = _next_free(dest, name)
        if _copy_verified(src, out, digest, result):
            result.copied += 1
        if progress:
            progress(index + 1, len(lib.tracks))

    # Orphans: duplicates of the library are skipped; unique content
    # is extracted (its own tags name the file).
    result.orphan_duplicates = len(scan.duplicates)
    for item in scan.unique:
        if cancel and cancel():
            result.errors.append("Cancelled during orphan copy.")
            return result
        orphan_dir = dest_root / "Orphans"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        out = _next_free(orphan_dir, _orphan_name(item.path))
        if _copy_verified(item.path, out, hashes[item.path], result):
            result.orphans_copied += 1

    # A regenerated DB makes the backup a restorable snapshot.
    if guid:
        (dest_root / "iTunesDB").write_bytes(write_db(lib, firewire_guid=guid))
    return result
