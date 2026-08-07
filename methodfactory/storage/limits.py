"""Size-bound constants, separated by object type (ADR-0012 §4).

FROZEN first-release values (review 4879090471, Finding 1): no limit is
preliminary. Rationale for each is inline. Limits are enforced at the owning
boundary (envelope parse, action canonicalization, manifest validation,
artifact store, serialization).

Units: fields named *_CHARS are measured in CHARACTERS (Unicode code points);
fields named *_BYTES are measured in UTF-8 BYTES. Multibyte strings may exceed
a byte budget while satisfying a char budget (and vice versa); tests cover the
distinction.

Never reuse an envelope limit as an event/manifest limit: an incoming action
envelope and a committed event carrying a cumulative manifest are different
objects with different sizes.
"""

from __future__ import annotations

# ── Action Envelope (wire/parse boundary) ───────────────────────────────
# Enforced on UTF-8 BYTES of the raw envelope BEFORE any JSON parse or prose
# extraction (Finding 1). 2 MiB bounds a conversational transport payload.
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024

# ── Individual content fields (CHARACTERS) ──────────────────────────────
MAX_CONTENT_CHARS = 1_048_576          # record_input / record_draft_artifact content
MAX_INTENT_CHARS = 65_536              # create_package intent.raw
MAX_STATEMENT_CHARS = 16_384           # set_objective statement / outcome
MAX_OUTCOMES = 100                     # desired_outcomes list length
MAX_ID_CHARS = 128                     # input_id / artifact_id / operator_id / kind
MAX_LOGICAL_PATH_CHARS = 255           # artifact logical_path (characters)
MAX_REASON_CHARS = 1024                # exclusion_reason / cancel reason
MAX_PREVIEW_CHARS = 512                # content-addressed summary preview

# ── Canonical action JSON (normalized semantic request; ADR-0012 §G) ────
# Enforced on the canonical BYTES of the normalized action before hashing
# (Finding 1). 4 MiB bounds the semantic request after canonicalization.
MAX_ACTION_JSON_BYTES = 4 * 1024 * 1024

# ── Manifest (complete resulting manifest per revision; ADR-0012 §4) ────
# Enforced on the canonical BYTES of the complete manifest by the
# authoritative manifest validator (Finding 1). 8 MiB bounds a cumulative
# manifest that references artifacts by digest (bodies live in the blob store).
MAX_MANIFEST_BYTES = 8 * 1024 * 1024

# ── Artifact / blob (content-addressed immutable store) ─────────────────
# Enforced at put(); the byte budget is the storage ceiling, the char budget
# bounds a string payload before encoding.
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
