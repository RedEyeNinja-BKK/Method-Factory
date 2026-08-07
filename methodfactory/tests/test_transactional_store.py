"""Transactional store tests — create/load/apply, idempotency, concurrency,
rollback fault injection, and query-plan evidence (ADR-0012 §6/§8).

Every mutation runs the single BEGIN IMMEDIATE transaction; failures roll
back with no event inserted, no historical row mutated, and no blob deleted.
Concurrency is proven with separate connections AND separate processes.
"""

from __future__ import annotations

import multiprocessing as mp
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from methodfactory.domain.errors import (
    ConcurrencyError,
    DuplicatePackageError,
    GateUnsatisfiedError,
    IllegalTransitionError,
    InvalidPayloadError,
    MethodFactoryError,
    StaleActionError,
)
from methodfactory.storage import store as store_mod
from methodfactory.storage.errors import (
    ActionIdConflictError,
    ArtifactVerificationError,
    ManifestInvalidError,
    PackageNotFoundError,
    StorageError,
)
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.store import SqliteManifestStore


def _envelope(action, *, action_id, expected_revision, package_id="pkg_demo_001",
              basis=None, payload=None):
    return {
        "protocol_version": "0.1",
        "action_id": action_id,
        "package_id": package_id,
        "expected_revision": expected_revision,
        "action": action,
        "basis": basis or {},
        "payload": payload or {},
    }


def _record_input(action_id="act_in_1", expected_revision=0, input_id="in_1",
                  content="hello", package_id="pkg_demo_001"):
    return _envelope(
        "record_input", action_id=action_id, expected_revision=expected_revision,
        package_id=package_id,
        payload={"input_id": input_id, "kind": "text", "content": content,
                 "source": "operator", "disposition": "incorporated"},
    )


def _set_objective(action_id="act_obj_1", expected_revision=1):
    return _envelope(
        "set_objective", action_id=action_id, expected_revision=expected_revision,
        payload={"statement": "Build a skill", "desired_outcomes": ["ship it"]},
    )


def _prepare_summary(action_id="act_prep_1", expected_revision=2):
    return _envelope("prepare_summary", action_id=action_id,
                     expected_revision=expected_revision)


def _confirm_summary(digest, action_id="act_conf_1", expected_revision=3):
    return _envelope("confirm_summary", action_id=action_id,
                     expected_revision=expected_revision,
                     basis={"summary_sha256": digest}, payload={"operator_id": "vincent"})


def _record_draft(action_id="act_art_1", expected_revision=4):
    return _envelope(
        "record_draft_artifact", action_id=action_id,
        expected_revision=expected_revision,
        payload={"artifact_id": "art_1", "kind": "skill",
                 "logical_path": "skills/x/SKILL.md", "content": "body"},
    )


def _cancel(action_id="act_cancel_1", expected_revision=5):
    return _envelope("cancel", action_id=action_id,
                     expected_revision=expected_revision,
                     payload={"reason": "done"})


def _full_lifecycle(store, package_id="pkg_demo_001"):
    m0 = store.create(package_id, "Build a skill", created_at="2026-08-07T00:00:00+00:00")
    m1 = store.apply(_record_input(expected_revision=0))
    m2 = store.apply(_set_objective(expected_revision=1))
    m3 = store.apply(_prepare_summary(expected_revision=2))
    digest = m3["summary"]["digest"]
    m4 = store.apply(_confirm_summary(digest, expected_revision=3))
    m5 = store.apply(_record_draft(expected_revision=4))
    m6 = store.apply(_cancel(expected_revision=5))
    return [m0, m1, m2, m3, m4, m5, m6]


def _event_count(root) -> int:
    with sqlite3.connect(str(root / DB_FILENAME)) as c:
        return c.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def _event_revisions(root) -> list[int]:
    with sqlite3.connect(str(root / DB_FILENAME)) as c:
        rows = c.execute("SELECT revision FROM events ORDER BY revision").fetchall()
        return [r[0] for r in rows]


def _latest_revision(root) -> int | None:
    with sqlite3.connect(str(root / DB_FILENAME)) as c:
        row = c.execute("SELECT MAX(revision) FROM events").fetchone()
        return row[0]


def _latest_row(root) -> dict:
    with sqlite3.connect(str(root / DB_FILENAME)) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM events ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        return dict(row)


