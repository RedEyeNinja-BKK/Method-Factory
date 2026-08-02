"""methodfactory — deterministic package-lifecycle engine.

Stdlib-only core. Code owns state, transitions, gates, manifest persistence,
and integrity checks; prompts (and adapters) propose via the action envelope.
"""

__version__ = "0.1.0"

from .engine import ApplyResult, PipelineEngine  # noqa: F401
from .manifest.store import ManifestStore  # noqa: F401
from .adapters.artifact_store import ArtifactStore  # noqa: F401
