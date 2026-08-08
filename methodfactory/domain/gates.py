"""Gate predicates — evidence and binding checks before any write (ADR-0008)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .errors import GateUnsatisfiedError, InvalidPayloadError, StaleActionError
from .transitions import Action

if TYPE_CHECKING:  # pragma: no cover
    from ..protocol.envelope import ActionEnvelope


def check_action_gate(action: Action, manifest: dict, envelope: "ActionEnvelope") -> None:
    """Raise before a transition commits if required evidence is missing.

    Raises:
        InvalidPayloadError — semantic payload violation.
        GateUnsatisfiedError — required evidence absent.
        StaleActionError — approval/digest binding mismatch.
    """
    ctx = dict(package_id=envelope.package_id, state=manifest.get("state"))

    if action == Action.RECORD_INPUT:
        input_id = envelope.payload.get("input_id")
        existing = {i["input_id"] for i in manifest.get("inputs", [])}
        if input_id in existing:
            raise InvalidPayloadError(f"duplicate input_id {input_id!r}", **ctx)
        if envelope.payload.get("disposition") == "excluded":
            reason = (envelope.payload.get("exclusion_reason") or "").strip()
            if not reason:
                raise InvalidPayloadError("excluded input requires exclusion_reason", **ctx)

    elif action == Action.SET_OBJECTIVE:
        statement = (envelope.payload.get("statement") or "").strip()
        if not statement:
            raise InvalidPayloadError("objective.statement is required", **ctx)

    elif action == Action.PREPARE_SUMMARY:
        intent_raw = (manifest.get("intent") or {}).get("raw") or ""
        objective_stmt = (manifest.get("objective") or {}).get("statement") or ""
        if not intent_raw.strip():
            raise GateUnsatisfiedError("cannot prepare summary: intent is missing", **ctx)
        if not objective_stmt.strip():
            raise GateUnsatisfiedError("cannot prepare summary: objective is missing", **ctx)

    elif action == Action.CONFIRM_SUMMARY:
        summary = manifest.get("summary")
        if not isinstance(summary, dict):
            raise GateUnsatisfiedError("cannot confirm: no summary prepared", **ctx)
        # Content-addressed summary (ADR-0012): the canonical hash of the
        # rendered summary body is summary.digest (the old JSONL-era
        # canonical_sha256 field does not exist in the content-addressed
        # manifest schema).
        current = summary.get("digest")
        if not current:
            raise GateUnsatisfiedError("cannot confirm: no summary prepared", **ctx)
        want = envelope.basis.get("summary_sha256")
        if want != current:
            raise StaleActionError(
                "summary digest mismatch: approval would bind a stale summary",
                package_id=envelope.package_id,
                state=manifest.get("state"),
                expected_revision=envelope.expected_revision,
                actual_revision=manifest.get("revision"),
            )

    elif action == Action.RECORD_DRAFT_ARTIFACT:
        summary = manifest.get("summary")
        if not isinstance(summary, dict):
            raise GateUnsatisfiedError(
                "authoring requires a confirmed summary bound to the current summary digest", **ctx
            )
        conf = summary.get("confirmation")
        confirmed_ok = (
            isinstance(conf, dict)
            and conf.get("status") == "confirmed"
            and conf.get("confirmed_summary_sha256") == summary.get("digest")
        )
        if not confirmed_ok:
            raise GateUnsatisfiedError(
                "authoring requires a confirmed summary bound to the current summary digest", **ctx
            )
        if not (envelope.payload.get("logical_path") or "").strip():
            raise InvalidPayloadError("logical_path is required", **ctx)

    # REVISE_INTAKE / CANCEL: no additional gate.
