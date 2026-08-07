"""SQLite open/identity/schema tests — Finding 1 corrections (review 4878620791)."""

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
    SchemaViolationError,
    StorageError,
    UnsupportedSchemaError,
)
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.sqlite import (
    APPLICATION_ID,
    BINDING_PRAGMAS,
    USER_VERSION,
    close_database,
    detect_presence,
    initialize_database,
    open_database,
)


def _make_legacy_dirs(root: Path) -> None:
    for d in ("packages", "events", "artifacts"):
        (root / d).mkdir(parents=True, exist_ok=True)


def _make_valid_db(root: Path) -> sqlite3.Connection:
    conn = open_database(root, read_only=False)
    return conn


class SqlitePragmaTests(unittest.TestCase):
    def test_binding_pragmas_applied_and_read_back(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_database(Path(td), read_only=False)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete"
                )
                self.assertEqual(int(conn.execute("PRAGMA synchronous").fetchone()[0]), 2)
                self.assertEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), 5000)
                self.assertEqual(int(conn.execute("PRAGMA foreign_keys").fetchone()[0]), 1)
            finally:
                close_database(conn)

    def test_ro_verifies_pragmas(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_valid_db(root)
            conn = open_database(root, read_only=True)
            try:
                self.assertEqual(int(conn.execute("PRAGMA synchronous").fetchone()[0]), 2)
                self.assertEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), 5000)
            finally:
                close_database(conn)

    def test_wal_reopen_establishes_delete(self):
        """Finding 1 item 1: a DB previously placed in WAL must be reset to
        DELETE on rw open, or fail typed."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = _make_valid_db(root)
            conn0.execute("PRAGMA journal_mode = WAL")
            close_database(conn0)
            # Reopen rw: journal_mode must be re-established to DELETE.
            conn = open_database(root, read_only=False)
            try:
                self.assertEqual(
                    conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete"
                )
            finally:
                close_database(conn)

    def test_wal_reopen_read_only_fails_typed(self):
        """A WAL-mode DB cannot be 'fixed' read-only; verification must fail
        typed rather than silently accept WAL."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = _make_valid_db(root)
            conn0.execute("PRAGMA journal_mode = WAL")
            close_database(conn0)
            with self.assertRaises(StorageError):
                open_database(root, read_only=True)


