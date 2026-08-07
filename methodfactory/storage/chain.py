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
- resulting manifest `created_at` == `updated_at` == indexed `created_at`
  (timestamp contract, invariant-closure review 4885538290);
- stored action JSON hashes to `action_sha256`;
- stored manifest JSON hashes to `resulting_manifest_sha256`.

Revision > 0:
- event N-1 exists and is the immediate predecessor;
- `state_before(N) == state_after(N-1)`;
- `previous_manifest_sha256(N) == resulting_manifest_sha256(N-1)`;
- manifest package_id / revision / state match the indexed row;
- manifest `updated_at` == indexed `created_at`; manifest `created_at` ==
  the revision-0 row `created_at` (threaded through the walk);
- **deterministic replay (invariant closure, review 4885538290):**
  reconstructing the normal ActionEnvelope from the stored canonical action
  and applying the SINGLE deterministic transition engine
  (`engine.apply.next_manifest`) to the predecessor manifest with the
  indexed event_id and event created_at MUST produce exactly the stored
  resulting manifest (canonical bytes equal). This proves the action's
  consequence-bearing fields — input content digest/size/path, objective
  statement/outcomes, summary digest/size/preview/presented_at/confirmation
  (incl. confirmed_at/operator_id/confirmed digest), artifact
  content digest/byte_count/path, state/revision/lineage — without building
  per-action consequence validators;
- stored action JSON hashes to `action_sha256`;
- stored manifest JSON hashes to `resulting_manifest_sha256`.

All revisions:
- event_id / action_id obey the identifier grammar (uniqueness is schema-
  enforced by the UNIQUE constraints on event_id and (package_id, action_id));
- action is the frozen vocabulary (or `create_package` at revision 0);
- stored JSON BLOBs are valid UTF-8 JSON objects AND are stored in the
  canonical serialized form (canonical_bytes(decoded) == stored bytes), with
  digests bound to those canonical bytes;
- the decoded semantic action object is bound back to the indexed event
  (protocol_version, package_id, action_id, action; frozen field set);
- when artifact verification is requested: every referenced input content
  blob, the summary body blob, and every artifact blob exists and verifies
  against its recorded digest.

Replay is **audit-path only**: `validate_chain` enables it; the transactional
apply hot path does not (it just produced the manifest via the same engine,
so replay would be redundant work). Replay is side-effect free: the engine's
`(manifest, blobs_to_write)` return is used for the manifest only — blobs are
discarded, nothing is persisted, and committed blobs are verified only by the
optional artifact-verification mode.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..domain.errors import MethodFactoryError
from ..domain.transitions import ACTION_VOCABULARY
from ..engine.apply import CREATE_PACKAGE_ACTION, next_manifest
from ..protocol.envelope import PROTOCOL_VERSION, envelope_from_dict
from .errors import ChainViolationError, StorageError
from .paths import validate_identifier
from .serialization import canonical_bytes, sha256_hex

EVENTS_BY_REVISION_SQL = """
SELECT package_id, revision, event_id, action_id, action, action_sha256,
       state_before, state_after, previous_manifest_sha256,
       resulting_manifest_sha256, created_at, action_json, manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision ASC
"""

# The frozen semantic-action field set (single canonical serializer output;
# closure review 4882624484-A3). Any deviation is a chain violation.
SEMANTIC_ACTION_FIELDS = frozenset(
    {"protocol_version", "action", "package_id", "action_id", "basis", "payload"}
)


