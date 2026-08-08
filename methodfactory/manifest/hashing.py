"""Canonical serialization and digest helpers (ADR-0004, superseded by ADR-0012).

This module is a LEGACY-SCOPED re-export of the single canonical
implementation in `methodfactory.storage.serialization`. The former
ASCII-escaped (`ensure_ascii=True`) canonical form was removed to guarantee
that every import path hashes the same UTF-8 canonical bytes (Finding 2
item 1). New code should import from `methodfactory.storage.serialization`
or the package root; this module exists for backward-compatible imports only.
"""

from __future__ import annotations

from ..storage.serialization import (
    canonical_bytes,
    canonical_json,
    digest_bytes,
    digest_json,
    digest_text,
    sha256_hex,
)

__all__ = [
    "canonical_bytes",
    "canonical_json",
    "digest_bytes",
    "digest_json",
    "digest_text",
    "sha256_hex",
]
