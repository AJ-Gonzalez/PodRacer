"""SyncSession tests: connect/add/remove/eject against a fake device
tree — no hardware, no Qt."""

import tempfile
import unittest
from pathlib import Path

from podracer import device
from podracer.sync import SyncSession
from podracer_db import parse_db

GUID = "000A27001BB9E492"


def _fake_ipod(tmp: Path, seeded: bool = True) -> device.IPod:
    """A fake mounted iPod; optionally seeded with the fixture DB."""
    ipod_dir = tmp / "HYPERPINK"
    (ipod_dir / "iPod_Control" / "iTunes").mkdir(parents=True)
    (ipod_dir / "iPod_Control" / "Music").mkdir(parents=True)
    if seeded:
        fixture = Path(__file__).resolve().parent.parent / "fixtures" / "raw" / "iTunesDB"
        if fixture.is_file():
            (ipod_dir / "iPod_Control" / "iTunes" / "iTunesDB").write_bytes(
                fixture.read_bytes()
            )
    return device.IPod(mountpoint=ipod_dir, label="HYPERPINK", guid=GUID)


class SyncSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ipod = _fake_ipod(root)
        self.session = SyncSession(self.ipod, sidecar=root / "lib.sqlite")

    def tearDown(self):
        self.session.close()
        self.tmp.cleanup()

    def test_connect_parses_device_library(self):
        self.assertEqual(len(self.session.tracks), 136)
        self.assertEqual(self.session.device_name, "Hyperpink")

    def test_connect_empty_device_starts_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipod = _fake_ipod(Path(tmp), seeded=False)
            session = SyncSession(ipod, sidecar=Path(tmp) / "lib.sqlite")
            self.assertEqual(session.tracks, [])
            self.assertEqual(session.device_name, "HYPERPINK")
            session.close()

    def test_add_appends_to_mpl_and_device(self):
        src = Path(self.tmp.name) / "new.mp3"
        _make_mp3(src, title="New Song")
        result = self.session.add(src)
        self.assertEqual(result.status, "added")
        self.assertEqual(len(self.session.tracks), 137)
        self.assertEqual(self.session.tracks[-1].title, "New Song")
        # File exists under iPod_Control/Music and is DB-referenced
        file_path = self.session.music_dir.joinpath(
            *result.track.ipod_path.split(":")[2:]
        )
        self.assertTrue(file_path.is_file())

    def test_duplicate_add_skipped(self):
        src = Path(self.tmp.name) / "dup.mp3"
        _make_mp3(src, title="Dup")
        self.assertEqual(self.session.add(src).status, "added")
        self.assertEqual(self.session.add(src).status, "content")
        self.assertEqual(len(self.session.tracks), 137)

    def test_remove_deletes_file_and_entry(self):
        src = Path(self.tmp.name) / "gone.mp3"
        _make_mp3(src, title="Gone")
        result = self.session.add(src)
        track = result.track
        file_path = self.session.music_dir.joinpath(*track.ipod_path.split(":")[2:])
        self.session.remove(track)
        self.assertFalse(file_path.exists())
        self.assertEqual(len(self.session.tracks), 136)
        self.assertNotIn(track, self.session.lib.master_playlist().members)

    def test_eject_writes_db_without_unmount(self):
        src = Path(self.tmp.name) / "eject.mp3"
        _make_mp3(src, title="Eject Me")
        self.session.add(src)
        self.session.eject(unmount=False)
        db = (self.ipod.db_path).read_bytes()
        back = parse_db(db)
        self.assertEqual(len(back.tracks), 137)
        self.assertEqual(back.tracks[-1].title, "Eject Me")


def _make_mp3(path: Path, title: str) -> None:
    import subprocess

    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1",
         "-metadata", f"title={title}", str(path)],
        capture_output=True, check=True,
    )


if __name__ == "__main__":
    unittest.main()
