"""Store-root and package-id path validation (ADR-0012 §4, §D)."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import InvalidPackageIdError, InvalidStoreRootError

PACKAGE_ID_RE = re.compile(r"^pkg_[A-Za-z0-9_-]{1,63}$")

# Canonical physical database filename (ADR-0012 §D).
DB_FILENAME = "methodfactory.sqlite3"


def validate_package_id(package_id: str) -> str:
    """Validate a package identifier against the canonical pattern. Rejects
    path separators, traversal, and non-string values by construction."""
    if not isinstance(package_id, str) or not PACKAGE_ID_RE.match(package_id):
        raise InvalidPackageIdError(f"invalid package_id {package_id!r}")
    return package_id


def validate_store_root(root: Path | str) -> Path:
    """Normalize and validate the store root. It must be a non-empty path;
    if it exists it must be a directory (a file at the root is unusable)."""
    if isinstance(root, str) and not root.strip():
        raise InvalidStoreRootError("store root must not be empty")
    p = Path(root)
    if p.exists() and not p.is_dir():
        raise InvalidStoreRootError(f"store root exists but is not a directory: {p}")
    return p


def database_path(root: Path | str) -> Path:
    """Canonical SQLite database location: <store_root>/methodfactory.sqlite3."""
    return validate_store_root(root) / DB_FILENAME
