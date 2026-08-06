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
