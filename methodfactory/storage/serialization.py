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

from .errors import SerializationError
from .limits import MAX_ACTION_JSON_BYTES


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


def canonical_bytes_bounded(value: Any, *, limit: int, what: str) -> bytes:
    """Canonicalize and enforce a BYTE bound on the canonical bytes.

    Raises ValueError (translated at the public boundary) when the canonical
    UTF-8 bytes exceed ``limit``. Used by action canonicalization and manifest
    validation so the exact accepted bytes are hashed/validated (Finding 1).
    """
    raw = canonical_bytes(value)
    if len(raw) > limit:
        raise ValueError(f"{what} exceeds {limit} bytes (got {len(raw)})")
    return raw


def try_canonical_bytes_bounded(value: Any, *, limit: int, what: str) -> tuple[bytes | None, str | None]:
    """Canonicalize with full native-failure translation (Finding 1 item 4).

    Returns (bytes, None) on success or (None, error_message) when the value
    cannot be canonicalized: unsupported JSON types, excessive recursion, or
    lone-surrogate UnicodeEncodeError are all captured as a message rather
    than leaking raw TypeError/RecursionError/UnicodeEncodeError.
    """
    try:
        raw = canonical_bytes(value)
    except (TypeError, RecursionError, UnicodeEncodeError, ValueError) as exc:
        return None, f"{what} cannot be canonicalized: {exc}"
    if len(raw) > limit:
        return None, f"{what} exceeds {limit} bytes (got {len(raw)})"
    return raw, None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_bytes(data: bytes) -> str:
    return sha256_hex(data)


def digest_text(content: str) -> str:
    return sha256_hex(content.encode("utf-8"))


def digest_json(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def contains_control_chars(value: str) -> bool:
    """True if the string contains C0/C1 control characters (incl. NUL, ESC),
    Unicode line/paragraph separators, lone surrogates, or format/bidi
    controls (JSON-safe but dangerous in terminal/line/path contexts)."""
    for ch in value:
        code = ord(ch)
        if code < 0x20 or (0x7F <= code <= 0x9F):
            return True
        if 0xD800 <= code <= 0xDFFF:  # lone surrogates
            return True
        if ch in "\u2028\u2029\u0085":
            return True
        if 0x200B <= code <= 0x200F or 0x202A <= code <= 0x202E or 0x2060 <= code <= 0x206F:
            return True  # bidi/format controls
        if code == 0x061C or code == 0x00AD:
            return True
    return False


def action_sha256(
    *,
    protocol_version: str,
    action: str,
    package_id: str,
    action_id: str,
    basis: dict[str, Any],
    payload: dict[str, Any],
) -> str:
    """Canonical semantic action hash (ADR-0012 §G, Finding 1).

    Hashes the complete normalized semantic request used for idempotency:
    {protocol_version, action, package_id, action_id, basis, payload}.

    - `protocol_version` is INCLUDED (a protocol change can alter the meaning
      of an action request).
    - `expected_revision` is the ONLY excluded envelope field (it is
      optimistic-concurrency/transport metadata, not part of the requested
      outcome, so a retry with an updated revision and the same action_id
      yields the same hash and replays).

    The normalized semantic action is canonicalized ONCE, enforced against
    MAX_ACTION_JSON_BYTES, and hashed from those exact accepted bytes.

    Public error boundary (Finding 4): every native failure — unsupported
    JSON types, excessive recursion, lone-surrogate encoding, and canonical
    byte overflow — is translated into SerializationError (a public
    MethodFactoryError with code SERIALIZATION); no raw
    TypeError/RecursionError/UnicodeEncodeError/ValueError escapes.
    """
    semantic = {
        "protocol_version": protocol_version,
        "action": action,
        "package_id": package_id,
        "action_id": action_id,
        "basis": basis,
        "payload": payload,
    }
    try:
        canonical = canonical_bytes_bounded(
            semantic,
            limit=MAX_ACTION_JSON_BYTES,
            what="canonical action",
        )
    except (TypeError, RecursionError, UnicodeEncodeError, ValueError) as exc:
        raise SerializationError(f"cannot canonicalize action: {exc}") from exc
    return sha256_hex(canonical)
