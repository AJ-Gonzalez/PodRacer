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


def _make_flac_with_art(path: Path, tags: dict[str, str] | None = None) -> Path:
    """FLAC with a big (3000x3000) embedded cover, to stress the
    art-downscaling transcode path.

    The picture block is inserted by hand: this ffmpeg build's FLAC
    muxer writes an empty audio stream when an attached_pic is present,
    so the picture must go in after encoding. FLAC picture blocks are
    simple (type 6, size-prefixed fields), so this is deterministic
    across ffmpeg versions.
    """
    _make_audio(path, "flac", tags)
    jpeg = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=3000x3000:duration=0.04",
         "-frames:v", "1", "-q:v", "1", "-f", "mjpeg", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout

    data = path.read_bytes()
    assert data[:4] == b"fLaC"
    blocks: list[tuple[bool, int, bytes]] = []
    pos = 4
    while pos < len(data):
        hdr = data[pos]
        last = bool(hdr & 0x80)
        size = int.from_bytes(data[pos + 1:pos + 4], "big")
        blocks.append((last, hdr & 0x7F, data[pos + 4:pos + 4 + size]))
        pos += 4 + size
        if last:
            break

    out = bytearray(data[:4])
    for last, btype, body in blocks:
        # None of the existing blocks are last anymore: the PICTURE
        # block we append below takes the last-flag (0x80).
        out += bytes([btype]) + len(body).to_bytes(3, "big") + body
    mime, desc = b"image/jpeg", b""
    picture = (
        (3).to_bytes(4, "big")                    # type: front cover
        + len(mime).to_bytes(4, "big") + mime
        + len(desc).to_bytes(4, "big") + desc
        + (0).to_bytes(4, "big") * 4              # w/h/depth/colors unknown
        + len(jpeg).to_bytes(4, "big") + jpeg
    )
    out += bytes([0x80 | 6]) + len(picture).to_bytes(3, "big") + picture
    out += data[pos:]                             # audio frames follow
    path.write_bytes(out)
    return path


def _source_art_size(path: Path) -> int:
    """Bytes of the source's embedded cover art (0 if none).

    Reads the FLAC PICTURE metadata block directly; the block format
    is fixed by the spec (type/mime/desc/dims, then the image).
    """
    data = Path(path).read_bytes()
    if data[:4] != b"fLaC":
        return 0
    pos = 4
    while pos < len(data):
        last = bool(data[pos] & 0x80)
        btype = data[pos] & 0x7F
        size = int.from_bytes(data[pos + 1:pos + 4], "big")
        body = data[pos + 4:pos + 4 + size]
        if btype == 6:  # PICTURE
            mime_len = int.from_bytes(body[4:8], "big")
            desc_len = int.from_bytes(body[8 + mime_len:12 + mime_len], "big")
            data_len_off = 12 + mime_len + desc_len + 16
            return int.from_bytes(body[data_len_off:data_len_off + 4], "big")
        pos += 4 + size
        if last:
            break
    return 0


def _id3_info(path: Path) -> tuple[int, int]:
    """(ID3v2 tag size, APIC frame count) of an MP3, or (0, 0) if untagged."""
    data = Path(path).read_bytes()
    if data[:3] != b"ID3":
        return 0, 0
    size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) \
        | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
    apics = 0
    pos, end = 10, 10 + size
    while pos + 10 <= end:
        if data[pos:pos + 4] == b"\x00\x00\x00\x00":
            break
        fsize = int.from_bytes(data[pos + 4:pos + 8], "big")
        if data[pos:pos + 4] == b"APIC":
            apics += 1
        pos += 10 + fsize
    return size, apics


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
        # Root-anchored device path (the leading colon is the root
        # marker; without it the nano cannot find the file).
        self.assertTrue(track.ipod_path.startswith(":iPod_Control:Music:F"))
        file_on_ipod = self.ipod_dir.joinpath(*pipeline.ipod_path_parts(track.ipod_path)[2:])
        self.assertTrue(file_on_ipod.is_file())
        self.assertEqual(track.size, file_on_ipod.stat().st_size)
        self.assertEqual(track.filetype_marker, int.from_bytes(b"MP3 ", "little"))
        self.assertIn(track, library)  # appended to library state
        self.assertEqual(self.db.device_files_count(), 1)
        # Every working writer stamps these (libgpod conventions).
        self.assertNotEqual(track.dbid, 0)
        self.assertEqual(track.dbid, track.dbid2)
        self.assertGreater(track.time_added, 0)
        self.assertEqual(track.samplerate2, float(track.samplerate))

    def test_add_transcodes_flac_to_mp3(self):
        src = _make_audio(Path(self.tmp.name) / "lossless.flac", "flac",
                          {"title": "Lossless", "artist": "A"})
        result = self._add(src)
        self.assertEqual(result.status, "added")
        track = result.track
        self.assertTrue(track.ipod_path.endswith(".mp3"))
        self.assertEqual(track.filetype, "MPEG audio file")
        # The DB must carry the encoded bitrate, not the FLAC's.
        self.assertEqual(track.bitrate, pipeline.TRANSCODE_BITRATE)
        file_on_ipod = self.ipod_dir.joinpath(*pipeline.ipod_path_parts(track.ipod_path)[2:])
        self.assertTrue(file_on_ipod.is_file())
        # The transcoded file must itself be playable/parseable audio.
        probed = read_tags(file_on_ipod)
        self.assertEqual(probed.title, "Lossless")

    def test_transcode_caps_embedded_art(self):
        # The nano 3G refuses MP3s with large ID3 tags: a hi-res FLAC
        # cover survives a verbatim copy as an ~890 KiB APIC and the
        # track lists but never plays. Transcoding must recompress the
        # art (iTunes-style, 600px) instead of copying it.
        src = _make_flac_with_art(Path(self.tmp.name) / "bigart.flac",
                                  {"title": "Big Art"})
        # Sanity: the fixture really carries a large picture, or this
        # test proves nothing.
        self.assertGreaterEqual(_source_art_size(src), 300_000)

        result = self._add(src)
        self.assertEqual(result.status, "added")
        track = result.track
        file_on_ipod = self.ipod_dir.joinpath(*pipeline.ipod_path_parts(track.ipod_path)[2:])
        tag_size, apics = _id3_info(file_on_ipod)
        self.assertGreaterEqual(apics, 1)          # art preserved
        self.assertLessEqual(tag_size, 200_000)    # but capped hard
        probed = read_tags(file_on_ipod)
        self.assertEqual(probed.title, "Big Art")


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


class CollectAudioTests(unittest.TestCase):
    def test_walks_folders_and_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "deep").mkdir(parents=True)
            (root / "b").mkdir()
            song1 = root / "a" / "one.mp3"
            song2 = root / "a" / "deep" / "two.FLAC"
            song3 = root / "b" / "three.ogg"
            for p in (song1, song2, song3):
                p.write_bytes(b"x")
            (root / "a" / "notes.txt").write_text("not music")
            (root / "b" / "cover.jpg").write_bytes(b"img")

            found = pipeline.collect_audio([root / "a", root / "b"])
            self.assertEqual(found, [song2, song1, song3])  # stable sorted order

    def test_single_file_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            song = root / "s.mp3"
            song.write_bytes(b"x")
            # same file dropped twice via folder + file -> deduped
            found = pipeline.collect_audio([root, song])
            self.assertEqual(found, [song])

    def test_non_audio_drop_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "movie.mp4").write_bytes(b"x")
            self.assertEqual(pipeline.collect_audio([root]), [])


if __name__ == "__main__":
    unittest.main()
