"""methodfactory — deterministic package-lifecycle engine (persistence reset).

Phase 2 foundation: storage-independent domain/protocol/adapters plus the
storage protocol and SQLite schema primitives. The JSONL-era store and engine
are NOT ported (ADR-0012 §8). Version follows the 2.0.0 prerelease ladder.
"""

__version__ = "2.0.0a1"

# Reusable foundation (ADR-0012 §8 port list). Deliberately does not import the
# JSONL store or the lifecycle engine (removed in the persistence reset).
from .adapters.artifact_store import ArtifactStore  # noqa: F401
from .manifest.hashing import canonical_json, digest_bytes, digest_json, digest_text  # noqa: F401
from .manifest.schema import new_manifest, validate_manifest  # noqa: F401
from .protocol.envelope import ActionEnvelope, parse_envelope  # noqa: F401
