"""Complete public error-boundary tests (Finding 4, review 4879090471;
closure review 4879440857).

Every currently exposed storage/artifact operation must surface typed
MethodFactoryError (never raw sqlite3/JSON/Unicode/OS/type), with specific
codes where the failure class is known.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import InvalidEnvelopeError, MethodFactoryError
from methodfactory.protocol.envelope import envelope_from_dict
from methodfactory.storage.errors import ManifestInvalidError, SerializationError, StorageError
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.serialization import action_sha256
from methodfactory.storage.sqlite import (
    APPLICATION_ID,
    close_database,
    explain_latest_event_plan,
    latest_event,
    open_database,
)


class LatestEventBoundaryTests(unittest.TestCase):
    def _db_with_manifest(self, raw: bytes):
        """Create a valid store, then write a specific manifest_json blob into
        the events table (bypassing the store) to test the read boundary.

        The temp store is removed when the test completes (closure review 4882624484-A4:
        no leaked host temp stores)."""
        import shutil
        import sqlite3

        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
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

    def test_non_bytes_stored_type_translated(self):
        """A manifest_json column holding a non-bytes/non-str SQLite dynamic
        type (e.g. INTEGER) is translated to MANIFEST_INVALID, never a raw
        AttributeError (Finding 3)."""
        import sqlite3

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            close_database(conn)
            c = sqlite3.connect(str(root / DB_FILENAME))
            c.execute(
                "INSERT INTO events (package_id, revision, event_id, action_id, action, "
                "action_sha256, state_before, state_after, previous_manifest_sha256, "
                "resulting_manifest_sha256, created_at, action_json, manifest_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "pkg_int_001", 0, "evt_int", "act_int", "create_package", "0" * 64,
                    None, "INTAKE", None, "0" * 64, "2026-08-07T00:00:00+00:00",
                    b'{"action":"create_package"}', 12345,
                ),
            )
            c.commit()
            c.close()
            conn = open_database(root, read_only=True)
            try:
                with self.assertRaises(MethodFactoryError) as ctx:
                    latest_event(conn, "pkg_int_001")
                self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")
            finally:
                close_database(conn)

    def test_non_object_json_translated(self):
        """A manifest_json BLOB containing a JSON ARRAY (not an object) is
        translated to MANIFEST_INVALID (Finding 3)."""
        root = self._db_with_manifest(b'["not", "an", "object"]')
        conn = open_database(root, read_only=True)
        try:
            with self.assertRaises(MethodFactoryError) as ctx:
                latest_event(conn, "pkg_demo_001")
            self.assertEqual(ctx.exception.code, "MANIFEST_INVALID")
        finally:
            close_database(conn)

    def test_str_manifest_json_accepted(self):
        """A TEXT-typed manifest_json is accepted and decoded (Finding 3)."""
        import sqlite3

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            close_database(conn)
            c = sqlite3.connect(str(root / DB_FILENAME))
            c.execute(
                "INSERT INTO events (package_id, revision, event_id, action_id, action, "
                "action_sha256, state_before, state_after, previous_manifest_sha256, "
                "resulting_manifest_sha256, created_at, action_json, manifest_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "pkg_str_001", 0, "evt_str", "act_str", "create_package", "0" * 64,
                    None, "INTAKE", None, "0" * 64, "2026-08-07T00:00:00+00:00",
                    b'{"action":"create_package"}', '{"schema_version":"0.1"}',
                ),
            )
            c.commit()
            c.close()
            conn = open_database(root, read_only=True)
            try:
                self.assertEqual(latest_event(conn, "pkg_str_001"), {"schema_version": "0.1"})
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


class SerializationBoundaryTests(unittest.TestCase):
    def _semantic(self, **over):
        s = {
            "protocol_version": "0.1",
            "action": "record_input",
            "package_id": "pkg_demo_001",
            "action_id": "act_1",
            "basis": {},
            "payload": {"content": "x"},
        }
        s.update(over)
        return s

    def test_over_limit_action_typed(self):
        with self.assertRaises(SerializationError) as ctx:
            action_sha256(**self._semantic(payload={"content": "x" * (4 * 1024 * 1024)}))
        self.assertEqual(ctx.exception.code, "SERIALIZATION")

    def test_lone_surrogate_action_typed(self):
        with self.assertRaises(SerializationError) as ctx:
            action_sha256(**self._semantic(payload={"content": "x\ud800"}))
        self.assertEqual(ctx.exception.code, "SERIALIZATION")

    def test_non_serializable_payload_typed(self):
        with self.assertRaises(SerializationError) as ctx:
            action_sha256(**self._semantic(payload={"content": object()}))
        self.assertEqual(ctx.exception.code, "SERIALIZATION")


class EnvelopeFromDictBoundaryTests(unittest.TestCase):
    def test_non_dict_input_translated(self):
        for bad in (None, "x", 5, []):
            with self.subTest(value=bad):
                with self.assertRaises(InvalidEnvelopeError):
                    envelope_from_dict(bad)  # type: ignore[arg-type]


class SqliteHelperBoundaryTests(unittest.TestCase):
    def test_explain_latest_event_plan_sqlite_error_typed(self):
        class BrokenConn:
            def execute(self, *args, **kwargs):
                raise __import__("sqlite3").Error("boom")

        with self.assertRaises(MethodFactoryError):
            explain_latest_event_plan(BrokenConn(), "pkg_demo_001")  # type: ignore[arg-type]

    def test_close_database_sqlite_error_typed(self):
        class BrokenConn:
            def close(self):
                raise __import__("sqlite3").Error("boom")

        with self.assertRaises(MethodFactoryError):
            close_database(BrokenConn())  # type: ignore[arg-type]

    def test_public_open_database_accepts_string_and_returns_closable(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_database(str(Path(td) / "nested" / "store"), read_only=False)
            close_database(conn)


if __name__ == "__main__":
    unittest.main()
