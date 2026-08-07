"""Manifest Contract v0.1 — schema and read-only validation (ADR-0004).

Phase 2 corrections (Finding 1): the authoritative manifest validator enforces
the complete first-release boundary model — total canonical MAX_MANIFEST_BYTES,
intent length, identifier limits, logical-path grammar, outcome count/length,
persisted content-size bounds, and control-character rules. The summary is
content-addressed (digest/size/preview; inline body rejected). Package-id,
identifier, logical-path, and control-character validation is centralized in
storage (paths/serialization) to prevent rule drift.
"""

from __future__ import annotations

from datetime import datetime

from ..domain.states import State
from ..storage.limits import (
    MAX_ARTIFACT_BODY_BYTES,
    MAX_CONTENT_CHARS,
    MAX_ID_CHARS,
    MAX_INPUT_CONTENT_BYTES,
    MAX_INTENT_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_OUTCOMES,
    MAX_PREVIEW_CHARS,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
    MAX_SUMMARY_BYTES,
)
from ..storage.paths import PACKAGE_ID_RE, validate_identifier, validate_logical_path, validate_package_id
from ..storage.serialization import contains_control_chars, try_canonical_bytes_bounded

SCHEMA_VERSION = "0.1"

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "package_id",
        "revision",
        "state",
        "created_at",
        "updated_at",
        "previous_manifest_sha256",
        "intent",
        "inputs",
        "objective",
        "summary",
        "artifacts",
        "transition",
    }
)

SHA256_RE = __import__("re").compile(r"^[0-9a-f]{64}$")
INPUT_KINDS = frozenset({"text", "url", "file-reference", "constraint"})
INPUT_SOURCES = frozenset({"operator", "adapter"})
DISPOSITIONS = frozenset({"incorporated", "excluded"})
CONFIRMATION_STATUSES = frozenset({"pending", "confirmed"})
# Optional bounded preview for the content-addressed summary.
SUMMARY_PREVIEW_MAX_CHARS = MAX_PREVIEW_CHARS


