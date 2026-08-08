"""Real fault-injection tests for immutable blob publication (Finding 2).

Injects failures at each durability point THROUGH THE REAL IMPLEMENTATION
PATH via the narrow module-level seams (_write_all, _fsync_file, _hardlink,
_unlink_tmp, _open_dir, _fsync_dir, _close_fd) — never by mocking put().

Directory-fsync scenario (review 4879440857 #2): file fsync succeeds, the
directory fsync fails; the canonical blob is already published, the operation
returns a typed error, retry verifies the existing blob and succeeds, and no
temporary file remains.

Honest labeling: a test where the destination already exists before put()
begins proves the idempotent verification path, not an in-flight race. The
coordinated race test makes the destination appear BETWEEN temp write and
publication via a _hardlink side effect.
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from methodfactory.adapters import artifact_store as as_mod
from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import InvalidPayloadError
from methodfactory.storage.serialization import digest_bytes


def _blob_count(store: ArtifactStore) -> int:
    return len([p for p in store.blobs.iterdir() if not p.name.startswith(".tmp.")])


def _tmp_count(store: ArtifactStore) -> int:
    return len([p for p in store.blobs.iterdir() if p.name.startswith(".tmp.")])


class PublicationFaultTests(unittest.TestCase):
    def test_write_failure_removes_temp_no_canonical(self):
        """Real implementation-path write failure (not a mock of put())."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(as_mod, "_write_all", side_effect=OSError("write fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual(_tmp_count(store), 0)

    def test_temp_creation_failure_typed_no_leftovers(self):
        """Local review (q-4): the _open_tmp seam fails first — typed error,
        zero canonical blobs, zero temp files."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(as_mod, "_open_tmp", side_effect=OSError("create fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual(_tmp_count(store), 0)

    def test_file_fsync_failure(self):
        """Temp-file fsync fails -> typed error; nothing published, no temp."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(as_mod, "_fsync_file", side_effect=OSError("fsync fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual(_tmp_count(store), 0)

    def test_publication_failure_removes_temp(self):
        """Hard-link publication fails -> typed error; no canonical, no temp."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(as_mod, "_hardlink", side_effect=OSError("link fail")):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(_blob_count(store), 0)
            self.assertEqual(_tmp_count(store), 0)

    def test_directory_fsync_failure_typed_blob_published_no_temp(self):
        """File fsync SUCCEEDS, directory fsync FAILS. Prove: canonical blob
        already published; typed error returned; retry verifies the existing
        blob and succeeds; no temporary file remains. The retry runs against
        the HEALTHY implementation after the patch exits (no fail-once replay
        is claimed under the fault)."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(
                as_mod, "_fsync_dir", side_effect=OSError("dir fsync fail")
            ):
                with self.assertRaises(InvalidPayloadError) as ctx:
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertIsInstance(ctx.exception, InvalidPayloadError)
            d = digest_bytes(b"content")
            self.assertTrue(store._blob_path(d).is_file(), "blob published despite dir fsync failure")
            self.assertEqual(store._blob_path(d).read_bytes(), b"content")
            self.assertEqual(_tmp_count(store), 0)
            # Retry: races with the existing destination, verifies it, succeeds.
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)
            self.assertTrue(store.verify(d))

    def test_temp_unlink_failure_after_publication_not_silent(self):
        """Unlink of the temporary file after publication fails (fail-once):
        the operation MUST return a typed error, never silent success. The
        outer cleanup removes the temp; the canonical blob stays published and
        a retry succeeds."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            real_unlink = as_mod._unlink_tmp
            state = {"calls": 0}

            def flaky_unlink(path):
                state["calls"] += 1
                if state["calls"] == 1:
                    raise OSError("unlink fail")
                return real_unlink(path)

            with mock.patch.object(as_mod, "_unlink_tmp", side_effect=flaky_unlink):
                with self.assertRaises(InvalidPayloadError) as ctx:
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertIsInstance(ctx.exception, InvalidPayloadError)
            d = digest_bytes(b"content")
            self.assertTrue(store._blob_path(d).is_file())
            self.assertEqual(_tmp_count(store), 0)
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)

    def test_directory_close_failure_typed_blob_published(self):
        """Directory fd close fails after a successful fsync: typed error, blob
        already published, no temp; retry (against the healthy implementation)
        succeeds."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with mock.patch.object(
                as_mod, "_close_fd", side_effect=OSError("close fail")
            ):
                with self.assertRaises(InvalidPayloadError) as ctx:
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertIsInstance(ctx.exception, InvalidPayloadError)
            d = digest_bytes(b"content")
            self.assertTrue(store._blob_path(d).is_file())
            self.assertEqual(_tmp_count(store), 0)
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)