def _check_canonical_form(
    decoded: dict[str, Any],
    stored_bytes: Any,
    expected_hash: str | None,
    what: str,
    violations: list[str],
    canonical: bytes | None = None,
) -> bytes | None:
    """Canonical-form + digest binding (senior review 4882624484, A2).

    The SINGLE implementation of the canonical-JSON invariant used by both the
    validator decode path and the hot-path current-row check:
    1. canonicalize the decoded object with the single canonical serializer;
    2. require canonical_bytes(decoded) == stored bytes (a non-canonical
       representation fails even when its raw-byte hash is recomputed);
    3. when expected_hash is given, require sha256(canonical) == expected_hash.

    Callers that already canonicalized (e.g. the schema validator's single
    pass) pass `canonical` to avoid a second serialization.
    """
    if canonical is None:
        try:
            canonical = canonical_bytes(decoded)
        except (TypeError, RecursionError, UnicodeEncodeError, ValueError) as exc:
            violations.append(f"{what} cannot be canonicalized: {exc}")
            return None
    try:
        stored = bytes(stored_bytes)
    except (TypeError, ValueError):
        violations.append(f"{what} is not bytes")
        return None
    if canonical != stored:
        violations.append(f"{what} is not stored in canonical JSON form")
    if expected_hash is not None and sha256_hex(canonical) != expected_hash:
        violations.append(f"{what} does not hash to its stored digest")
    return canonical


def _decode_canonical_json_object(
    data: Any, what: str, violations: list[str]
) -> tuple[dict | None, bytes | None]:
    """Decode a stored JSON BLOB and canonicalize it (senior review
    4882624484, A2).

    Returns ``(decoded_object, canonical_bytes)`` or ``(None, None)`` after
    reporting a violation for: invalid UTF-8, invalid JSON, a non-object
    value, or a NON-CANONICAL representation. Uses the single canonical
    serialization primitive — no second serializer is created.
    """
    if not isinstance(data, (bytes, bytearray)):
        violations.append(f"{what} is not bytes")
        return None, None
    raw = bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        violations.append(f"{what} is not valid UTF-8: {exc}")
        return None, None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        violations.append(f"{what} is not valid JSON: {exc}")
        return None, None
    if not isinstance(value, dict):
        violations.append(f"{what} is not a JSON object")
        return None, None
    canonical = _check_canonical_form(value, raw, None, what, violations)
    return value, canonical


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


def _bind_timestamp_fields(
    manifest: dict[str, Any],
    event: dict[str, Any],
    *,
    creation_timestamp: str | None,
    violations: list[str],
) -> None:
    """Timestamp contract (invariant-closure review 4885538290).

    Derived from the deterministic transition implementation, not from a
    blanket "every timestamp must match the row" rule:

    - Revision 0: the create manifest is born with
      ``created_at == updated_at == event.created_at`` (``new_manifest``),
      and the A1 semantic action binds ``payload.created_at == event.created_at``,
      so all four agree.
    - Revision > 0: ``next_manifest`` sets ``updated_at = created_at`` (the
      event row timestamp threaded into the engine), and ``created_at`` is
      carried unchanged from revision 0, so ``updated_at == event.created_at``
      and ``created_at == revision-0 created_at``.

    Action-specific timestamps (`summary.presented_at` on `prepare_summary`,
    `summary.confirmation.confirmed_at` on `confirm_summary`) are derived from
    the event timestamp by the engine and are therefore proven by the
    deterministic replay check (canonical equality) — they are not bound
    indiscriminately here.
    """
    revision = event.get("revision")
    row_created = event.get("created_at")
    created = manifest.get("created_at")
    updated = manifest.get("updated_at")
    if revision == 0:
        if created != row_created:
            violations.append(
                f"manifest created_at != indexed created_at at revision 0"
            )
        if updated != row_created:
            violations.append(
                f"manifest updated_at != indexed created_at at revision 0"
            )
    else:
        if updated != row_created:
            violations.append(
                f"manifest updated_at != indexed created_at at revision {revision}"
            )
        if creation_timestamp is not None and created != creation_timestamp:
            violations.append(
                f"manifest created_at != revision-0 created_at at revision {revision}"
            )


