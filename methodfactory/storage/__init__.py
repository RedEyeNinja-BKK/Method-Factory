"""Storage layer — protocol, canonical primitives, limits, and SQLite schema.

Phase 2 (ADR-0012 commits 2–4) established the storage-independent contracts
and SQLite schema creation/identity/append-only guards. The transactional
store, deterministic migration, and exports are implemented in
`storage.store`, `migrations.migrate`, and `migrations.export`.
"""

from .errors import (
    ActionIdConflictError,
    AppendOnlyViolationError,
    ArtifactVerificationError,
    ChainViolationError,
    DatabaseEmptyError,
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    DestinationExistsError,
    InvalidPackageIdError,
    InvalidStoreRootError,
    LegacyChainInvalidError,
    LegacySourceInvalidError,
    LegacyStoreDetectedError,
    ManifestInvalidError,
    MigrationIncompatibleError,
    MigrationPublishFailedError,
    PackageNotFoundError,
    SchemaViolationError,
    SerializationError,
    SourceChangedError,
    StorageError,
    UnsupportedSchemaError,
)
from ..domain.errors import MethodFactoryError
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
from .store import SqliteManifestStore

__all__ = [
    "ActionIdConflictError",
    "AppendOnlyViolationError",
    "ArtifactVerificationError",
    "ChainViolationError",
    "DB_FILENAME",
    "DatabaseEmptyError",
    "DatabaseIdMismatchError",
    "DatabaseNotFoundError",
    "DestinationExistsError",
    "InvalidPackageIdError",
    "InvalidStoreRootError",
    "LegacyChainInvalidError",
    "LegacySourceInvalidError",
    "LegacyStoreDetectedError",
    "ManifestInvalidError",
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
    "MethodFactoryError",
    "MigrationIncompatibleError",
    "MigrationPublishFailedError",
    "PackageNotFoundError",
    "SchemaViolationError",
    "SerializationError",
    "SourceChangedError",
    "SqliteManifestStore",
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
