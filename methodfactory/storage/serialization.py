"""Canonical serialization and digest helpers (ADR-0012 §4, §G).

This is the SINGLE authoritative canonical JSON byte implementation for
Method Factory. The legacy ASCII-escaped variant in manifest/hashing.py is
removed/redirected here so manifest, action, event, migration/export
preparation, artifact metadata, and package-level exports all hash the same
bytes regardless of import path (Finding 2 item 1).

Canonical JSON bytes:

    json.dumps(value, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False, allow_nan=False).encode("utf-8")
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, compact separators, UTF-8-safe,
    no NaN/Infinity (raises ValueError on non-finite numbers)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """The canonical byte form that is hashed (ADR-0012 §4)."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_bytes(data: bytes) -> str:
    return sha256_hex(data)


def digest_text(content: str) -> str:
    return sha256_hex(content.encode("utf-8"))


def digest_json(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def action_sha256(
    *,
    protocol_version: str,
    action: str,
    package_id: str,
    action_id: str,
    basis: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    """Canonical semantic action hash (ADR-0012 §G, Finding 2 item 2).

    Hashes the complete normalized semantic request used for idempotency:
    {protocol_version, action, package_id, action_id, basis, payload}.

    - `protocol_version` is INCLUDED (a protocol change can alter the meaning
      of an action request).
    - `expected_revision` is the ONLY excluded envelope field (it is
      optimistic-concurrency/transport metadata, not part of the requested
      outcome, so a retry with an updated revision and the same action_id
      yields the same hash and replays).
    """
    return digest_json(
        {
            "protocol_version": protocol_version,
            "action": action,
            "package_id": package_id,
            "action_id": action_id,
            "basis": basis,
            "payload": payload,
        }
    )
