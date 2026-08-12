"""Eject protocol: get the library state onto the device safely.

The DB is the only thing the device reads, so a crash mid-write must
never leave a half-written iTunesDB behind: the file is written to a
temp name, fsynced, then renamed into place.

Only iTunesDB is written. The classic family does not use iTunesCDB —
libgpod only writes it for the iPhone/iPod touch (compressed) family,
and the nano 3G shipped without one; its presence on this firmware is
untested (see LESSONS.md).

The hash58 checksum is applied when the device GUID is known (see
podracer_db.hash58); without a GUID the scheme byte stays 0 and the
hash slot stays empty.


from __future__ import annotations

import os
from pathlib import Path

from podracer_db import write_db
from podracer_db.model import Library

from .device import IPod, unmount_ipod


def write_dbs(itunes_dir: str | Path, db_bytes: bytes) -> None:
    """Write iTunesDB atomically into iPod_Control/iTunes."""
    itunes_dir = Path(itunes_dir)
    itunes_dir.mkdir(parents=True, exist_ok=True)
    dest = itunes_dir / "iTunesDB"
    tmp = itunes_dir / "iTunesDB.podracer-tmp"
    with open(tmp, "wb") as fh:
        fh.write(db_bytes)
        os.fsync(fh.fileno())
    os.replace(tmp, dest)  # atomic on the same filesystem


def eject_ipod(ipod: IPod, lib: Library, unmount: bool = True) -> None:
    """Serialize @lib and write it to @ipod, then unmount.

    The iTunesSD file (shuffle-format leftover) is left untouched:
    the device never reads it, and deleting it before the old sync
    tool is fully retired is unnecessary churn.
    """
    guid = ipod.guid if ipod and ipod.guid else None
    db_bytes = write_db(lib, firewire_guid=guid)
    write_dbs(ipod.ipod_control / "iTunes", db_bytes)
    if unmount:
        unmount_ipod(ipod)
