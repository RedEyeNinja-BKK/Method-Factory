"""Action Envelope — parsing and strict schema validation (ADR-0005).

The envelope is the only way a caller proposes a state-changing action.
Prose is never parsed for state-changing intent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import InvalidEnvelopeError
from ..domain.transitions import ACTION_VOCABULARY, Action
from ..domain.vocabulary import (
    DISPOSITIONS,
    INPUT_KINDS,
    INPUT_SOURCES,
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_OUTCOMES,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
    PACKAGE_ID_RE,
    contains_control_chars,
)

PROTOCOL_VERSION = "0.1"

ENVELOPE_FIELDS = frozenset(
    {"protocol_version", "action_id", "package_id", "expected_revision", "action", "basis", "payload"}
)

# Per-action allowed payload fields (strict; unknown rejected).
PAYLOAD_SCHEMA: dict[str, frozenset[str]] = {
    Action.RECORD_INPUT.value: frozenset(
        {"input_id", "kind", "content", "source", "disposition", "exclusion_reason"}
    ),
    Action.SET_OBJECTIVE.value: frozenset({"statement", "desired_outcomes"}),
    Action.PREPARE_SUMMARY.value: frozenset(),
    Action.CONFIRM_SUMMARY.value: frozenset({"operator_id"}),
    Action.REVISE_INTAKE.value: frozenset(),
    Action.RECORD_DRAFT_ARTIFACT.value: frozenset({"artifact_id", "kind", "logical_path", "content"}),
    Action.CANCEL.value: frozenset({"reason"}),
}

# Per-action allowed basis fields (strict; unknown rejected).
BASIS_SCHEMA: dict[str, frozenset[str]] = {
    Action.CONFIRM_SUMMARY.value: frozenset({"summary_sha256"}),
    Action.RECORD_INPUT.value: frozenset(),
    Action.SET_OBJECTIVE.value: frozenset(),
    Action.PREPARE_SUMMARY.value: frozenset(),
    Action.REVISE_INTAKE.value: frozenset(),
    Action.RECORD_DRAFT_ARTIFACT.value: frozenset(),
    Action.CANCEL.value: frozenset(),
}


@dataclass(frozen=True)
class ActionEnvelope:
    protocol_version: str
    action_id: str
    package_id: str
    expected_revision: int
    action: str
    basis: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "action_id": self.action_id,
            "package_id": self.package_id,
            "expected_revision": self.expected_revision,
            "action": self.action,
            "basis": self.basis,
            "payload": self.payload,
        }


def parse_envelope(raw: str) -> ActionEnvelope:
    """Parse exactly one JSON object, then validate it strictly.

    Tolerates surrounding prose (conversational transports) by extracting the
    text between the first '{' and the last '}'. Multiple JSON objects or
    unparseable text are INVALID_ENVELOPE.
    """
    text = raw.strip()
    if not text:
        raise InvalidEnvelopeError("empty envelope")
    if len(text) > MAX_ENVELOPE_BYTES or len(text.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise InvalidEnvelopeError(
            f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
        )
    try:
        candidate = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise InvalidEnvelopeError("malformed envelope: no JSON object found")
        try:
            candidate = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise InvalidEnvelopeError(f"malformed envelope: {exc}") from exc
        except RecursionError as exc:
            raise InvalidEnvelopeError("malformed envelope: JSON nesting too deep") from exc
    except RecursionError as exc:
        raise InvalidEnvelopeError("malformed envelope: JSON nesting too deep") from exc
    if not isinstance(candidate, dict):
        raise InvalidEnvelopeError("malformed envelope: expected a JSON object")
    return envelope_from_dict(candidate)


def envelope_from_dict(d: dict) -> ActionEnvelope:
    _validate_envelope_dict(d)
    return ActionEnvelope(
        protocol_version=d["protocol_version"],
        action_id=d["action_id"],
        package_id=d["package_id"],
        expected_revision=d["expected_revision"],
        action=d["action"],
        basis=dict(d["basis"]),
        payload=dict(d["payload"]),
    )


def _validate_envelope_dict(d: dict) -> None:
    for key in d:
        if key not in ENVELOPE_FIELDS:
            raise InvalidEnvelopeError(f"unknown envelope field {key!r}")

    missing = ENVELOPE_FIELDS - set(d)
    if missing:
        raise InvalidEnvelopeError(f"missing required fields: {sorted(missing)}")

    if d["protocol_version"] != PROTOCOL_VERSION:
        raise InvalidEnvelopeError(
            f"unsupported protocol_version {d['protocol_version']!r} (expected {PROTOCOL_VERSION!r})"
        )

    action_id = d["action_id"]
    if not isinstance(action_id, str) or not action_id or len(action_id) > 64:
        raise InvalidEnvelopeError("action_id must be a non-empty string <= 64 chars")

    package_id = d["package_id"]
    if not isinstance(package_id, str) or not PACKAGE_ID_RE.match(package_id):
        raise InvalidEnvelopeError(f"invalid package_id {package_id!r}")

    expected_revision = d["expected_revision"]
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
        raise InvalidEnvelopeError(f"expected_revision must be a non-negative int, got {expected_revision!r}")

    action = d["action"]
    if not isinstance(action, str) or action not in ACTION_VOCABULARY:
        raise InvalidEnvelopeError(f"unknown action {action!r}")

    basis = d["basis"]
    payload = d["payload"]
    if not isinstance(basis, dict):
        raise InvalidEnvelopeError("basis must be an object")
    if not isinstance(payload, dict):
        raise InvalidEnvelopeError("payload must be an object")

    for key in basis:
        if key not in BASIS_SCHEMA[action]:
            raise InvalidEnvelopeError(f"unknown basis field {key!r} for action {action!r}")
    for key in payload:
        if key not in PAYLOAD_SCHEMA[action]:
            raise InvalidEnvelopeError(f"unknown payload field {key!r} for action {action!r}")

    _validate_payload_types(action, payload, basis)


def _validate_payload_types(action: str, payload: dict, basis: dict) -> None:
    if action == Action.RECORD_INPUT.value:
        if not isinstance(payload.get("input_id"), str) or not payload["input_id"]:
            raise InvalidEnvelopeError("record_input requires input_id")
        if len(payload["input_id"]) > MAX_ID_CHARS:
            raise InvalidEnvelopeError("record_input input_id too long")
        if contains_control_chars(payload["input_id"]):
            raise InvalidEnvelopeError("record_input input_id must not contain control characters")
        if payload.get("kind") not in INPUT_KINDS:
            raise InvalidEnvelopeError("record_input kind must be text|url|file-reference|constraint")
        if not isinstance(payload.get("content"), str):
            raise InvalidEnvelopeError("record_input content must be a string")
        if len(payload["content"]) > MAX_CONTENT_CHARS:
            raise InvalidEnvelopeError("record_input content too long")
        if payload.get("source") not in INPUT_SOURCES:
            raise InvalidEnvelopeError("record_input source must be operator|adapter")
        if payload.get("disposition") not in DISPOSITIONS:
            raise InvalidEnvelopeError("record_input disposition must be incorporated|excluded")
        reason = payload.get("exclusion_reason")
        if reason is not None and not isinstance(reason, str):
            raise InvalidEnvelopeError("exclusion_reason must be a string")
        if isinstance(reason, str) and len(reason) > MAX_REASON_CHARS:
            raise InvalidEnvelopeError("exclusion_reason too long")
        if isinstance(reason, str) and contains_control_chars(reason):
            raise InvalidEnvelopeError("exclusion_reason must not contain control characters")

    elif action == Action.SET_OBJECTIVE.value:
        if not isinstance(payload.get("statement"), str):
            raise InvalidEnvelopeError("set_objective requires a string statement")
        if len(payload["statement"]) > MAX_STATEMENT_CHARS:
            raise InvalidEnvelopeError("set_objective statement too long")
        if contains_control_chars(payload["statement"]):
            raise InvalidEnvelopeError("set_objective statement must not contain control characters")
        outcomes = payload.get("desired_outcomes", [])
        if not isinstance(outcomes, list) or not all(isinstance(o, str) for o in outcomes):
            raise InvalidEnvelopeError("desired_outcomes must be a list of strings")
        if len(outcomes) > MAX_OUTCOMES:
            raise InvalidEnvelopeError("desired_outcomes too long")
        if any(len(o) > MAX_STATEMENT_CHARS for o in outcomes):
            raise InvalidEnvelopeError("desired_outcomes entry too long")
        if any(contains_control_chars(o) for o in outcomes):
            raise InvalidEnvelopeError("desired_outcomes entry must not contain control characters")

    elif action == Action.CONFIRM_SUMMARY.value:
        if not isinstance(basis.get("summary_sha256"), str) or not basis["summary_sha256"]:
            raise InvalidEnvelopeError("confirm_summary requires basis.summary_sha256")
        op = payload.get("operator_id")
        if op is not None and not isinstance(op, str):
            raise InvalidEnvelopeError("operator_id must be a string")
        if isinstance(op, str) and len(op) > MAX_ID_CHARS:
            raise InvalidEnvelopeError("operator_id too long")
        if isinstance(op, str) and contains_control_chars(op):
            raise InvalidEnvelopeError("operator_id must not contain control characters")

    elif action == Action.RECORD_DRAFT_ARTIFACT.value:
        if not isinstance(payload.get("artifact_id"), str) or not payload["artifact_id"]:
            raise InvalidEnvelopeError("record_draft_artifact requires artifact_id")
        if len(payload["artifact_id"]) > MAX_ID_CHARS:
            raise InvalidEnvelopeError("record_draft_artifact artifact_id too long")
        if contains_control_chars(payload["artifact_id"]):
            raise InvalidEnvelopeError("record_draft_artifact artifact_id must not contain control characters")
        if not isinstance(payload.get("kind"), str) or not payload["kind"]:
            raise InvalidEnvelopeError("record_draft_artifact requires kind")
        if len(payload["kind"]) > MAX_ID_CHARS:
            raise InvalidEnvelopeError("record_draft_artifact kind too long")
        if not isinstance(payload.get("logical_path"), str) or not payload["logical_path"]:
            raise InvalidEnvelopeError("record_draft_artifact requires logical_path")
        if len(payload["logical_path"]) > MAX_LOGICAL_PATH_CHARS:
            raise InvalidEnvelopeError("record_draft_artifact logical_path too long")
        if contains_control_chars(payload["logical_path"]):
            raise InvalidEnvelopeError("record_draft_artifact logical_path must not contain control characters")
        if not isinstance(payload.get("content"), str):
            raise InvalidEnvelopeError("record_draft_artifact content must be a string")
        if len(payload["content"]) > MAX_CONTENT_CHARS:
            raise InvalidEnvelopeError("record_draft_artifact content too long")

    elif action == Action.CANCEL.value:
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise InvalidEnvelopeError("cancel reason must be a string")
        if isinstance(reason, str) and len(reason) > MAX_REASON_CHARS:
            raise InvalidEnvelopeError("cancel reason too long")
        if isinstance(reason, str) and contains_control_chars(reason):
            raise InvalidEnvelopeError("cancel reason must not contain control characters")
