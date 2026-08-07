"""Typed storage/schema errors with stable machine-readable codes.

Extends the ADR-0008 stable error-code table for the storage layer
(ADR-0012 §B, §D, §E, §G). Codes are part of the public contract.

One public Method Factory error boundary (Finding 2 item 4): storage
failures are catchable through `methodfactory.domain.errors.MethodFactoryError`
or `methodfactory.storage.errors.StorageError` (a subclass), and raw
sqlite3/JSON/Unicode/OS/type exceptions are translated into typed errors at
the public boundary.
"""

from __future__ import annotations

from typing import Any, Optional

from ..domain.errors import MethodFactoryError as _PublicMethodFactoryError


class StorageError(_PublicMethodFactoryError):
    """Base for all storage-layer failures (public boundary: MethodFactoryError)."""

    code = "STORAGE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        package_id: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(message, package_id=package_id)
        self.message = message
        self.package_id = package_id
        self.context = context

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.package_id is not None:
            d["package_id"] = self.package_id
        d.update(self.context)
        return d


class DatabaseNotFoundError(StorageError):
    """No SQLite database exists (and none may be created on this path)."""

    code = "DATABASE_NOT_FOUND"


class DatabaseEmptyError(StorageError):
    """A zero-byte database file exists but carries no identity."""

    code = "DATABASE_EMPTY"


class DatabaseIdMismatchError(StorageError):
    """The database's application_id is not the canonical Method Factory ID."""

    code = "DATABASE_ID_MISMATCH"


class UnsupportedSchemaError(StorageError):
    """The database's user_version is not supported by this build."""

    code = "UNSUPPORTED_SCHEMA"


class LegacyStoreDetectedError(StorageError):
    """A public v0.1.2 JSONL store is present; run `mf migrate-store`."""

    code = "LEGACY_STORE_DETECTED"


class SchemaViolationError(StorageError):
    """A row violates a schema or chain invariant."""

    code = "SCHEMA_VIOLATION"


class AppendOnlyViolationError(StorageError):
    """An attempt to UPDATE or DELETE an immutable event row."""

    code = "APPEND_ONLY_VIOLATION"


class InvalidPackageIdError(StorageError):
    """package_id fails the canonical pattern `^pkg_[A-Za-z0-9_-]{1,63}$`."""

    code = "INVALID_PACKAGE_ID"


class InvalidStoreRootError(StorageError):
    """The store root path is unusable."""

    code = "INVALID_STORE_ROOT"


class ActionIdConflictError(StorageError):
    """Same action_id reused with a different action_sha256 (ADR-0012 §G).

    Supersedes the JSONL-era ACTION_ID_REUSE code for the SQLite store.
    """

    code = "ACTION_ID_CONFLICT"


class ManifestInvalidError(StorageError):
    """A stored manifest BLOB is malformed or invalid UTF-8 (Finding 4)."""

    code = "MANIFEST_INVALID"


class SerializationError(StorageError):
    """A value cannot be canonicalized or exceeds its canonical byte bound.

    Public boundary for action_sha256 (Finding 4): unsupported JSON types,
    excessive recursion, lone-surrogate encoding, and canonical-size overflow
    are all translated into this typed error — never leaked as raw
    TypeError/RecursionError/UnicodeEncodeError/ValueError.
    """

    code = "SERIALIZATION"


class PackageNotFoundError(StorageError):
    """The requested package has no committed events (load/apply on missing)."""

    code = "PACKAGE_NOT_FOUND"


class ArtifactVerificationError(StorageError):
    """A manifest-referenced artifact blob is missing, corrupt, or does not
    match its digest at transaction/chain verification time."""

    code = "ARTIFACT_VERIFICATION"


class ChainViolationError(StorageError):
    """The authoritative revision-chain validator found an invariant violation
    (revision zero rules, lineage, state continuity, digest binding, grammar,
    or referenced-artifact integrity)."""

    code = "CHAIN_VIOLATION"


class LegacySourceInvalidError(StorageError):
    """The legacy v0.1.2 source is unrecognized or unsupported (migration)."""

    code = "LEGACY_SOURCE_INVALID"


class LegacyChainInvalidError(StorageError):
    """The legacy v0.1.2 chain is invalid (migration fails closed)."""

    code = "LEGACY_CHAIN_INVALID"


class MigrationIncompatibleError(StorageError):
    """A legacy semantic action cannot be reconstructed or a public-valid value
    is now current-invalid (migration fails closed; no weakening)."""

    code = "MIGRATION_INCOMPATIBLE"


class SourceChangedError(StorageError):
    """The legacy source changed during migration; publication is refused."""

    code = "SOURCE_CHANGED"


class MigrationPublishFailedError(StorageError):
    """Atomic migration publication failed (rename/fsync/receipt)."""

    code = "MIGRATION_PUBLISH_FAILED"


class DestinationExistsError(StorageError):
    """The migration destination already exists; no overwrite is performed."""

    code = "DESTINATION_EXISTS"
