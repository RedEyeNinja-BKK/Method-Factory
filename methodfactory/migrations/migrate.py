"""Atomic v0.1.2 → current SQLite migration (ADR-0012 amendment).

Frozen algorithm (ADR-0012 amendment §7-§15):

1. validate CLI arguments;
2. resolve canonical source root; positive public v0.1.2 layout detection;
3. inventory/hash immutable source set (BEFORE);
4. open legacy source read-only (frozen reader);
5. full legacy validation (v0.1.2 semantics; fail closed on ambiguity);
6. per package (sorted package IDs, journal line order):
     a. rev 0: preserve legacy event_id + action_id "act_create_package";
        build current create semantic action;
     b. rev>0: reconstruct semantic action; require stored legacy
        action_sha256 == legacy hash of the unique candidate;
        if no unique candidate -> MIGRATION_INCOMPATIBLE;
     c. build current ActionEnvelope;
     d. run CURRENT next_manifest(predecessor, envelope,
        event_id=legacy event_id, created_at=legacy event.at);
     e. semantic equivalence check vs legacy snapshot (exclusions only);
7. calculate destination + temporary destination (same directory);
15. generate migration receipt data;
16. durably write temp receipt;
17. FINAL source inventory/hash (AFTER) — require exact equality with step 3;
18. ONLY THEN enter publication:
     a. durable final receipt publication (no-clobber os.link temp -> final;
        dir fsync);
     b. durable atomic final DB publication (no-clobber os.link temp DB ->
        final; dir fsync);
19. final read-only verification (binds the published receipt to the DB).

A receipt alone is NOT success. Success requires: final DB exists; matching
final receipt exists; same migration identity; final read-only validation
succeeds. Crash states fail closed with explicit operator instructions.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import uuid
from pathlib import Path
from typing import Any, Callable

from ..adapters.artifact_store import ArtifactStore
from ..domain.errors import (
    ActionIdReuseError,
    ConcurrencyError,
    GateUnsatisfiedError,
    IllegalTransitionError,
    InvalidEnvelopeError,
    InvalidPayloadError,
    ManifestInvalidError,
    MethodFactoryError,
    StaleActionError,
)
from ..engine.apply import CREATE_PACKAGE_ACTION, next_manifest
from ..protocol.envelope import PROTOCOL_VERSION, envelope_from_dict
from ..storage.errors import (
    ChainViolationError,
    DestinationExistsError,
    MigrationIncompatibleError,
    MigrationPublishFailedError,
    SourceChangedError,
    StorageError,
)
from ..storage.paths import DB_FILENAME
from ..storage.serialization import canonical_bytes, sha256_hex
from ..storage.sqlite import (
    APPLICATION_ID,
    USER_VERSION,
    close_database,
    open_database,
    readonly_uri,
)
from .v012_jsonl import (
    LEGACY_ACTION_CREATE,
    LEGACY_COMMIT,
    LEGACY_TAG,
    LegacySource,
    legacy_action_hash_semantic,
)

# Receipt format identity.
RECEIPT_FORMAT = "method-factory-migration-receipt"
RECEIPT_VERSION = "v1"

# ── Fault seams (tests inject precise single-point faults through the REAL
#    implementation path, matching the store.py FAULT_HOOK pattern) ──────
FAULT_HOOK: "Callable[[str], None] | None" = None


def _fault(stage: str) -> None:
    if FAULT_HOOK is not None:
        FAULT_HOOK(stage)

INSERT_EVENT_SQL = """
INSERT INTO events (
    package_id, revision, event_id, action_id, action, action_sha256,
    state_before, state_after, previous_manifest_sha256,
    resulting_manifest_sha256, created_at, action_json, manifest_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── semantic-action reconstruction ────────────────────────────────────
def _reconstruct_rev0(source: LegacySource, pkg, ev) -> dict:
    """Build the current create semantic action from a legacy rev-0 event.

    Preserves legacy event_id and action_id "act_create_package".
    """
    snap = ev.manifest_snapshot
    intent = snap.get("intent") or {}
    intent_raw = intent.get("raw")
    if not isinstance(intent_raw, str):
        raise MigrationIncompatibleError(
            f"revision 0 intent is not reconstructable for {pkg.package_id}"
        )
    created_at = ev.at
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": CREATE_PACKAGE_ACTION,
        "package_id": pkg.package_id,
        "action_id": LEGACY_ACTION_CREATE,
        "basis": {},
        "payload": {"intent": intent_raw, "created_at": created_at},
    }


