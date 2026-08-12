"""Pipeline tests: tag reading, transcode decision, add_file end-to-end
on a fake iPod tree. Real audio files are generated with ffmpeg, so no
fixtures or hardware are needed."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from podracer import pipeline
from podracer.pipeline import AddResult, add_file, needs_transcode, read_tags
from podracer.provenance import ProvenanceDB


def _make_audio(path: Path, fmt: str, tags: dict[str, str] | None = None) -> Path:
    """Encode 1 second of silence in @fmt (e.g. 'mp3', 'flac', 'm4a')."""
    args = ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    for key, value in (tags or {}).items():
        args += ["-metadata", f"{key}={value}"]
    args += [str(path)]
    subprocess.run(args, capture_output=True, check=True)
    return path


class NeedsTranscodeTests(unittest.TestCase):
    def test_native_extensions_copy(self):
        for ext in (".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif"):
            self.assertFalse(needs_transcode(f"x{ext}"), ext)
            self.assertFalse(needs_transcode(f"x{ext.upper()}"), ext)

    def test_other_extensions_transcode(self):
        for ext in (".flac", ".ogg", ".opus", ".wma", ".ape"):
            self.assertTrue(needs_transcode(f"x{ext}"), ext)


class ReadTagsTests(unittest.TestCase):
    def test_reads_tags_and_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _make_audio(
                Path(tmp) / "song.mp3",
                "mp3",
                {"title": "My Title", "artist": "My Artist",
                 "album": "My Album", "genre": "Rock", "date": "2001-07-15"},
            )
            track = read_tags(src)
            self.assertEqual(track.title, "My Title")
            self.assertEqual(track.artist, "My Artist")
            self.assertEqual(track.album, "My Album")
            self.assertEqual(track.genre, "Rock")
            self.assertEqual(track.year, 2001)
            self.assertAlmostEqual(track.tracklen, 1000, delta=400)
            self.assertGreater(track.bitrate, 0)

    def test_untagged_file_uses_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _make_audio(Path(tmp) / "no tags.mp3", "mp3")
            self.assertEqual(read_tags(src).title, "no tags")


class AddFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.db = ProvenanceDB(root / "library.sqlite")
        self.ipod_dir = root / "iPod_Control" / "Music"
        self.ipod_dir.mkdir(parents=True)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _add(self, src: Path, library: list | None = None) -> AddResult:
        tracks = library if library is not None else []
        return add_file(tracks, self.db, src, self.ipod_dir)
    def test_add_native_mp3(self):
        src = _make_audio(Path(self.tmp.name) / "native.mp3", "mp3",
                          {"title": "Native", "artist": "A", "album": "B"})
        library: list = []
        result = self._add(src, library)
        self.assertEqual(result.status, "added")
        track = result.track
        self.assertEqual(track.title, "Native")
        self.assertEqual(track.filetype, "MPEG audio file")
        self.assertTrue(track.ipod_path.startswith("iPod_Control:Music:F"))
        file_on_ipod = self.ipod_dir.joinpath(*track.ipod_path.split(":")[2:])
        self.assertTrue(file_on_ipod.is_file())
        self.assertEqual(track.size, file_on_ipod.stat().st_size)
        self.assertEqual(track.filetype_marker, int.from_bytes(b"MP3 ", "little"))
        self.assertIn(track, library)  # appended to library state
        self.assertEqual(self.db.device_files_count(), 1)

    def test_add_transcodes_flac_to_m4a(self):
        src = _make_audio(Path(self.tmp.name) / "lossless.flac", "flac",
                          {"title": "Lossless", "artist": "A"})
        result = self._add(src)
        self.assertEqual(result.status, "added")
        track = result.track
        self.assertTrue(track.ipod_path.endswith(".m4a"))
        self.assertEqual(track.filetype, "AAC audio file")
        file_on_ipod = self.ipod_dir.joinpath(*track.ipod_path.split(":")[2:])
        self.assertTrue(file_on_ipod.is_file())
        # The transcoded file must itself be playable/parseable audio.
        probed = read_tags(file_on_ipod)
        self.assertEqual(probed.title, "Lossless")

    def test_content_duplicate_skipped(self):
        src = _make_audio(Path(self.tmp.name) / "same.mp3", "mp3")
        library: list = []
        self.assertEqual(self._add(src, library).status, "added")
        self.assertEqual(self._add(src, library).status, "content")
        self.assertEqual(len(library), 1)

    def test_metadata_duplicate_skipped(self):
        from podracer_db.model import Track

        src = _make_audio(Path(self.tmp.name) / "dup.mp3", "mp3",
                          {"title": "Same Song", "artist": "Same Artist"})
        preexisting = Track(title="Same Song", artist="Same Artist",
                            album=None, tracklen=read_tags(src).tracklen)
        result = self._add(src, [preexisting])
        self.assertEqual(result.status, "metadata")

    def test_unique_names(self):
        used: set[str] = set()
        names = [pipeline.ipod_filename(".mp3", used) for _ in range(30)]
        self.assertEqual(len(set(names)), 30)
        for name in names:
            self.assertRegex(name, r"^[A-Z0-9]{4}\.mp3$")


if __name__ == "__main__":
    unittest.main()
