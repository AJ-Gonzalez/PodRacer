#!/usr/bin/env python3
"""Extract iTunesDB fixtures from a mounted iPod for the test suite.

Copies the binary database (and a few sample tracks) from a real device into
fixtures/raw/ so the ipod_db codec can be tested against real hardware data
without the hardware present. Raw fixtures are gitignored.

Usage:
    python3 scripts/extract_fixtures.py [--mount PATH] [--limit N] [--out PATH] [--force]

Without --mount, scans /run/media/<user>/ for a directory containing
iPod_Control/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shutil
import sys
import time
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "raw"
DB_FILES = (
    "iPod_Control/iTunes/iTunesDB",
    "iPod_Control/iTunes/iTunesCDB",
)
AUDIO_EXTS = {".m4a", ".mp3", ".aac"}


def find_ipod() -> Path | None:
    """Return the mounted iPod under /run/media/<user>, if any."""
    media = Path("/run/media") / pwd.getpwuid(os.getuid()).pw_name
    if not media.is_dir():
        return None
    for candidate in sorted(media.iterdir()):
        if (candidate / "iPod_Control").is_dir():
            return candidate
    return None


def sample_tracks(ipod: Path, limit: int) -> list[Path]:
    """Pick up to `limit` audio files spread across the Music tree."""
    music = ipod / "iPod_Control" / "Music"
    found = sorted(p for p in music.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    if not found:
        return []
    step = max(1, len(found) // limit)
    return found[::step][:limit]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mount", help="mount point of the iPod (default: auto-detect)")
    parser.add_argument("--limit", type=int, default=3, help="sample tracks to copy (default 3)")
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR, help="output dir (default fixtures/raw)")
    parser.add_argument("--force", action="store_true", help="overwrite existing fixtures")
    args = parser.parse_args()

    start = time.monotonic()
    ipod = Path(args.mount) if args.mount else find_ipod()
    if ipod is None or not (ipod / "iPod_Control").is_dir():
        print("No iPod found. Plug it in, or pass --mount <path>.", file=sys.stderr)
        return 1

    if args.out.exists() and any(args.out.iterdir()) and not args.force:
        print(f"{args.out} is not empty; pass --force to overwrite.", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"device": str(ipod), "db_family": "itunesdb", "files": []}

    for rel in DB_FILES:
        src = ipod / rel
        if not src.is_file():
            continue
        dest = args.out / rel.rsplit("/", 1)[-1]
        shutil.copy2(src, dest)
        manifest["files"].append(
            {"path": dest.name, "source": rel, "size": dest.stat().st_size, "sha256": sha256(dest)}
        )
        print(f"copied {rel} ({dest.stat().st_size} bytes)")

    if not any(f["path"] in ("iTunesDB", "iTunesCDB") for f in manifest["files"]):
        print("No database file found under iPod_Control/iTunes/ — not an iPod library?", file=sys.stderr)
        return 1

    # Family is decided by the DB's own magic, not by file presence:
    # classic-format DBs start 'mhbd', iTunesSD-family DBs 'shdb'.
    # A file named iTunesSD can exist on classic devices (this repo's
    # nano 3G has one — a leftover from the previous sync tool) and is
    # not a family signal.
    for entry in manifest["files"]:
        if entry["path"] not in ("iTunesDB", "iTunesCDB"):
            continue
        with open(args.out / entry["path"], "rb") as fh:
            magic = fh.read(4)
        if magic in (b"shdb", b"bdhs"):
            manifest["db_family"] = "itunessd"
            print("note: DB magic is 'shdb' (iTunesSD family, not the v1 target); copied for reference")
        elif magic != b"mhbd":
            print(f"warning: unexpected DB magic {magic!r}", file=sys.stderr)

    for src in sample_tracks(ipod, args.limit):
        dest = args.out / f"sample_{len(manifest['files']):02d}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        manifest["files"].append(
            {"path": dest.name, "source": str(src.relative_to(ipod)), "size": dest.stat().st_size, "sha256": sha256(dest)}
        )
        print(f"copied sample {dest.name} ({dest.stat().st_size} bytes)")

    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"manifest: {args.out / 'manifest.json'}")
    print(f"Took {time.monotonic() - start:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
