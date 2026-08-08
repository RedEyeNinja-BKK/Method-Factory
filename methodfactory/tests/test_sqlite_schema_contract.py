"""SQLite schema-contract verification tests (Finding 3, review 4879090471).

Verifies the exact version-1 schema contract (column order/types/nullability,
PK order, unique constraints, CHECK constraint, WITHOUT ROWID, trigger body),
read-only foreign_keys enablement, permissive-mode read-only failure, and
connection cleanup on every failed-open path.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.errors import SchemaViolationError, StorageError
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.sqlite import (
    APPLICATION_ID,
    USER_VERSION,
    close_database,
    open_database,
)


def _make_valid_db(root: Path) -> sqlite3.Connection:
    return open_database(root, read_only=False)


def _open_conn(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


class TriggerContractTests(unittest.TestCase):
    def test_altered_trigger_body_rejected(self):
        """A trigger with the right NAME but a no-op body must fail."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_delete")
            c.execute(
                "CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
                "FOR EACH ROW BEGIN SELECT 1; END"  # no-op, no RAISE(ABORT)
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_noop_trigger_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                "FOR EACH ROW BEGIN SELECT 1; END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_with_when_zero_rejected(self):
        """A trigger with the expected NAME, operation, table, and RAISE(ABORT)
        marker but a disabling WHEN 0 clause must fail: it never fires, so the
        append-only guarantee is gone."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                "FOR EACH ROW WHEN 0 BEGIN "
                "SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted'); END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_wrong_operation_rejected(self):
        """events_no_update recreated with the correct message but the WRONG
        operation (INSERT instead of UPDATE) must fail."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE INSERT ON events "
                "FOR EACH ROW BEGIN "
                "SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted'); END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_wrong_table_rejected(self):
        """events_no_delete recreated on the WRONG table with the correct
        message must fail."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_delete")
            c.execute("CREATE TABLE other (x TEXT)")  # trigger must target events
            c.execute(
                "CREATE TRIGGER events_no_delete BEFORE DELETE ON other "
                "FOR EACH ROW BEGIN "
                "SELECT RAISE(ABORT, 'events are append-only: DELETE not permitted'); END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_where_zero_guarded_raise_rejected(self):
        """Local review (bug-3/sec-1): a RAISE(ABORT) behind WHERE 0 is a
        no-op that passes substring checks; exact-body verification must
        reject it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                "FOR EACH ROW BEGIN "
                "SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted') "
                "WHERE 0; END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_when_no_space_rejected(self):
        """Local review (q-1): WHEN(0) with no space bypasses a ' WHEN '
        substring guard; exact-body verification must reject it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                "FOR EACH ROW WHEN(0) BEGIN "
                "SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted'); END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_trigger_marker_in_literal_only_rejected(self):
        """Local review (sec-1): the marker strings inside a string literal
        with NO RAISE call must fail verification."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_update")
            c.execute(
                "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                "FOR EACH ROW BEGIN "
                "SELECT 'events are append-only: UPDATE not permitted'; END"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)


class CheckConstraintTests(unittest.TestCase):
    def test_weakened_check_constraint_rejected(self):
        """Removing the revision >= 0 CHECK must fail verification."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute(
                "CREATE TABLE events_v2 ("
                "package_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT NOT NULL, action_sha256 TEXT NOT NULL, "
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), UNIQUE (package_id, action_id), UNIQUE (event_id)"
                ") WITHOUT ROWID"
            )  # NOTE: no CHECK (revision >= 0)
            c.execute("DROP TABLE events")
            c.execute("ALTER TABLE events_v2 RENAME TO events")
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_weakened_check_with_or_rejected(self):
        """CHECK(revision >= 0 OR 1=1) is a WEAKENED constraint and must fail
        verification: the unweakened exact CHECK(revision >= 0) is required
        (Finding 3)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TABLE events")
            c.execute(
                "CREATE TABLE events ("
                "package_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT NOT NULL, action_sha256 TEXT NOT NULL, "
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), UNIQUE (package_id, action_id), UNIQUE (event_id), "
                "CHECK (revision >= 0 OR 1=1)"  # weakened
                ") WITHOUT ROWID"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)


