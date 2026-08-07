"""Authoritative revision-chain validator tests (ADR-0012 §F).

A valid chain validates clean; every individual invariant, corrupted
independently, raises ChainViolationError. Tampering bypasses the append-only
triggers via a raw connection (DROP TRIGGER -> UPDATE), matching how a
tampered store file would appear; the validator runs on the already-open
store connection so schema re-verification does not mask the test.

Each manifest-field tamper recomputes resulting_manifest_sha256 from the
tampered bytes so ONLY the intended invariant fires (the digest binding is
tested separately).
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


def _record_input(action_id="act_in_1", expected_revision=0, input_id="in_1",
                  content="hello"):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": "pkg_demo_001", "expected_revision": expected_revision,
        "action": "record_input", "basis": {},
        "payload": {"input_id": input_id, "kind": "text", "content": content,
                    "source": "operator", "disposition": "incorporated"},
    }


def _set_objective(action_id="act_obj_1", expected_revision=1):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": "pkg_demo_001", "expected_revision": expected_revision,
        "action": "set_objective", "basis": {},
        "payload": {"statement": "Build a skill", "desired_outcomes": []},
    }


def _prepare_summary(action_id="act_prep_1", expected_revision=2):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": "pkg_demo_001", "expected_revision": expected_revision,
        "action": "prepare_summary", "basis": {}, "payload": {},
    }


def _confirm_summary(digest, action_id="act_conf_1", expected_revision=3):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": "pkg_demo_001", "expected_revision": expected_revision,
        "action": "confirm_summary", "basis": {"summary_sha256": digest},
        "payload": {"operator_id": "vincent"},
    }


def _record_draft(action_id="act_art_1", expected_revision=4):
    return {
        "protocol_version": "0.1", "action_id": action_id,
        "package_id": "pkg_demo_001", "expected_revision": expected_revision,
        "action": "record_draft_artifact", "basis": {},
        "payload": {"artifact_id": "art_1", "kind": "skill",
                    "logical_path": "skills/x/SKILL.md", "content": "body"},
    }


def _full_chain(store):
    store.create("pkg_demo_001", "Build a skill",
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


def _tamper_manifest(root: Path, package_id: str, revision: int, transform) -> None:
    """Decode a stored manifest, transform it, and rewrite bytes + digest."""
    c = _raw(root)
    row = c.execute(
        "SELECT manifest_json FROM events WHERE package_id=? AND revision=?",
        (package_id, revision),
    ).fetchone()
    m = json.loads(row[0])
    transform(m)
    data = canonical_bytes(m)
    c.execute(
        "UPDATE events SET manifest_json=?, resulting_manifest_sha256=? "
        "WHERE package_id=? AND revision=?",
        (data, sha256_hex(data), package_id, revision),
    )
    c.commit()
    c.close()


def _tamper_fields(root: Path, package_id: str, revision: int, fields: dict) -> None:
    c = _raw(root)
    sets = ", ".join(f"{k}=?" for k in fields)
    c.execute(
        f"UPDATE events SET {sets} WHERE package_id=? AND revision=?",
        (*fields.values(), package_id, revision),
    )
    c.commit()
    c.close()


def _delete_event(root: Path, package_id: str, revision: int) -> None:
    c = _raw(root)
    c.execute("DELETE FROM events WHERE package_id=? AND revision=?",
              (package_id, revision))
    c.commit()
    c.close()


def _tamper_blob(root: Path, package_id: str, revision: int, column: str, data: bytes) -> None:
    c = _raw(root)
    c.execute(
        f"UPDATE events SET {column}=? WHERE package_id=? AND revision=?",
        (data, package_id, revision),
    )
    c.commit()
    c.close()


def _tamper_action_raw(root: Path, package_id: str, revision: int, raw: bytes) -> None:
    """Write raw action_json bytes and recompute action_sha256 over THOSE raw
    bytes, so only canonical-form (A2) or action-binding (A3) invariants can
    fail."""
    c = _raw(root)
    c.execute(
        "UPDATE events SET action_json=?, action_sha256=? "
        "WHERE package_id=? AND revision=?",
        (raw, sha256_hex(raw), package_id, revision),
    )
    c.commit()
    c.close()


def _tamper_action_canonical(
    root: Path, package_id: str, revision: int, semantic: dict
) -> None:
    """Write a CANONICAL semantic action (possibly for a different package /
    action_id / action) and recompute action_sha256 over those canonical
    bytes, so only the action-binding (A3) invariants can fail."""
    data = canonical_bytes(semantic)
    _tamper_action_raw(root, package_id, revision, data)


class ChainValidatorTests(unittest.TestCase):
    def test_valid_chain_passes(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                result = store.validate_chain("pkg_demo_001")
                self.assertEqual(result["package_id"], "pkg_demo_001")
                self.assertEqual(result["events"], 6)  # create + 5 applies
                self.assertTrue(result["valid"])
            finally:
                store.close()

    def test_missing_package_raises(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                with self.assertRaises(ChainViolationError):
                    store.validate_chain("pkg_missing_999")
            finally:
                store.close()

    def test_semantic_action_fields_pinned_to_serializer(self):
        """The kernel's frozen semantic-action field set must never drift from
        the canonical serializer's output (single source of truth)."""
        from methodfactory.storage.chain import SEMANTIC_ACTION_FIELDS
        from methodfactory.storage.serialization import semantic_action

        produced = set(semantic_action(
            protocol_version="0.1", action="record_input",
            package_id="pkg_demo_001", action_id="act_1",
            basis={}, payload={},
        ).keys())
        self.assertEqual(produced, SEMANTIC_ACTION_FIELDS)


