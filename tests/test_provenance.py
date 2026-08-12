"""Provenance sidecar and duplicate-detection tests."""

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from podracer import provenance
from podracer.provenance import ProvenanceDB, check_duplicate
from podracer_db.model import Track


def _make_db(tmp: str) -> ProvenanceDB:
    return ProvenanceDB(Path(tmp) / "library.sqlite")


class ProvenanceDBTests(unittest.TestCase):
    def test_remember_and_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _make_db(tmp) as db:
                self.assertIsNone(db.source_digest("/x.mp3", 10, 1.0))
                db.remember_source("/x.mp3", 10, 1.0, "abc")
                self.assertEqual(db.source_digest("/x.mp3", 10, 1.0), "abc")
                # changed file (new mtime) invalidates the cache
                self.assertIsNone(db.source_digest("/x.mp3", 10, 2.0))
                self.assertIsNone(db.source_digest("/x.mp3", 11, 1.0))

    def test_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "library.sqlite"
            with ProvenanceDB(path) as db:
                db.remember_source("/a.mp3", 5, 1.0, "dig")
            with ProvenanceDB(path) as db:
                self.assertEqual(db.source_digest("/a.mp3", 5, 1.0), "dig")

    def test_device_files_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _make_db(tmp) as db:
                self.assertFalse(db.device_has_digest("d1"))
                db.remember_device_file("iPod_Control:Music:F00:a.mp3", "d1")
                self.assertTrue(db.device_has_digest("d1"))
                self.assertEqual(db.device_files_count(), 1)
                db.forget_device_file("iPod_Control:Music:F00:a.mp3")
                self.assertFalse(db.device_has_digest("d1"))


class HashFileTests(unittest.TestCase):
    def test_matches_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "song.mp3"
            payload = b"not really audio" * 1000
            path.write_bytes(payload)
            self.assertEqual(
                provenance.hash_file(path),
                hashlib.sha256(payload).hexdigest(),
            )


class DuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = _make_db(self.tmp.name)
        self.src = Path(self.tmp.name) / "song.mp3"
        self.src.write_bytes(b"audio data here")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _probe(self, **kw: object) -> Track:
        """A Track carrying the four fields the matcher compares."""
        return Track(
            title=str(kw.get("title", "Song")),
            artist=str(kw.get("artist", "Artist")),
            album=str(kw.get("album", "Album")),
            tracklen=int(kw.get("tracklen", 180000)),
        )

    def test_new_file_is_not_duplicate(self):
        lib = [self._probe(title="Other")]
        self.assertIsNone(check_duplicate(self.db, self.src, self._probe(), lib))
        self.assertEqual(self.db.device_files_count(), 0)

    def test_content_duplicate_same_sha(self):
        # Same bytes on the device (as we recorded it), different name.
        digest = provenance.hash_file(self.src)
        self.db.remember_device_file("iPod_Control:Music:F00:other.mp3", digest)
        lib = [self._probe(title="Something Else")]
        self.assertEqual(check_duplicate(self.db, self.src, self._probe(), lib), "content")

    def test_cached_source_digest_reused(self):
        lib = []
        self.assertIsNone(check_duplicate(self.db, self.src, self._probe(), lib))
        digest = provenance.hash_file(self.src)
        self.db.remember_device_file("iPod_Control:Music:F00:x.mp3", digest)
        # Second drag: cached triple, no re-hash needed, caught as dup.
        self.assertEqual(check_duplicate(self.db, self.src, self._probe(), lib), "content")

    def test_metadata_duplicate_fallback(self):
        lib = [self._probe(title="Song", artist="Artist", album="Album", tracklen=179000)]
        # No provenance, no device record -> metadata match.
        self.assertEqual(
            check_duplicate(self.db, self.src, self._probe(), lib), "metadata"
        )

    def test_metadata_mismatch_on_artist(self):
        lib = [self._probe(title="Song", artist="Someone Else")]
        self.assertIsNone(check_duplicate(self.db, self.src, self._probe(), lib))

    def test_duration_tolerance(self):
        lib = [self._probe(title="Song", tracklen=180000 + 2500)]
        self.assertIsNone(check_duplicate(self.db, self.src, self._probe(), lib))
        lib = [self._probe(title="Song", tracklen=180000 - 1500)]
        self.assertEqual(check_duplicate(self.db, self.src, self._probe(), lib), "metadata")


if __name__ == "__main__":
    unittest.main()
