"""Store-root and package-id path validation tests (ADR-0012 §D)."""

from __future__ import annotations

import unittest
from pathlib import Path

from methodfactory.storage.errors import InvalidPackageIdError, InvalidStoreRootError
from methodfactory.storage.paths import (
    DB_FILENAME,
    database_path,
    validate_package_id,
    validate_store_root,
)


class PackageIdValidationTests(unittest.TestCase):
    def test_accepts_valid_ids(self):
        for pid in ("pkg_demo_001", "pkg_a", "pkg_x-y_9"):
            self.assertEqual(validate_package_id(pid), pid)

    def test_rejects_invalid_ids(self):
        for pid in (
            "../evil",
            "core",
            "pkg",           # too short after prefix
            "pkg_" + "x" * 64,  # too long
            "pkg/a/b",
            "pkg with space",
            "",
            None,
            123,
        ):
            with self.subTest(pid=pid):
                with self.assertRaises(InvalidPackageIdError):
                    validate_package_id(pid)  # type: ignore[arg-type]


class StoreRootValidationTests(unittest.TestCase):
    def test_database_path_is_beneath_root(self):
        root = Path("/tmp/mf-store-test")
        self.assertEqual(database_path(root), root / DB_FILENAME)
        self.assertEqual(DB_FILENAME, "methodfactory.sqlite3")

    def test_empty_root_rejected(self):
        with self.assertRaises(InvalidStoreRootError):
            validate_store_root("")

    def test_file_root_rejected(self):
        import tempfile

        with tempfile.NamedTemporaryFile() as fh:
            with self.assertRaises(InvalidStoreRootError):
                validate_store_root(Path(fh.name))

    def test_directory_root_accepted(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(validate_store_root(Path(td)), Path(td))


if __name__ == "__main__":
    unittest.main()