def _candidate_hashes(source: LegacySource, pkg, ev, candidates: list[dict]) -> list[dict]:
    """Return candidates whose legacy hash matches the stored legacy hash."""
    matches = []
    for cand in candidates:
        if legacy_action_hash_semantic(cand) == ev.action_sha256:
            matches.append(cand)
    return matches


def _reconstruct_record_input(source: LegacySource, pkg, ev) -> dict:
    snap = ev.manifest_snapshot
    entry = snap["inputs"][-1]
    blob = source.artifact_bytes(entry["content_sha256"])
    try:
        content = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationIncompatibleError(
            f"record_input content for {pkg.package_id} rev {ev.revision} "
            f"is not valid UTF-8"
        ) from exc
    # Candidate: exclusion_reason omitted vs null (finite).
    candidates = []
    base = {
        "input_id": entry["input_id"],
        "kind": entry["kind"],
        "content": content,
        "source": entry["source"],
        "disposition": entry["disposition"],
    }
    omitted = _semantic(pkg, ev, dict(base))
    candidates.append(omitted)
    nulled = dict(base)
    nulled["exclusion_reason"] = None
    candidates.append(_semantic(pkg, ev, nulled))
    if entry.get("exclusion_reason") is not None:
        explicit = dict(base)
        explicit["exclusion_reason"] = entry["exclusion_reason"]
        candidates.append(_semantic(pkg, ev, explicit))
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"record_input semantic action not uniquely reconstructable for "
            f"{pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_set_objective(source: LegacySource, pkg, ev) -> dict:
    snap = ev.manifest_snapshot
    obj = snap["objective"]
    candidates = []
    omitted = _semantic(pkg, ev, {"statement": obj["statement"]})
    candidates.append(omitted)
    explicit = _semantic(
        pkg, ev,
        {"statement": obj["statement"],
         "desired_outcomes": obj.get("desired_outcomes", [])},
    )
    candidates.append(explicit)
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"set_objective semantic action not uniquely reconstructable for "
            f"{pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_prepare_summary(source: LegacySource, pkg, ev) -> dict:
    candidates = [_semantic(pkg, ev, {})]
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"prepare_summary semantic action not uniquely reconstructable for "
            f"{pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_confirm_summary(source: LegacySource, pkg, ev) -> dict:
    snap = ev.manifest_snapshot
    summary = snap.get("summary") or {}
    conf = summary.get("confirmation") or {}
    confirmed_sha = conf.get("confirmed_summary_sha256") or summary.get(
        "canonical_sha256"
    )
    basis = {"summary_sha256": confirmed_sha}
    op_value = conf.get("operator_id")
    candidates = []
    if op_value == "operator":
        # operator default may derive from omitted / null / "" / "operator".
        for op in (None, "", "operator"):
            candidates.append(_semantic(pkg, ev, {"operator_id": op}, basis=basis))
        omitted = _semantic(pkg, ev, {}, basis=basis)
        candidates.append(omitted)
    else:
        candidates.append(_semantic(pkg, ev, {"operator_id": op_value}, basis=basis))
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"confirm_summary semantic action not uniquely reconstructable for "
            f"{pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_revise_intake(source: LegacySource, pkg, ev) -> dict:
    candidates = [_semantic(pkg, ev, {})]
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"revise_intake semantic action not uniquely reconstructable for "
            f"{pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_record_draft_artifact(source: LegacySource, pkg, ev) -> dict:
    snap = ev.manifest_snapshot
    art = snap["artifacts"][-1]
    blob = source.artifact_bytes(art["sha256"])
    try:
        content = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationIncompatibleError(
            f"artifact content for {pkg.package_id} rev {ev.revision} "
            f"is not valid UTF-8"
        ) from exc
    payload = {
        "artifact_id": art["artifact_id"],
        "kind": art["kind"],
        "logical_path": art["logical_path"],
        "content": content,
    }
    candidate = _semantic(pkg, ev, payload)
    matches = _candidate_hashes(source, pkg, ev, [candidate])
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"record_draft_artifact semantic action not uniquely "
            f"reconstructable for {pkg.package_id} rev {ev.revision}"
        )
    return matches[0]


