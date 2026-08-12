"""Orphan scan tests: hidden-duplicate detection and deletion."""

import tempfile
import unittest
from pathlib import Path

from podracer.orphans import delete_orphans, scan_orphans
from podracer_db.model import Library, Playlist, Track


def _track(folder: str, name: str, title: str) -> Track:
    t = Track(title=title, artist="Artist", album="Album")
    t.ipod_path = f":iPod_Control:Music:{folder}:{name}"
    return t


class OrphanScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.music = self.root / "iPod_Control" / "Music"
        self.music.mkdir(parents=True)

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

    def test_classifies_duplicates_and_unique(self):
        self._write("F01/AAAA.mp3", b"track")
        self._write("F99/DUPE.mp3", b"track")          # hidden duplicate
        self._write("F99/STRAY.mp3", b"unique stuff")  # unique orphan
        lib = self._lib(_track("F01", "AAAA.mp3", "Track"))
        scan = scan_orphans(lib, self.music)
        self.assertEqual(len(scan.duplicates), 1)
        self.assertEqual(scan.duplicates[0].duplicate_of, "Track")
        self.assertEqual(len(scan.unique), 1)
        self.assertEqual(scan.unique[0].path.name, "STRAY.mp3")

    def test_library_files_not_reported(self):
        self._write("F01/AAAA.mp3")
        lib = self._lib(_track("F01", "AAAA.mp3", "Track"))
        scan = scan_orphans(lib, self.music)
        self.assertEqual(scan.duplicates, [])
        self.assertEqual(scan.unique, [])

    def test_missing_library_file_tolerated(self):
        # A DB entry whose file is gone must not break the scan.
        self._write("F99/STRAY.mp3", b"x")
        lib = self._lib(_track("F01", "GHOST.mp3", "Ghost"))
        scan = scan_orphans(lib, self.music)
        self.assertEqual(len(scan.unique), 1)

    def test_delete_frees_bytes(self):
        self._write("F99/DUPE.mp3", b"track")
        scan = scan_orphans(self._lib(), self.music)
        self.assertEqual(len(scan.unique), 1)
        deleted, freed, errors = delete_orphans(scan.unique)
        self.assertEqual((deleted, freed, errors), (1, 5, []))
        self.assertFalse((self.music / "F99" / "DUPE.mp3").exists())

    def test_cancel_aborts(self):
        self._write("F99/STRAY.mp3", b"x")
        scan = scan_orphans(self._lib(), self.music, cancel=lambda: True)
        self.assertTrue(scan.errors)


if __name__ == "__main__":
    unittest.main()