def _replay_violations(
    *,
    package_id: str,
    revision: Any,
    event: dict[str, Any],
    action_obj: dict[str, Any] | None,
    prev_manifest: dict[str, Any] | None,
    manifest_canonical: bytes | None,
    violations: list[str],
) -> None:
    """Deterministic action -> resulting-manifest validation (invariant
    closure, review 4885538290).

    Reconstructs the normal internal ActionEnvelope from the stored canonical
    action (injecting `expected_revision = revision - 1`, the only field the
    semantic-action form omits by contract), then applies the SINGLE
    deterministic transition engine to the predecessor manifest with the
    indexed event_id and created_at. The canonical bytes of the replayed
    manifest must equal the stored resulting manifest — this proves every
    consequence-bearing field (input digest/size/path, objective,
    summary digest/size/preview/presented_at/confirmation, artifact
    digest/byte_count/path, state/revision/lineage, updated_at) with one
    rule instead of seven per-action validators.

    Side-effect free: the engine returns `(next_manifest, blobs_to_write)`;
    blobs are discarded here and nothing is persisted during audit replay.
    Blob METADATA is proven by canonical equality; committed-blob integrity
    is verified by the optional artifact-verification mode.

    Fail-closed reconstruction: an unsupported protocol version, unknown
    action, malformed basis/payload, invalid IDs, or invalid payload
    structure all fail via the existing envelope validator — the stored bytes
    are never trusted merely because they were persisted.
    """
    if revision == 0:
        return  # create is validated by its own revision-0 contract, not replay
    if action_obj is None or manifest_canonical is None:
        return  # decode failure already reported by the caller
    if prev_manifest is None:
        violations.append(
            f"deterministic replay unavailable at revision {revision}: "
            "missing predecessor manifest"
        )
        return

    try:
        reconstructed = dict(action_obj)
        reconstructed["expected_revision"] = revision - 1
        envelope = envelope_from_dict(reconstructed)
    except (MethodFactoryError, TypeError, ValueError, UnicodeError, RecursionError) as exc:
        violations.append(
            f"stored action cannot be reconstructed at revision {revision}: {exc}"
        )
        return

    try:
        replayed, blobs = next_manifest(
            prev_manifest,
            envelope,
            event_id=event.get("event_id"),
            created_at=event.get("created_at"),
        )
    except MethodFactoryError as exc:
        violations.append(
            f"stored action is not a legal deterministic transition at revision {revision}: {exc}"
        )
        return
    del blobs  # side-effect free: never persist blobs during audit replay

    try:
        replayed_canonical = canonical_bytes(replayed)
    except (TypeError, RecursionError, UnicodeEncodeError, ValueError) as exc:
        violations.append(
            f"replayed manifest cannot be canonicalized at revision {revision}: {exc}"
        )
        return
    if replayed_canonical != manifest_canonical:
        violations.append(
            f"stored resulting manifest is not the deterministic result of the "
            f"stored action at revision {revision}: replayed digest "
            f"{sha256_hex(replayed_canonical)} != stored "
            f"{sha256_hex(manifest_canonical)}"
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
    prev_manifest: dict[str, Any] | None = None,
    replay: bool = False,
    creation_timestamp: str | None = None,
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
    - `replay`: run the deterministic action -> resulting-manifest replay
      check (audit/full-validation mode only; the apply hot path passes
      False because it just produced the manifest via the same engine).
      Requires `prev_manifest` (decoded predecessor) for revision > 0.
    - `creation_timestamp`: the revision-0 row `created_at`, threaded through
      the walk so every revision > 0 can bind `manifest.created_at` to it and
      `manifest.updated_at` to its own row `created_at`. The create path
      passes the creation timestamp; the apply path passes None (unchanged
      hot path — full timestamp binding is enforced by the authoritative
      validator).
    """
    violations: list[str] = []
    revision = event.get("revision")
    state_after = event.get("state_after")
    resulting_hash = event.get("resulting_manifest_sha256")
    action_hash = event.get("action_sha256")
    action_name = event.get("action")
    event_id = event.get("event_id")
    action_id = event.get("action_id")

    # ── Stored BLOB validity + canonical form + digest binding ─────────
    # (closure review 4882624484-A2): a syntactically valid but non-canonical JSON
    # representation with a recomputed raw-byte hash must FAIL — the digest is
    # bound to the CANONICAL bytes of the decoded object.
    manifest_from_bytes = None
    manifest_canonical = None
    action_obj = None
    action_canonical = None
    if decode_blobs:
        manifest_from_bytes, manifest_canonical = _decode_canonical_json_object(
            event.get("manifest_json"),
            f"manifest_json({package_id}, rev {revision})", violations,
        )
        action_obj, action_canonical = _decode_canonical_json_object(
            event.get("action_json"),
            f"action_json({package_id}, rev {revision})", violations,
        )
    if manifest is None and manifest_from_bytes is not None:
        # Caller (validator) did not pre-decode; use the kernel's decode so
        # field checks still run.
        manifest = manifest_from_bytes

    manifest_raw = None
    if isinstance(event.get("manifest_json"), (bytes, bytearray)):
        manifest_raw = bytes(event["manifest_json"])
    elif decode_blobs:
        # Non-bytes stored types are already reported by the decoder above.
        pass
    else:
        try:
            manifest_raw = bytes(event.get("manifest_json"))
        except (TypeError, ValueError):
            violations.append(f"manifest_json({package_id}, rev {revision}) is not bytes")
    if manifest_raw is not None:
        digest_input = manifest_canonical if manifest_canonical is not None else manifest_raw
        if sha256_hex(digest_input) != resulting_hash:
            violations.append(
                f"manifest_json({package_id}, rev {revision}) does not hash to resulting_manifest_sha256"
            )
    action_raw = None
    if isinstance(event.get("action_json"), (bytes, bytearray)):
        action_raw = bytes(event["action_json"])
    elif decode_blobs:
        pass
    else:
        try:
            action_raw = bytes(event.get("action_json"))
        except (TypeError, ValueError):
            violations.append(f"action_json({package_id}, rev {revision}) is not bytes")
    if action_raw is not None:
        digest_input = action_canonical if action_canonical is not None else action_raw
        if sha256_hex(digest_input) != action_hash:
            violations.append(
                f"action_json({package_id}, rev {revision}) does not hash to action_sha256"
            )

    # ── Semantic-action binding (senior review 4882624484, A3) ─────────
    # Bind the decoded action object back to the indexed event: exact frozen
    # field set, protocol_version, package_id, action_id, action; revision 0
    # requires the canonical create_package structure (including the semantic
    # creation timestamp bound to the row).
    # NOTE (upgrade policy): protocol_version is bound by EXACT equality with
    # the current constant. When PROTOCOL_VERSION increments, historical rows
    # written under the old version must be migrated (recompute canonical
    # action bytes + hashes) before validate_chain — see ADR-0012 §G / the
    # migration slice. Fail-closed is deliberate.
    if action_obj is not None:
        awhat = f"action_json({package_id}, rev {revision})"
        if set(action_obj.keys()) != SEMANTIC_ACTION_FIELDS:
            violations.append(
                f"{awhat} is not a canonical semantic action (field set mismatch)"
            )
        else:
            if action_obj.get("protocol_version") != PROTOCOL_VERSION:
                violations.append(f"{awhat} protocol_version != {PROTOCOL_VERSION!r}")
            if action_obj.get("package_id") != package_id:
                violations.append(f"{awhat} package_id != indexed {package_id!r}")
            if action_obj.get("action_id") != action_id:
                violations.append(f"{awhat} action_id != indexed {action_id!r}")
            if action_obj.get("action") != action_name:
                violations.append(f"{awhat} action != indexed action {action_name!r}")
            if not isinstance(action_obj.get("basis"), dict) or not isinstance(
                action_obj.get("payload"), dict
            ):
                violations.append(f"{awhat} basis/payload must be objects")
            if revision == 0:
                if action_obj.get("action") != CREATE_PACKAGE_ACTION:
                    violations.append(f"{awhat} action must be create_package")
                if action_obj.get("basis") != {}:
                    violations.append(f"{awhat} basis must be empty")
                payload = action_obj.get("payload")
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("intent"), str
                ):
                    violations.append(
                        f"{awhat} payload must contain intent string"
                    )
                if not isinstance(payload, dict) or payload.get("created_at") != event.get("created_at"):
                    violations.append(
                        f"{awhat} payload.created_at != indexed created_at"
                    )

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
        # Timestamp contract (invariant-closure review 4885538290): revision-0
        # created_at/updated_at and revision>0 updated_at/created_at row
        # bindings derived from the deterministic transition implementation.
        _bind_timestamp_fields(
            manifest, event, creation_timestamp=creation_timestamp, violations=violations,
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

    # ── Deterministic replay (invariant-closure review 4885538290) ───────
    # Audit-path only: the stored action, replayed through the SINGLE
    # deterministic transition engine over the predecessor manifest, must
    # reproduce the stored resulting manifest exactly. Proves every
    # consequence-bearing field with one rule. Side-effect free (blobs
    # returned by the engine are discarded).
    if replay:
        _replay_violations(
            package_id=package_id,
            revision=revision,
            event=event,
            action_obj=action_obj,
            prev_manifest=prev_manifest,
            manifest_canonical=manifest_canonical,
            violations=violations,
        )

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
    # Canonical-form + digest binding (senior review 4882624484, A2) with a
    # SINGLE canonicalization: the schema validator's canonical pass feeds the
    # A2 compare/hash, so the hot path does not serialize the manifest twice.
    from ..manifest.schema import validate_manifest_canonical as _vmc

    schema_errors, manifest_canonical = _vmc(manifest)
    if check_schema:
        for schema_error in schema_errors:
            violations.append(f"manifest schema violation: {schema_error}")
    _check_canonical_form(
        manifest,
        manifest_json_bytes,
        event.get("resulting_manifest_sha256"),
        f"manifest_json({package_id})",
        violations,
        canonical=manifest_canonical,
    )
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
    validation + deterministic replay enabled, and raises ChainViolationError
    (code CHAIN_VIOLATION) with ALL violations of the failing event on the
    FIRST invalid event. Returns a summary on success.

    This is the explicit full-chain/audit validation path: it replays every
    revision > 0 through the deterministic transition engine (side-effect
    free) and enforces the timestamp contract. The hot paths (load/apply) do
    not replay history.
    """
    try:
        cursor = conn.execute(EVENTS_BY_REVISION_SQL, (package_id,))
    except sqlite3.Error as exc:
        raise StorageError(f"chain validation query failed: {exc}") from exc
    row = cursor.fetchone()
    if row is None:
        raise ChainViolationError(f"package {package_id} has no events")

    # Lazy walk: one event at a time, so memory stays bounded to a single
    # event even for long chains (perf, audit path). prev_manifest is the
    # decoded predecessor manifest needed for deterministic replay;
    # creation_timestamp is threaded from the revision-0 row for the
    # timestamp contract.
    prev_event: dict[str, Any] | None = None
    prev_manifest: dict[str, Any] | None = None
    creation_timestamp: str | None = None
    event_count = 0
    while row is not None:
        event = dict(row)
        event_count += 1
        # The kernel decodes and reports malformed BLOBs as violations, and
        # re-validates the manifest schema + deterministic replay (audit mode).
        violations = check_event_invariants(
            package_id=package_id,
            event=event,
            prev_event=prev_event,
            prev_manifest=prev_manifest,
            replay=True,
            creation_timestamp=creation_timestamp,
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
        if event.get("revision") == 0:
            creation_timestamp = event.get("created_at")
        prev_event = event
        # Decode the just-validated manifest for the NEXT event's replay
        # (bounded to one predecessor; a decode failure here is impossible for
        # a validated event and would fail the next replay closed).
        scratch: list[str] = []
        pm, _ = _decode_canonical_json_object(
            event.get("manifest_json"),
            f"manifest_json({package_id}, rev {event.get('revision')})",
            scratch,
        )
        prev_manifest = pm
        row = cursor.fetchone()

    return {"package_id": package_id, "events": event_count, "valid": True}
