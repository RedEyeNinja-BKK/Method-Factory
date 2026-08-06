"""Canonical serialization and hash primitives (ADR-0012 §4, §G).

Canonical JSON bytes are produced exactly as:

    json.dumps(value, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False, allow_nan=False).encode("utf-8")

and those bytes are what is hashed. `action_sha256` is the frozen semantic
action hash (ADR-0012 §G).
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
    action: str,
    package_id: str,
    action_id: str,
    basis: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    """Canonical semantic action hash (ADR-0012 §G).

    Hashes the complete normalized semantic request used for idempotency:
    {action, package_id, action_id, basis, payload}. Every field that could
    change the requested outcome is included. Only `expected_revision`
    (optimistic-concurrency/transport metadata) is excluded — it is not part
    of the requested outcome, so a retry with an updated revision and the
    same action_id yields the same hash and replays.
    """
    return digest_json(
        {
            "action": action,
            "package_id": package_id,
            "action_id": action_id,
            "basis": basis,
            "payload": payload,
        }
    )
