"""Storage layer — protocol, canonical primitives, limits, and SQLite schema.

Phase 2 (ADR-0012 commits 2–4). The transactional store, migration, and export
are implemented in later commits; this package carries the storage-independent
contracts and the SQLite schema creation/identity/append-only guards.
"""

from .errors import (
    ActionIdConflictError,
    AppendOnlyViolationError,
    DatabaseEmptyError,
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    InvalidPackageIdError,
    InvalidStoreRootError,
    LegacyStoreDetectedError,
    SchemaViolationError,
    StorageError,
    UnsupportedSchemaError,
)
from .limits import (
    MAX_ACTION_JSON_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_INTENT_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_OUTCOMES,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
)
from .paths import DB_FILENAME, database_path, validate_package_id, validate_store_root
from .protocol import ManifestStore
from .serialization import (
    action_sha256,
    canonical_bytes,
    canonical_json,
    digest_bytes,
    digest_json,
    digest_text,
    sha256_hex,
)

__all__ = [
    "ActionIdConflictError",
    "AppendOnlyViolationError",
    "DB_FILENAME",
    "DatabaseEmptyError",
    "DatabaseIdMismatchError",
    "DatabaseNotFoundError",
    "InvalidPackageIdError",
    "InvalidStoreRootError",
    "LegacyStoreDetectedError",
    "ManifestStore",
    "MAX_ACTION_JSON_BYTES",
    "MAX_ARTIFACT_BYTES",
    "MAX_CONTENT_CHARS",
    "MAX_ENVELOPE_BYTES",
    "MAX_ID_CHARS",
    "MAX_INTENT_CHARS",
    "MAX_LOGICAL_PATH_CHARS",
    "MAX_MANIFEST_BYTES",
    "MAX_OUTCOMES",
    "MAX_REASON_CHARS",
    "MAX_STATEMENT_CHARS",
    "SchemaViolationError",
    "StorageError",
    "UnsupportedSchemaError",
    "action_sha256",
    "canonical_bytes",
    "canonical_json",
    "database_path",
    "digest_bytes",
    "digest_json",
    "digest_text",
    "sha256_hex",
    "validate_package_id",
    "validate_store_root",
]
