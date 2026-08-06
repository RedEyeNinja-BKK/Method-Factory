"""Size-bound constants, separated by object type (ADR-0012 §4).

Never reuse an envelope limit as an event/manifest limit: an incoming action
envelope and a committed event carrying a cumulative manifest are different
objects with different sizes. Values are preliminary and frozen by ADR review
(the Phase 2 submission reports them; the senior reviewer approves the set).
"""

from __future__ import annotations

# ── Action Envelope (wire/parse boundary) ───────────────────────────────
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024

# ── Individual content fields ───────────────────────────────────────────
MAX_CONTENT_CHARS = 1_048_576          # record_input / record_draft_artifact content
MAX_INTENT_CHARS = 65_536              # create_package intent.raw
MAX_STATEMENT_CHARS = 16_384           # set_objective statement / outcome
MAX_OUTCOMES = 100                     # desired_outcomes list length
MAX_ID_CHARS = 128                     # input_id / artifact_id / operator_id / kind
MAX_LOGICAL_PATH_CHARS = 255           # artifact logical_path
MAX_REASON_CHARS = 1024                # exclusion_reason / cancel reason

# ── Canonical action JSON (normalized semantic request; ADR-0012 §G) ────
MAX_ACTION_JSON_BYTES = 4 * 1024 * 1024

# ── Manifest (complete resulting manifest per revision; ADR-0012 §4) ────
MAX_MANIFEST_BYTES = 8 * 1024 * 1024

# ── Artifact / blob (content-addressed immutable store) ─────────────────
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
