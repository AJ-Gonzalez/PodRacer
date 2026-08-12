"""Codec tests: parse the real-device fixture, round-trip it, verify the
hash58 checksum, and exercise a synthetic library (no fixture needed).

Run with: python3 -m unittest discover -s tests -v
"""

import os
import struct
import unittest
from pathlib import Path

from podracer_db import FormatError, compute_hash58, parse_db, write_db
from podracer_db.model import Library, Playlist, Track

RAW = Path(
    os.environ.get(
        "IPOD_THINGY_FIXTURES",
        Path(__file__).resolve().parent.parent / "fixtures" / "raw",
    )
)

# The fixture-gated hash test needs the real device's FireWire GUID as
# hash58 key material; that GUID is hardware-identifying, so it lives in
# a gitignored local file (tests/.fixture_guid) instead of the repo.
_GUID_FILE = Path(__file__).resolve().parent / ".fixture_guid"
GUID = (_GUID_FILE.read_text().splitlines()[0].strip()
        if _GUID_FILE.is_file() else "0011223344556677")


def _fixture_bytes() -> bytes | None:
    path = RAW / "iTunesDB"
    if not path.is_file():
        return None
    return path.read_bytes()


def synthetic_library() -> Library:
    """Two-track library with an MPL; no fixture required."""
    t1 = Track(
        title="Hello",
        artist="World",
        album="First",
        genre="Rock",
        tracklen=210000,
        size=1234567,
        year=2001,
        track_nr=1,
        bitrate=128000,
        samplerate=44100,
        dbid=0xDEADBEEF,
        dbid2=0xDEADBEEF,
        ipod_path="iPod_Control:Music:F00:hello.mp3",
        filetype="MPEG audio file",
    )
    t2 = Track(
        title="Second",
        artist="World",
        album="First",
        genre="Rock",
        tracklen=180000,
        size=987654,
        year=2003,
        track_nr=2,
        dbid=0xCAFE,
        dbid2=0xCAFE,
        ipod_path="iPod_Control:Music:F00:second.mp3",
    )
    lib = Library(tracks=[t1, t2])
    mpl = Playlist(name="My iPod", ptype=1, id=0x1234, members=[t1, t2])
    lib.playlists = [mpl]
    return lib


class SyntheticRoundTrip(unittest.TestCase):
    def test_synthetic_round_trip(self):
        lib = synthetic_library()
        out = write_db(lib)
        back = parse_db(out)
        self.assertEqual([t.title for t in back.tracks], ["Hello", "Second"])
        mpl = back.master_playlist()
        self.assertEqual(mpl.name, "My iPod")
        self.assertEqual(len(mpl.members), 2)
        # ids are renumbered from FIRST_IPOD_ID on write
        self.assertEqual([t.id for t in back.tracks], [52, 53])

    def test_write_rejects_library_without_mpl(self):
        lib = Library(tracks=[Track(title="x")])
        with self.assertRaises(ValueError):
            write_db(lib)


class Hash58Tests(unittest.TestCase):
    def setUp(self):
        lib = synthetic_library()
        self.db = write_db(lib)

    def test_hash_written_and_verifies(self):
        out = write_db(parse_db(self.db), firewire_guid=GUID)
        # The device's own DB uses scheme 0x0001, hashed over (see hash58.py)
        self.assertEqual(struct.unpack_from("<H", out, 0x30)[0], 0x0001)
        stored = out[0x58:0x6C]
        self.assertEqual(compute_hash58(out, GUID), stored)

    def test_scheme_byte_participates_in_hash(self):
        # Changing the stored scheme invalidates the hash: this is why
        # a 0x58-scheme DB shows an empty library on the nano 3G.
        out = bytearray(write_db(parse_db(self.db), firewire_guid=GUID))
        stored = bytes(out[0x58:0x6C])
        out[0x30] = 0x58
        self.assertNotEqual(compute_hash58(bytes(out), GUID), stored)

    def test_bad_guid_rejected(self):
        with self.assertRaises(ValueError):
            compute_hash58(self.db, "xyz")


