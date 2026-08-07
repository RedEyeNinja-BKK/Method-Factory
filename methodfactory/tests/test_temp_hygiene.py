"""Temp-leak hygiene proof (senior review 4882624484, A4).

The affected test suites (test_sqlite_open, test_public_error_boundary)
previously created unmanaged temporary stores via ``tempfile.mkdtemp()`` that
leaked as ``/tmp/tmp*/methodfactory.sqlite3`` on the host. All unmanaged temp
stores are now deterministic-cleanup (``TemporaryDirectory`` /
``addCleanup``).

This proof is BEHAVIORAL and ISOLATED: it runs the corrected affected suites
in a SUBPROCESS whose TMPDIR points at a dedicated empty directory, then
asserts that NO Method Factory SQLite store survives anywhere under that
isolated root. A dedicated temp root avoids host-wide snapshot races (parallel
CI shards) and process-global state coupling; scanning the isolated root with
``rglob`` also covers nested store directories.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.paths import DB_FILENAME

# The suites that previously used unmanaged tempfile.mkdtemp() stores.
AFFECTED_SUITES = [
    "methodfactory.tests.test_sqlite_open",
    "methodfactory.tests.test_public_error_boundary",
]


class TempLeakHygieneProof(unittest.TestCase):
    def test_affected_suites_leave_no_mf_stores(self):
        with tempfile.TemporaryDirectory() as isolated:
            # The nested suites inherit a dedicated, empty temp root.
            env = dict(os.environ)
            env["TMPDIR"] = isolated
            env["TEMP"] = isolated
            env["TMP"] = isolated

            result = subprocess.run(
                [sys.executable, "-m", "unittest", *AFFECTED_SUITES],
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"affected suites failed:\n{result.stdout}\n{result.stderr}",
            )

            leftovers = list(Path(isolated).rglob(DB_FILENAME))
            self.assertEqual(
                leftovers,
                [],
                f"corrected suites leaked MF temp stores: {[str(p) for p in leftovers]}",
            )


if __name__ == "__main__":
    unittest.main()
