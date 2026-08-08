"""Deterministic manifest transitions — the single apply rule (ADR-0003/0005).

`next_manifest` is the ONLY place a legal action transforms a manifest:

1. legality (domain.transitions — the transition table is the sole authority);
2. gate check (domain.gates — evidence/binding checks, no writes);
3. deterministic mutation for the action;
4. revision increment, target state, updated_at, and write-lineage fields
   (previous_manifest_sha256 = canonical digest of the current manifest;
   transition.last_event_id / last_action_id).

Returns ``(next_manifest, blobs_to_write)`` where ``blobs_to_write`` is a
list of ``(logical_path, content)`` the storage layer must persist into the
content-addressed artifact store before committing (immutable blobs; on a
transaction rollback the blobs are kept — content-addressed and harmless).

The engine is persistence-free (no SQLite, no filesystem, no artifact store)
but deliberately uses the storage package's canonical serialization and
limit constants as the single shared infrastructure (ADR-0012 §4) — the same
bytes the storage layer hashes and persists, so engine-produced digests can
never drift from stored hashes.

Gates are re-evaluated here so apply validity cannot diverge from the shared
rule; the storage layer then re-checks chain invariants via the single
invariant kernel (storage.chain) before INSERT.
"""

from __future__ import annotations

import copy
from typing import Any

from ..domain.errors import IllegalTransitionError, InvalidPayloadError
from ..domain.gates import check_action_gate
from ..domain.states import State
from ..domain.transitions import Action, transition_target
from ..manifest.render import render_summary
from ..protocol.envelope import ActionEnvelope
from ..storage.limits import MAX_PREVIEW_CHARS
from ..storage.serialization import digest_bytes, digest_json

# The canonical create operation. Deliberately NOT in the envelope Action
# vocabulary: a package is created only through the store's create(), never
# by a caller-proposed envelope action.
CREATE_PACKAGE_ACTION = "create_package"

# Deterministic blob paths (internal bookkeeping; not part of the public
# manifest contract beyond the logical-path grammar).
SUMMARY_BLOB_TEMPLATE = "summaries/r{revision}.txt"
INPUT_BLOB_TEMPLATE = "inputs/{input_id}.txt"


def _content_digest(content: str, field: str) -> tuple[str, int]:
    """Encode content to UTF-8 bytes and compute digest + size; translate
    lone surrogates typed."""
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidPayloadError(f"{field} is not valid UTF-8 (lone surrogate?)") from exc
    return digest_bytes(data), len(data)


def _apply_record_input(m: dict, envelope: ActionEnvelope) -> list[tuple[str, str]]:
    payload = envelope.payload
    digest, size = _content_digest(payload["content"], "record_input content")
    path = INPUT_BLOB_TEMPLATE.format(input_id=payload["input_id"])
    m["inputs"] = [*m.get("inputs", []), {
        "input_id": payload["input_id"],
        "kind": payload["kind"],
        "source": payload["source"],
        "disposition": payload["disposition"],
        "exclusion_reason": payload.get("exclusion_reason"),
        "content_sha256": digest,
        "content_size": size,
        "content_path": path,
    }]
    return [(path, payload["content"])]


def _apply_set_objective(m: dict, envelope: ActionEnvelope) -> list[tuple[str, str]]:
    m["objective"] = {
        "statement": envelope.payload["statement"],
        "desired_outcomes": list(envelope.payload.get("desired_outcomes", [])),
    }
    return []


def _apply_prepare_summary(
    m: dict, envelope: ActionEnvelope, *, revision: int, created_at: str
) -> list[tuple[str, str]]:
    try:
        body = render_summary(m)
    except (KeyError, TypeError, IndexError, AttributeError, ValueError) as exc:
        raise InvalidPayloadError(
            f"current manifest is not well-formed for summary rendering: {exc}"
        ) from exc
    digest, size = _content_digest(body, "summary body")
    path = SUMMARY_BLOB_TEMPLATE.format(revision=revision)
    # Preview is a single-line bounded snippet: collapse all whitespace runs
    # (newlines/tabs are C0 control chars and are rejected by the manifest
    # validator's control-character rule).
    preview = " ".join(body.split())[:MAX_PREVIEW_CHARS]
    m["summary"] = {
        "digest": digest,
        "size": size,
        "preview": preview,
        "presented_at": created_at,
        "confirmation": {
            "status": "pending",
            "confirmed_at": None,
            "operator_id": None,
            "confirmed_summary_sha256": None,
        },
    }
    return [(path, body)]


