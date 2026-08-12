"""iTunesDB codec for the classic iPod family.

Pure stdlib, zero dependencies: the codec stays testable and portable
independently of the Qt UI. Parse and write land in M1.

Public API:

    from podracer_db import parse_db, write_db

    lib = parse_db(db_bytes)          # Library
    db_bytes = write_db(lib, firewire_guid="0011223344556677")
"""

from .binary import FormatError
from .hash58 import apply_hash58, compute_hash58
from .model import FIRST_IPOD_ID, Library, Playlist, Track
from .parser import parse_db
from .writer import write_db

__all__ = [
    "FIRST_IPOD_ID",
    "FormatError",
    "Library",
    "Playlist",
    "Track",
    "apply_hash58",
    "compute_hash58",
    "parse_db",
    "write_db",
]
