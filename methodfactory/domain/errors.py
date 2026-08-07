"""Error hierarchy with stable machine-readable codes (ADR-0008)."""

from __future__ import annotations

from typing import Any, Optional


class MethodFactoryError(Exception):
    code = "MF_ERROR"

    def __init__(
        self,
        message: str,
        *,
        package_id: Optional[str] = None,
        state: Optional[str] = None,
        expected_revision: Optional[int] = None,
        actual_revision: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.package_id = package_id
        self.state = state
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.package_id is not None:
            d["package_id"] = self.package_id
        if self.state is not None:
            d["state"] = self.state
        if self.expected_revision is not None:
            d["expected_revision"] = self.expected_revision
        if self.actual_revision is not None:
            d["actual_revision"] = self.actual_revision
        return d


class InvalidEnvelopeError(MethodFactoryError):
    code = "INVALID_ENVELOPE"


class IllegalTransitionError(MethodFactoryError):
    code = "ILLEGAL_TRANSITION"


class GateUnsatisfiedError(MethodFactoryError):
    code = "GATE_UNSATISFIED"


class StaleActionError(MethodFactoryError):
    code = "STALE_ACTION"


class ActionIdReuseError(MethodFactoryError):
    """Legacy JSONL-era action-id reuse conflict (ADR-0008).

    Superseded for the SQLite store by ActionIdConflictError
    (ACTION_ID_CONFLICT). Retained only for legacy-scoped paths; new code must
    raise/import the storage-layer ActionIdConflictError.
    """

    code = "ACTION_ID_REUSE"


class ActionIdConflictError(MethodFactoryError):
    """Canonical SQLite-era action-id conflict (ADR-0012 §G, Finding 2).

    Same action_id reused with a different action_sha256. Supersedes
    ACTION_ID_REUSE.
    """

    code = "ACTION_ID_CONFLICT"


class InvalidPayloadError(MethodFactoryError):
    code = "INVALID_PAYLOAD"


class ManifestInvalidError(MethodFactoryError):
    code = "MANIFEST_INVALID"


class DuplicatePackageError(MethodFactoryError):
    code = "PACKAGE_EXISTS"


class ConcurrencyError(MethodFactoryError):
    code = "CONCURRENCY"
