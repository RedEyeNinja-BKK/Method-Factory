"""Append-only guard tests (ADR-0012 §E): UPDATE/DELETE rejected by triggers."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.sqlite import close_database, open_database


def make_event(package_id="pkg_demo_001", revision=0, action_id="act_1"):
    return (
        package_id,
        revision,
        f"evt_{package_id}_{revision}",
        action_id,
        "create_package",
        "0" * 64,
        None,
        "INTAKE",
        None,
        "0" * 64,
        "2026-08-07T00:00:00+00:00",
        b'{"action":"create_package"}',
        b'{"schema_version":"0.1"}',
    )


INSERT_EVENT_SQL = """
INSERT INTO events (
    package_id, revision, event_id, action_id, action, action_sha256,
    state_before, state_after, previous_manifest_sha256,
    resulting_manifest_sha256, created_at, action_json, manifest_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class AppendOnlyTests(unittest.TestCase):
    def _db(self, td):
        root = Path(td)
        conn = open_database(root, read_only=False)
        return root, conn

    def test_insert_works(self):
        with tempfile.TemporaryDirectory() as td:
            _, conn = self._db(td)
            try:
                conn.execute(INSERT_EVENT_SQL, make_event())
                conn.commit()
                n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                self.assertEqual(n, 1)
            finally:
                close_database(conn)

    def test_update_rejected_by_trigger(self):
        with tempfile.TemporaryDirectory() as td:
            _, conn = self._db(td)
            try:
                conn.execute(INSERT_EVENT_SQL, make_event())
                conn.commit()
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute(
                        "UPDATE events SET state_after = 'CANCELLED' WHERE package_id = 'pkg_demo_001'"
                    )
                self.assertIn("append-only", str(ctx.exception).lower())
            finally:
                close_database(conn)

    def test_delete_rejected_by_trigger(self):
        with tempfile.TemporaryDirectory() as td:
            _, conn = self._db(td)
            try:
                conn.execute(INSERT_EVENT_SQL, make_event())
                conn.commit()
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    conn.execute("DELETE FROM events WHERE package_id = 'pkg_demo_001'")
                self.assertIn("append-only", str(ctx.exception).lower())
            finally:
                close_database(conn)

    def test_primary_key_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, conn = self._db(td)
            try:
                conn.execute(INSERT_EVENT_SQL, make_event())
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(INSERT_EVENT_SQL, make_event(revision=0, action_id="act_2"))
                conn.rollback()
            finally:
                close_database(conn)

    def test_action_id_unique_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            _, conn = self._db(td)
            try:
                conn.execute(INSERT_EVENT_SQL, make_event(revision=0))
                with self.assertRaises(sqlite3.IntegrityError):
                    conn.execute(INSERT_EVENT_SQL, make_event(revision=1, action_id="act_1"))
                conn.rollback()
            finally:
                close_database(conn)


if __name__ == "__main__":
    unittest.main()