class CreateTests(unittest.TestCase):
    def test_create_revision_zero(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                m = store.create("pkg_demo_001", "Build a skill",
                                 created_at="2026-08-07T00:00:00+00:00")
                self.assertEqual(m["revision"], 0)
                self.assertEqual(m["state"], "INTAKE")
                self.assertEqual(m["package_id"], "pkg_demo_001")
                self.assertEqual(m["intent"]["raw"], "Build a skill")
                self.assertIsNone(m["previous_manifest_sha256"])
                rows = store.read_events("pkg_demo_001")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["revision"], 0)
                self.assertEqual(rows[0]["action"], "create_package")
                self.assertIsNone(rows[0]["state_before"])
                self.assertIsNone(rows[0]["previous_manifest_sha256"])
            finally:
                store.close()

    def test_duplicate_create_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                with self.assertRaises(DuplicatePackageError) as ctx:
                    store.create("pkg_demo_001", "Different intent")
                self.assertEqual(ctx.exception.code, "PACKAGE_EXISTS")
                self.assertEqual(_event_count(Path(td)), 1)
            finally:
                store.close()

    def test_exact_create_replay_returns_original(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                m1 = store.create("pkg_demo_001", "Build a skill",
                                  created_at="2026-08-07T00:00:00+00:00")
                m2 = store.create("pkg_demo_001", "Build a skill",
                                  created_at="2026-08-07T00:00:00+00:00")
                self.assertEqual(m1, m2)
                self.assertEqual(_event_count(Path(td)), 1)  # no second insert
            finally:
                store.close()

    def test_create_different_intent_is_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                # Creating an existing package with different intent is NOT a
                # replay -> the stable PACKAGE_EXISTS error (create contract).
                with self.assertRaises(DuplicatePackageError) as ctx:
                    store.create("pkg_demo_001", "Build a DIFFERENT skill")
                self.assertEqual(ctx.exception.code, "PACKAGE_EXISTS")
            finally:
                store.close()

    def test_create_invalid_intent(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                for bad in (None, 5, "x" * 65537, "bad\x01intent"):
                    with self.subTest(intent=bad):
                        with self.assertRaises(InvalidPayloadError):
                            store.create("pkg_demo_001", bad)  # type: ignore[arg-type]
                self.assertEqual(_event_count(Path(td)), 0)
            finally:
                store.close()


class LoadTests(unittest.TestCase):
    def test_load_missing_package_raises(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                with self.assertRaises(PackageNotFoundError) as ctx:
                    store.load("pkg_missing_999")
                self.assertEqual(ctx.exception.code, "PACKAGE_NOT_FOUND")
            finally:
                store.close()

    def test_load_returns_complete_current_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                manifests = _full_lifecycle(store)
                loaded = store.load("pkg_demo_001")
                self.assertEqual(loaded, manifests[-1])
                self.assertEqual(loaded["revision"], 6)
                self.assertEqual(loaded["state"], "CANCELLED")
            finally:
                store.close()

    def test_load_rejects_mismatched_row(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_lifecycle(store)
                # Tamper the latest row's manifest_json state field and
                # recompute the digest so ONLY the state binding fires.
                import json as _json

                from methodfactory.storage.serialization import canonical_bytes, sha256_hex
                c = sqlite3.connect(str(Path(td) / DB_FILENAME))
                c.execute("DROP TRIGGER IF EXISTS events_no_update")
                row = c.execute(
                    "SELECT manifest_json FROM events WHERE package_id='pkg_demo_001' "
                    "ORDER BY revision DESC LIMIT 1"
                ).fetchone()
                m = _json.loads(row[0])
                m["state"] = "INTAKE"
                data = canonical_bytes(m)
                c.execute(
                    "UPDATE events SET manifest_json=?, resulting_manifest_sha256=? "
                    "WHERE package_id='pkg_demo_001' AND revision=6",
                    (data, sha256_hex(data)),
                )
                c.commit()
                c.close()
                with self.assertRaises(ManifestInvalidError):
                    store.load("pkg_demo_001")
            finally:
                store.close()


class ApplyLifecycleTests(unittest.TestCase):
    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                [m0, m1, m2, m3, m4, m5, m6] = _full_lifecycle(store)
                self.assertEqual([m["revision"] for m in (m0, m1, m2, m3, m4, m5, m6)],
                                 [0, 1, 2, 3, 4, 5, 6])
                self.assertEqual([m["state"] for m in (m0, m1, m2, m3, m4, m5, m6)],
                                 ["INTAKE", "INTAKE", "INTAKE", "SUMMARY_PENDING",
                                  "AUTHORING_AUTHORIZED", "DRAFT_READY", "CANCELLED"])
                self.assertEqual(len(m1["inputs"]), 1)
                self.assertEqual(m2["objective"]["statement"], "Build a skill")
                self.assertIsNotNone(m3["summary"]["digest"])
                self.assertEqual(m4["summary"]["confirmation"]["status"], "confirmed")
                self.assertEqual(len(m5["artifacts"]), 1)
                # exactly one event per revision, contiguous
                self.assertEqual(_event_revisions(Path(td)), [0, 1, 2, 3, 4, 5, 6])
                store.validate_chain("pkg_demo_001")
            finally:
                store.close()

    def test_revise_intake_path(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                store.apply(_set_objective(expected_revision=1))
                m3 = store.apply(_prepare_summary(expected_revision=2))
                digest = m3["summary"]["digest"]
                m4 = store.apply(_confirm_summary(digest, expected_revision=3))
                self.assertEqual(m4["state"], "AUTHORING_AUTHORIZED")
                m5 = store.apply(_envelope(
                    "revise_intake", action_id="act_rev_1", expected_revision=4))
                self.assertEqual(m5["state"], "INTAKE")
                self.assertIsNone(m5["summary"])
                # intake material preserved (inputs + objective survive)
                self.assertEqual(len(m5["inputs"]), 1)
                self.assertEqual(m5["inputs"][0]["input_id"], "in_1")
                self.assertEqual(m5["objective"]["statement"], "Build a skill")
                store.validate_chain("pkg_demo_001")
            finally:
                store.close()

    def test_stale_revision_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                with self.assertRaises(StaleActionError) as ctx:
                    store.apply(_record_input(action_id="act_in_2", input_id="in_2",
                                              expected_revision=0))
                self.assertEqual(ctx.exception.code, "STALE_ACTION")
                self.assertEqual(ctx.exception.expected_revision, 0)
                self.assertEqual(ctx.exception.actual_revision, 1)
            finally:
                store.close()

    def test_illegal_transition_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                store.apply(_set_objective(expected_revision=1))
                store.apply(_prepare_summary(expected_revision=2))
                # record_input is not legal from SUMMARY_PENDING
                with self.assertRaises(IllegalTransitionError) as ctx:
                    store.apply(_record_input(action_id="act_in_9", input_id="in_9",
                                              expected_revision=3))
                self.assertEqual(ctx.exception.code, "ILLEGAL_TRANSITION")
            finally:
                store.close()

    def test_gate_failure_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                # prepare_summary requires an objective
                with self.assertRaises(GateUnsatisfiedError) as ctx:
                    store.apply(_prepare_summary(action_id="act_prep_9",
                                                 expected_revision=1))
                self.assertEqual(ctx.exception.code, "GATE_UNSATISFIED")
            finally:
                store.close()

    def test_apply_missing_package(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                with self.assertRaises(PackageNotFoundError):
                    store.apply(_record_input(action_id="act_x", expected_revision=0,
                                              package_id="pkg_missing_999"))
            finally:
                store.close()

    def test_apply_invalid_envelope(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                from methodfactory.domain.errors import InvalidEnvelopeError
                with self.assertRaises(InvalidEnvelopeError):
                    store.apply({"protocol_version": "0.1", "action_id": "act_1",
                                 "package_id": "pkg_demo_001",
                                 "expected_revision": 0, "action": "nope",
                                 "basis": {}, "payload": {}})
                with self.assertRaises(InvalidPayloadError):
                    store.apply("not a dict")  # type: ignore[arg-type]
            finally:
                store.close()

    def test_apply_tampered_current_manifest_typed(self):
        """A tampered current manifest (digest-consistent but schema-invalid,
        e.g. summary is a string) is rejected typed before the transition —
        never a raw AttributeError from the gates (type-guarded)."""
        import json as _json

        from methodfactory.storage.serialization import canonical_bytes, sha256_hex
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                store.apply(_set_objective(expected_revision=1))
                store.apply(_prepare_summary(expected_revision=2))
                # tamper the latest manifest: state SUMMARY_PENDING with a
                # non-dict summary; recompute the digest so ONLY the schema
                # violation is present
                c = sqlite3.connect(str(Path(td) / DB_FILENAME))
                c.execute("DROP TRIGGER IF EXISTS events_no_update")
                row = c.execute(
                    "SELECT manifest_json FROM events WHERE package_id='pkg_demo_001' "
                    "ORDER BY revision DESC LIMIT 1"
                ).fetchone()
                m = _json.loads(row[0])
                m["summary"] = "SOME STRING"
                data = canonical_bytes(m)
                c.execute(
                    "UPDATE events SET manifest_json=?, resulting_manifest_sha256=? "
                    "WHERE package_id='pkg_demo_001' AND revision=3",
                    (data, sha256_hex(data)),
                )
                c.commit()
                c.close()
                with self.assertRaises(MethodFactoryError) as ctx:
                    store.apply(_confirm_summary("0" * 64, action_id="act_conf_tamper",
                                                 expected_revision=3))
                self.assertNotIsInstance(ctx.exception, AttributeError)
                self.assertIn(ctx.exception.code,
                              ("MANIFEST_INVALID", "GATE_UNSATISFIED"))
            finally:
                store.close()


class IdempotencyOrderingTests(unittest.TestCase):
    def test_replay_before_stale_check(self):
        """Same action_id + same hash with an OLDER expected_revision must
        replay the committed result, NOT fail stale (lookup happens before
        the revision comparison)."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                m1 = store.apply(_record_input(expected_revision=0))
                # Advance the package, then retry act_in_1 with the ORIGINAL
                # expected_revision (0) — must replay m1, not raise stale.
                store.apply(_set_objective(expected_revision=1))
                store.apply(_prepare_summary(expected_revision=2))
                replay = store.apply(_record_input(
                    action_id="act_in_1", input_id="in_1", content="hello",
                    expected_revision=0,
                ))
                self.assertEqual(replay, m1)
                # exactly one event per action_id; 4 events total
                # (create + 3 applies: record_input, set_objective, prepare_summary)
                self.assertEqual(_event_revisions(Path(td)), [0, 1, 2, 3])
            finally:
                store.close()

    def test_same_action_id_different_hash_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(action_id="act_x", input_id="in_1",
                                          content="hello", expected_revision=0))
                with self.assertRaises(ActionIdConflictError) as ctx:
                    store.apply(_record_input(action_id="act_x", input_id="in_1",
                                              content="DIFFERENT", expected_revision=0))
                self.assertEqual(ctx.exception.code, "ACTION_ID_CONFLICT")
                self.assertEqual(_event_count(Path(td)), 2)  # no extra insert
            finally:
                store.close()

    def test_conflict_wins_over_stale(self):
        """Reusing an action_id with different content returns CONFLICT even
        when the expected_revision is also stale (lookup ordering)."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(action_id="act_x", input_id="in_1",
                                          content="hello", expected_revision=0))
                with self.assertRaises(ActionIdConflictError):
                    store.apply(_record_input(action_id="act_x", input_id="in_1",
                                              content="DIFFERENT", expected_revision=5))
            finally:
                store.close()

    def test_exactly_one_event_per_successful_revision(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_lifecycle(store)
                # re-apply an already committed action (replay) -> no insert
                m3 = store.load("pkg_demo_001")
                # replay the record_input from rev 1
                store.apply(_record_input(action_id="act_in_1", input_id="in_1",
                                          content="hello", expected_revision=0))
                self.assertEqual(_event_revisions(Path(td)), [0, 1, 2, 3, 4, 5, 6])
            finally:
                store.close()


class RollbackFaultTests(unittest.TestCase):
    STAGES = [
        "before_begin",
        "after_begin",
        "after_state_load",
        "after_transition",
        "after_manifest_validate",
        "after_artifact_verify",
        "before_insert",
        "after_insert",
    ]

    def _hook(self, stage):
        def hook(s):
            if s == stage:
                raise StorageError(f"fault at {stage}")
        return hook

    def test_rollback_at_each_precommit_boundary(self):
        for stage in self.STAGES:
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory() as td:
                    store = SqliteManifestStore(td)
                    try:
                        store.create("pkg_demo_001", "Build a skill")
                        old = store_mod.FAULT_HOOK
                        store_mod.FAULT_HOOK = self._hook(stage)
                        try:
                            with self.assertRaises(StorageError):
                                store.apply(_record_input(expected_revision=0))
                        finally:
                            store_mod.FAULT_HOOK = old
                        # no new event; current revision unchanged; historical
                        # rows intact (verified via a SEPARATE connection)
                        self.assertEqual(_event_count(Path(td)), 1)
                        self.assertEqual(_latest_revision(Path(td)), 0)
                        row = _latest_row(Path(td))
                        self.assertEqual(row["action"], "create_package")
                        self.assertEqual(row["state_after"], "INTAKE")
                        # the SAME store must remain usable: no leaked
                        # transaction (a subsequent valid action commits)
                        m = store.apply(_record_input(
                            action_id=f"act_after_{stage}", input_id="in_after",
                            expected_revision=0))
                        self.assertEqual(m["revision"], 1)
                        self.assertEqual(_event_revisions(Path(td)), [0, 1])
                    finally:
                        store.close()

    def test_commit_failure_then_retry_succeeds(self):
        """A commit failure BEFORE the database commits is classified: the
        transaction rolls back, no event is visible, and a retry commits
        cleanly (the failure was pre-commit, not an ambiguous outcome)."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                with mock.patch.object(store_mod, "_commit",
                                       side_effect=StorageError("commit fail")):
                    with self.assertRaises(StorageError):
                        store.apply(_record_input(expected_revision=0))
                self.assertEqual(_event_count(Path(td)), 1)
                self.assertEqual(_latest_revision(Path(td)), 0)
                # retry after the known-failed commit
                m = store.apply(_record_input(expected_revision=0))
                self.assertEqual(m["revision"], 1)
                self.assertEqual(_event_revisions(Path(td)), [0, 1])
            finally:
                store.close()

    def test_precommit_failure_keeps_blobs(self):
        """Blobs written inside the transaction before a later fault are NOT
        deleted on rollback (content-addressed and immutable)."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                old = store_mod.FAULT_HOOK
                store_mod.FAULT_HOOK = self._hook("before_insert")
                try:
                    with self.assertRaises(StorageError):
                        store.apply(_record_input(expected_revision=0))
                finally:
                    store_mod.FAULT_HOOK = old
                blobs = list((Path(td) / "blobs").glob("*"))
                self.assertTrue(blobs, "prewritten content blob must remain")
            finally:
                store.close()

    def test_no_raw_exception_escapes(self):
        """A native failure of a contract-listed family (type error here,
        simulating an unexpected internal TypeError) is translated to typed
        StorageError — no raw exception escapes the transactional API."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                old = store_mod.FAULT_HOOK
                store_mod.FAULT_HOOK = lambda s: (_ for _ in ()).throw(
                    TypeError("unexpected native failure")
                )
                try:
                    with self.assertRaises(StorageError) as ctx:
                        store.apply(_record_input(expected_revision=0))
                    self.assertEqual(ctx.exception.code, "STORAGE_ERROR")
                finally:
                    store_mod.FAULT_HOOK = old
            finally:
                store.close()


class MissingArtifactTests(unittest.TestCase):
    def test_missing_artifact_blob_raises_typed(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                store.apply(_record_input(expected_revision=0))
                store.apply(_set_objective(expected_revision=1))
                m3 = store.apply(_prepare_summary(expected_revision=2))
                store.apply(_confirm_summary(m3["summary"]["digest"], expected_revision=3))
                store.apply(_record_draft(expected_revision=4))
                blob_dir = Path(td) / "blobs"
                m5 = store.load("pkg_demo_001")
                digest = m5["artifacts"][0]["sha256"]
                (blob_dir / digest).unlink()
                # chain validator in artifact-verification mode surfaces the
                # missing blob as a typed CHAIN_VIOLATION
                from methodfactory.storage.errors import ChainViolationError
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001", verify_artifacts=True)
                self.assertIn("missing/corrupt", str(ctx.exception))
            finally:
                store.close()

    def test_apply_verifies_newly_referenced_blobs(self):
        """Transaction step 10: a newly referenced blob that fails
        verification (patched verify -> False) raises ArtifactVerificationError
        and the transaction rolls back."""
        from unittest import mock

        from methodfactory.adapters import artifact_store as art_mod
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create("pkg_demo_001", "Build a skill")
                with mock.patch.object(
                    art_mod.ArtifactStore, "verify", return_value=False
                ):
                    with self.assertRaises(ArtifactVerificationError) as ctx:
                        store.apply(_record_input(expected_revision=0))
                    self.assertEqual(ctx.exception.code, "ARTIFACT_VERIFICATION")
                self.assertEqual(_event_count(Path(td)), 1)  # rolled back
                self.assertEqual(_latest_revision(Path(td)), 0)
            finally:
                store.close()


class ConcurrencyTests(unittest.TestCase):
    def test_two_writers_distinct_actions_one_wins(self):
        """Two writers from the same revision cannot both commit distinct
        next revisions: one commits revision 1, the loser returns the stable
        stale error; no duplicate revision; no partial event. Each writer
        opens its OWN store/connection in its own thread (SQLite connections
        are thread-bound; separate connections are the real contention
        evidence)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup = SqliteManifestStore(root)
            setup.create("pkg_demo_001", "Build a skill")
            setup.close()
            barrier = threading.Barrier(2)
            results: dict[str, tuple] = {}

            def writer(name, envelope):
                s = SqliteManifestStore(root)
                try:
                    barrier.wait()
                    m = s.apply(envelope)
                    results[name] = ("ok", m["revision"])
                except Exception as exc:  # noqa: BLE001
                    results[name] = ("err", type(exc).__name__,
                                     getattr(exc, "code", None))
                finally:
                    s.close()

            t1 = threading.Thread(target=writer, args=(
                "a", _record_input(action_id="act_a", input_id="in_a")))
            t2 = threading.Thread(target=writer, args=(
                "b", _record_input(action_id="act_b", input_id="in_b")))
            t1.start(); t2.start(); t1.join(); t2.join()

            oks = [v for v in results.values() if v[0] == "ok"]
            errs = [v for v in results.values() if v[0] == "err"]
            self.assertEqual(len(oks), 1, results)
            self.assertEqual(oks[0][1], 1)
            self.assertEqual(len(errs), 1, results)
            self.assertEqual(errs[0][1], "StaleActionError")
            self.assertEqual(errs[0][2], "STALE_ACTION")
            self.assertEqual(_event_revisions(root), [0, 1])
            self.assertEqual(_event_count(root), 2)

    def test_same_action_concurrent_retries_converge(self):
        """Same action_id + same hash concurrently: exactly one event; both
        writers return the same manifest (one commits, one replays)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup = SqliteManifestStore(root)
            setup.create("pkg_demo_001", "Build a skill")
            setup.close()
            barrier = threading.Barrier(2)
            results: list = []

            def writer():
                s = SqliteManifestStore(root)
                try:
                    barrier.wait()
                    results.append(("ok", s.apply(
                        _record_input(action_id="act_same", input_id="in_1"))))
                except Exception as exc:  # noqa: BLE001
                    results.append(("err", type(exc).__name__,
                                    getattr(exc, "code", None)))
                finally:
                    s.close()

            t1 = threading.Thread(target=writer)
            t2 = threading.Thread(target=writer)
            t1.start(); t2.start(); t1.join(); t2.join()

            self.assertEqual(len(results), 2)
            self.assertTrue(all(r[0] == "ok" for r in results), results)
            self.assertEqual(results[0][1], results[1][1])
            self.assertEqual(_event_count(root), 2)  # create + one apply
            self.assertEqual(_event_revisions(root), [0, 1])

    def test_conflicting_same_action_id_cannot_both_succeed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup = SqliteManifestStore(root)
            setup.create("pkg_demo_001", "Build a skill")
            setup.close()
            barrier = threading.Barrier(2)
            results: list = []

            def writer(content):
                s = SqliteManifestStore(root)
                try:
                    barrier.wait()
                    results.append(("ok", s.apply(
                        _record_input(action_id="act_conflict", input_id="in_1",
                                      content=content))))
                except Exception as exc:  # noqa: BLE001
                    results.append(("err", type(exc).__name__,
                                    getattr(exc, "code", None)))
                finally:
                    s.close()

            t1 = threading.Thread(target=writer, args=("hello",))
            t2 = threading.Thread(target=writer, args=("world",))
            t1.start(); t2.start(); t1.join(); t2.join()

            oks = [r for r in results if r[0] == "ok"]
            errs = [r for r in results if r[0] == "err"]
            self.assertEqual(len(oks), 1, results)
            self.assertEqual(len(errs), 1, results)
            self.assertEqual(errs[0][1], "ActionIdConflictError")
            self.assertEqual(errs[0][2], "ACTION_ID_CONFLICT")
            self.assertEqual(_event_count(root), 2)

    def test_begin_immediate_bounded_by_busy_timeout(self):
        """A held write lock makes BEGIN IMMEDIATE wait the configured busy
        timeout then surface a typed ConcurrencyError — never a raw sqlite
        exception."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            blocker = sqlite3.connect(str(Path(td) / DB_FILENAME))
            try:
                store.create("pkg_demo_001", "Build a skill")
                blocker.execute("BEGIN IMMEDIATE")
                with self.assertRaises(ConcurrencyError) as ctx:
                    store.apply(_record_input(expected_revision=0))
                self.assertEqual(ctx.exception.code, "CONCURRENCY")
                self.assertEqual(_event_count(Path(td)), 1)
            finally:
                blocker.rollback()
                blocker.close()
                store.close()


def _proc_apply(root_str: str, envelope: dict, barrier, q):
    s = SqliteManifestStore(root_str)
    try:
        m = s.apply(envelope)
        q.put(("ok", m["revision"]))
    except Exception as exc:  # noqa: BLE001
        q.put(("err", type(exc).__name__, getattr(exc, "code", None)))
    finally:
        s.close()


class SeparateProcessConcurrencyTests(unittest.TestCase):
    def test_two_processes_from_same_revision(self):
        """Real separate-process writers: one commits revision 1, the loser
        returns the stable stale error; no duplicate revision; no partial
        event (multiprocessing fork context)."""
        ctx = mp.get_context("fork")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SqliteManifestStore(root)
            store.create("pkg_demo_001", "Build a skill")
            store.close()

            barrier = ctx.Barrier(2)
            q = ctx.Queue()
            p1 = ctx.Process(target=_proc_apply, args=(
                str(root), _record_input(action_id="act_p1", input_id="in_p1"),
                barrier, q))
            p2 = ctx.Process(target=_proc_apply, args=(
                str(root), _record_input(action_id="act_p2", input_id="in_p2"),
                barrier, q))
            p1.start(); p2.start(); p1.join(30); p2.join(30)
            self.assertEqual(p1.exitcode, 0)
            self.assertEqual(p2.exitcode, 0)

            results = [q.get(timeout=5) for _ in range(2)]
            oks = [r for r in results if r[0] == "ok"]
            errs = [r for r in results if r[0] == "err"]
            self.assertEqual(len(oks), 1, results)
            self.assertEqual(oks[0][1], 1)
            self.assertEqual(len(errs), 1, results)
            self.assertEqual(errs[0][1], "StaleActionError")
            self.assertEqual(errs[0][2], "STALE_ACTION")
            self.assertEqual(_event_revisions(root), [0, 1])
            self.assertEqual(_event_count(root), 2)


class QueryPlanTests(unittest.TestCase):
    def test_hot_path_plan_uses_primary_key_after_events(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_lifecycle(store)
                plan = store.explain_latest_plan("pkg_demo_001")
                text = " ".join(" ".join(str(c) for c in row) for row in plan)
                self.assertIn("SEARCH events USING", text)
                self.assertNotIn("SCAN events", text)
            finally:
                store.close()


class LockClassificationTests(unittest.TestCase):
    def test_locked_classified_by_errorcode(self):
        """Local review (sec-4/q-8): lock classification uses the SQLite
        extended error code, not message substrings."""
        busy = sqlite3.OperationalError("database is locked")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        self.assertTrue(store_mod._is_locked(busy))
        locked = sqlite3.OperationalError("database table is locked: events")
        locked.sqlite_errorcode = sqlite3.SQLITE_LOCKED
        self.assertTrue(store_mod._is_locked(locked))
        # an unrelated operational error is NOT lock-classified
        other = sqlite3.OperationalError("no such table: events")
        other.sqlite_errorcode = sqlite3.SQLITE_ERROR
        self.assertFalse(store_mod._is_locked(other))
        # pre-3.11 fallback: message heuristic when no errorcode attribute
        legacy = sqlite3.OperationalError("database is locked")
        self.assertTrue(store_mod._is_locked(legacy))


if __name__ == "__main__":
    unittest.main()
