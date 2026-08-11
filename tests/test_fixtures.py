"""Guard fixture extraction: extracted fixtures must be self-consistent.

Skipped until fixtures exist. Extract them from a real iPod with
scripts/extract_fixtures.py, or point IPOD_THINGY_FIXTURES at a directory
containing a manifest.json for a smoke run.
"""

import hashlib
import json
import os
import unittest
from pathlib import Path

RAW = Path(
    os.environ.get(
        "IPOD_THINGY_FIXTURES",
        Path(__file__).resolve().parent.parent / "fixtures" / "raw",
    )
)


def _manifest() -> dict | None:
    path = RAW / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())


@unittest.skipUnless(_manifest() is not None, "no extracted fixtures; run scripts/extract_fixtures.py")
class FixtureIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _manifest()

    def test_manifest_lists_files(self):
        self.assertGreaterEqual(len(self.manifest["files"]), 1)

    def test_hashes_match(self):
        for entry in self.manifest["files"]:
            path = RAW / entry["path"]
            self.assertTrue(path.is_file(), f"fixture missing: {path}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, entry["sha256"], f"hash mismatch: {path}")

    def test_db_family_recorded(self):
        self.assertIn(self.manifest["db_family"], ("itunesdb", "itunessd"))

    def test_db_present(self):
        names = {e["path"] for e in self.manifest["files"]}
        self.assertTrue(names & {"iTunesDB", "iTunesCDB"}, "no database file extracted")


if __name__ == "__main__":
    unittest.main()