class RevisionZeroInvariantTests(unittest.TestCase):
    def test_action_must_be_create_package(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 0, {"action": "record_input"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("revision 0 action", str(ctx.exception))
            finally:
                store.close()

    def test_state_before_must_be_null(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 0, {"state_before": "INTAKE"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("state_before", str(ctx.exception))
            finally:
                store.close()

    def test_previous_manifest_hash_must_be_null(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 0,
                               {"previous_manifest_sha256": "0" * 64})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("previous_manifest_sha256", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_package_id_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), "pkg_demo_001", 0,
                                 lambda m: m.update(package_id="pkg_evil_001"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("package_id", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_revision_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), "pkg_demo_001", 0,
                                 lambda m: m.update(revision=5))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("revision", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_state_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), "pkg_demo_001", 0,
                                 lambda m: m.update(state="CANCELLED"))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("state", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 0,
                               {"resulting_manifest_sha256": "0" * 64})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("manifest_json", str(ctx.exception))
            finally:
                store.close()

    def test_action_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 0,
                               {"action_sha256": "0" * 64})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action_json", str(ctx.exception))
            finally:
                store.close()


class LineageInvariantTests(unittest.TestCase):
    def test_state_before_matches_previous_state_after(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 1,
                               {"state_before": "CANCELLED"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("state_before", str(ctx.exception))
            finally:
                store.close()

    def test_previous_hash_matches_previous_resulting(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 1,
                               {"previous_manifest_sha256": "0" * 64})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("previous_manifest_sha256", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_revision_matches_indexed(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), "pkg_demo_001", 1,
                                 lambda m: m.update(revision=99))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("revision", str(ctx.exception))
            finally:
                store.close()

    def test_missing_predecessor_detected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _delete_event(Path(td), "pkg_demo_001", 1)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("predecessor", str(ctx.exception))
            finally:
                store.close()


class StoredBytesInvariantTests(unittest.TestCase):
    def test_malformed_manifest_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_blob(Path(td), "pkg_demo_001", 0,
                             "manifest_json", b"{not json")
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("manifest_json", str(ctx.exception))
            finally:
                store.close()

    def test_malformed_action_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_blob(Path(td), "pkg_demo_001", 0,
                             "action_json", b"\xff\xfe\x00 invalid")
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action_json", str(ctx.exception))
            finally:
                store.close()


class CanonicalFormInvariantTests(unittest.TestCase):
    """Closure review A2: stored action/manifest JSON must themselves be
    canonical. A syntactically valid but NON-canonical representation with a
    recomputed raw-byte digest must fail canonical-form verification."""

    def _non_canonical_bytes(self, obj: dict) -> bytes:
        # Semantically equal but NOT the canonical serialization: unsorted
        # keys + different separators. canonical_bytes(obj) != this output.
        text = json.dumps(obj, sort_keys=False, separators=(", ", ": "),
                          ensure_ascii=False)
        self.assertNotEqual(
            text.encode("utf-8"),
            canonical_bytes(obj),
            "fixture must actually be non-canonical",
        )
        return text.encode("utf-8")

    def test_non_canonical_action_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                # read a valid stored action, re-serialize non-canonically,
                # recompute the hash over the raw tampered bytes
                c = _raw(Path(td))
                row = c.execute(
                    "SELECT action_json FROM events "
                    "WHERE package_id='pkg_demo_001' AND revision=1"
                ).fetchone()
                action = json.loads(row[0])
                c.close()
                raw = self._non_canonical_bytes(action)
                _tamper_action_raw(Path(td), "pkg_demo_001", 1, raw)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("canonical", str(ctx.exception))
            finally:
                store.close()

    def test_non_canonical_manifest_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                c = _raw(Path(td))
                row = c.execute(
                    "SELECT manifest_json FROM events "
                    "WHERE package_id='pkg_demo_001' AND revision=1"
                ).fetchone()
                manifest = json.loads(row[0])
                c.close()
                raw = self._non_canonical_bytes(manifest)
                _tamper_blob(Path(td), "pkg_demo_001", 1, "manifest_json", raw)
                c = _raw(Path(td))
                c.execute(
                    "UPDATE events SET resulting_manifest_sha256=? "
                    "WHERE package_id='pkg_demo_001' AND revision=1",
                    (sha256_hex(raw),),
                )
                c.commit()
                c.close()
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("canonical", str(ctx.exception))
            finally:
                store.close()


class ActionBindingInvariantTests(unittest.TestCase):
    """Closure review A3: the decoded semantic action object is bound back to
    the indexed event. Canonical actions for a DIFFERENT package / action_id /
    action (with recomputed hashes) must all be rejected."""

    def test_action_for_different_package_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                c = _raw(Path(td))
                row = c.execute(
                    "SELECT action_json FROM events "
                    "WHERE package_id='pkg_demo_001' AND revision=1"
                ).fetchone()
                action = json.loads(row[0])
                c.close()
                action["package_id"] = "pkg_evil_001"
                _tamper_action_canonical(Path(td), "pkg_demo_001", 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("package_id != indexed", str(ctx.exception))
            finally:
                store.close()

    def test_action_id_inside_action_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                c = _raw(Path(td))
                row = c.execute(
                    "SELECT action_json FROM events "
                    "WHERE package_id='pkg_demo_001' AND revision=1"
                ).fetchone()
                action = json.loads(row[0])
                c.close()
                action["action_id"] = "act_evil_99"
                _tamper_action_canonical(Path(td), "pkg_demo_001", 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action_id != indexed", str(ctx.exception))
            finally:
                store.close()

    def test_action_name_inside_action_json_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                c = _raw(Path(td))
                row = c.execute(
                    "SELECT action_json FROM events "
                    "WHERE package_id='pkg_demo_001' AND revision=1"
                ).fetchone()
                action = json.loads(row[0])
                c.close()
                action["action"] = "cancel"
                _tamper_action_canonical(Path(td), "pkg_demo_001", 1, action)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action != indexed", str(ctx.exception))
            finally:
                store.close()

    def test_non_semantic_field_set_rejected(self):
        """A canonical JSON object that is NOT a semantic action (extra or
        missing fields) must fail the frozen field-set check."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                not_semantic = {"action": "record_input", "extra": 1}
                _tamper_action_canonical(Path(td), "pkg_demo_001", 1, not_semantic)
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("field set", str(ctx.exception))
            finally:
                store.close()


class GrammarInvariantTests(unittest.TestCase):
    def test_bad_event_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 1, {"event_id": "bad id"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("event_id", str(ctx.exception))
            finally:
                store.close()

    def test_bad_action_id_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 1, {"action_id": "bad id"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action_id", str(ctx.exception))
            finally:
                store.close()

    def test_unknown_action_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_fields(Path(td), "pkg_demo_001", 1, {"action": "frobnicate"})
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("action", str(ctx.exception))
            finally:
                store.close()


class ManifestLineageBindingTests(unittest.TestCase):
    """Local review (bug-2): the manifest-internal lineage claims
    (previous_manifest_sha256, transition.last_event_id/last_action_id) are
    chain facts the engine writes; the validator must bind them to the
    indexed row even when the digest is recomputed consistently."""

    def test_manifest_previous_hash_bound_to_row(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(Path(td), "pkg_demo_001", 1,
                                 lambda m: m.update(previous_manifest_sha256="1" * 64))
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("previous_manifest_sha256", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_transition_event_id_bound_to_row(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(
                    Path(td), "pkg_demo_001", 1,
                    lambda m: m.update(transition={
                        "last_event_id": "evt_evil_99",
                        "last_action_id": m["transition"]["last_action_id"],
                    }),
                )
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("last_event_id", str(ctx.exception))
            finally:
                store.close()

    def test_manifest_transition_action_id_bound_to_row(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(
                    Path(td), "pkg_demo_001", 1,
                    lambda m: m.update(transition={
                        "last_event_id": m["transition"]["last_event_id"],
                        "last_action_id": "act_evil_99",
                    }),
                )
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("last_action_id", str(ctx.exception))
            finally:
                store.close()


class SchemaTamperTests(unittest.TestCase):
    """Local review (sec-1): the authoritative validator re-validates the
    manifest schema, so digest-consistent schema-level tamper is detected."""

    def test_schema_violation_detected(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(
                    Path(td), "pkg_demo_001", 1,
                    lambda m: m.__setitem__("inputs", [{
                        **m["inputs"][0],
                        "content_size": 10**12,
                        "content_sha256": "0" * 64,
                    }]),
                )
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001")
                self.assertIn("schema", str(ctx.exception))
            finally:
                store.close()

    def test_load_rejects_schema_invalid_current_manifest(self):
        """load() runs the bounded current-row consistency check, which now
        includes schema validation: a digest-consistent schema violation in
        the latest manifest is rejected (ManifestInvalidError), not returned."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(
                    Path(td), "pkg_demo_001", 5,
                    lambda m: m.__setitem__("artifacts", [{
                        **m["artifacts"][0], "byte_count": -5,
                    }]),
                )
                from methodfactory.storage.errors import ManifestInvalidError
                with self.assertRaises(ManifestInvalidError):
                    store.load("pkg_demo_001")
            finally:
                store.close()

    def test_verify_artifacts_non_dict_entry_no_crash(self):
        """Local review (bug-1): a structurally invalid inputs/artifacts entry
        must be reported as a violation, never crash with AttributeError."""
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                _tamper_manifest(
                    Path(td), "pkg_demo_001", 1,
                    lambda m: m.__setitem__("inputs", ["garbage-not-a-dict"]),
                )
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001", verify_artifacts=True)
                self.assertIn("not an object", str(ctx.exception))
            finally:
                store.close()


class ArtifactVerificationTests(unittest.TestCase):
    def test_missing_referenced_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            store = SqliteManifestStore(td)
            try:
                _full_chain(store)
                m5 = store.load("pkg_demo_001")
                digest = m5["artifacts"][0]["sha256"]
                (Path(td) / "blobs" / digest).unlink()
                with self.assertRaises(ChainViolationError) as ctx:
                    store.validate_chain("pkg_demo_001", verify_artifacts=True)
                self.assertIn("artifact", str(ctx.exception))
                # without artifact verification the chain still validates
                result = store.validate_chain("pkg_demo_001")
                self.assertTrue(result["valid"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
