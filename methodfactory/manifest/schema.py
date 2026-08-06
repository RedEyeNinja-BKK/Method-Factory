"""Manifest Contract v0.1 — schema and read-only validation (ADR-0004)."""

from __future__ import annotations

from datetime import datetime

from ..domain.states import State
from ..domain.vocabulary import DISPOSITIONS, INPUT_KINDS, INPUT_SOURCES, PACKAGE_ID_RE, SHA256_RE

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

CONFIRMATION_STATUSES = frozenset({"pending", "confirmed"})


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
    """Collect all schema/invariant violations (read-only; no state change)."""
    errors: list[str] = []

    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

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
            seen_ids.add(iid)
            if item.get("kind") not in INPUT_KINDS:
                errors.append(f"{tag}.kind invalid")
            if item.get("source") not in INPUT_SOURCES:
                errors.append(f"{tag}.source invalid")
            if item.get("disposition") not in DISPOSITIONS:
                errors.append(f"{tag}.disposition invalid")
            elif item.get("disposition") == "excluded" and not str(item.get("exclusion_reason") or "").strip():
                errors.append(f"{tag}: excluded input requires exclusion_reason")
            if not (isinstance(item.get("content_sha256"), str) and SHA256_RE.match(item["content_sha256"])):
                errors.append(f"{tag}.content_sha256 invalid")
            if not isinstance(item.get("content_size"), int) or item["content_size"] < 0:
                errors.append(f"{tag}.content_size invalid")
            if not isinstance(item.get("content_path"), str) or not item["content_path"]:
                errors.append(f"{tag}.content_path invalid")

    objective = manifest.get("objective")
    if not isinstance(objective, dict) or not isinstance(objective.get("statement"), str):
        errors.append("objective.statement must be a string")
    if not isinstance(objective.get("desired_outcomes"), list) or not all(
        isinstance(o, str) for o in objective.get("desired_outcomes", [])
    ):
        errors.append("objective.desired_outcomes must be a list of strings")

    summary = manifest.get("summary")
    if summary is not None:
        if not isinstance(summary, dict):
            errors.append("summary must be an object or null")
        else:
            if not isinstance(summary.get("content"), str):
                errors.append("summary.content must be a string")
            if not (isinstance(summary.get("canonical_sha256"), str) and SHA256_RE.match(summary["canonical_sha256"])):
                errors.append("summary.canonical_sha256 invalid")
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
                    if not isinstance(conf.get("operator_id"), str):
                        errors.append("confirmed summary requires operator_id")

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
            seen_art.add(aid)
            if not isinstance(art.get("kind"), str) or not art["kind"]:
                errors.append(f"{tag}.kind invalid")
            if not isinstance(art.get("logical_path"), str) or not art["logical_path"]:
                errors.append(f"{tag}.logical_path invalid")
            if not (isinstance(art.get("sha256"), str) and SHA256_RE.match(art["sha256"])):
                errors.append(f"{tag}.sha256 invalid")
            if not isinstance(art.get("byte_count"), int) or art["byte_count"] < 0:
                errors.append(f"{tag}.byte_count invalid")
            if art.get("status") != "draft":
                errors.append(f"{tag}.status must be 'draft' in v0.1")

    transition = manifest.get("transition")
    if not isinstance(transition, dict):
        errors.append("transition must be an object")
    else:
        for f in ("last_event_id", "last_action_id"):
            v = transition.get(f)
            if v is not None and not isinstance(v, str):
                errors.append(f"transition.{f} must be a string or null")

    return errors