class PublicationRaceTests(unittest.TestCase):
    def test_coordinated_race_appears_between_write_and_publication(self):
        """A destination that appears BETWEEN the temp write and os.link (via a
        _hardlink side effect that creates it, then the real link raises
        FileExistsError) is verified: valid -> idempotent success; corrupt ->
        typed failure and the corrupt destination is NOT replaced."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))

            def valid_race(tmp, dest):
                dest.write_bytes(b"content")  # appears mid-publication
                return os.link(tmp, dest)     # FileExistsError

            with mock.patch.object(as_mod, "_hardlink", side_effect=valid_race):
                d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, digest_bytes(b"content"))

            def corrupt_race(tmp, dest):
                dest.write_bytes(b"corrupt")  # raced destination is corrupt
                return os.link(tmp, dest)

            # Remove the existing canonical blob so the fast-path short-circuit
            # does not run; the corrupt destination must appear DURING
            # publication (between temp write and os.link).
            store._blob_path(d).unlink()
            with mock.patch.object(as_mod, "_hardlink", side_effect=corrupt_race):
                with self.assertRaises(InvalidPayloadError):
                    store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            # Immutability: the corrupt raced destination is NOT replaced.
            self.assertEqual(store._blob_path(d).read_bytes(), b"corrupt")
            self.assertFalse(store.verify(d))

    def test_existing_destination_before_put_is_verification_not_race(self):
        """HONEST LABEL: the destination already exists before put() begins.
        This proves the idempotent verification path (valid -> success; corrupt
        -> typed failure), NOT an in-flight publication race. The coordinated
        race above is the race proof."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            dest = store._blob_path(d)
            # valid existing destination -> idempotent success
            d2, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(d, d2)
            # corrupt existing destination -> typed failure, NOT replaced
            dest.write_bytes(b"corrupt")
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertEqual(dest.read_bytes(), b"corrupt")
            self.assertFalse(store.verify(d))

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

    def test_lone_surrogate_content_translated(self):
        """content.encode() Unicode failures are translated (Finding 2)."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", "x\ud800")

    def test_non_canonical_digest_spellings_rejected(self):
        """Local review (bug-4): only strict ^[0-9a-f]{64}$ digests are
        accepted — 0x-prefixed, uppercase, and underscore forms are typed
        errors, matching the manifest validator."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            self.assertTrue(store.verify(d))
            for bad in ("0x" + "a" * 62, "ABCDEF" + "a" * 58, "a_b" + "a" * 61, ""):
                with self.subTest(digest=bad[:12]):
                    with self.assertRaises(InvalidPayloadError):
                        store.get(bad)
                    with self.assertRaises(InvalidPayloadError):
                        store.artifact_bytes(bad)

    def test_private_modes_enforced(self):
        """Local review (sec-2): root and blobs dirs are 0o700 even under a
        permissive umask, so the digest namespace is not group/world-writable."""
        old_umask = os.umask(0o002)
        try:
            with tempfile.TemporaryDirectory() as td:
                store = ArtifactStore(Path(td))
                self.assertEqual(os.stat(store.root).st_mode & 0o777, 0o700)
                self.assertEqual(os.stat(store.blobs).st_mode & 0o777, 0o700)
        finally:
            os.umask(old_umask)

    def test_invalid_root_types_translated(self):
        """ArtifactStore construction with invalid root types is translated to
        InvalidPayloadError (Finding 2), never a raw TypeError."""
        for bad in (None, 123, b"/tmp/x"):
            with self.subTest(root=bad):
                with self.assertRaises(InvalidPayloadError):
                    ArtifactStore(bad)  # type: ignore[arg-type]

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
