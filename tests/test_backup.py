"""Backup tests: extraction, orphan dedup, verification — fake tree."""

import tempfile
import unittest
from pathlib import Path

from podracer.backup import _sanitize, backup_collection
from podracer_db.model import Library, Playlist, Track

GUID = "000A27001BB9E492"


def _track(folder: str, name: str, title: str, artist: str = "Artist",
           album: str = "Album", track_nr: int = 0) -> Track:
    t = Track(title=title, artist=artist, album=album, track_nr=track_nr)
    t.ipod_path = f":iPod_Control:Music:{folder}:{name}"
    return t


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.music = self.root / "iPod_Control" / "Music"
        self.music.mkdir(parents=True)
        self.dest = self.root / "backup"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, data: bytes = b"data") -> Path:
        p = self.music / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def _lib(self, *tracks: Track) -> Library:
        lib = Library(tracks=list(tracks))
        lib.playlists = [Playlist(name="Test", ptype=1, members=list(tracks))]
        return lib

    def test_extracts_artist_album_track_tree(self):
        self._write("F01/AAAA.mp3")
        lib = self._lib(_track("F01", "AAAA.mp3", "Song", "Artist",
                               "Album", track_nr=3))
        result = backup_collection(lib, self.music, self.dest, guid=GUID)
        self.assertEqual(result.copied, 1)
        out = self.dest / "Artist" / "Album" / "03 Song.mp3"
        self.assertTrue(out.is_file())
        self.assertEqual(out.read_bytes(), b"data")
        self.assertEqual(result.verified, 1)
        # restorable snapshot
        self.assertTrue((self.dest / "iTunesDB").is_file())

    def test_missing_file_reported_not_copied(self):
        lib = self._lib(_track("F01", "MMMM.mp3", "Ghost Song"))
        result = backup_collection(lib, self.music, self.dest)
        self.assertEqual(result.copied, 0)
        self.assertEqual(result.missing, ["Ghost Song"])

    def test_collision_gets_suffix(self):
        self._write("F01/AAAA.mp3")
        self._write("F02/BBBB.mp3", b"other")
        lib = self._lib(
            _track("F01", "AAAA.mp3", "Same"),
            _track("F02", "BBBB.mp3", "Same"),
        )
        backup_collection(lib, self.music, self.dest)
        album = self.dest / "Artist" / "Album"
        self.assertTrue((album / "Same.mp3").is_file())
        self.assertTrue((album / "Same (2).mp3").is_file())

    def test_duplicate_content_reported(self):
        self._write("F01/AAAA.mp3")
        self._write("F02/BBBB.mp3", b"data")  # identical content
        lib = self._lib(
            _track("F01", "AAAA.mp3", "First"),
            _track("F02", "BBBB.mp3", "Second"),
        )
        result = backup_collection(lib, self.music, self.dest)
        self.assertEqual(result.duplicate_songs, ["First / Second"])
        self.assertEqual(result.copied, 2)  # both kept (different entries)

    def test_orphan_duplicate_skipped_unique_copied(self):
        self._write("F01/AAAA.mp3", b"track")
        # orphan with the same content as the track: a dup of the library
        self._write("F99/ORPH1.mp3", b"track")
        # orphan with unique content: backed up under Orphans/
        self._write("F99/ORPH2.mp3", b"unique stray")
        lib = self._lib(_track("F01", "AAAA.mp3", "Track"))
        result = backup_collection(lib, self.music, self.dest)
        self.assertEqual(result.orphan_duplicates, 1)
        self.assertEqual(result.orphans_copied, 1)
        orphans = list((self.dest / "Orphans").iterdir())
        self.assertEqual(len(orphans), 1)
        self.assertIn(b"unique stray", orphans[0].read_bytes())

    def test_sanitize_removes_path_characters(self):
        self.assertEqual(_sanitize("A/B\\C:D*?"), "A_B_C_D*?")
        self.assertEqual(_sanitize("  padded  "), "padded")
        self.assertEqual(_sanitize("___"), "___")   # all-removed stays legal
        self.assertEqual(_sanitize("x" * 300), "x" * 150)

    def test_cancel_aborts(self):
        self._write("F01/AAAA.mp3")
        lib = self._lib(_track("F01", "AAAA.mp3", "Song"))
        result = backup_collection(lib, self.music, self.dest,
                                   cancel=lambda: True)
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
