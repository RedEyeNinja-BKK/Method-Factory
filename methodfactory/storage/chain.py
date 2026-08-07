"""Authoritative revision-chain invariants and validator (ADR-0012 §F).

This module owns the SINGLE invariant kernel. Both the transactional apply
(storage.store) and the authoritative validator use the same
`check_event_invariants` — there are no competing "apply validity" and
"full-chain validity" implementations with divergent rules.

Enforced invariants per event revision N:

Revision 0:
- action is `create_package`;
- `state_before IS NULL`;
- `previous_manifest_sha256 IS NULL`;
- resulting manifest package_id == indexed package_id;
- resulting manifest revision == 0;
- resulting manifest state == indexed `state_after`;
- stored action JSON hashes to `action_sha256`;
- stored manifest JSON hashes to `resulting_manifest_sha256`.

Revision > 0:
- event N-1 exists and is the immediate predecessor;
- `state_before(N) == state_after(N-1)`;
- `previous_manifest_sha256(N) == resulting_manifest_sha256(N-1)`;
- manifest package_id / revision / state match the indexed row;
- stored action JSON hashes to `action_sha256`;
- stored manifest JSON hashes to `resulting_manifest_sha256`.

All revisions:
- event_id / action_id obey the identifier grammar (uniqueness is schema-
  enforced by the UNIQUE constraints on event_id and (package_id, action_id));
- action is the frozen vocabulary (or `create_package` at revision 0);
- stored JSON BLOBs are valid UTF-8 JSON objects;
- when artifact verification is requested: every referenced input content
  blob, the summary body blob, and every artifact blob exists and verifies
  against its recorded digest.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.transitions import ACTION_VOCABULARY
from ..engine.apply import CREATE_PACKAGE_ACTION
from .errors import ChainViolationError, StorageError
from .paths import validate_identifier
from .serialization import sha256_hex

EVENTS_BY_REVISION_SQL = """
SELECT package_id, revision, event_id, action_id, action, action_sha256,
       state_before, state_after, previous_manifest_sha256,
       resulting_manifest_sha256, created_at, action_json, manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision ASC