def _apply_confirm_summary(m: dict, envelope: ActionEnvelope, *, created_at: str) -> list[tuple[str, str]]:
    m["summary"]["confirmation"] = {
        "status": "confirmed",
        "confirmed_at": created_at,
        "operator_id": envelope.payload.get("operator_id") or "operator",
        "confirmed_summary_sha256": envelope.basis["summary_sha256"],
    }
    return []


def _apply_revise_intake(m: dict, _envelope: ActionEnvelope) -> list[tuple[str, str]]:
    # Mutators share one signature for uniform dispatch; the envelope is
    # unused here by design (revise_intake carries no payload state).
    # Summary and any draft artifacts are stale after the operator revises
    # intake; inputs and objective are intake material and are preserved.
    m["summary"] = None
    m["artifacts"] = []
    return []


def _apply_record_draft_artifact(m: dict, envelope: ActionEnvelope) -> list[tuple[str, str]]:
    payload = envelope.payload
    digest, size = _content_digest(payload["content"], "artifact content")
    m["artifacts"] = [*m.get("artifacts", []), {
        "artifact_id": payload["artifact_id"],
        "kind": payload["kind"],
        "logical_path": payload["logical_path"],
        "sha256": digest,
        "byte_count": size,
        "status": "draft",
    }]
    return [(payload["logical_path"], payload["content"])]


def _apply_cancel(m: dict, _envelope: ActionEnvelope) -> list[tuple[str, str]]:
    # Mutators share one signature for uniform dispatch; the envelope is
    # unused here by design (cancel is a transition-only action; the reason
    # payload is recorded nowhere in v0.1).
    return []


_ACTION_MUTATORS = {
    Action.RECORD_INPUT: _apply_record_input,
    Action.SET_OBJECTIVE: _apply_set_objective,
    Action.PREPARE_SUMMARY: _apply_prepare_summary,
    Action.CONFIRM_SUMMARY: _apply_confirm_summary,
    Action.REVISE_INTAKE: _apply_revise_intake,
    Action.RECORD_DRAFT_ARTIFACT: _apply_record_draft_artifact,
    Action.CANCEL: _apply_cancel,
}


def next_manifest(
    current: dict[str, Any],
    envelope: ActionEnvelope,
    *,
    event_id: str,
    created_at: str,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Compute the next manifest for a legal, gate-passing action.

    Raises (all public MethodFactoryError):
        IllegalTransitionError — action not legal in the current state.
        GateUnsatisfiedError / StaleActionError / InvalidPayloadError —
        gate evidence or binding failures.

    Returns (next_manifest, blobs_to_write).
    """
    if not isinstance(current, dict):
        raise InvalidPayloadError("current manifest must be an object")
    state = current.get("state")
    try:
        current_state = State(state)
    except ValueError:
        raise InvalidPayloadError(f"current manifest has invalid state {state!r}") from None
    revision = current.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise InvalidPayloadError(
            f"current manifest revision must be a non-negative int, got {revision!r}"
        )
    try:
        action = Action(envelope.action)
    except ValueError:
        raise InvalidPayloadError(f"unknown action {envelope.action!r}") from None

    target = transition_target(current_state, action)
    if target is None:
        raise IllegalTransitionError(
            f"action {envelope.action!r} is not legal from state {current_state.value}",
            package_id=envelope.package_id,
            state=current_state.value,
        )

    # Gate evidence/binding checks BEFORE any mutation (no writes here).
    check_action_gate(action, current, envelope)

    m = copy.deepcopy(current)
    new_revision = revision + 1
    mutator = _ACTION_MUTATORS[action]
    if action == Action.PREPARE_SUMMARY:
        blobs = mutator(m, envelope, revision=new_revision, created_at=created_at)
    elif action == Action.CONFIRM_SUMMARY:
        blobs = mutator(m, envelope, created_at=created_at)
    else:
        blobs = mutator(m, envelope)

    m["revision"] = new_revision
    m["state"] = target.value
    m["updated_at"] = created_at
    m["previous_manifest_sha256"] = digest_json(current)
    m["transition"] = {"last_event_id": event_id, "last_action_id": envelope.action_id}
    return m, blobs
