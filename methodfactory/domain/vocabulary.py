"""Shared contract vocabulary (single source of truth).

These constants are part of the Manifest Contract v0.1 / Action Envelope v0.1
vocabulary. They are imported by both the envelope parser and the manifest
schema so validation boundaries cannot silently diverge (ADR-0004, ADR-0005).
"""

from __future__ import annotations

import re

PACKAGE_ID_RE = re.compile(r"^pkg_[A-Za-z0-9_-]{1,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

INPUT_KINDS = frozenset({"text", "url", "file-reference", "constraint"})
INPUT_SOURCES = frozenset({"operator", "adapter"})
DISPOSITIONS = frozenset({"incorporated", "excluded"})

# ── Size limits (v2.0.0 review remediation; sec-7) ─────────────────────
# Enforced at the envelope parse boundary (fail fast) and in manifest schema
# validation (authoritative for on-disk manifests). Envelope payloads are
# bounded so an untrusted transport cannot exhaust memory or bloat journals.
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024      # raw envelope byte cap
MAX_CONTENT_CHARS = 1_048_576             # record_input / record_draft_artifact content
MAX_INTENT_CHARS = 65_536                 # create_package intent.raw
MAX_STATEMENT_CHARS = 16_384              # set_objective statement / outcome
MAX_OUTCOMES = 100                        # desired_outcomes list length
MAX_ID_CHARS = 128                        # input_id / artifact_id / operator_id / kind
MAX_LOGICAL_PATH_CHARS = 255              # artifact logical_path
MAX_REASON_CHARS = 1024                   # exclusion_reason / cancel reason


def contains_control_chars(value: str) -> bool:
    """True if the string contains C0/C1 control characters (incl. NUL, ESC,
    and the Unicode line/paragraph separators that are JSON-safe but
    dangerous in terminal/line contexts)."""
    for ch in value:
        code = ord(ch)
        if code < 0x20 or (0x7F <= code <= 0x9F):
            return True
        if ch in "\u2028\u2029\u0085":
            return True
    return False
