"""Canonical serialization and digest helpers (ADR-0004)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> bytes:
    """Canonical byte form: sorted keys, compact separators, ASCII-escaped."""
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest_text(content: str) -> str:
    return digest_bytes(content.encode("utf-8"))


def digest_json(data: Any) -> str:
    return digest_bytes(canonical_json(data))


def utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
