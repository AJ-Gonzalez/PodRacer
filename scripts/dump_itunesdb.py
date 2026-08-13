#!/usr/bin/env python3
"""Dump your iPod's iTunesDB for the test corpus.

Finds a mounted iPod by looking for iPod_Control/iTunes/iTunesDB under
the usual mount points, copies the DB out, and when the codec is
importable reports the device name and track count so the dump is
self-describing.

The corpus wants real DBs from devices we cannot verify ourselves:
nano 1G-2G especially, plus any classic or mini.

Usage:
    python3 scripts/dump_itunesdb.py [output]             # output defaults to ./iTunesDB
    python3 scripts/dump_itunesdb.py --root /mnt out.db   # scan a custom mount root
"""

from __future__ import annotations

import argparse
import getpass
import shutil
import sys
from pathlib import Path

DB_REL = Path("iPod_Control") / "iTunes" / "iTunesDB"


def find_dbs(root: Path) -> list[Path]:
    """Every mounted iPod DB under @root (one per mount point)."""
    if not root.is_dir():
        return []
    return sorted(
        p / DB_REL for p in root.iterdir() if (p / DB_REL).is_file()
    )


def _describe(db: Path) -> str:
    """Device name and track count via the codec, when importable."""
    codec_src = (Path(__file__).resolve().parent.parent
                 / "packages" / "podracer_db" / "src")
    sys.path.insert(0, str(codec_src))
    try:
        from podracer_db import parse_db
    except ImportError:
        return ""
    try:
        lib = parse_db(db.read_bytes())
    except Exception:
        return ""
    mpl = lib.master_playlist()
    name = mpl.name if mpl else "unknown device"
    return f" ({name}, {len(lib.tracks)} tracks)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output", nargs="?", default="iTunesDB",
        help="where to write the copy (default ./iTunesDB)",
    )
    parser.add_argument(
        "--root", default=None,
        help="scan this mount root instead of the usual ones",
    )
    args = parser.parse_args()

    if args.root:
        roots = [Path(args.root)]
    else:
        user = getpass.getuser()
        roots = [
            Path("/run/media") / user,
            Path("/media") / user,
            Path("/media"),
            Path("/Volumes"),
        ]
    dbs = sorted({db for root in roots for db in find_dbs(root)})
    if not dbs:
        print("No iPod found. Plug it in (it must be mounted), then retry.",
              file=sys.stderr)
        return 1
    if len(dbs) > 1:
        print(f"{len(dbs)} iPods found; dumping the first:")
        for db in dbs:
            print(f"  {db}")
    db = dbs[0]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(db, out)
    print(f"Dumped {db} -> {out}{_describe(db)}")
    print("Open a PR adding it under fixtures/public/<model>/ or send it along.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