def _reconstruct_cancel(source: LegacySource, pkg, ev) -> dict:
    # Arbitrary reason is not recoverable from the snapshot. Finite
    # candidates: omitted / null / empty string. If none matches, fail closed.
    candidates = [
        _semantic(pkg, ev, {}),
        _semantic(pkg, ev, {"reason": None}),
        _semantic(pkg, ev, {"reason": ""}),
    ]
    matches = _candidate_hashes(source, pkg, ev, candidates)
    if len(matches) != 1:
        raise MigrationIncompatibleError(
            f"cancel semantic action is not reconstructable for "
            f"{pkg.package_id} rev {ev.revision}: reason not recoverable from "
            "persisted public evidence"
        )
    return matches[0]


def _semantic(pkg, ev, payload, basis=None) -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "action": ev.action,
        "package_id": pkg.package_id,
        "action_id": ev.action_id,
        "basis": basis or {},
        "payload": payload,
    }


def _reconstruct_action(source: LegacySource, pkg, ev) -> dict:
    """Reconstruct the exact six-field historical semantic action.

    Returns the current-valid semantic action object (protocol_version is
    current; other fields preserved) after unique hash verification.
    """
    action = ev.action
    if action == "record_input":
        return _reconstruct_record_input(source, pkg, ev)
    if action == "set_objective":
        return _reconstruct_set_objective(source, pkg, ev)
    if action == "prepare_summary":
        return _reconstruct_prepare_summary(source, pkg, ev)
    if action == "confirm_summary":
        return _reconstruct_confirm_summary(source, pkg, ev)
    if action == "revise_intake":
        return _reconstruct_revise_intake(source, pkg, ev)
    if action == "record_draft_artifact":
        return _reconstruct_record_draft_artifact(source, pkg, ev)
    if action == "cancel":
        return _reconstruct_cancel(source, pkg, ev)
    raise MigrationIncompatibleError(
        f"unknown legacy action {action!r} for {pkg.package_id} rev {ev.revision}"
    )


# ── current-envelope construction ─────────────────────────────────────
def _to_envelope(semantic: dict, expected_revision: int):
    env_dict = dict(semantic)
    env_dict["expected_revision"] = expected_revision
    return envelope_from_dict(env_dict)