class CorruptInputTests(unittest.TestCase):
    def test_not_a_db(self):
        with self.assertRaises(FormatError):
            parse_db(b"not an itunes db at all")

    def test_truncated_db(self):
        good = write_db(synthetic_library())
        with self.assertRaises(FormatError):
            parse_db(good[: len(good) // 2])


@unittest.skipUnless(_fixture_bytes() is not None, "no extracted fixtures; run scripts/extract_fixtures.py")
class FixtureRoundTrip(unittest.TestCase):
    """Gated on the real device fixture (see scripts/extract_fixtures.py)."""

    @classmethod
    def setUpClass(cls):
        cls.db = _fixture_bytes()
        cls.lib = parse_db(cls.db)

    @staticmethod
    def _key(t):
        return (t.title, t.artist, t.album, t.tracklen, t.size, t.dbid)

    def test_inventory_matches_device(self):
        self.assertEqual(len(self.lib.tracks), 136)
        mpl = self.lib.master_playlist()
        self.assertEqual(mpl.name, "Hyperpink")
        self.assertEqual(len(mpl.members), 136)

    def test_metadata_fields_parsed(self):
        t = next(t for t in self.lib.tracks if t.title)
        self.assertTrue(t.tracklen > 0)
        self.assertTrue(t.size > 0)
        self.assertNotEqual(t.dbid, 0)
        self.assertEqual(t.dbid, t.dbid2)

    def test_smart_playlists_preserved(self):
        self.assertEqual(len(self.lib.mhsd5_playlists), 5)
        music = self.lib.mhsd5_playlists[0]
        self.assertEqual(music.name, "Music")
        self.assertIsNotNone(music.splpref)
        self.assertIsNotNone(music.splrules)
        self.assertEqual(len(music.splrules.rules), 2)

    def test_round_trip_preserves_inventory(self):
        out = write_db(self.lib)
        back = parse_db(out)
        self.assertEqual(
            [self._key(t) for t in self.lib.tracks],
            [self._key(t) for t in back.tracks],
        )
        self.assertEqual(
            [self._key(t) for t in self.lib.master_playlist().members],
            [self._key(t) for t in back.master_playlist().members],
        )

    def test_round_trip_preserves_track_fields(self):
        out = write_db(self.lib)
        back = parse_db(out)
        fields = (
            "title", "artist", "album", "genre", "ipod_path", "filetype",
            "tracklen", "size", "bitrate", "samplerate", "samplerate_low",
            "year", "track_nr", "cd_nr", "rating", "playcount", "dbid",
            "dbid2", "mediatype", "unk126", "mark_unplayed", "time_added",
            "volume", "skipcount", "filetype_marker",
        )
        for orig, new in zip(self.lib.tracks, back.tracks):
            for f in fields:
                self.assertEqual(
                    getattr(orig, f), getattr(new, f),
                    f"{f} differs on track '{orig.title}'",
                )

    def test_round_trip_preserves_spl_rules(self):
        out = write_db(self.lib)
        back = parse_db(out)
        for orig, new in zip(self.lib.mhsd5_playlists, back.mhsd5_playlists):
            self.assertEqual(orig.name, new.name)
            self.assertEqual(orig.mhsd5_type, new.mhsd5_type)
            self.assertEqual(orig.splpref, new.splpref)
            self.assertEqual(orig.splrules, new.splrules)

    def test_round_trip_preserves_header(self):
        out = write_db(self.lib)
        back = parse_db(out)
        for f in ("db_id", "pid", "id_0x24", "platform", "version",
                  "tzoffset", "lang", "unk_0x50", "unk_0x54", "compressed"):
            self.assertEqual(getattr(self.lib, f), getattr(back, f), f)

    def test_fixture_hash58_verifies(self):
        # The previous sync tool's DB carries a hash our implementation
        # reproduces byte-for-byte (scheme byte 0, hash covers it).
        stored = self.db[0x58:0x6C]
        self.assertEqual(compute_hash58(self.db, GUID), stored)

if __name__ == "__main__":
    unittest.main()