def _is_iso8601(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def new_manifest(package_id: str, intent_raw: str, created_at: str) -> dict:
    """Initial manifest (revision 0, INTAKE). Caller validated by engine."""
    return {
        "schema_version": SCHEMA_VERSION,
        "package_id": package_id,
        "revision": 0,
        "state": State.INTAKE.value,
        "created_at": created_at,
        "updated_at": created_at,
        "previous_manifest_sha256": None,
        "intent": {"raw": intent_raw, "clarified": None},
        "inputs": [],
        "objective": {"statement": "", "desired_outcomes": []},
        "summary": None,
        "artifacts": [],
        "transition": {"last_event_id": None, "last_action_id": None},
    }


def validate_manifest(manifest: dict) -> list[str]:
    """Collect all schema/invariant violations (read-only; no state change).

    Enforces the complete first-release boundary model (Finding 1): total
    canonical MAX_MANIFEST_BYTES plus every persisted field/path/identifier/
    control limit.
    """
    errors: list[str] = []

    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

    # Total canonical manifest byte bound. Native canonicalization failures
    # (unsupported types, deep recursion, lone-surrogate encoding) are
    # translated into manifest errors — never leaked raw (Finding 1).
    _, canonical_error = try_canonical_bytes_bounded(
        manifest, limit=MAX_MANIFEST_BYTES, what="manifest"
    )
    if canonical_error is not None:
        errors.append(canonical_error)

    for key in manifest:
        if key not in TOP_LEVEL_FIELDS:
            errors.append(f"unknown top-level field {key!r}")

    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r}")

    pid = manifest.get("package_id")
    if not isinstance(pid, str) or not PACKAGE_ID_RE.match(pid):
        errors.append(f"invalid package_id {pid!r}")

    rev = manifest.get("revision")
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0:
        errors.append(f"revision must be a non-negative int, got {rev!r}")

    state = manifest.get("state")
    if state not in State._value2member_map_:
        errors.append(f"invalid state {state!r}")

    for field in ("created_at", "updated_at"):
        if not _is_iso8601(manifest.get(field)):
            errors.append(f"{field} must be ISO-8601, got {manifest.get(field)!r}")

    prev = manifest.get("previous_manifest_sha256")
    if prev is not None and not (isinstance(prev, str) and SHA256_RE.match(prev)):
        errors.append(f"previous_manifest_sha256 must be a 64-hex digest or null")

    intent = manifest.get("intent")
    if not isinstance(intent, dict) or not isinstance(intent.get("raw"), str):
        errors.append("intent.raw must be a string")
    else:
        if len(intent["raw"]) > MAX_INTENT_CHARS:
            errors.append(f"intent.raw exceeds {MAX_INTENT_CHARS} chars")
        if contains_control_chars(intent["raw"]):
            errors.append("intent.raw must not contain control characters")
    if isinstance(intent, dict) and "clarified" in intent:
        clarified = intent["clarified"]
        if clarified is not None and not isinstance(clarified, str):
            errors.append("intent.clarified must be a string or null")
        elif isinstance(clarified, str):
            if len(clarified) > MAX_INTENT_CHARS:
                errors.append(f"intent.clarified exceeds {MAX_INTENT_CHARS} chars")
            if contains_control_chars(clarified):
                errors.append("intent.clarified must not contain control characters")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, list):
        errors.append("inputs must be a list")
    else:
        seen_ids = set()
        for i, item in enumerate(inputs):
            tag = f"inputs[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{tag} must be an object")
                continue
            iid = item.get("input_id")
            if not isinstance(iid, str) or not iid:
                errors.append(f"{tag}.input_id invalid")
            elif iid in seen_ids:
                errors.append(f"{tag}.input_id duplicated")
            if isinstance(iid, str):
                try:
                    validate_identifier(iid, field=f"{tag}.input_id")
                except Exception:
                    errors.append(f"{tag}.input_id invalid")
            seen_ids.add(iid) if isinstance(iid, str) else None
            if item.get("kind") not in INPUT_KINDS:
                errors.append(f"{tag}.kind invalid")
            if item.get("source") not in INPUT_SOURCES:
                errors.append(f"{tag}.source invalid")
            if item.get("disposition") not in DISPOSITIONS:
                errors.append(f"{tag}.disposition invalid")
            elif item.get("disposition") == "excluded" and not (isinstance(item.get("exclusion_reason"), str) and item["exclusion_reason"].strip()):
                errors.append(f"{tag}: excluded input requires exclusion_reason")
            exclusion_reason = item.get("exclusion_reason")
            if exclusion_reason is not None and not isinstance(exclusion_reason, str):
                errors.append(f"{tag}.exclusion_reason must be a string or null")
            elif isinstance(exclusion_reason, str):
                if len(exclusion_reason) > MAX_REASON_CHARS:
                    errors.append(f"{tag}.exclusion_reason exceeds {MAX_REASON_CHARS} chars")
                if contains_control_chars(exclusion_reason):
                    errors.append(f"{tag}.exclusion_reason must not contain control characters")
            if not (isinstance(item.get("content_sha256"), str) and SHA256_RE.match(item["content_sha256"])):
                errors.append(f"{tag}.content_sha256 invalid")
            if isinstance(item.get("content_size"), bool) or not isinstance(item.get("content_size"), int) or item["content_size"] < 0:
                errors.append(f"{tag}.content_size invalid")
            elif item["content_size"] > MAX_INPUT_CONTENT_BYTES:
                errors.append(f"{tag}.content_size exceeds {MAX_INPUT_CONTENT_BYTES} bytes")
            if not isinstance(item.get("content_path"), str) or not item["content_path"]:
                errors.append(f"{tag}.content_path invalid")
            else:
                try:
                    validate_logical_path(item["content_path"])
                except Exception:
                    errors.append(f"{tag}.content_path invalid")

    objective = manifest.get("objective")
    if not isinstance(objective, dict) or not isinstance(objective.get("statement"), str):
        errors.append("objective.statement must be a string")
    else:
        if len(objective["statement"]) > MAX_STATEMENT_CHARS:
            errors.append(f"objective.statement exceeds {MAX_STATEMENT_CHARS} chars")
        if contains_control_chars(objective["statement"]):
            errors.append("objective.statement must not contain control characters")
    if isinstance(objective, dict) and not isinstance(objective.get("desired_outcomes"), list):
        errors.append("objective.desired_outcomes must be a list of strings")
    elif isinstance(objective, dict):
        outcomes = objective.get("desired_outcomes", [])
        if not all(isinstance(o, str) for o in outcomes):
            errors.append("objective.desired_outcomes must be a list of strings")
        elif len(outcomes) > MAX_OUTCOMES:
            errors.append(f"objective.desired_outcomes exceeds {MAX_OUTCOMES} entries")
        elif any(len(o) > MAX_STATEMENT_CHARS for o in outcomes):
            errors.append(f"objective.desired_outcomes entry exceeds {MAX_STATEMENT_CHARS} chars")
        elif any(contains_control_chars(o) for o in outcomes):
            errors.append("objective.desired_outcomes entry must not contain control characters")

    summary = manifest.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("summary must be an object or null")
        else:
            # Content-addressed summary body (ADR-0012 §4 / Finding 2 item 3):
            # the manifest stores digest + size + optional bounded preview;
            # the full body lives in the blob store. An unbounded inline
            # summary.content is rejected.
            if "content" in summary:
                errors.append("summary.content is not allowed (content-addressed body; use digest/size/preview)")
            if not (isinstance(summary.get("digest"), str) and SHA256_RE.match(summary.get("digest", ""))):
                errors.append("summary.digest invalid (64-hex required)")
            if isinstance(summary.get("size"), bool) or not isinstance(summary.get("size"), int) or summary["size"] < 0:
                errors.append("summary.size invalid (non-negative int required)")
            elif summary["size"] > MAX_SUMMARY_BYTES:
                errors.append(f"summary.size exceeds {MAX_SUMMARY_BYTES} bytes")
            preview = summary.get("preview")
            if preview is not None:
                if not isinstance(preview, str):
                    errors.append("summary.preview must be a string or null")
                elif len(preview) > SUMMARY_PREVIEW_MAX_CHARS:
                    errors.append(f"summary.preview exceeds {SUMMARY_PREVIEW_MAX_CHARS} chars")
                if isinstance(preview, str) and contains_control_chars(preview):
                    errors.append("summary.preview must not contain control characters")
            if not _is_iso8601(summary.get("presented_at")):
                errors.append("summary.presented_at must be ISO-8601")
            conf = summary.get("confirmation")
            if not isinstance(conf, dict):
                errors.append("summary.confirmation must be an object")
            else:
                if conf.get("status") not in CONFIRMATION_STATUSES:
                    errors.append("summary.confirmation.status invalid")
                confirmed_sha = conf.get("confirmed_summary_sha256")
                if confirmed_sha is not None and not (isinstance(confirmed_sha, str) and SHA256_RE.match(confirmed_sha)):
                    errors.append("summary.confirmation.confirmed_summary_sha256 invalid")
                if conf.get("status") == "confirmed":
                    if not _is_iso8601(conf.get("confirmed_at")):
                        errors.append("confirmed summary requires confirmed_at")
                    operator_id = conf.get("operator_id")
                    if not isinstance(operator_id, str) or not operator_id:
                        errors.append("confirmed summary requires operator_id")
                    else:
                        try:
                            validate_identifier(operator_id, field="summary.confirmation.operator_id")
                        except Exception:
                            errors.append("summary.confirmation.operator_id invalid identifier")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("artifacts must be a list")
    else:
        seen_art = set()
        for i, art in enumerate(artifacts):
            tag = f"artifacts[{i}]"
            if not isinstance(art, dict):
                errors.append(f"{tag} must be an object")
                continue
            aid = art.get("artifact_id")
            if not isinstance(aid, str) or not aid:
                errors.append(f"{tag}.artifact_id invalid")
            elif aid in seen_art:
                errors.append(f"{tag}.artifact_id duplicated")
            if isinstance(aid, str):
                try:
                    validate_identifier(aid, field=f"{tag}.artifact_id")
                except Exception:
                    errors.append(f"{tag}.artifact_id invalid")
            seen_art.add(aid) if isinstance(aid, str) else None
            if not isinstance(art.get("kind"), str) or not art["kind"]:
                errors.append(f"{tag}.kind invalid")
            elif len(art["kind"]) > MAX_ID_CHARS:
                errors.append(f"{tag}.kind exceeds {MAX_ID_CHARS} chars")
            elif contains_control_chars(art["kind"]):
                errors.append(f"{tag}.kind must not contain control characters")
            else:
                try:
                    validate_identifier(art["kind"], field=f"{tag}.kind")
                except Exception:
                    errors.append(f"{tag}.kind invalid identifier")
            if not isinstance(art.get("logical_path"), str) or not art["logical_path"]:
                errors.append(f"{tag}.logical_path invalid")
            else:
                try:
                    validate_logical_path(art["logical_path"])
                except Exception:
                    errors.append(f"{tag}.logical_path invalid")
            if not (isinstance(art.get("sha256"), str) and SHA256_RE.match(art["sha256"])):
                errors.append(f"{tag}.sha256 invalid")
            if isinstance(art.get("byte_count"), bool) or not isinstance(art.get("byte_count"), int) or art["byte_count"] < 0:
                errors.append(f"{tag}.byte_count invalid")
            elif art["byte_count"] > MAX_ARTIFACT_BODY_BYTES:
                errors.append(f"{tag}.byte_count exceeds {MAX_ARTIFACT_BODY_BYTES} bytes")
            if art.get("status") != "draft":
                errors.append(f"{tag}.status must be 'draft' in v0.1")

    transition = manifest.get("transition")
    if not isinstance(transition, dict):
        errors.append("transition must be an object")
    else:
        for f in ("last_event_id", "last_action_id"):
            v = transition.get(f)
            if v is None:
                continue
            if not isinstance(v, str):
                errors.append(f"transition.{f} must be a string or null")
            else:
                try:
                    validate_identifier(v, field=f"transition.{f}")
                except Exception:
                    errors.append(f"transition.{f} invalid identifier")

    return errors
