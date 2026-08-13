"""Demo mode tests: synthetic data is invented, the UI renders it."""

import tempfile
import unittest
from pathlib import Path

from podracer import demo
from podracer_db import parse_db


class DemoLibraryTests(unittest.TestCase):
    def test_library_is_substantial_and_invented(self):
        lib = demo.demo_library()
        self.assertGreaterEqual(len(lib.tracks), 30)
        mpl = lib.master_playlist()
        self.assertEqual(mpl.name, "Demo Nano")
        for track in lib.tracks:
            self.assertTrue(track.title)
            self.assertTrue(track.artist)
            self.assertTrue(track.album)
            self.assertTrue(track.ipod_path.startswith(":iPod_Control:Music:"))

    def test_build_demo_writes_db_and_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipod, music = demo.build_demo(Path(tmp))
            db = (ipod.mountpoint / "iPod_Control/iTunes/iTunesDB").read_bytes()
            back = parse_db(db)
            self.assertEqual(len(back.tracks), len(demo.demo_library().tracks))
            albums = sorted(
                str(p.relative_to(music))
                for p in music.glob("*/*")
                if p.is_dir()
            )
            self.assertGreaterEqual(len(albums), 8)
            self.assertTrue((music / "Neon Harbor/Afterglow Boulevard").is_dir())


if __name__ == "__main__":
    unittest.main()
