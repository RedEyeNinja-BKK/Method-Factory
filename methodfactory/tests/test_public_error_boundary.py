"""Complete public error-boundary tests (Finding 4, review 4879090471).

Every currently exposed storage/artifact operation must surface typed
MethodFactoryError (never raw sqlite3/JSON/Unicode/OS/type), with specific
codes where the failure class is known.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import MethodFactoryError
from methodfactory.storage.errors import ManifestInvalidError
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.sqlite import (
    APPLICATION_ID,
    close_database,
    latest_event,
    open_database,
)


class LatestEventBoundaryTests(unittest.TestCase):
    def _db_with_manifest(self, raw: bytes):
        """Create a valid store, then write a specific manifest_json blob into
        the events table (bypassing the store) to test the read boundary."""
        import sqlite3

        root = Path(tempfile.mkdtemp())
        conn = open_database(root, read_only=False)
        close_database(conn)
        c = sqlite3.connect(str(root / DB_FILENAME))
        c.execute(
            "INSERT INTO events (package_id, revision, event_id, action_id, action, "
            "action_sha256, state_before, state_after, previous_manifest_sha256, "
            "resulting_manifest_sha256, created_at, action_json, manifest_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "pkg_demo_001", 0, "evt_1", "act_1", "create_package", "0" * 64,
                None, "INTAKE", None, "0" * 64, "2026-08-07T00:00:00+00:00",
                b'{"action":"create_package"}', raw,
            ),
        )
        c.commit()
        c.close()
        return root

    def test_malformed_manifest_blob_typed(self):
        root = self._db_with_manifest(b"{not json")
        conn = open_database(root, read_only=True)
        try:
            with self.assertRaises(MethodFactoryError) as ctx:
                latest_event(conn, "pkg_demo_001")
            self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")
        finally:
            close_database(conn)

    def test_invalid_utf8_manifest_blob_typed(self):
        root = self._db_with_manifest(b"\xff\xfe\x00 invalid")
        conn = open_database(root, read_only=True)
        try:
            with self.assertRaises(MethodFactoryError) as ctx:
                latest_event(conn, "pkg_demo_001")
            self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")
        finally:
            close_database(conn)

    def test_valid_manifest_blob_returns(self):
        root = self._db_with_manifest(b'{"schema_version":"0.1"}')
        conn = open_database(root, read_only=True)
        try:
            self.assertEqual(latest_event(conn, "pkg_demo_001"), {"schema_version": "0.1"})
        finally:
            close_database(conn)

    def test_missing_package_returns_none(self):
        root = self._db_with_manifest(b'{"schema_version":"0.1"}')
        conn = open_database(root, read_only=True)
        try:
            self.assertIsNone(latest_event(conn, "pkg_missing_999"))
        finally:
            close_database(conn)


class ArtifactBoundaryTests(unittest.TestCase):
    def test_invalid_utf8_blob_get_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            blob = store._blob_path(d)
            blob.write_bytes(b"\xff\xfe\x00 invalid")
            with self.assertRaises(MethodFactoryError):
                store.get(d)

    def test_unreadable_missing_blob_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with self.assertRaises(MethodFactoryError):
                store.get("0" * 64)
            with self.assertRaises(MethodFactoryError):
                store.artifact_bytes("0" * 64)

    def test_invalid_argument_types_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            with self.assertRaises(MethodFactoryError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", 123)  # type: ignore[arg-type]
            with self.assertRaises(MethodFactoryError):
                store.put("pkg_demo_001", "skills/x/SKILL.md", None)  # type: ignore[arg-type]
            with self.assertRaises(MethodFactoryError):
                store.get(None)  # type: ignore[arg-type]

    def test_corrupt_blob_get_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            d, _ = store.put("pkg_demo_001", "skills/x/SKILL.md", "content")
            blob = store._blob_path(d)
            blob.write_bytes(b"tampered")
            with self.assertRaises(MethodFactoryError):
                store.get(d)


if __name__ == "__main__":
    unittest.main()
