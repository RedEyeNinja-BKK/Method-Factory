"""Phase 4.1 integrity, crash, and contention proofs."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import ManifestInvalidError, StaleActionError
from methodfactory.engine import PipelineEngine
from methodfactory.manifest.store import ManifestStore

PKG = "pkg_integrity_001"
NOW = "2026-08-03T04:00:00+00:00"


def action(action, revision, action_id=None, payload=None):
    return {
        "protocol_version": "0.1",
        "action_id": action_id or f"act_{action}_{revision}",
        "package_id": PKG,
        "expected_revision": revision,
        "action": action,
        "basis": {},
        "payload": payload or {},
    }


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.store = ManifestStore(self.root / "store", artifact_store=self.artifacts)
        self.engine = PipelineEngine(self.store, self.artifacts, now=lambda: NOW)

    def tearDown(self):
        self.tmp.cleanup()

    def create(self):
        return self.engine.create_package(PKG, "Build an integrity test package.")

    def test_artifact_blob_immutable(self):
        digest1, size1 = self.artifacts.put(PKG, "one.txt", "same content")
        blob = self.root / "artifacts" / "blobs" / digest1
        before = blob.read_bytes()
        digest2, size2 = self.artifacts.put("pkg_other", "different.txt", "same content")
        self.assertEqual((digest1, size1), (digest2, size2))
        self.assertEqual(blob.read_bytes(), before)
        self.assertEqual(self.artifacts.get(digest1), "same content")

    def test_orphaned_blob_is_harmless(self):
        self.create()
        digest, _ = self.artifacts.put(PKG, "orphan.txt", "written before failed CAS")
        current = self.store.load(PKG)
        with self.assertRaises(StaleActionError):
            self.store.compare_and_swap(PKG, 99, current, {"event_id": "evt_bad"})
        self.assertTrue(self.artifacts.verify(digest))
        self.assertEqual(self.store.load(PKG)["artifacts"], [])

    def test_crash_between_event_and_snapshot_recovery(self):
        self.create()
        original = self.store._atomic_write
        calls = 0

        def crash_once(path, data):
            nonlocal calls
            calls += 1
            raise RuntimeError("simulated crash after journal fsync")

        self.store._atomic_write = crash_once
        with self.assertRaises(RuntimeError):
            self.engine.apply_json(json.dumps(action("set_objective", 0, payload={
                "statement": "recover from journal",
                "desired_outcomes": [],
            })))
        self.store._atomic_write = original
        recovered = ManifestStore(self.root / "store", artifact_store=self.artifacts)
        manifest = recovered.load(PKG)
        self.assertEqual(calls, 1)
        self.assertEqual(manifest["revision"], 1)
        self.assertEqual(manifest["objective"]["statement"], "recover from journal")

    def test_event_chain_continuity_detected(self):
        self.create()
        self.engine.apply_json(json.dumps(action("set_objective", 0, payload={
            "statement": "chain test", "desired_outcomes": []
        })))
        path = self.root / "store" / "events" / f"{PKG}.events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[1]["state_after"] = "CANCELLED"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        with self.assertRaisesRegex(ManifestInvalidError, "state_after"):
            self.store.load(PKG)

    def test_revision_gap_detected(self):
        self.create()
        self.engine.apply_json(json.dumps(action("set_objective", 0, payload={
            "statement": "gap test", "desired_outcomes": []
        })))
        path = self.root / "store" / "events" / f"{PKG}.events.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[1]["revision"] = 4
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        with self.assertRaisesRegex(ManifestInvalidError, "revision gap"):
            self.store.load(PKG)

    def test_concurrent_cas_contention(self):
        self.create()
        store2 = ManifestStore(self.root / "store", artifact_store=self.artifacts)
        engine2 = PipelineEngine(store2, self.artifacts, now=lambda: NOW)
        first = self.engine.apply_json(json.dumps(action("set_objective", 0,
            action_id="act_first", payload={"statement": "first", "desired_outcomes": []})))
        self.assertEqual(first.manifest["revision"], 1)
        with self.assertRaises(StaleActionError):
            engine2.apply_json(json.dumps(action("set_objective", 0,
                action_id="act_second", payload={"statement": "second", "desired_outcomes": []})))

    def test_last_event_id_populated(self):
        self.create()
        result = self.engine.apply_json(json.dumps(action("set_objective", 0, payload={
            "statement": "event id", "desired_outcomes": []
        })))
        self.assertEqual(result.manifest["transition"]["last_event_id"], result.event["event_id"])
        self.assertEqual(self.store.load(PKG)["transition"]["last_event_id"], result.event["event_id"])

    def test_retry_with_updated_revision_replays_same_action(self):
        self.create()
        payload = {"statement": "retry-safe", "desired_outcomes": []}
        first = self.engine.apply_json(json.dumps(action(
            "set_objective", 0, action_id="act_retry", payload=payload
        )))
        replay = self.engine.apply_json(json.dumps(action(
            "set_objective", 1, action_id="act_retry", payload=payload
        )))
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.event["event_id"], first.event["event_id"])

    def test_stale_cas_orphaned_blob(self):
        self.create()
        digest, _ = self.artifacts.put(PKG, "failed.txt", "failed CAS content")
        manifest = self.store.load(PKG)
        with self.assertRaises(StaleActionError):
            self.store.compare_and_swap(PKG, manifest["revision"] + 1, manifest, {"event_id": "evt_stale"})
        self.assertTrue(self.artifacts.verify(digest))
        self.assertNotIn(digest, [a["sha256"] for a in self.store.load(PKG)["artifacts"]])

    def test_full_chain_verifies_artifact_digests(self):
        self.create()
        content = "input content"
        self.engine.apply_json(json.dumps(action("record_input", 0, payload={
            "input_id": "in_001", "kind": "text", "content": content,
            "source": "operator", "disposition": "incorporated",
        })))
        manifest = self.store.load(PKG)
        self.assertTrue(self.artifacts.verify(manifest["inputs"][0]["content_sha256"]))


if __name__ == "__main__":
    unittest.main()
