"""Typed storage/schema errors with stable machine-readable codes.

Extends the ADR-0008 stable error-code table for the storage layer
(ADR-0012 §B, §D, §E, §G). Codes are part of the public contract.
"""

from __future__ import annotations

from typing import Any, Optional


class StorageError(Exception):
    """Base for all storage-layer failures."""

    code = "STORAGE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        package_id: Optional[str] = None,
        **context: Any,
    ) -> None:
        super().__init__(message)
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
