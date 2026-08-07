"""Deterministic replay + timestamp-contract tests (invariant closure,
senior review 4885538290, Lane 1).

The authoritative validator (validate_chain) must PROVE that the stored
resulting manifest is exactly the deterministic result Method Factory would
have produced from the stored action and predecessor manifest, using the
SINGLE deterministic transition engine (engine.apply.next_manifest) — not a
second per-action validator, and not the transactional mutation path.

Adversarial tampering recomputes every immediate hash (action_sha256 /
resulting_manifest_sha256) so the new deterministic replay invariant is the
ONLY reason the test fails — exactly the coherent-looking-rewrite scenario
the closure targets. Valid history must still pass.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from methodfactory.storage.errors import ChainViolationError
from methodfactory.storage.paths import DB_FILENAME
from methodfactory.storage.serialization import canonical_bytes, sha256_hex
from methodfactory.storage.store import SqliteManifestStore

PKG = "pkg_demo_001"


# ── fixtures (mirror the chain-validator patterns; local helpers are an
#    accepted cosmetic nit, kept local so this module is self-contained) ──


def _record_input(action_id="act_in_1", expected_revision=0, input_id="in_1",
                  content="hello"):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": PKG, "expected_revision": expected_revision,
        "action": "record_input", "basis": {},
        "payload": {"input_id": input_id, "kind": "text", "content": content,
                    "source": "operator", "disposition": "incorporated"},
    }


def _set_objective(action_id="act_obj_1", expected_revision=1):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": PKG, "expected_revision": expected_revision,
        "action": "set_objective", "basis": {},
        "payload": {"statement": "Build a skill", "desired_outcomes": []},
    }


def _prepare_summary(action_id="act_prep_1", expected_revision=2):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": PKG, "expected_revision": expected_revision,
        "action": "prepare_summary", "basis": {}, "payload": {},
    }


def _confirm_summary(digest, action_id="act_conf_1", expected_revision=3):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": PKG, "expected_revision": expected_revision,
        "action": "confirm_summary", "basis": {"summary_sha256": digest},
        "payload": {"operator_id": "vincent"},
    }


def _record_draft(action_id="act_art_1", expected_revision=4):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": PKG, "expected_revision": expected_revision,
        "action": "record_draft_artifact", "basis": {},
        "payload": {"artifact_id": "art_1", "kind": "skill",
                    "logical_path": "skills/x/SKILL.md", "content": "body"},
    }


def _full_chain(store):
    store.create(PKG, "Build a skill",
                 created_at="2026-08-07T00:00:00+00:00")
    store.apply(_record_input(expected_revision=0))
    store.apply(_set_objective(expected_revision=1))
    m3 = store.apply(_prepare_summary(expected_revision=2))
    store.apply(_confirm_summary(m3["summary"]["digest"], expected_revision=3))
    store.apply(_record_draft(expected_revision=4))


def _raw(root: Path):
    c = sqlite3.connect(str(root / DB_FILENAME))
    c.execute("DROP TRIGGER IF EXISTS events_no_update")
    c.execute("DROP TRIGGER IF EXISTS events_no_delete")
    return c


def _tamper_action(root: Path, revision: int, semantic: dict,
                   *, action: str | None = None) -> None:
    """Write a CANONICAL semantic action (with the SAME frozen field set) and
    recompute action_sha256 over those canonical bytes, so only the replay
    invariant (or an explicit A3 binding) can fail. Optionally updates the
    indexed action column for coherent rewrites."""
    data = canonical_bytes(semantic)
    c = _raw(root)
    if action is None:
        c.execute(
            "UPDATE events SET action_json=?, action_sha256=? "
            "WHERE package_id=? AND revision=?",
            (data, sha256_hex(data), PKG, revision),
        )
    else:
        c.execute(
            "UPDATE events SET action_json=?, action_sha256=?, action=? "
            "WHERE package_id=? AND revision=?",
            (data, sha256_hex(data), action, PKG, revision),
        )
    c.commit()
    c.close()


def _tamper_manifest(root: Path, revision: int, transform) -> None:
    """Decode a stored manifest, transform it, rewrite bytes + digest so only
    the intended invariant can fail."""
    c = _raw(root)
    row = c.execute(
        "SELECT manifest_json FROM events WHERE package_id=? AND revision=?",
        (PKG, revision),
    ).fetchone()
    m = json.loads(row[0])
    transform(m)
    data = canonical_bytes(m)
    c.execute(
        "UPDATE events SET manifest_json=?, resulting_manifest_sha256=? "
        "WHERE package_id=? AND revision=?",
        (data, sha256_hex(data), PKG, revision),
    )
    c.commit()
    c.close()


def _tamper_fields(root: Path, revision: int, fields: dict) -> None:
    c = _raw(root)
    sets = ", ".join(f"{k}=?" for k in fields)
    c.execute(
        f"UPDATE events SET {sets} WHERE package_id=? AND revision=?",
        (*fields.values(), PKG, revision),
    )
    c.commit()
    c.close()


def _semantic_of(root: Path, revision: int) -> dict:
    c = _raw(root)
    row = c.execute(
        "SELECT action_json FROM events WHERE package_id=? AND revision=?",
        (PKG, revision),
    ).fetchone()
    c.close()
    return json.loads(row[0])


class ReplayPositiveTests(unittest.TestCase):
    def test_valid_full_chain_replays_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                result = store.validate_chain(PKG)
                self.assertTrue(result["valid"])
                self.assertEqual(result["events"], 6)
            finally:
                store.close()

    def test_cancel_chain_replays_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                store.create(PKG, "Build a skill",
                             created_at="2026-08-07T00:00:00+00:00")
                store.apply({
                    "protocol_version": "0.1", "action_id": "act_cancel_1",
                    "package_id": PKG, "expected_revision": 0,
                    "action": "cancel", "basis": {}, "payload": {},
                })
                result = store.validate_chain(PKG)
                self.assertTrue(result["valid"])
                self.assertEqual(store.load(PKG)["state"], "CANCELLED")
            finally:
                store.close()


class ReplayAdversarialTests(unittest.TestCase):
    """Coherent-looking rewrites: every immediate hash is recomputed so the
    deterministic replay invariant is the ONLY reason validation fails."""

    def test_record_input_content_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 1)
                action["payload"]["content"] = "HELLO"
                _tamper_action(Path(td), 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_set_objective_statement_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 2)
                action["payload"]["statement"] = "A totally different goal"
                _tamper_action(Path(td), 2, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_artifact_content_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 5)
                action["payload"]["content"] = "EVIL CONTENT"
                _tamper_action(Path(td), 5, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_confirm_operator_id_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 4)
                action["payload"]["operator_id"] = "mallory"
                _tamper_action(Path(td), 4, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_confirm_summary_basis_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 4)
                action["basis"]["summary_sha256"] = "1" * 64
                _tamper_action(Path(td), 4, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                # The gate re-evaluated during replay binds the basis to the
                # stored summary digest; a stale basis fails the transition.
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_event_timestamp_change_with_manifest_inconsistent_rejected(self):
        """Event row created_at changed; manifest updated_at left at the
        original — the row binding and/or replay must catch it."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), 3, {"created_at": "2099-01-01T00:00:00+00:00"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                text = str(ctx.exception)
                self.assertTrue(
                    "updated_at" in text or "deterministic" in text,
                    f"expected timestamp/replay violation, got: {text}",
                )
            finally:
                store.close()

    def test_manifest_updated_at_change_with_hash_recomputed_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), 2, lambda m: m.update(
                    updated_at="2099-01-01T00:00:00+00:00"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("updated_at", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_created_at_change_with_hash_recomputed_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), 1, lambda m: m.update(
                    created_at="2099-01-01T00:00:00+00:00"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("created_at", str(ctx.exception))
            finally:
                store.close()

    def test_action_and_manifest_changed_inconsistently_rejected(self):
        """Action payload and resulting manifest BOTH rewritten (hashes
        recomputed) but inconsistent with each other — replay must catch the
        mismatch."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 2)
                action["payload"]["statement"] = "Action says THIS"
                _tamper_action(Path(td), 2, action)
                _tamper_manifest(Path(td), 2, lambda m: m["objective"].update(
                    statement="Manifest says THAT"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_illegal_transition_encoded_coherently_rejected(self):
        """A canonical, rehashed action for a transition that is ILLEGAL from
        the predecessor state (row action column updated coherently) must fail
        replay even though every hash and binding passes."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                # Rev 2's predecessor is INTAKE; record_draft_artifact is not
                # legal from INTAKE. Rewrite the action AND the indexed action
                # column coherently, with a schema-valid payload.
                semantic = {
                    "protocol_version": "0.1",
                    "action": "record_draft_artifact",
                    "package_id": PKG,
                    "action_id": "act_obj_1",
                    "basis": {},
                    "payload": {"artifact_id": "art_evil", "kind": "skill",
                                "logical_path": "skills/x/SKILL.md", "content": "x"},
                }
                _tamper_action(Path(td), 2, semantic, action="record_draft_artifact")
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()


class ReconstructionFailClosedTests(unittest.TestCase):
    """Stored-action reconstruction reuses the normal envelope validator; a
    persisted action that would not parse today must fail closed."""

    def test_malformed_payload_for_action_fails_reconstruction(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 1)
                del action["payload"]["kind"]  # record_input requires kind
                _tamper_action(Path(td), 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("cannot be reconstructed", str(ctx.exception))
            finally:
                store.close()

    def test_unsupported_protocol_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                action = _semantic_of(Path(td), 1)
                action["protocol_version"] = "9.9"
                _tamper_action(Path(td), 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("protocol_version", str(ctx.exception))
            finally:
                store.close()


class TimestampIndependentTests(unittest.TestCase):
    """Independent corruption tests for the timestamp contract (steering §4):
    action-specific timestamps are derived from the event timestamp by the
    transition, so digest-consistent tamper is caught by replay."""

    def test_rev0_created_at_binding(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), 0, lambda m: m.update(
                    created_at="2099-01-01T00:00:00+00:00"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("created_at", str(ctx.exception))
            finally:
                store.close()

    def test_summary_presented_at_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), 3, lambda m: m["summary"].update(
                    presented_at="2099-01-01T00:00:00+00:00"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()

    def test_summary_confirmed_at_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), 4, lambda m: m["summary"]["confirmation"].update(
                    confirmed_at="2099-01-01T00:00:00+00:00"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain(PKG)
                self.assertIn("deterministic", str(ctx.exception))
            finally:
                store.close()


class SideEffectFreeReplayTests(unittest.TestCase):
    def test_validate_chain_writes_no_blobs(self):
        """Audit replay is side-effect free: validate_chain (even with
        artifact verification) must not create, modify, or delete blobs."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                blobs_dir = Path(td) / "blobs"

                def snapshot() -> dict[str, bytes]:
                    return {p.name: p.read_bytes() for p in blobs_dir.iterdir()} if blobs_dir.exists() else {}

                before = snapshot()
                result = store.validate_chain(PKG, verify_artifacts=True)
                self.assertTrue(result["valid"])
                after = snapshot()
                self.assertEqual(before, after)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