# ── migration driver ──────────────────────────────────────────────────
def migrate_store(
    source_root: str | Path,
    dest: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen migration. Returns the receipt dict."""
    source = LegacySource(source_root)
    source.validate()

    # Destination default: <source>/methodfactory.sqlite3
    src = Path(source_root)
    final_dest = Path(dest) if dest is not None else (src / DB_FILENAME)
    # Reject a symlinked destination ROOT before resolving: resolve() would
    # follow the link and the lstat gate below would never see it. Only the
    # destination root leaf is gated (mirroring the source-side reader);
    # ancestor symlinks are intentionally not rejected here.
    dest_parent = final_dest.parent
    if dest_parent.is_symlink():
        raise StorageError(
            f"destination root {dest_parent} must not be a symlink"
        )
    final_dest = final_dest.resolve()
    if final_dest.exists():
        raise DestinationExistsError(f"migration destination exists: {final_dest}")

    # Lock refusal: any applicable legacy .lock file -> CONCURRENCY.
    locks = sorted(source.events_dir.glob("*.lock"))
    if locks:
        raise ConcurrencyError(
            f"legacy lock file(s) present; refusing to start migration: "
            + ", ".join(str(p) for p in locks)
        )

    before = source.source_inventory()
    _fault("after_source_inventory_before")

    # Build temp destination (same directory as final for atomic rename).
    # NOTE: the current API treats a store path as a ROOT DIRECTORY (it
    # appends DB_FILENAME and creates blobs/). The temp build therefore uses
    # a temp root directory; publication moves the DB FILE to the final path.
    #
    # Never chmod an EXISTING destination root: when --dest is omitted the
    # default root IS the legacy source root, and mutating its permissions
    # would violate source immutability (ADR-0012 §12). Only newly-created
    # roots get the private mode. An EXISTING root must already satisfy the
    # current store-root invariant (0700, ADR-0012 §D): otherwise the
    # published store could not be reopened by the standard public API, so
    # migration fails closed with operator instructions rather than
    # publishing an unreopenable store.
    final_root = final_dest.parent
    root_existed = final_root.is_dir()
    # Atomically claim the destination root leaf and pin its inode.
    # An unconditional lstat/S_ISLNK/S_ISDIR/mode gate runs for BOTH
    # existing and freshly-created roots: never trust a path that could
    # have been swapped between mkdir and chmod (chmod follows symlinks).
    root_fd: int | None = None
    try:
        if root_existed:
            # Leaf already exists; exist_ok=True no-ops (kept for the
            # remove-between-check-and-mkdir race).
            final_root.mkdir(parents=True, exist_ok=True)
        else:
            # Atomically claim the leaf; a racer's leaf is treated as
            # pre-existing (never chmod a directory we did not create).
            try:
                final_root.mkdir(parents=True, mode=0o700)
            except FileExistsError:
                root_existed = True
            if not root_existed:
                # mkdir(mode=0o700) is umask-masked; pin the inode we
                # created and fchmod it so the 0700 guarantee holds under
                # ANY umask WITHOUT a path-based chmod that could follow a
                # swapped symlink.
                root_fd = os.open(
                    final_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                os.fchmod(root_fd, 0o700)
    except OSError as exc:
        if root_fd is not None:
            os.close(root_fd)
        raise StorageError(
            f"cannot create destination parent directory: {exc}"
        ) from exc
    # Reject a non-directory or symlinked destination root. is_dir() follows
    # symlinks; the mode gate below must not bless a file or a link.
    try:
        st = final_root.lstat()
    except OSError as exc:
        if root_fd is not None:
            os.close(root_fd)
        raise StorageError(
            f"cannot stat destination root {final_root}: {exc}"
        ) from exc
    if stat.S_ISLNK(st.st_mode):
        if root_fd is not None:
            os.close(root_fd)
        raise StorageError(
            f"destination root {final_root} must not be a symlink"
        )
    if not stat.S_ISDIR(st.st_mode):
        if root_fd is not None:
            os.close(root_fd)
        raise StorageError(
            f"destination root {final_root} exists but is not a directory"
        )
    root_mode = st.st_mode & 0o777
    if root_mode != 0o700:
        if root_fd is not None:
            os.close(root_fd)
        raise StorageError(
            f"destination root {final_root} has mode {root_mode:03o}, "
            "expected 0700 (ADR-0012 §D store-root invariant). Fix the "
            "root permissions or pass an explicit --dest under a private "
            "root; the legacy source root is never chmod'd by migration."
        )
    if root_fd is not None:
        os.close(root_fd)
    temp_root = final_root / f".{final_dest.name}.tmp.{uuid.uuid4().hex}"
    # Pre-create the temp root private (umask-immune) with fd-pinned fchmod.
    # open_database's own root.mkdir() is umask-masked; a hostile umask
    # would otherwise leave the temp dir without owner-execute and SQLite
    # could not open it.
    try:
        os.mkdir(temp_root, mode=0o700)
        _fault("after_temp_root_mkdir")
        tfd = os.open(
            temp_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            os.fchmod(tfd, 0o700)
        finally:
            os.close(tfd)
    except OSError as exc:
        # Failure before use: remove the created temp dir so no orphan
        # accumulates under the destination root.
        try:
            temp_root.rmdir()
        except OSError:
            pass
        raise StorageError(
            f"cannot create temporary store root {temp_root}: {exc}"
        ) from exc

    # Build the modern store. Blobs publish to the FINAL artifact store root
    # (orphan-safe on failure; ADR-0012 §11), while the DB builds at temp_root.
    # chmod_existing=False: the default destination root IS the legacy source
    # root; its permissions must not be mutated (ADR-0012 §12 source
    # immutability). ArtifactStore init is INSIDE the try so its failure also
    # cleans up temp_root (no orphan accumulates).
    try:
        artifacts = ArtifactStore(final_root, chmod_existing=False)
        _fault("before_build_store")
        _build_store(temp_root, source, artifacts)
        _fault("after_build_store")

        # Full validation before publication.
        _validate_temp_store(temp_root, artifacts)
        _fault("after_validate_temp_store")

        # Source stability proof BEFORE publication.
        after = source.source_inventory()
        _fault("after_source_inventory_after")
        if after != before:
            raise SourceChangedError(
                "legacy source changed during migration; destination not published"
            )
    except BaseException:
        # Failure before publication: remove the temp DB root. Blobs already
        # published to the final artifact root are orphan-safe (ADR-0012 §11).
        import shutil

        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        raise

    # Publication: receipt first, then DB (ADR-0012 §11).
    receipt = _build_receipt(source, before)
    temp_receipt = final_dest.with_name(
        f".{final_dest.name}.receipt.tmp.{uuid.uuid4().hex}"
    )
    final_receipt = final_dest.with_name(final_dest.name + ".receipt.json")

    db_replaced = False
    try:
        _fault("before_receipt_write")
        _write_durable(temp_receipt, receipt)
        _fault("before_receipt_replace")
        _publish_noclobber(temp_receipt, final_receipt)
        _fault("before_dir_fsync_receipt")
        _fsync_dir(final_root)
        _fault("before_db_replace")
        _publish_noclobber(temp_root / DB_FILENAME, final_dest)
        db_replaced = True
        _fault("before_dir_fsync_db")
        _fsync_dir(final_root)
        _fault("after_publication")
    except BaseException as exc:
        # Clean up temp artifacts; never leave a partial publication claimed.
        import shutil

        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        for p in (temp_receipt,):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # A durable PASS receipt without its database is a misleading crash
        # state: remove the final receipt unless the DB itself was already
        # published (DB-with-receipt is complete-but-unverified; the raise
        # below prevents any success claim).
        if not db_replaced:
            try:
                if final_receipt.exists():
                    final_receipt.unlink()
            except OSError:
                pass
        if isinstance(exc, MethodFactoryError):
            raise
        raise MigrationPublishFailedError(
            "migration publication failed; the destination may be incomplete. "
            f"Operator instructions: if {final_receipt.name} exists without "
            f"{final_dest.name}, remove the receipt and re-run. If both exist, "
            f"run `mf export`/validation to confirm the DB, then re-run after "
            f"removing the destination. Cause: {exc}"
        ) from exc

    # Success-path hygiene: the temp root dir is now empty (DB file moved out).
    import shutil

    if temp_root.exists():
        shutil.rmtree(temp_root, ignore_errors=True)

    # Final read-only verification (binds the published receipt to the DB).
    _fault("before_final_verify")
    _verify_final(final_dest, receipt=receipt)
    _fault("after_final_verify")

    return receipt


def _build_store(temp_root: Path, source: LegacySource, artifacts: ArtifactStore) -> None:
    conn = open_database(temp_root, read_only=False)
    try:
        for package_id in sorted(source.packages.keys()):
            pkg = source.packages[package_id]
            _import_package(conn, source, pkg, artifacts)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        close_database(conn)


def _import_package(
    conn: sqlite3.Connection,
    source: LegacySource,
    pkg,
    artifacts: ArtifactStore,
) -> None:
    previous_manifest: dict | None = None
    for ev in pkg.events:
        try:
            manifest = _import_event(
                conn, source, pkg, ev, previous_manifest, artifacts
            )
        except MigrationIncompatibleError:
            raise
        except (
            # Current-boundary rejections of legacy-valid historical values
            # are MIGRATION_INCOMPATIBLE (ADR-0012 §7), never leaked as
            # engine/validator errors.
            InvalidEnvelopeError,
            InvalidPayloadError,
            ManifestInvalidError,
            IllegalTransitionError,
            GateUnsatisfiedError,
            StaleActionError,
            ActionIdReuseError,
            ChainViolationError,
        ) as exc:
            raise MigrationIncompatibleError(
                f"legacy value for {pkg.package_id} rev {ev.revision} is "
                f"current-invalid: {exc}"
            ) from exc
        except UnicodeEncodeError as exc:
            # A journal-sourced field (intent, created_at, event_id, state,
            # summary body, ...) that cannot be UTF-8 encoded (lone
            # surrogate) must fail typed at the migration boundary, never
            # leak a raw UnicodeEncodeError from canonicalization or the
            # SQLite TEXT bind.
            raise MigrationIncompatibleError(
                f"legacy value for {pkg.package_id} rev {ev.revision} is "
                f"not valid UTF-8: {exc}"
            ) from exc
        except sqlite3.IntegrityError as exc:
            # Duplicate event_id (global uniqueness) or other row-integrity
            # violation -> MIGRATION_INCOMPATIBLE (ADR-0012 §7 event-ID
            # global uniqueness), never a raw sqlite error.
            raise MigrationIncompatibleError(
                f"legacy value for {pkg.package_id} rev {ev.revision} "
                f"violates destination row integrity: {exc}"
            ) from exc
        previous_manifest = manifest


def _import_event(
    conn: sqlite3.Connection,
    source: LegacySource,
    pkg,
    ev,
    previous_manifest: dict | None,
    artifacts: ArtifactStore,
) -> dict:
    if ev.revision == 0:
        semantic = _reconstruct_rev0(source, pkg, ev)
        # Build the modern rev-0 manifest deterministically (create_package
        # is NOT an envelope action; migration inserts the row directly,
        # preserving legacy event_id/action_id).
        from ..manifest.schema import new_manifest

        created_at = semantic["payload"]["created_at"]
        manifest = new_manifest(
            pkg.package_id, semantic["payload"]["intent"], created_at
        )
        manifest_bytes = canonical_bytes(manifest)
        blobs: list = []
    else:
        semantic = _reconstruct_action(source, pkg, ev)
        env = _to_envelope(semantic, expected_revision=ev.revision - 1)
        next_m, blobs = next_manifest(
            previous_manifest,
            env,
            event_id=ev.event_id,
            created_at=ev.at,
        )
        manifest = next_m
        manifest_bytes = canonical_bytes(manifest)

    # Publish blobs via current immutable store (orphan-safe).
    for path, content in blobs:
        artifacts.put(pkg.package_id, path, content)

    # Verify semantic equivalence vs legacy snapshot (excluded: hashes,
    # summary inline body, normalized timestamps, lineage hashes).
    _verify_equivalence(ev, manifest)

    action_bytes = canonical_bytes(semantic)
    action_hash = sha256_hex(action_bytes)
    resulting_hash = sha256_hex(manifest_bytes)
    prev_hash = (
        None
        if ev.revision == 0
        else sha256_hex(canonical_bytes(previous_manifest))
    )

    row = (
        pkg.package_id, ev.revision, ev.event_id, semantic["action_id"],
        semantic["action"], action_hash,
        ev.state_before, ev.state_after, prev_hash, resulting_hash,
        ev.at, action_bytes, manifest_bytes,
    )
    conn.execute(INSERT_EVENT_SQL, row)
    return manifest


def _verify_equivalence(ev, manifest: dict) -> None:
    """Compare current manifest to legacy snapshot on surviving semantics."""
    snap = ev.manifest_snapshot
    # identity / state / revision
    if manifest.get("package_id") != snap.get("package_id"):
        raise MigrationIncompatibleError("package_id mismatch after transform")
    if manifest.get("revision") != ev.revision:
        raise MigrationIncompatibleError("revision mismatch after transform")
    if manifest.get("state") != snap.get("state"):
        raise MigrationIncompatibleError("state mismatch after transform")
    # intent
    if manifest.get("intent") != snap.get("intent"):
        raise MigrationIncompatibleError("intent mismatch after transform")
    # inputs (content bytes verified by digest)
    mi = manifest.get("inputs", [])
    si = snap.get("inputs", [])
    if len(mi) != len(si):
        raise MigrationIncompatibleError("inputs count mismatch after transform")
    for a, b in zip(mi, si):
        for field in ("input_id", "kind", "source", "disposition",
                      "exclusion_reason", "content_sha256", "content_size",
                      "content_path"):
            if a.get(field) != b.get(field):
                raise MigrationIncompatibleError(
                    f"input field {field} mismatch after transform"
                )
    # objective
    if manifest.get("objective") != snap.get("objective"):
        raise MigrationIncompatibleError("objective mismatch after transform")
    # summary: compare semantic confirmation + digest-vs-canonical_sha256
    ms = manifest.get("summary")
    ss = snap.get("summary")
    if (ms is None) != (ss is None):
        raise MigrationIncompatibleError("summary presence mismatch after transform")
    if ms is not None and ss is not None:
        if ms.get("digest") != ss.get("canonical_sha256"):
            raise MigrationIncompatibleError("summary digest mismatch after transform")
        if ms.get("size") != len((ss.get("content") or "").encode("utf-8")):
            raise MigrationIncompatibleError("summary size mismatch after transform")
        mc = ms.get("confirmation") or {}
        sc = ss.get("confirmation") or {}
        # Normalized timestamps (confirmed_at/presented_at) are excluded by
        # ADR-0012 §9: current engine derives them from created_at=legacy
        # event.at, not the legacy engine's distinct intermediate clocks.
        for field in ("status", "operator_id", "confirmed_summary_sha256"):
            if mc.get(field) != sc.get(field):
                raise MigrationIncompatibleError(
                    f"summary confirmation {field} mismatch after transform"
                )
    # artifacts
    ma = manifest.get("artifacts", [])
    sa = snap.get("artifacts", [])
    if len(ma) != len(sa):
        raise MigrationIncompatibleError("artifacts count mismatch after transform")
    for a, b in zip(ma, sa):
        for field in ("artifact_id", "kind", "logical_path", "sha256",
                      "byte_count", "status"):
            if a.get(field) != b.get(field):
                raise MigrationIncompatibleError(
                    f"artifact field {field} mismatch after transform"
                )
    # transition IDs (preserved historical). Rev-0 has {None, None} by
    # contract in BOTH eras (no prior action); rev>0 must match the legacy
    # event's preserved IDs.
    mt = manifest.get("transition") or {}
    st = snap.get("transition") or {}
    if ev.revision == 0:
        if mt.get("last_event_id") is not None or mt.get("last_action_id") is not None:
            raise MigrationIncompatibleError(
                "revision 0 transition must be null in the modern manifest"
            )
    else:
        if mt.get("last_event_id") != ev.event_id:
            raise MigrationIncompatibleError("transition last_event_id mismatch")
        if mt.get("last_action_id") != ev.action_id:
            raise MigrationIncompatibleError("transition last_action_id mismatch")
        if st.get("last_event_id") != ev.event_id:
            raise MigrationIncompatibleError(
                "legacy snapshot transition last_event_id inconsistent"
            )


def _validate_temp_store(temp_root: Path, artifacts: ArtifactStore) -> None:
    conn = open_database(temp_root, read_only=False)
    try:
        # integrity check
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise StorageError("temporary SQLite integrity_check failed")
    finally:
        close_database(conn)
    # authoritative full chain validation via a store wrapper
    from ..storage.store import SqliteManifestStore

    store = SqliteManifestStore(temp_root, artifact_store=artifacts)
    try:
        for package_id in store.list_package_ids():
            try:
                store.validate_chain(package_id, verify_artifacts=True)
            except ChainViolationError as exc:
                # Current-manifest rejection of a migrated legacy value is
                # MIGRATION_INCOMPATIBLE (ADR-0012 §7), never a raw chain
                # error from the validator.
                raise MigrationIncompatibleError(
                    f"migrated chain for {package_id} is current-invalid: {exc}"
                ) from exc
    finally:
        store.close()


def _verify_final(final_dest: Path, receipt: dict | None = None) -> None:
    """Read-only verification of the FINAL DB FILE (not a store root).

    Opens the exact file path read-only; never creates or mutates. When a
    receipt dict is provided (the one just published), its semantic identity
    is validated against the final DB so a mismatched or stale receipt can
    never be reported as success (ADR-0012 §11 success predicate).
    """
    import sqlite3

    db = final_dest.resolve()
    uri = readonly_uri(db)
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise MigrationPublishFailedError(
                "final database failed read-only integrity_check"
            )
        app = int(conn.execute("PRAGMA application_id").fetchone()[0])
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if app != APPLICATION_ID or ver != USER_VERSION:
            raise MigrationPublishFailedError(
                "final database identity mismatch after publication"
            )
        if receipt is not None:
            _verify_receipt_against_db(final_dest, receipt, conn)
    except sqlite3.Error as exc:
        raise MigrationPublishFailedError(
            f"final database read-only verification failed: {exc}"
        ) from exc
    finally:
        if conn is not None:
            conn.close()


def _verify_receipt_against_db(
    final_dest: Path, receipt: dict, conn: sqlite3.Connection
) -> None:
    """Bind the published receipt to the published DB (success predicate)."""
    pkg_count = int(
        conn.execute("SELECT COUNT(DISTINCT package_id) FROM events").fetchone()[0]
    )
    ev_count = int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    if receipt.get("destination_package_count") != pkg_count:
        raise MigrationPublishFailedError(
            "published receipt package count does not match final database"
        )
    if receipt.get("destination_event_count") != ev_count:
        raise MigrationPublishFailedError(
            "published receipt event count does not match final database"
        )
    if receipt.get("validation_verdict") != "PASS":
        raise MigrationPublishFailedError(
            "published receipt does not carry a PASS verdict"
        )
    # The receipt must be the exact file that was just published.
    receipt_path = final_dest.with_name(final_dest.name + ".receipt.json")
    try:
        on_disk = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MigrationPublishFailedError(
            f"cannot re-read published receipt {receipt_path}: {exc}"
        ) from exc
    if on_disk != receipt:
        raise MigrationPublishFailedError(
            "published receipt does not match the migration result"
        )


def _build_receipt(source: LegacySource, before: dict) -> dict:
    src_event_count = sum(len(p.events) for p in source.packages.values())
    dst_event_count = src_event_count  # 1:1 revision mapping
    return {
        "receipt_format": RECEIPT_FORMAT,
        "receipt_version": RECEIPT_VERSION,
        "legacy_source_format": "v0.1.2-integrity",
        "legacy_source_commit": LEGACY_COMMIT,
        "legacy_source_tag": LEGACY_TAG,
        "semantic_source_inventory": before,
        "source_package_count": len(source.packages),
        "source_event_count": src_event_count,
        "destination_schema_application_id": APPLICATION_ID,
        "destination_schema_version": USER_VERSION,
        "destination_package_count": len(source.packages),
        "destination_event_count": dst_event_count,
        "migration_implementation": "methodfactory.migrations",
        "validation_verdict": "PASS",
    }


def _write_durable(path: Path, data: dict) -> None:
    """Write `data` durably to the caller-supplied unique temp path (fsync).

    The caller publishes via `_publish_noclobber`; this function only
    ensures the temp content is on disk before publication. Content is JSON
    canonical, UTF-8, one object.
    """
    # O_EXCL: the temp path must never pre-exist or follow a raced symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False))
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _publish_noclobber(src: Path, dst: Path) -> None:
    """Atomically publish src to dst WITHOUT overwriting an existing dst.

    Uses the same no-clobber hard-link primitive as the artifact store
    (ADR-0007): os.link fails if dst exists, so a raced destination is never
    replaced. On FileExistsError the publication is aborted with a typed
    error (the caller fails closed).

    After a SUCCESSFUL link the destination is published; the temp source
    unlink is best-effort. A temp-unlink failure is NOT fatal: an orphan
    `.tmp.*` file is harmless and a re-raise here would falsely report the
    publication as failed while the destination is already complete.
    """
    try:
        os.link(src, dst)
    except FileExistsError:
        raise DestinationExistsError(
            f"publication destination appeared during migration: {dst}"
        ) from None
    except OSError as exc:
        raise MigrationPublishFailedError(
            f"cannot publish {dst}: {exc}"
        ) from exc
    # Best-effort cleanup of the temp source after successful publication.
    try:
        src.unlink()
    except OSError:
        pass  # published-but-unclean; orphan temp is harmless


def _fsync_dir(path: Path) -> None:
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
