"""SqliteManifestStore — transactional create/load/apply (ADR-0012 §6, §8).

This is the canonical transactional persistence implementation. Every
mutation executes as ONE bounded transaction:

    BEGIN IMMEDIATE
    1.  Validate the incoming Action Envelope and its canonical semantic
        action (envelope_from_dict + canonical_action_bytes).
    2.  Compute the canonical action_sha256 (hash of the exact stored bytes).
    3.  Look up (package_id, action_id) BEFORE stale-revision rejection.
    4.  If the action ID already exists:
        * same canonical hash  -> return the previously committed result
          (no second insert);
        * different hash       -> raise ACTION_ID_CONFLICT.
    5.  Load the indexed latest event for the package.
    6.  Compare expected_revision to the authoritative current revision.
    7.  Apply the deterministic state transition (engine.apply.next_manifest).
    8.  Produce the complete resulting manifest.
    9.  Validate the resulting manifest and all transaction/chain invariants
        (single kernel: storage.chain.check_event_invariants).
    10. Verify every newly referenced artifact blob (content blobs written
        via the immutable ArtifactStore; all new references verified).
    11. Canonicalize the stored action and resulting manifest once.
    12. Insert exactly one immutable event row.
    13. COMMIT.

The numbered algorithm is authoritative in docs/public-surface.md
(Transaction algorithm); this docstring is the short invariant summary.

On any failure before commit: roll back, insert no event, do not mutate
historical rows, do not delete prewritten content-addressed blobs (they are
immutable and harmless if orphaned).

Package creation freezes revision-zero semantics: created ONLY by the
canonical create_package operation, revision 0, state_before NULL, no
predecessor manifest hash, initial valid state INTAKE, one valid complete
manifest, exactly one event. Duplicate create raises PACKAGE_EXISTS unless
it is an exact idempotent replay of the original creation action.

Concurrency: BEGIN IMMEDIATE + the binding busy_timeout (5000 ms). A lock
contention that exceeds the timeout surfaces as ConcurrencyError
(CONCURRENCY), never a raw sqlite exception. One store owns one connection;
use one store per thread/process for real concurrency.

No mutable head table, lock files, JSONL repair, journal framing, cache
reconciliation, or second notion of canonical state are introduced.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable

from ..domain.errors import (
    ConcurrencyError,
    DuplicatePackageError,
    InvalidPayloadError,
    MethodFactoryError,
    StaleActionError,
)
from ..engine.apply import CREATE_PACKAGE_ACTION, next_manifest
from ..manifest.schema import new_manifest, validate_manifest_canonical
from ..protocol.envelope import PROTOCOL_VERSION, envelope_from_dict
from ..storage.errors import (
    ActionIdConflictError,
    ArtifactVerificationError,
    ManifestInvalidError,
    PackageNotFoundError,
    StorageError,
)
from ..storage.limits import MAX_INTENT_CHARS
from ..storage.paths import validate_package_id, validate_store_root
from ..storage.serialization import (
    canonical_action_bytes,
    contains_control_chars,
    sha256_hex,
)
from ..storage.sqlite import (
    close_database,
    explain_latest_event_plan,
    latest_event_row,
    open_database,
)
from .chain import (
    check_current_row_consistency,
    check_event_invariants,
    validate_chain as _validate_chain,
)

# ── SQL ────────────────────────────────────────────────────────────────
INSERT_EVENT_SQL = """
INSERT INTO events (
    package_id, revision, event_id, action_id, action, action_sha256,
    state_before, state_after, previous_manifest_sha256,
    resulting_manifest_sha256, created_at, action_json, manifest_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

ACTION_LOOKUP_SQL = """
SELECT package_id, revision, action_sha256, state_after,
       resulting_manifest_sha256, created_at, manifest_json
FROM events
WHERE package_id = ? AND action_id = ?
"""

EVENTS_ALL_SQL = """
SELECT package_id, revision, event_id, action_id, action, action_sha256,
       state_before, state_after, previous_manifest_sha256,
       resulting_manifest_sha256, created_at, action_json, manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision ASC
"""


# ── Transaction seams + fault hooks (tests inject precise single-point
#    faults through the REAL implementation path) ───────────────────────
FAULT_HOOK: Callable[[str], None] | None = None


def _fault(stage: str) -> None:
    if FAULT_HOOK is not None:
        FAULT_HOOK(stage)


def _begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _insert_event(conn: sqlite3.Connection, row: tuple) -> None:
    conn.execute(INSERT_EVENT_SQL, row)


def _commit(conn: sqlite3.Connection) -> None:
    conn.commit()


def _rollback(conn: sqlite3.Connection) -> None:
    conn.rollback()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_created_at(value: str | None) -> str:
    """Normalize a caller-supplied creation timestamp to canonical UTC ISO-8601.

    Semantic identity (senior review 4882624484, A1): ``fromisoformat`` then
    ``astimezone(UTC)`` collapses every spelling of the SAME INSTANT to one
    canonical text form (``Z``, ``+00:00``, any offset), so retries from any
    timezone replay identically. Naive/date-only timestamps are rejected: the
    manifest contract requires an explicit UTC offset (no ambiguous local
    wall-clock time in the identity).
    """
    if value is None:
        return _utcnow()
    if not isinstance(value, str):
        raise InvalidPayloadError(
            f"created_at must be an ISO-8601 string, got {type(value).__name__}"
        )
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidPayloadError(
            f"created_at is not valid ISO-8601: {value!r}"
        ) from exc
    if dt.tzinfo is None:
        raise InvalidPayloadError(
            "created_at must include a UTC offset (naive timestamps are "
            "ambiguous in the creation identity)"
        )
    return dt.astimezone(timezone.utc).isoformat()


def _is_locked(exc: sqlite3.Error) -> bool:
    """Classify retryable SQLite lock contention by extended error code,
    falling back to the message heuristic only for interpreters without
    sqlite_errorcode."""
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    text = str(exc).lower()
    return "locked" in text or "busy" in text


class _Transaction:
    """One bounded BEGIN IMMEDIATE transaction.

    Owns begin/commit/rollback; on any exception before commit the
    transaction rolls back (no event, no historical mutation). `_fault`
    stages fire inside the body so fault injection is unchanged. The
    translation ladder lives in the store methods' outer try.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self) -> "_Transaction":
        _fault("before_begin")
        _begin(self._conn)
        try:
            _fault("after_begin")
        except BaseException:
            # A fault after BEGIN but before the body must not leak an open
            # write transaction: roll back before re-raising.
            try:
                _rollback(self._conn)
            except sqlite3.Error:
                pass
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            try:
                _commit(self._conn)
            except BaseException:
                # Commit failure: the seam raises before the database commits;
                # roll back so no transaction leaks into the next operation.
                try:
                    _rollback(self._conn)
                except sqlite3.Error:
                    pass
                raise
        else:
            try:
                _rollback(self._conn)
            except sqlite3.Error:
                pass
        return False  # propagate


def _event_row_tuple(e: dict[str, Any]) -> tuple:
    return (
        e["package_id"], e["revision"], e["event_id"], e["action_id"],
        e["action"], e["action_sha256"], e["state_before"], e["state_after"],
        e["previous_manifest_sha256"], e["resulting_manifest_sha256"],
        e["created_at"], e["action_json"], e["manifest_json"],
    )


def _decode_json_blob(raw: Any, *, what: str, package_id: str) -> dict[str, Any]:
    if not isinstance(raw, (bytes, str)):
        raise ManifestInvalidError(
            f"{what} for {package_id} has unexpected type {type(raw).__name__}"
        )
    try:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, json.JSONDecodeError,
            TypeError, ValueError, RecursionError) as exc:
        raise ManifestInvalidError(
            f"{what} corrupt for {package_id}: {exc}"
        ) from exc
    if not isinstance(decoded, dict):
        raise ManifestInvalidError(
            f"{what} for {package_id} is not a JSON object"
        )
    return decoded


def _find_action(
    conn: sqlite3.Connection, package_id: str, action_id: str
) -> dict[str, Any] | None:
    row = conn.execute(ACTION_LOOKUP_SQL, (package_id, action_id)).fetchone()
    return dict(row) if row is not None else None


def _decode_and_check_row(
    event: dict[str, Any], *, package_id: str
) -> dict[str, Any]:
    """Decode a stored manifest and run the bounded current-row consistency
    check (identity/state/digest + schema). Used by load() and the idempotent
    replay paths so every path that returns a stored manifest applies the same
    verification."""
    manifest = _decode_json_blob(event["manifest_json"], what="stored manifest",
                                 package_id=package_id)
    try:
        violations = check_current_row_consistency(
            package_id=package_id,
            event=event,
            manifest=manifest,
            manifest_json_bytes=bytes(event["manifest_json"]),
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ManifestInvalidError(
            f"consistency check failed for {package_id}: {exc}",
            package_id=package_id,
        ) from exc
    if violations:
        raise ManifestInvalidError(
            f"consistency violation for {package_id}: {violations[0]}",
            package_id=package_id,
        )
    return manifest


def _verify_new_references(
    next_m: dict[str, Any],
    current_m: dict[str, Any],
    artifacts: "ArtifactStore",
    package_id: str,
) -> None:
    """Verify every newly referenced artifact blob (transaction step 10)."""
    old_inputs = {(i or {}).get("input_id") for i in (current_m.get("inputs") or [])}
    for entry in next_m.get("inputs") or []:
        if entry.get("input_id") not in old_inputs:
            digest = entry.get("content_sha256")
            if digest and not artifacts.verify(digest):
                raise ArtifactVerificationError(
                    f"input {entry.get('input_id')!r} content blob {digest} missing/corrupt",
                    package_id=package_id,
                )
    old_arts = {(a or {}).get("artifact_id") for a in (current_m.get("artifacts") or [])}
    for art in next_m.get("artifacts") or []:
        if art.get("artifact_id") not in old_arts:
            digest = art.get("sha256")
            if digest and not artifacts.verify(digest):
                raise ArtifactVerificationError(
                    f"artifact {art.get('artifact_id')!r} blob {digest} missing/corrupt",
                    package_id=package_id,
                )
    if (current_m.get("summary") is None) and isinstance(next_m.get("summary"), dict):
        digest = next_m["summary"].get("digest")
        if digest and not artifacts.verify(digest):
            raise ArtifactVerificationError(
                f"summary body blob {digest} missing/corrupt",
                package_id=package_id,
            )


class SqliteManifestStore:
    """Canonical transactional store over the frozen SQLite model."""

    def __init__(self, root: "str | Path", *, artifact_store: "ArtifactStore | None" = None) -> None:
        from ..adapters.artifact_store import ArtifactStore  # lazy: avoids import cycle

        self._root = validate_store_root(root)
        self._conn = open_database(self._root, read_only=False)
        try:
            self._artifacts = (
                artifact_store if artifact_store is not None else ArtifactStore(self._root)
            )
        except BaseException:
            close_database(self._conn)
            raise

    # ── create ─────────────────────────────────────────────────────────
    def create(
        self, package_id: str, intent_raw: str, created_at: str | None = None
    ) -> dict[str, Any]:
        """Create a package at revision 0 (exactly one event).

        `created_at` is SEMANTIC (closure review 4882624484-A1): the normalized creation
        timestamp is part of the canonical create_package semantic action and
        therefore of the resulting action_sha256. A repeat with the same
        package/intent but a DIFFERENT timestamp is NOT an exact replay — it
        raises DuplicatePackageError. Omitted -> internal UTC now.

        Duplicate create raises DuplicatePackageError unless it is an exact
        idempotent replay of the original creation action (same deterministic
        action_id + same semantic action hash including the timestamp).
        """
        validate_package_id(package_id)
        if not isinstance(intent_raw, str):
            raise InvalidPayloadError("intent_raw must be a string")
        if len(intent_raw) > MAX_INTENT_CHARS:
            raise InvalidPayloadError(
                f"intent_raw exceeds {MAX_INTENT_CHARS} chars"
            )
        if contains_control_chars(intent_raw):
            raise InvalidPayloadError(
                "intent_raw must not contain control characters"
            )
        created_at_provided = created_at is not None
        created_at = _normalize_created_at(created_at)
        action_id = f"act_create_{package_id}"
        event_id = f"evt_{package_id}_0"

        action_bytes = canonical_action_bytes(
            protocol_version=PROTOCOL_VERSION,
            action=CREATE_PACKAGE_ACTION,
            package_id=package_id,
            action_id=action_id,
            basis={},
            payload={"intent": intent_raw, "created_at": created_at},
        )
        action_hash = sha256_hex(action_bytes)

        conn = self._conn
        try:
            with _Transaction(conn):
                existing = _find_action(conn, package_id, action_id)
                if existing is not None:
                    if not created_at_provided:
                        # Omitted timestamp on a retry: idempotent replay uses
                        # the STORED creation time (A1) so a caller that did
                        # not pin a timestamp can replay the original create.
                        action_bytes = canonical_action_bytes(
                            protocol_version=PROTOCOL_VERSION,
                            action=CREATE_PACKAGE_ACTION,
                            package_id=package_id,
                            action_id=action_id,
                            basis={},
                            payload={
                                "intent": intent_raw,
                                "created_at": existing["created_at"],
                            },
                        )
                        action_hash = sha256_hex(action_bytes)
                    if existing["action_sha256"] == action_hash:
                        return _decode_and_check_row(existing, package_id=package_id)
                    # The package exists and the requested creation differs
                    # (different intent or an EXPLICIT different timestamp).
                    # Per the create contract, attempting to create an existing
                    # package returns the stable PACKAGE_EXISTS error — exact
                    # idempotent replay is the only accepted repeat.
                    raise DuplicatePackageError(
                        f"package {package_id} already exists", package_id=package_id
                    )
                latest = latest_event_row(conn, package_id)
                if latest is not None:
                    raise DuplicatePackageError(
                        f"package {package_id} already exists", package_id=package_id
                    )
                manifest = new_manifest(package_id, intent_raw, created_at)
                violations, manifest_bytes = validate_manifest_canonical(manifest)
                if violations:
                    raise ManifestInvalidError(
                        f"new manifest invalid: {violations[0]}", package_id=package_id
                    )
                event = {
                    "package_id": package_id,
                    "revision": 0,
                    "event_id": event_id,
                    "action_id": action_id,
                    "action": CREATE_PACKAGE_ACTION,
                    "action_sha256": action_hash,
                    "state_before": None,
                    "state_after": manifest["state"],
                    "previous_manifest_sha256": None,
                    "resulting_manifest_sha256": sha256_hex(manifest_bytes),
                    "created_at": created_at,
                    "action_json": action_bytes,
                    "manifest_json": manifest_bytes,
                }
                violations = check_event_invariants(
                    package_id=package_id, event=event, prev_event=None,
                    manifest=manifest, decode_blobs=False,
                    creation_timestamp=created_at,
                )
                if violations:
                    raise ManifestInvalidError(
                        f"chain invariant violation on create: {violations[0]}",
                        package_id=package_id,
                    )
                _fault("before_insert")
                _insert_event(conn, _event_row_tuple(event))
                _fault("after_insert")
                return manifest
        except MethodFactoryError:
            raise
        except sqlite3.OperationalError as exc:
            if _is_locked(exc):
                raise ConcurrencyError(
                    f"database is locked: {exc}", package_id=package_id
                ) from exc
            raise StorageError(
                f"create failed for {package_id}: {exc}", package_id=package_id
            ) from exc
        except (sqlite3.Error, OSError, ValueError, TypeError, UnicodeError,
                RecursionError) as exc:
            raise StorageError(
                f"create failed for {package_id}: {exc}", package_id=package_id
            ) from exc

    # ── apply ──────────────────────────────────────────────────────────
    def apply(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Apply one action envelope in one bounded transaction.

        `envelope` is the parsed Action Envelope dict (see parse_envelope /
        envelope_from_dict). Idempotency lookup (step 3) happens BEFORE the
        stale-revision comparison (step 6): a retry of an already-committed
        action replays the previous result even with an older
        expected_revision; reusing an action_id with a different semantic
        hash always returns ACTION_ID_CONFLICT.
        """
        if not isinstance(envelope, dict):
            raise InvalidPayloadError("envelope must be a JSON object")
        env = envelope_from_dict(envelope)  # INVALID_ENVELOPE on schema failure
        # package_id grammar is enforced authoritatively by envelope_from_dict
        # (InvalidEnvelopeError); no redundant re-validation here.
        package_id = env.package_id

        action_bytes = canonical_action_bytes(
            protocol_version=PROTOCOL_VERSION,
            action=env.action,
            package_id=package_id,
            action_id=env.action_id,
            basis=env.basis,
            payload=env.payload,
        )
        action_hash = sha256_hex(action_bytes)
        created_at = _utcnow()

        conn = self._conn
        try:
            with _Transaction(conn):
                existing = _find_action(conn, package_id, env.action_id)
                if existing is not None:
                    if existing["action_sha256"] == action_hash:
                        # Idempotent replay BEFORE stale check: return the
                        # previously committed result (consistency-verified),
                        # insert nothing.
                        return _decode_and_check_row(existing, package_id=package_id)
                    raise ActionIdConflictError(
                        f"action_id {env.action_id!r} reused with different content "
                        f"for {package_id}",
                        package_id=package_id,
                    )
                latest = latest_event_row(conn, package_id)
                if latest is None:
                    raise PackageNotFoundError(
                        f"package {package_id} does not exist", package_id=package_id
                    )
                if env.expected_revision != latest["revision"]:
                    raise StaleActionError(
                        f"expected revision {env.expected_revision}, "
                        f"current {latest['revision']}",
                        package_id=package_id,
                        state=latest["state_after"],
                        expected_revision=env.expected_revision,
                        actual_revision=latest["revision"],
                    )
                current_manifest = _decode_and_check_row(dict(latest), package_id=package_id)
                _fault("after_state_load")

                new_revision = latest["revision"] + 1
                event_id = f"evt_{package_id}_{new_revision}"
                next_m, blobs = next_manifest(
                    current_manifest, env, event_id=event_id, created_at=created_at
                )
                _fault("after_transition")

                # Single canonicalization: validate AND obtain the exact
                # canonical bytes that will be stored (perf: no second pass).
                violations, manifest_bytes = validate_manifest_canonical(next_m)
                if violations:
                    raise ManifestInvalidError(
                        f"resulting manifest invalid: {violations[0]}", package_id=package_id
                    )
                _fault("after_manifest_validate")

                for path, content in blobs:
                    self._artifacts.put(package_id, path, content)
                _verify_new_references(next_m, current_manifest, self._artifacts, package_id)
                _fault("after_artifact_verify")

                event = {
                    "package_id": package_id,
                    "revision": new_revision,
                    "event_id": event_id,
                    "action_id": env.action_id,
                    "action": env.action,
                    "action_sha256": action_hash,
                    "state_before": latest["state_after"],
                    "state_after": next_m["state"],
                    "previous_manifest_sha256": latest["resulting_manifest_sha256"],
                    "resulting_manifest_sha256": sha256_hex(manifest_bytes),
                    "created_at": created_at,
                    "action_json": action_bytes,
                    "manifest_json": manifest_bytes,
                }
                violations = check_event_invariants(
                    package_id=package_id,
                    event=event,
                    prev_event=dict(latest),
                    manifest=next_m,
                    decode_blobs=False,  # self-produced bytes; digest-bound
                )
                if violations:
                    raise ManifestInvalidError(
                        f"chain invariant violation on apply: {violations[0]}",
                        package_id=package_id,
                    )
                _fault("before_insert")
                _insert_event(conn, _event_row_tuple(event))
                _fault("after_insert")
                return next_m
        except MethodFactoryError:
            raise
        except sqlite3.OperationalError as exc:
            if _is_locked(exc):
                raise ConcurrencyError(
                    f"database is locked: {exc}", package_id=package_id
                ) from exc
            raise StorageError(
                f"apply failed for {package_id}: {exc}", package_id=package_id
            ) from exc
        except (sqlite3.Error, OSError, ValueError, TypeError, UnicodeError,
                RecursionError) as exc:
            raise StorageError(
                f"apply failed for {package_id}: {exc}", package_id=package_id
            ) from exc

    # ── load ───────────────────────────────────────────────────────────
    def load(self, package_id: str) -> dict[str, Any]:
        """Return the complete current manifest via the indexed latest-event
        query only (never a history scan). Raises PackageNotFoundError for a
        missing package; validates current-row consistency (identity/state/
        digest binding + schema) so obviously mismatched rows are never
        returned."""
        validate_package_id(package_id)
        # latest_event_row already translates sqlite3.Error -> StorageError.
        row = latest_event_row(self._conn, package_id)
        if row is None:
            raise PackageNotFoundError(
                f"package {package_id} does not exist", package_id=package_id
            )
        return _decode_and_check_row(dict(row), package_id=package_id)

    # ── read_events (ordered audit/export primitive) ───────────────────
    def read_events(self, package_id: str) -> list[dict[str, Any]]:
        """Return every event for a package in revision order, with the
        stored action/manifest BLOBs decoded to JSON objects."""
        validate_package_id(package_id)
        try:
            rows = self._conn.execute(EVENTS_ALL_SQL, (package_id,)).fetchall()
        except sqlite3.Error as exc:
            raise StorageError(
                f"read_events failed for {package_id}: {exc}", package_id=package_id
            ) from exc
        events: list[dict[str, Any]] = []
        for row in rows:
            ev = dict(row)
            ev["action_json"] = _decode_json_blob(
                ev["action_json"], what="stored action", package_id=package_id)
            ev["manifest_json"] = _decode_json_blob(
                ev["manifest_json"], what="stored manifest", package_id=package_id)
            events.append(ev)
        return events

    # ── authoritative chain validator (delegates to the single kernel) ──
    def validate_chain(
        self, package_id: str, *, verify_artifacts: bool = False
    ) -> dict[str, Any]:
        """Run the authoritative revision-chain validator for one package.

        Raises ChainViolationError on the first invariant violation.
        """
        validate_package_id(package_id)
        return _validate_chain(
            self._conn,
            package_id,
            verify_artifacts=verify_artifacts,
            artifact_store=self._artifacts,
        )

    # ── query-plan evidence ────────────────────────────────────────────
    def explain_latest_plan(self, package_id: str) -> list[tuple]:
        """EXPLAIN QUERY PLAN for the hot-path latest-event lookup."""
        return explain_latest_event_plan(self._conn, package_id)

    def list_package_ids(self) -> list[str]:
        """Return distinct package ids in deterministic (id) order."""
        rows = self._conn.execute(
            "SELECT DISTINCT package_id FROM events ORDER BY package_id"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        close_database(self._conn)
