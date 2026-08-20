"""Demo mode tests: synthetic data is invented, the UI renders it."""

import tempfile
import unittest
from pathlib import Path

from podracer import demo
from podracer.pipeline import read_tags
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

    def test_demo_tree_files_are_real_tagged_audio(self):
        """Every demo file must probe and carry the catalog tags, so the
        add flow (drag -> probe -> copy) is demonstrable end-to-end."""
        with tempfile.TemporaryDirectory() as tmp:
            _ipod, music = demo.build_demo(Path(tmp))
            seen = 0
            for artist, (album, _year, titles) in demo._CATALOG.items():
                for n, title in enumerate(titles, start=1):
                    f = music / artist / album / f"{n:02d} - {title}.mp3"
                    track = read_tags(f)
                    self.assertEqual(track.title, title)
                    self.assertEqual(track.artist, artist)
                    self.assertEqual(track.album, album)
                    self.assertGreaterEqual(track.tracklen, 100)
                    seen += 1
            self.assertGreaterEqual(seen, 30)


if __name__ == "__main__":
    unittest.main()
