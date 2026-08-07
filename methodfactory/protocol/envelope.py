"""Action Envelope — parsing and strict schema validation (ADR-0005).

The envelope is the only way a caller proposes a state-changing action.
Prose is never parsed for state-changing intent.

Finding 1 (review 4879090471): the envelope enforces the complete boundary
model —
- MAX_ENVELOPE_BYTES on UTF-8 bytes BEFORE any JSON parse or prose extraction;
- centralized package-ID, identifier, logical-path, and control-character
  validators (storage.paths / storage.serialization);
- every declared action-field limit (content, statement, outcome count,
  individual outcomes, reasons, identifiers, logical paths).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..domain.errors import InvalidEnvelopeError
from ..domain.transitions import ACTION_VOCABULARY, Action
from ..storage.limits import (
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_OUTCOMES,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
)
from ..storage.paths import validate_identifier, validate_logical_path, validate_package_id
from ..storage.serialization import contains_control_chars

PROTOCOL_VERSION = "0.1"

ENVELOPE_FIELDS = frozenset(
    {"protocol_version", "action_id", "package_id", "expected_revision", "action", "basis", "payload"}
)

INPUT_KINDS = frozenset({"text", "url", "file-reference", "constraint"})
INPUT_SOURCES = frozenset({"operator", "adapter"})
DISPOSITIONS = frozenset({"incorporated", "excluded"})

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

    Enforces MAX_ENVELOPE_BYTES on the ORIGINAL RAW UTF-8 input BEFORE
    strip(), parsing, or prose extraction (Finding 1): a raw input that
    exceeds the bound because of surrounding whitespace is still rejected.
    Encoding failures (e.g. lone-surrogate UnicodeEncodeError) are translated
    to InvalidEnvelopeError. Tolerates surrounding prose by extracting the
    text between the first '{' and the last '}' only within the byte bound.
    """
    if not isinstance(raw, str):
        raise InvalidEnvelopeError("envelope must be a string")
    # Fast-fail on character count BEFORE encoding (local review, perf-2):
    # every UTF-8 char is >= 1 byte, so len(raw) > bound implies the byte
    # bound is exceeded — oversized inputs are rejected without an O(n)
    # allocation. The exact UTF-8 byte measurement below stays authoritative
    # (multibyte strings can exceed the byte bound under the char count).
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise InvalidEnvelopeError(
            f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
        )
    try:
        raw_bytes = raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidEnvelopeError(f"envelope is not valid UTF-8: {exc}") from exc
    if len(raw_bytes) > MAX_ENVELOPE_BYTES:
        raise InvalidEnvelopeError(
            f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
        )
    text = raw.strip()
    if not text:
        raise InvalidEnvelopeError("empty envelope")
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
    if not isinstance(action_id, str) or not action_id:
        raise InvalidEnvelopeError("action_id must be a non-empty string")
    if contains_control_chars(action_id):
        raise InvalidEnvelopeError("action_id must not contain control characters")
    if len(action_id) > 64:
        raise InvalidEnvelopeError("action_id must be <= 64 chars")

    package_id = d["package_id"]
    try:
        validate_package_id(package_id)
    except Exception as exc:
        raise InvalidEnvelopeError(f"invalid package_id {package_id!r}") from exc

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
        input_id = payload.get("input_id")
        if not isinstance(input_id, str) or not input_id:
            raise InvalidEnvelopeError("record_input requires input_id")
        try:
            validate_identifier(input_id, field="input_id")
        except Exception as exc:
            raise InvalidEnvelopeError(f"invalid input_id {input_id!r}") from exc
        if contains_control_chars(input_id):
            raise InvalidEnvelopeError("record_input input_id must not contain control characters")
        if payload.get("kind") not in INPUT_KINDS:
            raise InvalidEnvelopeError("record_input kind must be text|url|file-reference|constraint")
        if not isinstance(payload.get("content"), str):
            raise InvalidEnvelopeError("record_input content must be a string")
        if len(payload["content"]) > MAX_CONTENT_CHARS:
            raise InvalidEnvelopeError(f"record_input content exceeds {MAX_CONTENT_CHARS} chars")
        if payload.get("source") not in INPUT_SOURCES:
            raise InvalidEnvelopeError("record_input source must be operator|adapter")
        if payload.get("disposition") not in DISPOSITIONS:
            raise InvalidEnvelopeError("record_input disposition must be incorporated|excluded")
        reason = payload.get("exclusion_reason")
        if reason is not None and not isinstance(reason, str):
            raise InvalidEnvelopeError("exclusion_reason must be a string")
        if isinstance(reason, str) and len(reason) > MAX_REASON_CHARS:
            raise InvalidEnvelopeError(f"exclusion_reason exceeds {MAX_REASON_CHARS} chars")
        if isinstance(reason, str) and contains_control_chars(reason):
            raise InvalidEnvelopeError("exclusion_reason must not contain control characters")

    elif action == Action.SET_OBJECTIVE.value:
        if not isinstance(payload.get("statement"), str):
            raise InvalidEnvelopeError("set_objective requires a string statement")
        if len(payload["statement"]) > MAX_STATEMENT_CHARS:
            raise InvalidEnvelopeError(f"set_objective statement exceeds {MAX_STATEMENT_CHARS} chars")
        if contains_control_chars(payload["statement"]):
            raise InvalidEnvelopeError("set_objective statement must not contain control characters")
        outcomes = payload.get("desired_outcomes", [])
        if not isinstance(outcomes, list) or not all(isinstance(o, str) for o in outcomes):
            raise InvalidEnvelopeError("desired_outcomes must be a list of strings")
        if len(outcomes) > MAX_OUTCOMES:
            raise InvalidEnvelopeError(f"desired_outcomes exceeds {MAX_OUTCOMES} entries")
        if any(len(o) > MAX_STATEMENT_CHARS for o in outcomes):
            raise InvalidEnvelopeError(f"desired_outcomes entry exceeds {MAX_STATEMENT_CHARS} chars")
        if any(contains_control_chars(o) for o in outcomes):
            raise InvalidEnvelopeError("desired_outcomes entry must not contain control characters")

    elif action == Action.CONFIRM_SUMMARY.value:
        if not isinstance(basis.get("summary_sha256"), str) or not basis["summary_sha256"]:
            raise InvalidEnvelopeError("confirm_summary requires basis.summary_sha256")
        op = payload.get("operator_id")
        if op is not None and not isinstance(op, str):
            raise InvalidEnvelopeError("operator_id must be a string")
        if isinstance(op, str):
            try:
                validate_identifier(op, field="operator_id")
            except Exception as exc:
                raise InvalidEnvelopeError(f"invalid operator_id {op!r}") from exc
        if isinstance(op, str) and contains_control_chars(op):
            raise InvalidEnvelopeError("operator_id must not contain control characters")

    elif action == Action.RECORD_DRAFT_ARTIFACT.value:
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise InvalidEnvelopeError("record_draft_artifact requires artifact_id")
        try:
            validate_identifier(artifact_id, field="artifact_id")
        except Exception as exc:
            raise InvalidEnvelopeError(f"invalid artifact_id {artifact_id!r}") from exc
        if contains_control_chars(artifact_id):
            raise InvalidEnvelopeError("record_draft_artifact artifact_id must not contain control characters")
        if not isinstance(payload.get("kind"), str) or not payload["kind"]:
            raise InvalidEnvelopeError("record_draft_artifact requires kind")
        if len(payload["kind"]) > MAX_ID_CHARS:
            raise InvalidEnvelopeError(f"record_draft_artifact kind exceeds {MAX_ID_CHARS} chars")
        if contains_control_chars(payload["kind"]):
            raise InvalidEnvelopeError("record_draft_artifact kind must not contain control characters")
        logical_path = payload.get("logical_path")
        if not isinstance(logical_path, str) or not logical_path:
            raise InvalidEnvelopeError("record_draft_artifact requires logical_path")
        try:
            validate_logical_path(logical_path)
        except Exception as exc:
            raise InvalidEnvelopeError(f"invalid logical_path {logical_path!r}") from exc
        if len(logical_path) > MAX_LOGICAL_PATH_CHARS:
            raise InvalidEnvelopeError(f"logical_path exceeds {MAX_LOGICAL_PATH_CHARS} chars")
        if not isinstance(payload.get("content"), str):
            raise InvalidEnvelopeError("record_draft_artifact content must be a string")
        if len(payload["content"]) > MAX_CONTENT_CHARS:
            raise InvalidEnvelopeError(f"record_draft_artifact content exceeds {MAX_CONTENT_CHARS} chars")

    elif action == Action.CANCEL.value:
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise InvalidEnvelopeError("cancel reason must be a string")
        if isinstance(reason, str) and len(reason) > MAX_REASON_CHARS:
            raise InvalidEnvelopeError(f"cancel reason exceeds {MAX_REASON_CHARS} chars")
        if isinstance(reason, str) and contains_control_chars(reason):
            raise InvalidEnvelopeError("cancel reason must not contain control characters")
