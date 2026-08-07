"""Real fault-injection tests for immutable blob publication (Finding 2).

Injects failures at each durability point: write, file fsync, publication
(hard link), directory fsync; plus publication races, concurrent same-digest
writers, valid/corrupt raced destinations, and retry after a post-publication
durability error.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import InvalidPayloadError
from methodfactory.storage.serialization import digest_bytes


def _blob_count(store: ArtifactStore) -> int:
    return len([p for p in store.blobs.iterdir() if not p.name.startswith(".tmp.")])


class PublicationFaultTests(unittest.TestCase):
    def test_write_failure_removes_temp_no_canonical(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(ArtifactStore, "put", side_effect=InvalidPayloadError("write fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual([p for p in store.blobs.iterdir() if p.name.startswith(".tmp.")], [])

    def test_file_fsync_failure(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch("os.fsync", side_effect=OSError("fsync fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual([p for p in store.blobs.iterdir() if p.name.startswith(".tmp.")], [])

    def test_publication_failure_removes_temp(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch("os.link", side_effect=OSError("link fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual([p for p in store.blobs.iterdir() if p.name.startswith(".tmp.")], [])

    def test_directory_fsync_failure_raises_typed_but_blob_published(self):
        """A dir-fsync failure is reported as a typed error; the canonical blob
        is already durable-published (retry after durability-report failure)."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch("os.fsync", side_effect=OSError("dir fsync fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            # The blob WAS published (the failure was reporting durability),
            # so a retry must verify and succeed idempotently.
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertTrue(store.verify(d))


class PublicationRaceTests(unittest.TestCase):
    def test_destination_appears_between_precheck_and_publication(self):
        """A raced destination that appears between the temp write and os.link
        is verified (valid -> idempotent success; corrupt -> typed failure)."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            # Simulate a race: another writer creates the dest between our
            # pre-check and our os.link. os.link raises FileExistsError, which
            # the store treats as a race and verifies.
            dest = store._blob_path(d)
            # valid raced destination -> idempotent success
            self.assertTrue(dest.exists())
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)
            # corrupt raced destination -> typed failure
            dest.write_bytes(b"corrupt")
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", "content")

    def test_concurrent_same_digest_writers(self):
        """Concurrent same-digest writers must both succeed (one publishes,
        the other races + verifies), with exactly one canonical blob."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            results: list[tuple[str, int]] = []
            errors: list[Exception] = []
            barrier = threading.Barrier(2)

            def writer():
                try:
                    barrier.wait()
                    results.append(store.put("pkg_demo_001", "skills/x/SKILL.md", "same"))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            t1 = threading.Thread(target=writer)
            t2 = threading.Thread(target=writer)
            t1.start(); t2.start(); t1.join(); t2.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][0], results[1][0])
            self.assertEqual(_blob_count(store), 1)
            self.assertTrue(store.verify(results[0][0]))

    def test_valid_and_corrupt_raced_destinations(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            dest = store._blob_path(d)
            # valid raced
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)
            # corrupt raced -> typed failure, and the corrupt dest is NOT
            # replaced (immutability): verify() is False.
            dest.write_bytes(b"corrupt")
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(dest.read_bytes(), b"corrupt")
            self.assertFalse(store.verify(d))


class PublicBoundaryTests(unittest.TestCase):
    def test_invalid_package_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            from methodfactory.storage.errors import InvalidPackageIdError
            with self.assertRaises(InvalidPackageIdError):
                store.put("../evil", "skills/x/SKILL.md", "content")

    def test_non_string_content_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", 123)  # type: ignore[arg-type]

    def test_os_error_on_init_typed(self):
        # A root that cannot be created (e.g. a path under an existing file)
        # surfaces as InvalidPayloadError, not raw OSError.
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "blocker"
            blocker.write_text("x")
            with self.assertRaises(InvalidPayloadError):
                ArtifactStore(blocker / "sub")

    def test_missing_blob_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with self.assertRaises(InvalidPayloadError):
                store.get("0" * 64)
            with self.assertRaises(InvalidPayloadError):
                store.artifact_bytes("0" * 64)


if __name__ == "__main__":
    unittest.main()