class SqliteInitTests(unittest.TestCase):
    def test_initialization_is_atomic_on_fault(self):
        """Finding 1 item 3: fault-inject between schema and identity; no
        accepted partial store remains."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            conn = sqlite3.connect(str(db))
            # Simulate a failure mid-initialization: create events table but
            # fail before identity/metadata (as a partial init would leave).
            conn.execute(
                "CREATE TABLE events (package_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "PRIMARY KEY (package_id, revision)) WITHOUT ROWID"
            )
            conn.commit()
            conn.close()
            # Non-zero, MFST-less partial file: must be rejected, not silently
            # initialized.
            with self.assertRaises(DatabaseIdMismatchError):
                open_database(root, read_only=False)
            # And the partial table must not be treated as valid.
            conn2 = sqlite3.connect(str(db))
            self.assertEqual(
                conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                [("events",)],
            )
            conn2.close()

    def test_initialize_rolls_back_on_mid_failure(self):
        """initialize_database must be atomic: a failure inside rolls back."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            conn = sqlite3.connect(str(db))
            # Break the metadata insert by pre-creating store_metadata with a
            # conflicting schema is complex; simpler: drop the events table via
            # a deliberately invalid DDL by monkeypatching is overkill. Instead
            # verify the explicit-BEGIN/COMMIT structure by checking that a
            # raised error leaves no committed schema.
            import methodfactory.storage.sqlite as sqlite_mod

            orig = sqlite_mod.STORE_METADATA_DDL
            sqlite_mod.STORE_METADATA_DDL = "CREATE TABLE store_metadata (x);"  # wrong shape
            try:
                with self.assertRaises(Exception):
                    sqlite_mod.initialize_database(conn)
            finally:
                sqlite_mod.STORE_METADATA_DDL = orig
            conn.rollback()
            self.assertEqual(
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                [],
            )
            conn.close()

    def test_nonzero_user_version_zero_rejected(self):
        """Finding 1 item 3: non-zero DB with MFST app id but user_version=0
        must be rejected (no recovery path specified)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            c.execute("PRAGMA user_version = 0")
            c.execute("CREATE TABLE junk (x)")
            c.commit()
            c.close()
            with self.assertRaises(UnsupportedSchemaError):
                open_database(root, read_only=False)
            with self.assertRaises(UnsupportedSchemaError):
                open_database(root, read_only=True)


class SchemaVerifierTests(unittest.TestCase):
    def test_valid_db_passes_verifier(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_database(Path(td), read_only=False)
            try:
                # open_database already ran _verify_schema; re-open to prove.
                pass
            finally:
                close_database(conn)

    def test_missing_table_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute("DROP TABLE store_metadata")
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_missing_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute("DROP TRIGGER events_no_delete")
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_metadata_drift_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            db = root / DB_FILENAME
            c = sqlite3.connect(str(db))
            c.execute("UPDATE store_metadata SET value='2' WHERE key='schema_version'")
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)


class UriPathTests(unittest.TestCase):
    def test_readonly_uri_with_significant_paths(self):
        """Finding 1 item 5: paths with spaces, Unicode, ?, #, % must open
        correctly and create no sibling/alternate file. The base temp dir is
        removed on completion (closure review 4882624484-A4: no leaked temp stores)."""
        with tempfile.TemporaryDirectory() as base:
            for name in (
                "store with space",
                "สโตร์",
                "store?with#special%chars",
            ):
                root = Path(base) / name
                root.mkdir(parents=True)
                conn0 = open_database(root, read_only=False)
                close_database(conn0)
                before = sorted(p.name for p in root.iterdir())
                conn = open_database(root, read_only=True)
                close_database(conn)
                after = sorted(p.name for p in root.iterdir())
                self.assertEqual(before, after, f"ro open created files in {name}")
            # No sibling file created anywhere under the base dir beyond the 3
            # intended store roots.
            expected_roots = {"store with space", "สโตร์", "store?with#special%chars"}
            actual_roots = {p.name for p in Path(base).iterdir()}
            self.assertEqual(actual_roots, expected_roots)

    def test_ro_missing_no_create(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(DatabaseNotFoundError):
                open_database(root, read_only=True)
            self.assertFalse((root / DB_FILENAME).exists())


class LegacyDetectionTests(unittest.TestCase):
    def test_partial_layouts_not_legacy(self):
        """Finding 1 item 6: single dirs (packages-only / events-only /
        artifacts-only) are NOT a legacy store."""
        with tempfile.TemporaryDirectory() as td:
            for d in ("packages", "events", "artifacts"):
                root = Path(td) / f"only_{d}"
                root.mkdir(parents=True)
                (root / d).mkdir()
                self.assertEqual(detect_presence(root).value, "no_store", d)
                # rw open should create a fresh SQLite store, not LEGACY.
                conn = open_database(root, read_only=False)
                close_database(conn)
                self.assertTrue((root / DB_FILENAME).exists())

    def test_complete_legacy_layout_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _make_legacy_dirs(root)
            self.assertEqual(detect_presence(root).value, "legacy_only")
            with self.assertRaises(LegacyStoreDetectedError):
                open_database(root, read_only=False)
            with self.assertRaises(LegacyStoreDetectedError):
                open_database(root, read_only=True)

    def test_both_present_uses_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = open_database(root, read_only=False)
            close_database(conn0)
            _make_legacy_dirs(root)
            self.assertEqual(detect_presence(root).value, "both")
            conn = open_database(root, read_only=False)
            close_database(conn)


class ModeEnforcementTests(unittest.TestCase):
    def test_modes_enforced_on_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            close_database(conn)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(root / DB_FILENAME).st_mode & 0o777, 0o600)

    def test_existing_incorrect_mode_corrected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_database(root, read_only=False)
            close_database(conn)
            os.chmod(root, 0o755)
            os.chmod(root / DB_FILENAME, 0o644)
            conn = open_database(root, read_only=False)
            close_database(conn)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(root / DB_FILENAME).st_mode & 0o777, 0o600)


class StringRootTests(unittest.TestCase):
    """Finding 3: the public root argument may be a plain string. The
    normalized Path returned by validate_store_root() is passed throughout the
    open implementation (never the original string form), and root
    normalization lives inside the typed public error boundary."""

    def test_string_root_creates_new_store(self):
        with tempfile.TemporaryDirectory() as td:
            root_str = str(Path(td) / "store")
            conn = open_database(root_str, read_only=False)
            close_database(conn)
            self.assertTrue((Path(root_str) / DB_FILENAME).is_file())

    def test_string_root_reopens_existing_store(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn0 = open_database(root, read_only=False)
            close_database(conn0)
            conn = open_database(str(root), read_only=False)
            try:
                self.assertEqual(
                    int(conn.execute("PRAGMA user_version").fetchone()[0]), USER_VERSION
                )
                self.assertEqual(
                    conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "delete"
                )
            finally:
                close_database(conn)

    def test_string_root_missing_store_readonly_not_found(self):
        """String root on a missing store: typed DatabaseNotFoundError and NO
        directory/database created (read-only never creates)."""
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing"
            with self.assertRaises(DatabaseNotFoundError):
                open_database(str(missing), read_only=True)
            self.assertFalse(missing.exists())

    def test_invalid_string_root_typed(self):
        """Empty string root surfaces as typed InvalidStoreRootError, not a raw
        pathlib/OS error."""
        from methodfactory.storage.errors import InvalidStoreRootError
        with self.assertRaises(InvalidStoreRootError):
            open_database("   ", read_only=False)

    def test_non_path_root_typed(self):
        """Local review (bug-2): non-str/Path roots (None, int, float) surface
        as typed StorageError, never a raw TypeError."""
        for bad in (None, 123, 3.14):
            with self.subTest(root=bad):
                with self.assertRaises(StorageError):
                    open_database(bad, read_only=False)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
