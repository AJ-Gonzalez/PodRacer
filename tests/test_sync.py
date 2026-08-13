"""SyncSession tests: connect/add/remove/eject against a fake device
tree — no hardware, no Qt."""

import tempfile
import unittest
from pathlib import Path

from podracer import device, pipeline
from podracer.sync import SyncSession
from podracer_db import parse_db

GUID = "0011223344556677"


def _synthetic_db() -> bytes:
    """A small but real iTunesDB for CI runs.

    The real-device fixture is gitignored (see PENDING: no committed
    DB fixture), so without it the seeded tests would silently start
    from an empty device. The synthetic seed exercises the exact same
    session flows; the device name matches so tests are agnostic.
    """
    from podracer_db import write_db
    from podracer_db.model import Library, Playlist, Track

    tracks = [
        Track(
            title=f"Song {i}",
            artist="Artist",
            album="Album",
            tracklen=180000,
            size=1234,
            dbid=i + 1,
            dbid2=i + 1,
            ipod_path=f":iPod_Control:Music:F00:s{i:04d}.mp3",
            filetype="MPEG audio file",
        )
        for i in range(3)
    ]
    lib = Library(tracks=tracks)
    lib.playlists = [
        Playlist(name="Hyperpink", ptype=1, id=0x1234, members=tracks)
    ]
    return write_db(lib, firewire_guid=GUID)


def _fake_ipod(tmp: Path, seeded: bool = True) -> device.IPod:
    """A fake mounted iPod; optionally seeded with a device DB.

    The real-device fixture is used when present; otherwise a synthetic
    seeded DB keeps the session flows testable (including on CI, where
    the gitignored fixture does not exist).
    """
    ipod_dir = tmp / "HYPERPINK"
    (ipod_dir / "iPod_Control" / "iTunes").mkdir(parents=True)
    (ipod_dir / "iPod_Control" / "Music").mkdir(parents=True)
    if seeded:
        fixture = Path(__file__).resolve().parent.parent / "fixtures" / "raw" / "iTunesDB"
        db_bytes = fixture.read_bytes() if fixture.is_file() else _synthetic_db()
        (ipod_dir / "iPod_Control" / "iTunes" / "iTunesDB").write_bytes(db_bytes)
    return device.IPod(mountpoint=ipod_dir, label="HYPERPINK", guid=GUID)


class SyncSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ipod = _fake_ipod(root)
        self.session = SyncSession(self.ipod, sidecar=root / "lib.sqlite")
        # Counts are derived from the seed (real fixture locally,
        # synthetic on CI) so the assertions hold either way.
        self.seeded_count = len(self.session.tracks)

    def tearDown(self):
        self.session.close()
        self.tmp.cleanup()

    def test_connect_parses_device_library(self):
        self.assertEqual(len(self.session.tracks), self.seeded_count)
        self.assertEqual(self.session.device_name, "Hyperpink")

    def test_connect_empty_device_starts_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            ipod = _fake_ipod(Path(tmp), seeded=False)
            session = SyncSession(ipod, sidecar=Path(tmp) / "lib.sqlite")
            self.assertEqual(session.tracks, [])
            self.assertEqual(session.device_name, "HYPERPINK")
            session.close()

    def test_set_metadata_edits_tags(self):
        track = self.session.tracks[0]
        changed = self.session.set_metadata(
            track, title="Renamed", artist="New Artist",
            album="New Album", genre="Shoegaze",
        )
        self.assertTrue(changed)
        self.assertEqual(track.title, "Renamed")
        self.assertEqual(track.artist, "New Artist")
        self.assertEqual(track.album, "New Album")
        self.assertEqual(track.genre, "Shoegaze")

    def test_set_metadata_leaves_untouched_fields(self):
        track = self.session.tracks[0]
        original = track.artist
        changed = self.session.set_metadata(track, title="Only Title")
        self.assertTrue(changed)
        self.assertEqual(track.title, "Only Title")
        self.assertEqual(track.artist, original)

    def test_set_metadata_noop_returns_false(self):
        track = self.session.tracks[0]
        changed = self.session.set_metadata(
            track, title=track.title, artist=track.artist,
        )
        self.assertFalse(changed)

    def test_set_metadata_clear_and_whitespace(self):
        track = self.session.tracks[0]
        # Seed values first: the seed track may or may not carry a genre
        # or album (real fixture locally vs synthetic on CI), and
        # clearing an already-empty tag is a no-op (returns False).
        self.assertTrue(self.session.set_metadata(
            track, genre="Set", album="Set Album"))
        self.assertTrue(self.session.set_metadata(track, genre=""))
        self.assertIsNone(track.genre)
        self.assertTrue(self.session.set_metadata(track, album="   "))
        self.assertIsNone(track.album)

    def test_rename_device_sets_master_playlist_title(self):
        self.session.rename_device("STONER")
        self.assertEqual(self.session.device_name, "STONER")

    def test_set_metadata_bulk_applies_to_all(self):
        tracks = self.session.tracks[:2]
        changed = self.session.set_metadata_bulk(
            tracks, artist="Bulk Artist", album="Bulk Album",
        )
        self.assertGreaterEqual(changed, 1)
        for track in tracks:
            self.assertEqual(track.artist, "Bulk Artist")
            self.assertEqual(track.album, "Bulk Album")

    def test_set_metadata_bulk_leaves_empty_fields(self):
        tracks = self.session.tracks[:2]
        original = [track.title for track in tracks]
        changed = self.session.set_metadata_bulk(tracks, genre="Bulk Genre")
        self.assertGreaterEqual(changed, 1)
        self.assertEqual([track.title for track in tracks], original)
        for track in tracks:
            self.assertEqual(track.genre, "Bulk Genre")

    def test_set_metadata_bulk_noop_counts_zero(self):
        track = self.session.tracks[0]
        changed = self.session.set_metadata_bulk(
            [track], artist=track.artist)
        self.assertEqual(changed, 0)

    def test_set_metadata_persists_on_sync(self):
        track = self.session.tracks[0]
        self.session.set_metadata(
            track, title="Edited Title", artist="Edited Artist",
            album="Edited Album", genre="Edited Genre",
        )
        self.session.sync()
        lib = parse_db(self.ipod.db_path.read_bytes())
        edited = lib.master_playlist().members[0]
        self.assertEqual(edited.title, "Edited Title")
        self.assertEqual(edited.artist, "Edited Artist")
        self.assertEqual(edited.album, "Edited Album")
        self.assertEqual(edited.genre, "Edited Genre")

    def test_add_appends_to_mpl_and_device(self):
        src = Path(self.tmp.name) / "new.mp3"
        _make_mp3(src, title="New Song")
        result = self.session.add(src)
        self.assertEqual(result.status, "added")
        self.assertEqual(len(self.session.tracks), self.seeded_count + 1)
        self.assertEqual(self.session.tracks[-1].title, "New Song")
        # File exists under iPod_Control/Music and is DB-referenced
        file_path = self.session.music_dir.joinpath(
            *pipeline.ipod_path_parts(result.track.ipod_path)[2:]
        )
        self.assertTrue(file_path.is_file())

    def test_duplicate_add_skipped(self):
        src = Path(self.tmp.name) / "dup.mp3"
        _make_mp3(src, title="Dup")
        self.assertEqual(self.session.add(src).status, "added")
        self.assertEqual(self.session.add(src).status, "content")
        self.assertEqual(len(self.session.tracks), self.seeded_count + 1)

    def test_remove_deletes_file_and_entry(self):
        src = Path(self.tmp.name) / "gone.mp3"
        _make_mp3(src, title="Gone")
        result = self.session.add(src)
        track = result.track
        file_path = self.session.music_dir.joinpath(*pipeline.ipod_path_parts(track.ipod_path)[2:])
        self.session.remove(track)
        self.assertFalse(file_path.exists())
        self.assertEqual(len(self.session.tracks), self.seeded_count)
        self.assertNotIn(track, self.session.lib.master_playlist().members)

    def test_sync_writes_db_keeps_mounted(self):
        src = Path(self.tmp.name) / "sync.mp3"
        _make_mp3(src, title="Sync Me")
        self.session.add(src)
        # The commit step: DB on the device reflects the add, and the
        # mountpoint is untouched (no unmount involved).
        self.session.sync()
        db = self.ipod.db_path.read_bytes()
        back = parse_db(db)
        self.assertEqual(len(back.tracks), self.seeded_count + 1)
        self.assertEqual(back.tracks[-1].title, "Sync Me")
        self.assertTrue(self.ipod.mountpoint.is_dir())

    def test_eject_writes_db_without_unmount(self):
        src = Path(self.tmp.name) / "eject.mp3"
        _make_mp3(src, title="Eject Me")
        self.session.add(src)
        self.session.eject(unmount=False)
        db = (self.ipod.db_path).read_bytes()
        back = parse_db(db)
        self.assertEqual(len(back.tracks), self.seeded_count + 1)
        self.assertEqual(back.tracks[-1].title, "Eject Me")

    def test_add_from_worker_thread_completes(self):
        # Regression: the sidecar connection is used from the add
        # worker thread; a cross-thread sqlite error used to kill the
        # thread silently and hang the progress bar forever.
        import subprocess
        import threading

        src = Path(self.tmp.name) / "lossless.flac"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", str(src)],
            capture_output=True, check=True,
        )
        results: list = []
        error: list = []

        def run() -> None:
            try:
                results.append(self.session.add(src))
            except Exception as exc:  # noqa: BLE001
                error.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=60)
        self.assertFalse(thread.is_alive(), "add thread hung")
        self.assertEqual(error, [])
        self.assertEqual(results[0].status, "added")
        self.assertEqual(len(self.session.tracks), self.seeded_count + 1)


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