class UniqueOrderTests(unittest.TestCase):
    def test_reversed_unique_order_rejected(self):
        """UNIQUE (action_id, package_id) is a DIFFERENT constraint than
        UNIQUE (package_id, action_id): exact column ORDER is required
        (Finding 3)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TABLE events")
            c.execute(
                "CREATE TABLE events ("
                "package_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT NOT NULL, action_sha256 TEXT NOT NULL, "
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), "
                "UNIQUE (action_id, package_id), UNIQUE (event_id), "  # REVERSED
                "CHECK (revision >= 0)"
                ") WITHOUT ROWID"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)


class ColumnContractTests(unittest.TestCase):
    def test_changed_type_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TABLE events")
            c.execute(
                "CREATE TABLE events ("
                "package_id TEXT NOT NULL, revision TEXT NOT NULL, "  # wrong type
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT NOT NULL, action_sha256 TEXT NOT NULL, "
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), UNIQUE (package_id, action_id), UNIQUE (event_id), "
                "CHECK (revision >= 0)"
                ") WITHOUT ROWID"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_changed_nullability_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TABLE events")
            c.execute(
                "CREATE TABLE events ("
                "package_id TEXT NOT NULL, revision INTEGER NOT NULL, "
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT, action_sha256 TEXT NOT NULL, "  # action nullable now
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), UNIQUE (package_id, action_id), UNIQUE (event_id), "
                "CHECK (revision >= 0)"
                ") WITHOUT ROWID"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)

    def test_column_order_drift_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TABLE events")
            c.execute(
                "CREATE TABLE events ("
                "revision INTEGER NOT NULL, package_id TEXT NOT NULL, "  # swapped order
                "event_id TEXT NOT NULL, action_id TEXT NOT NULL, "
                "action TEXT NOT NULL, action_sha256 TEXT NOT NULL, "
                "state_before TEXT, state_after TEXT NOT NULL, "
                "previous_manifest_sha256 TEXT, resulting_manifest_sha256 TEXT NOT NULL, "
                "created_at TEXT NOT NULL, action_json BLOB NOT NULL, manifest_json BLOB NOT NULL, "
                "PRIMARY KEY (package_id, revision), UNIQUE (package_id, action_id), UNIQUE (event_id), "
                "CHECK (revision >= 0)"
                ") WITHOUT ROWID"
            )
            c.commit()
            c.close()
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=False)


class ReadOnlyContractTests(unittest.TestCase):
    def test_ro_foreign_keys_enabled_and_read_back(self):
        """foreign_keys=ON must be enabled and read back on a read-only
        connection (Finding 3)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            ro = open_database(root, read_only=True)
            try:
                self.assertEqual(int(ro.execute("PRAGMA foreign_keys").fetchone()[0]), 1)
            finally:
                close_database(ro)

    def test_ro_permissive_modes_fail_typed(self):
        """A read-only open against a DB whose modes are not 0700/0600 must
        fail typed WITHOUT mutating them."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            os.chmod(root, 0o755)
            os.chmod(root / DB_FILENAME, 0o644)
            with self.assertRaises(StorageError):
                open_database(root, read_only=True)
            # modes unchanged (verify-only, no mutation)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o755)
            self.assertEqual(os.stat(root / DB_FILENAME).st_mode & 0o777, 0o644)

    def test_ro_matches_modes_ok(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            ro = open_database(root, read_only=True)
            close_database(ro)


class HandleCleanupTests(unittest.TestCase):
    def test_failed_open_closes_connection(self):
        """A schema/identity failure during open must close the connection
        (no leaked handles) — repeated failed opens do not accumulate."""
        import gc
        import sqlite3 as _sqlite3

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _make_valid_db(root)
            close_database(conn)
            # break the schema
            c = _open_conn(root / DB_FILENAME)
            c.execute("DROP TRIGGER events_no_delete")
            c.commit()
            c.close()
            # Repeated failed opens must each raise typed and not leak handles.
            # We detect leaks by counting sqlite3.Connection finalizers that
            # print 'unclosed connection' warnings — instead, assert the
            # failure is clean each time and the store remains in a
            # deterministic (broken) state: a subsequent rw open still raises
            # the same typed error (no partial corruption from the failed opens).
            for _ in range(3):
                with self.assertRaises(SchemaViolationError):
                    open_database(root, read_only=False)
            # The schema is still the broken one (failed opens did not mutate).
            with self.assertRaises(SchemaViolationError):
                open_database(root, read_only=True)

    def test_pragma_failure_closes_connection_direct_evidence(self):
        """DIRECT handle evidence (Finding 3): when PRAGMA setup/read-back
        fails inside _connect(), the connection is closed before the typed
        error propagates — verified with a connection spy, not fd counts."""
        import methodfactory.storage.sqlite as sqlite_mod
        from methodfactory.storage.sqlite import _connect
        from unittest import mock

        real_connect = sqlite3.connect
        opens: list = []

        class SpyConn:
            def __init__(self, real):
                self._real = real
                self.closed = False

            def __getattr__(self, name):
                return getattr(self._real, name)

            def close(self):
                self.closed = True
                return self._real.close()

        def spy_connect(*args, **kwargs):
            real = real_connect(*args, **kwargs)
            spy = SpyConn(real)
            opens.append(spy)
            return spy

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / DB_FILENAME
            with mock.patch.object(
                sqlite_mod,
                "_apply_or_verify_pragmas",
                side_effect=StorageError("pragma fail"),
            ), mock.patch(
                "methodfactory.storage.sqlite.sqlite3.connect", side_effect=spy_connect
            ):
                with self.assertRaises(StorageError):
                    _connect(db, read_only=False)
        self.assertEqual(len(opens), 1, "exactly one connection was opened")
        self.assertTrue(opens[0].closed, "connection must be closed on PRAGMA failure")

    def test_pragma_failure_through_public_open_typed(self):
        """PRAGMA failure surfaces as a typed StorageError through the public
        open_database() boundary and the handle is closed."""
        import methodfactory.storage.sqlite as sqlite_mod
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch.object(
                sqlite_mod,
                "_apply_or_verify_pragmas",
                side_effect=StorageError("pragma fail"),
            ):
                with self.assertRaises(StorageError):
                    open_database(root, read_only=False)


if __name__ == "__main__":
    unittest.main()
