"""ArtifactStore guard and integrity tests — remediation of code-review
F6 (logical_path contract), F11 (blob poisoning), and adversarial fixtures
for sec-6.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore, validate_logical_path
from methodfactory.domain.errors import InvalidPayloadError
from methodfactory.manifest.hashing import digest_bytes


class LogicalPathTests(unittest.TestCase):
    def test_accepts_normal_relative_path(self):
        self.assertEqual(validate_logical_path("skills/standup-notes/SKILL.md"), "skills/standup-notes/SKILL.md")

    def test_rejects_absolute_unix_path(self):
        for bad in ("/etc/passwd", "//etc//passwd", "/skills/x/SKILL.md"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPayloadError):
                    validate_logical_path(bad)

    def test_rejects_backslash_and_windows_drive(self):
        for bad in ("a\\..\\b", "C:\\evil", "C:/evil", "skills\\x"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPayloadError):
                    validate_logical_path(bad)

    def test_rejects_dot_and_dotdot_segments(self):
        for bad in ("..", "a/../b", "./x", "a/./b", "../x"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPayloadError):
                    validate_logical_path(bad)

    def test_rejects_percent_encoded_separators(self):
        for bad in ("skills%2f..%2f..%2fetc", "a%5c..%5cb"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPayloadError):
                    validate_logical_path(bad)

    def test_rejects_empty_and_too_long(self):
        with self.assertRaises(InvalidPayloadError):
            validate_logical_path("   ")
        with self.assertRaises(InvalidPayloadError):
            validate_logical_path("x" * 256)


class ArtifactIntegrityTests(unittest.TestCase):
    def test_put_returns_digest_and_size(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            digest, size = store.put("pkg_art_001", "skills/x/SKILL.md", "content")
            self.assertEqual(size, len("content"))
            self.assertEqual(digest, digest_bytes(b"content"))

    def test_put_poisoned_blob_is_rejected(self):
        """F11: a second put of content whose existing blob is corrupted must
        not silently succeed (would permanently poison the digest)."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            digest, _ = store.put("pkg_art_001", "skills/x/SKILL.md", "original")
            blob = store._blob_path(digest)
            blob.write_bytes(b"tampered")
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_art_001", "skills/x/SKILL.md", "original")

    def test_get_verifies_content_against_digest(self):
        """F11: reading a corrupted blob must fail rather than return bad bytes."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            digest, _ = store.put("pkg_art_001", "skills/x/SKILL.md", "original")
            blob = store._blob_path(digest)
            blob.write_bytes(b"tampered")
            with self.assertRaises(InvalidPayloadError):
                store.get(digest)
            with self.assertRaises(InvalidPayloadError):
                store.artifact_bytes(digest)
            self.assertFalse(store.verify(digest))

    def test_duplicate_put_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d1, s1 = store.put("pkg_art_001", "skills/x/SKILL.md", "same")
            d2, s2 = store.put("pkg_art_001", "skills/x/SKILL.md", "same")
            self.assertEqual((d1, s1), (d2, s2))


if __name__ == "__main__":
    unittest.main()
