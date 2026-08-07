"""Store-root, package-id, identifier, and logical-path validation.

Centralized validation (ADR-0012 §4, §D; Finding 3 item 4) so reusable
package/identifier/path rules cannot drift across modules. `validate_logical_path`
enforces the strict logical-path grammar:

- relative only (absolute paths, drive letters rejected);
- '/' separators only (backslash rejected);
- no '.' / '..' segments, no empty prohibited segments;
- no percent-encoding, no control characters;
- length capped by MAX_LOGICAL_PATH_CHARS (characters).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..domain.errors import InvalidPayloadError
from .errors import InvalidPackageIdError, InvalidStoreRootError
from .limits import MAX_ID_CHARS, MAX_LOGICAL_PATH_CHARS
from .serialization import contains_control_chars  # noqa: F401  (re-export for convenience)

PACKAGE_ID_RE = re.compile(r"^pkg_[A-Za-z0-9_-]{1,63}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,%d}$" % MAX_ID_CHARS)

# Canonical physical database filename (ADR-0012 §D).
DB_FILENAME = "methodfactory.sqlite3"

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")

LOGICAL_PATH_BLOCKED_SEGMENTS = frozenset({"..", "."})


def validate_package_id(package_id: str) -> str:
    """Validate a package identifier against the canonical pattern. Rejects
    path separators, traversal, and non-string values by construction."""
    if not isinstance(package_id, str) or not PACKAGE_ID_RE.match(package_id):
        raise InvalidPackageIdError(f"invalid package_id {package_id!r}")
    return package_id


def validate_identifier(value: str, *, field: str) -> str:
    """Validate a short identifier (input_id / artifact_id / operator_id /
    kind) against the shared pattern (Finding 3 item 4)."""
    if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
        raise InvalidPayloadError(f"{field} invalid: {value!r}")
    return value


def validate_logical_path(logical_path: str) -> str:
    """Validate an artifact logical path (strict grammar, Finding 3 item 3).

    Raises InvalidPayloadError (a public MethodFactoryError) on:
    - empty value or non-string;
    - absolute path (leading '/') or Windows drive/backslash form;
    - backslash separators (must be '/');
    - '.' / '..' segments;
    - empty segments where prohibited (consecutive slashes);
    - percent-encoding;
    - control characters (C0/C1/DEL/U+2028/U+2029, bidi/format, lone surrogates);
    - length > MAX_LOGICAL_PATH_CHARS (characters).
    """
    if not isinstance(logical_path, str):
        raise InvalidPayloadError("logical_path must be a string")
    if not logical_path:
        raise InvalidPayloadError("logical_path is empty")
    if logical_path.startswith("/") or logical_path.startswith("\\"):
        raise InvalidPayloadError(f"logical_path must be relative: {logical_path!r}")
    if _WINDOWS_DRIVE_RE.match(logical_path):
        raise InvalidPayloadError(f"logical_path must be relative: {logical_path!r}")
    if "\\" in logical_path:
        raise InvalidPayloadError(f"logical_path must use '/' separators: {logical_path!r}")
    if "%" in logical_path:
        raise InvalidPayloadError(f"logical_path must not contain percent-encoding: {logical_path!r}")
    if contains_control_chars(logical_path):
        raise InvalidPayloadError(f"logical_path must not contain control characters: {logical_path!r}")
    parts = logical_path.split("/")
    if any(p in LOGICAL_PATH_BLOCKED_SEGMENTS for p in parts):
        raise InvalidPayloadError(f"logical_path contains blocked segment: {logical_path!r}")
    if any(not p for p in parts):
        raise InvalidPayloadError(f"logical_path contains empty segment: {logical_path!r}")
    if len(logical_path) > MAX_LOGICAL_PATH_CHARS:
        raise InvalidPayloadError(
            f"logical_path exceeds {MAX_LOGICAL_PATH_CHARS} chars"
        )
    return logical_path


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
