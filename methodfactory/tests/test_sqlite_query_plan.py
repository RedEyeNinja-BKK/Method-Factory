"""Indexed latest-event query evidence (ADR-0012 §9 item 14).

Asserts the query plan uses the package/revision primary key and does not
scan the complete history — the hot path must stay bounded.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.sqlite import (
    close_database,
    explain_latest_event_plan,
    latest_event,
    open_database,
)


class QueryPlanTests(unittest.TestCase):
    def test_latest_event_plan_uses_primary_key(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_database(Path(td), read_only=False)
            try:
                plan = explain_latest_event_plan(conn, "pkg_demo_001")
                text = " ".join(" ".join(str(c) for c in row) for row in plan)
                self.assertIn("SEARCH events USING", text)
                self.assertNotIn("SCAN events", text)
            finally:
                close_database(conn)

    def test_latest_event_empty_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_database(Path(td), read_only=False)
            try:
                self.assertIsNone(latest_event(conn, "pkg_demo_001"))
            finally:
                close_database(conn)


if __name__ == "__main__":
    unittest.main()
