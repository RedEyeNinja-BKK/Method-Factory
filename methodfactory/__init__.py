"""methodfactory — deterministic package-lifecycle engine (persistence reset).

Phase 2 corrections (Finding 2): the package root now re-exports the SINGLE
canonical serialization implementation from storage.serialization (the legacy
ensure_ascii=True variant is removed/legacy-scoped in manifest/hashing.py).
"""

__version__ = "2.0.0a1"

# Reusable foundation (ADR-0012 §8 port list). Canonical serialization is the
# single storage-layer implementation; manifest.hashing re-exports it.
from .adapters.artifact_store import ArtifactStore  # noqa: F401
from .domain.errors import MethodFactoryError  # noqa: F401
from .manifest.hashing import canonical_bytes, canonical_json, digest_bytes, digest_json, digest_text  # noqa: F401
from .manifest.schema import new_manifest, validate_manifest  # noqa: F401
from .protocol.envelope import ActionEnvelope, parse_envelope  # noqa: F401
from .storage.errors import StorageError  # noqa: F401
from .storage.serialization import action_sha256  # noqa: F401
