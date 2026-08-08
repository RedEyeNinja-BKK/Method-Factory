"""Public error boundary tests (Finding 2 item 4).

Raw sqlite3/JSON/Unicode/OS/type exceptions must not escape public storage
operations; storage failures must be catchable through the one public
MethodFactoryError boundary.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from methodfactory.domain.errors import (
    ActionIdConflictError,
    MethodFactoryError,
)
from methodfactory.storage.errors import (
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    LegacyStoreDetectedError,
    StorageError,
    UnsupportedSchemaError,
)
from methodfactory.storage.paths import DB_FILENAME


class ErrorBoundaryTests(unittest.TestCase):
    def test_storage_error_is_method_factory_error(self):
        self.assertTrue(issubclass(StorageError, MethodFactoryError))
        self.assertTrue(issubclass(DatabaseNotFoundError, MethodFactoryError))
        self.assertTrue(issubclass(LegacyStoreDetectedError, MethodFactoryError))
        self.assertTrue(issubclass(DatabaseIdMismatchError, MethodFactoryError))
        self.assertTrue(issubclass(UnsupportedSchemaError, MethodFactoryError))

    def test_action_id_conflict_is_canonical(self):
        # ACTION_ID_CONFLICT is the canonical SQLite-era code and is a public
        # MethodFactoryError. ACTION_ID_REUSE is retained only as legacy.
        self.assertEqual(ActionIdConflictError.code, "ACTION_ID_CONFLICT")
        self.assertTrue(issubclass(ActionIdConflictError, MethodFactoryError))
        from methodfactory.domain.errors import ActionIdReuseError
        self.assertEqual(ActionIdReuseError.code, "ACTION_ID_REUSE")

    def test_raw_sqlite_exception_does_not_escape_public_open(self):
        """A corrupt/wrong-format DB surfaces as a typed StorageError, not a raw
        sqlite3 exception."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / DB_FILENAME
            db.write_bytes(b"\x00" * 8 + b"NOT A REAL SQLITE DB AT ALL, THIS IS GARBAGE DATA" * 4)
            from methodfactory.storage.sqlite import open_database
            with self.assertRaises(MethodFactoryError):
                open_database(root, read_only=False)

    def test_missing_db_surfaces_typed(self):
        from methodfactory.storage.sqlite import open_database
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(MethodFactoryError):
                open_database(Path(td), read_only=True)

    def test_legacy_surfaces_typed(self):
        from methodfactory.storage.sqlite import open_database
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ("packages", "events", "artifacts"):
                (root / d).mkdir()
            with self.assertRaises(MethodFactoryError):
                open_database(root, read_only=False)


if __name__ == "__main__":
    unittest.main()
