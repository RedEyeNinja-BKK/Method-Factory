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
    code = "ACTION_ID_REUSE"


class InvalidPayloadError(MethodFactoryError):
    code = "INVALID_PAYLOAD"


class ManifestInvalidError(MethodFactoryError):
    code = "MANIFEST_INVALID"


class DuplicatePackageError(MethodFactoryError):
    code = "PACKAGE_EXISTS"


class ConcurrencyError(MethodFactoryError):
    code = "CONCURRENCY"


class FileIoError(MethodFactoryError):
    """Stable CLI/IO error — reading or writing a file failed (ADR-0008)."""

    code = "FILE_IO"


class NoSummaryError(MethodFactoryError):
    """A summary has not been prepared for the package."""

    code = "NO_SUMMARY"