"""


def _decode_json_object(data: bytes, what: str, violations: list[str]) -> dict | None:
    """Decode a stored JSON BLOB; report a violation (not raise) on failure."""
    try:
        text = data.decode("utf-8")
    except (UnicodeDecodeError, AttributeError) as exc:
        violations.append(f"{what} is not valid UTF-8: {exc}")
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        violations.append(f"{what} is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        violations.append(f"{what} is not a JSON object")
        return None
    return value


def _bind_manifest_fields(
    manifest: dict[str, Any],
    *,
    package_id: str,
    revision: Any,
    state_after: Any,
    violations: list[str],
) -> None:
    """Shared manifest<->row field-binding checks (single implementation)."""
    if manifest.get("package_id") != package_id:
        violations.append(
            f"manifest package_id {manifest.get('package_id')!r} != indexed {package_id!r}"
        )
    if manifest.get("revision") != revision:
        violations.append(
            f"manifest revision {manifest.get('revision')!r} != indexed {revision!r}"
        )
    if manifest.get("state") != state_after:
        violations.append(
            f"manifest state {manifest.get('state')!r} != indexed state_after {state_after!r}"
        )


def check_event_invariants(
    *,
    package_id: str,
    event: dict[str, Any],
    prev_event: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    verify_artifacts: bool = False,
    artifact_store: Any = None,
    check_schema: bool = False,
    decode_blobs: bool = True,
) -> list[str]:
    """Return every invariant violation for one event (empty = valid).

    `event` / `prev_event` are row dicts whose action_json/manifest_json are
    the RAW stored BLOB bytes. `manifest` is the decoded resulting manifest
    (None when the BLOB could not be decoded; the decode violation is reported
    by this kernel and field checks are skipped).

    Mode flags (single kernel, parameterized — no divergent implementations):
    - `check_schema`: also run the authoritative manifest schema validator on
      the decoded manifest (audit/validator mode; apply validates immediately
      before this call, so it passes False).
    - `decode_blobs`: decode the stored BLOBs to verify JSON validity.
      True for the on-disk validator; the transactional apply passes False
      because the bytes it stores are self-produced and digest-bound.
    """
    violations: list[str] = []
    revision = event.get("revision")
    state_after = event.get("state_after")
    resulting_hash = event.get("resulting_manifest_sha256")
    action_hash = event.get("action_sha256")
    action_name = event.get("action")
    event_id = event.get("event_id")
    action_id = event.get("action_id")

    # ── Stored BLOB validity + digest binding ──────────────────────────
    manifest_from_bytes = None
    if decode_blobs:
        manifest_from_bytes = _decode_json_object(
            event.get("manifest_json"), f"manifest_json({package_id}, rev {revision})", violations
        )
        _decode_json_object(
            event.get("action_json"), f"action_json({package_id}, rev {revision})", violations
        )
    if manifest is None and manifest_from_bytes is not None:
        # Caller (validator) did not pre-decode; use the kernel's decode so
        # field checks still run.
        manifest = manifest_from_bytes
    try:
        if sha256_hex(bytes(event.get("manifest_json"))) != resulting_hash:
            violations.append(
                f"manifest_json({package_id}, rev {revision}) does not hash to resulting_manifest_sha256"
            )
    except (TypeError, ValueError):
        violations.append(f"manifest_json({package_id}, rev {revision}) is not bytes")
    try:
        if sha256_hex(bytes(event.get("action_json"))) != action_hash:
            violations.append(
                f"action_json({package_id}, rev {revision}) does not hash to action_sha256"
            )
    except (TypeError, ValueError):
        violations.append(f"action_json({package_id}, rev {revision}) is not bytes")

    # ── Revision-zero contract ─────────────────────────────────────────
    if revision == 0:
        if action_name != CREATE_PACKAGE_ACTION:
            violations.append(
                f"revision 0 action must be {CREATE_PACKAGE_ACTION!r}, got {action_name!r}"
            )
        if event.get("state_before") is not None:
            violations.append("revision 0 state_before must be NULL")
        if event.get("previous_manifest_sha256") is not None:
            violations.append("revision 0 previous_manifest_sha256 must be NULL")
    else:
        # ── Revision > 0 lineage ───────────────────────────────────────
        if prev_event is None:
            violations.append(f"revision {revision} has no predecessor event")
        else:
            if prev_event.get("revision") != revision - 1:
                violations.append(
                    f"revision {revision} predecessor is revision {prev_event.get('revision')}, "
                    f"expected {revision - 1}"
                )
            if event.get("state_before") != prev_event.get("state_after"):
                violations.append(
                    f"state_before({revision}) != state_after({revision - 1})"
                )
            if event.get("previous_manifest_sha256") != prev_event.get("resulting_manifest_sha256"):
                violations.append(
                    f"previous_manifest_sha256({revision}) != "
                    f"resulting_manifest_sha256({revision - 1})"
                )

    # ── Manifest field binding (runs when a manifest dict is available) ─
    if manifest is not None:
        _bind_manifest_fields(
            manifest, package_id=package_id, revision=revision,
            state_after=state_after, violations=violations,
        )
        # Manifest-internal lineage claims must match the indexed row (the
        # engine writes these as chain facts; the validator cross-checks them).
        # Revision 0 is exempt: the create manifest's transition fields are
        # None by contract (there is no PRIOR action before create).
        if revision != 0:
            if manifest.get("previous_manifest_sha256") != event.get("previous_manifest_sha256"):
                violations.append(
                    "manifest previous_manifest_sha256 does not match the indexed row"
                )
            transition = manifest.get("transition")
            if isinstance(transition, dict):
                if transition.get("last_event_id") != event_id:
                    violations.append(
                        "manifest transition.last_event_id does not match the indexed event_id"
                    )
                if transition.get("last_action_id") != action_id:
                    violations.append(
                        "manifest transition.last_action_id does not match the indexed action_id"
                    )
        # Optional authoritative schema validation (audit/validator mode).
        if check_schema:
            from ..manifest.schema import validate_manifest as _vm

            for schema_error in _vm(manifest):
                violations.append(f"manifest schema violation: {schema_error}")

    # ── Grammar / vocabulary ───────────────────────────────────────────
    for field, value in (("event_id", event_id), ("action_id", action_id)):
        if not isinstance(value, str) or not value:
            violations.append(f"{field} must be a non-empty string")
        else:
            try:
                validate_identifier(value, field=field)
            except Exception as exc:
                violations.append(f"{field} {value!r} violates identifier grammar: {exc}")
    # Revision 0 must be create_package (enforced unconditionally above), so
    # the vocabulary membership check applies to revision > 0 only.
    if revision != 0 and action_name not in ACTION_VOCABULARY:
        violations.append(f"unknown action {action_name!r}")

    # ── Referenced-artifact verification (optional mode) ───────────────
    if verify_artifacts and manifest is not None and artifact_store is not None:
        for entry in manifest.get("inputs", []) or []:
            if not isinstance(entry, dict):
                violations.append("inputs entry is not an object")
                continue
            digest = entry.get("content_sha256")
            if digest and not artifact_store.verify(digest):
                violations.append(f"input {entry.get('input_id')!r} content blob {digest} missing/corrupt")
        summary = manifest.get("summary")
        if isinstance(summary, dict):
            digest = summary.get("digest")
            if digest and not artifact_store.verify(digest):
                violations.append(f"summary body blob {digest} missing/corrupt")
        for art in manifest.get("artifacts", []) or []:
            if not isinstance(art, dict):
                violations.append("artifacts entry is not an object")
                continue
            digest = art.get("sha256")
            if digest and not artifact_store.verify(digest):
                violations.append(f"artifact {art.get('artifact_id')!r} blob {digest} missing/corrupt")

    return violations


def check_current_row_consistency(
    *,
    package_id: str,
    event: dict[str, Any],
    manifest: dict[str, Any],
    manifest_json_bytes: bytes,
    check_schema: bool = True,
) -> list[str]:
    """Hot-path current-row self-consistency (load).

    Deliberately bounded: verifies the decoded manifest against the indexed
    row's identity/state/hash fields WITHOUT scanning history, and runs the
    authoritative schema validator on the single current manifest (bounded to
    one row — never a history scan). Full chain verification belongs to
    `validate_chain`.
    """
    violations: list[str] = []
    _bind_manifest_fields(
        manifest, package_id=package_id, revision=event.get("revision"),
        state_after=event.get("state_after"), violations=violations,
    )
    try:
        if sha256_hex(bytes(manifest_json_bytes)) != event.get("resulting_manifest_sha256"):
            violations.append(
                "manifest_json bytes do not hash to resulting_manifest_sha256"
            )
    except (TypeError, ValueError):
        violations.append("manifest_json is not bytes")
    if check_schema:
        from ..manifest.schema import validate_manifest as _vm

        for schema_error in _vm(manifest):
            violations.append(f"manifest schema violation: {schema_error}")
    return violations


def validate_chain(
    conn: sqlite3.Connection,
    package_id: str,
    *,
    verify_artifacts: bool = False,
    artifact_store: Any = None,
    check_schema: bool = True,
) -> dict[str, Any]:
    """Authoritative revision-chain validator for one package.

    Walks every event in revision order (lazily, one row at a time), applies
    the single invariant kernel per event with BLOB decoding + schema
    validation enabled, and raises ChainViolationError (code CHAIN_VIOLATION)
    with ALL violations of the failing event on the FIRST invalid event.
    Returns a summary on success.
    """
    try:
        cursor = conn.execute(EVENTS_BY_REVISION_SQL, (package_id,))
    except sqlite3.Error as exc:
        raise StorageError(f"chain validation query failed: {exc}") from exc
    row = cursor.fetchone()
    if row is None:
        raise ChainViolationError(f"package {package_id} has no events")

    # Lazy walk: one event at a time, so memory stays bounded to a single
    # event even for long chains (perf, audit path).
    prev_event: dict[str, Any] | None = None
    event_count = 0
    while row is not None:
        event = dict(row)
        event_count += 1
        # The kernel decodes and reports malformed BLOBs as violations, and
        # re-validates the manifest schema (audit mode).
        violations = check_event_invariants(
            package_id=package_id,
            event=event,
            prev_event=prev_event,
            manifest=None,
            verify_artifacts=verify_artifacts,
            artifact_store=artifact_store,
            check_schema=check_schema,
            decode_blobs=True,
        )
        if violations:
            raise ChainViolationError(
                f"chain violation for {package_id} rev {event.get('revision')}: "
                + "; ".join(violations)
            )
        prev_event = event
        row = cursor.fetchone()

    return {"package_id": package_id, "events": event_count, "valid": True}
