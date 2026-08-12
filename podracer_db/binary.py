"""Binary helpers for the iTunesDB codec.

The DB is little-endian, fixed header sizes are explicit in every chunk,
and lengths are double-stored (header length + total length) so a parser
can walk the file without trusting any single field. Reader and Writer
share the little-endian pack/unpack layer.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class FormatError(Exception):
    """The bytes are not a parseable iTunesDB (or are corrupt)."""


@dataclass
class Reader:
    """Bounds-checked little-endian reader over an immutable buffer."""

    data: bytes
    pos: int = 0

    def _need(self, n: int) -> None:
        if self.pos + n > len(self.data):
            raise FormatError(
                f"truncated iTunesDB: need {n} bytes at 0x{self.pos:x}, "
                f"file is {len(self.data)} bytes"
            )

    def u8(self) -> int:
        self._need(1)
        v = self.data[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        self._need(2)
        v: int = struct.unpack_from("<H", self.data, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        self._need(4)
        v: int = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def u64(self) -> int:
        self._need(8)
        v: int = struct.unpack_from("<Q", self.data, self.pos)[0]
        self.pos += 8
        return v

    def f32(self) -> float:
        self._need(4)
        v: float = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return v

    def bytes(self, n: int) -> bytes:
        self._need(n)
        v = self.data[self.pos : self.pos + n]
        self.pos += n
        return v

    def skip(self, n: int) -> None:
        self._need(n)
        self.pos += n

    def at(self, pos: int) -> "Reader":
        """A sub-reader positioned at an absolute offset (shares buffer)."""
        return Reader(self.data, pos)

    def magic(self, expected: bytes, where: str = "chunk") -> None:
        got = self.data[self.pos : self.pos + 4]
        if got != expected:
            raise FormatError(
                f"bad {where} magic at 0x{self.pos:x}: "
                f"expected {expected!r}, got {got!r}"
            )
        self.pos += 4

class Writer:
    """Growing bytearray with patching (for size back-fills)."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def u8(self, v: int) -> None:
        self.buf += struct.pack("<B", v)

    def u16(self, v: int) -> None:
        self.buf += struct.pack("<H", v)

    def u32(self, v: int) -> None:
        self.buf += struct.pack("<I", v & 0xFFFFFFFF)

    def u64(self, v: int) -> None:
        self.buf += struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)


    def be_u16(self, v: int) -> None:
        self.buf += struct.pack(">H", v & 0xFFFF)

    def be_u32(self, v: int) -> None:
        self.buf += struct.pack(">I", v & 0xFFFFFFFF)

    def be_u64(self, v: int) -> None:
        self.buf += struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF)
    def f32(self, v: float) -> None:
        self.buf += struct.pack("<f", v)

    def raw(self, b: bytes) -> None:
        self.buf += b

    def zeros(self, n: int) -> None:
        self.buf += b"\x00" * n

    def magic(self, tag: str) -> None:
        self.raw(tag.encode("ascii"))

    def patch_u32(self, at: int, v: int) -> None:
        struct.pack_into("<I", self.buf, at, v & 0xFFFFFFFF)

    def patch_u16(self, at: int, v: int) -> None:
        struct.pack_into("<H", self.buf, at, v & 0xFFFF)

    @property
    def pos(self) -> int:
        return len(self.buf)

    def finish(self) -> bytes:
        return bytes(self.buf)
