"""SQLite open/identity/state tests (ADR-0012 §D state table)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.errors import (
    DatabaseEmptyError,
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    LegacyStoreDetectedError,
    UnsupportedSchemaError,
)
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.sqlite import (
    APPLICATION_ID,
    USER_VERSION,
    close_database,
    detect_presence,
    initialize_database,
    open_database,
)


def _make_legacy_dirs(root: Path) -> None:
    for d in ("packages", "events", "artifacts"):
        (root / d).mkdir(parents=True, exist_ok=True)


class SqliteOpenTests(unittest.TestCase):
    def test_fresh_rw_creates_and_initializes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            try:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                uv = conn.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(int(app_id), APPLICATION_ID)
                self.assertEqual(int(uv), USER_VERSION)
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("store_metadata", tables)
                self.assertIn("events", tables)
                triggers = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'")}
                self.assertIn("events_no_update", triggers)
                self.assertIn("events_no_delete", triggers)
                meta = {r["key"]: r["value"] for r in conn.execute(
                    "SELECT key, value FROM store_metadata")}
                self.assertEqual(meta.get("schema_version"), str(USER_VERSION))
            finally:
                close_database(conn)

    def test_file_and_dir_modes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            close_database(conn)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(root / DB_FILENAME).st_mode & 0o777, 0o600)

    def test_ro_missing_does_not_create(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(DatabaseNotFoundError):
                open_database(root, read_only=True)
            self.assertFalse((root / DB_FILENAME).exists())

    def test_ro_neither_raises_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DatabaseNotFoundError):
                open_database(Path(td), read_only=True)

    def test_legacy_only_rw_and_ro_raise(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_legacy_dirs(root)
            with self.assertRaises(LegacyStoreDetectedError):
                open_database(root, read_only=False)
            with self.assertRaises(LegacyStoreDetectedError):
                open_database(root, read_only=True)
            self.assertFalse((root / DB_FILENAME).exists())

    def test_zero_byte_rw_initializes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / DB_FILENAME).write_bytes(b"")
            conn = open_database(root, read_only=False)
            try:
                self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), USER_VERSION)
            finally:
                close_database(conn)

    def test_zero_byte_ro_raises_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / DB_FILENAME).write_bytes(b"")
            with self.assertRaises(DatabaseEmptyError):
                open_database(root, read_only=True)

    def test_wrong_application_id_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute(f"PRAGMA application_id = {0xDEADBEEF}")
            c.execute("CREATE TABLE junk (x)")
            c.commit()
            c.close()
            with self.assertRaises(DatabaseIdMismatchError):
                open_database(root, read_only=False)
            with self.assertRaises(DatabaseIdMismatchError):
                open_database(root, read_only=True)

    def test_future_user_version_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            c.execute(f"PRAGMA user_version = {USER_VERSION + 1}")
            c.execute("CREATE TABLE t (x)")
            c.commit()
            c.close()
            with self.assertRaises(UnsupportedSchemaError):
                open_database(root, read_only=False)
            with self.assertRaises(UnsupportedSchemaError):
                open_database(root, read_only=True)

    def test_both_present_uses_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = open_database(root, read_only=False)  # create SQLite first
            close_database(conn0)
            _make_legacy_dirs(root)  # then legacy dirs -> BOTH
            conn = open_database(root, read_only=False)
            try:
                self.assertEqual(int(conn.execute("PRAGMA user_version").fetchone()[0]), USER_VERSION)
            finally:
                close_database(conn)

    def test_detect_presence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(detect_presence(root).value, "no_store")
            conn = open_database(root, read_only=False)
            close_database(conn)
            self.assertEqual(detect_presence(root).value, "sqlite_only")
            _make_legacy_dirs(root)
            self.assertEqual(detect_presence(root).value, "both")

    def test_ro_open_on_valid_db_works_and_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = open_database(root, read_only=False)
            initialize_database(conn0)
            close_database(conn0)
            before = (root / DB_FILENAME).stat().st_mtime_ns
            conn = open_database(root, read_only=True)
            close_database(conn)
            after = (root / DB_FILENAME).stat().st_mtime_ns
            self.assertEqual(before, after)  # read-only open did not touch the file


if __name__ == "__main__":
    unittest.main()
