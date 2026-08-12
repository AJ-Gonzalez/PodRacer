"""Eject protocol tests: atomic iTunesDB write on a fake tree."""

import tempfile
import unittest
from pathlib import Path

from podracer.eject import write_dbs
from podracer_db import parse_db, write_db
from podracer_db.model import Library, Playlist, Track

GUID = "000A27001BB9E492"


def _library() -> Library:
    t = Track(title="Song", artist="Artist", album="Album", tracklen=120000)
    lib = Library(tracks=[t])
    lib.playlists = [Playlist(name="Test", ptype=1, members=[t])]
    return lib


class WriteDBsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.itunes: Path = Path(self.tmp.name) / "iPod_Control" / "iTunes"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_itunesdb(self):
        db = write_db(_library(), firewire_guid=GUID)
        write_dbs(self.itunes, db)
        self.assertEqual((self.itunes / "iTunesDB").read_bytes(), db)

    def test_no_itunescdb_for_classic_devices(self):
        # The nano 3G never had a backup copy; writing one is
        # unnecessary churn on a family that does not use it.
        write_dbs(self.itunes, write_db(_library()))
        self.assertFalse((self.itunes / "iTunesCDB").exists())

    def test_written_db_parses(self):
        db = write_db(_library(), firewire_guid=GUID)
        write_dbs(self.itunes, db)
        back = parse_db((self.itunes / "iTunesDB").read_bytes())
        self.assertEqual(len(back.tracks), 1)
        self.assertEqual(back.tracks[0].title, "Song")

    def test_no_temp_files_left(self):
        write_dbs(self.itunes, write_db(_library()))
        leftovers = list(self.itunes.glob("*.podracer-tmp"))
        self.assertEqual(leftovers, [])

    def test_overwrites_existing_db(self):
        write_dbs(self.itunes, b"old")
        db = write_db(_library())
        write_dbs(self.itunes, db)
        self.assertEqual((self.itunes / "iTunesDB").read_bytes(), db)


if __name__ == "__main__":
    unittest.main()
