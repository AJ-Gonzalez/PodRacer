#!/usr/bin/env python3
"""Headless repair: purge iTunesDB entries whose device file is gone.

A track can end up referenced by the DB while its file no longer
exists on disk (files deleted out from under the DB, or a write that
never landed). The device then lists a track that can never play.
This script finds every such entry and — with --apply — removes them
from the library, forgets their sidecar rows, and rewrites the DB
atomically, preserving the device GUID so hash58 stays valid.

Repair is a dry run by default; pass --apply to write.

Usage:
    python3 scripts/repair_stale_entries.py [--mount PATH] [--sidecar PATH] [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "packages" / "podracer_db" / "src"))

from podracer.device import IPod, fill_identity, mounted_ipods  # noqa: E402
from podracer.orphans import stale_entries  # noqa: E402
from podracer.sync import SyncSession  # noqa: E402


def find_ipod(mount: str | None) -> IPod:
    """The repair target: --mount, else the first mounted iPod."""
    if mount:
        ipod = IPod(mountpoint=Path(mount), label=Path(mount).name)
    else:
        found = mounted_ipods()
        if not found:
            sys.exit("no mounted iPod found under /run/media/<user>; pass --mount")
        ipod = found[0]
    fill_identity(ipod)  # GUID needed for hash58 on the rewrite
    return ipod


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mount", help="iPod mountpoint (default: auto-detect first mounted)"
    )
    parser.add_argument(
        "--sidecar", help="sidecar sqlite path (default: the app's library.sqlite)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="purge stale entries and rewrite the DB (default is a dry run)",
    )
    args = parser.parse_args()

    ipod = find_ipod(args.mount)
    if not ipod.db_path.is_file():
        print(f"{ipod.mountpoint}: no iTunesDB, nothing to do")
        return 0

    session = SyncSession(ipod, sidecar=args.sidecar)
    stale = stale_entries(session.lib, session.music_dir)
    msg = (
        f"{ipod.mountpoint}: {len(session.tracks)} tracks, "
        f"{len(stale)} stale (DB references a file that is gone)"
    )
    print(msg)
    for track in stale:
        print(f"  {track.ipod_path}  {track.title!r}")
    if not stale:
        return 0

    if not args.apply:
        print("Dry run — pass --apply to purge these entries and rewrite the DB.")
        return 0

    for track in stale:
        session.remove(track)
    session.sync()
    print(f"Purged {len(stale)} stale entries; wrote {ipod.db_path}.")
    session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
