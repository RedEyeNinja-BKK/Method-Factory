"""Vertical-slice integration tests — engine end-to-end (Phases 2d + 2e).

Covers the single-phase loop (intent → inputs → objective → summary →
confirmation) and slice completion (authoring → one draft artifact →
DRAFT_READY), plus the integrity proofs: stale actions, invalid transitions,
approval binding, code-computed digests, restart preservation, tamper
detection, idempotency, and scope confinement.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.adapters.artifact_store import ArtifactStore
from core.domain.errors import (
    ActionIdReuseError,
    GateUnsatisfiedError,
    IllegalTransitionError,
    InvalidPayloadError,
    ManifestInvalidError,
    StaleActionError,
)
from core.engine import PipelineEngine
from core.manifest.hashing import digest_text
from core.manifest.store import ManifestStore

PKG = "pkg_demo_001"
FIXED_NOW = "2026-08-03T04:00:00+00:00"


def envelope(action, revision, action_id=None, basis=None, payload=None):
    return {
        "protocol_version": "0.1",
        "action_id": action_id or f"act_{action}_{revision}",
        "package_id": PKG,
        "expected_revision": revision,
        "action": action,
        "basis": basis or {},
        "payload": payload or {},
    }


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = ManifestStore(self.root / "store")
        self.artifacts = ArtifactStore(self.root / "artifacts")
        self.engine = PipelineEngine(self.store, self.artifacts, now=lambda: FIXED_NOW)

    def tearDown(self):
        self._tmp.cleanup()

    def apply(self, action, revision, **kw):
        return self.engine.apply_json(json.dumps(envelope(action, revision, **kw)))

    def run_to_summary_pending(self):
        self.engine.create_package(PKG, "Build a standup-notes skill.")
        self.apply("record_input", 0, payload={
            "input_id": "in_001", "kind": "text", "content": "rough notes",
            "source": "operator", "disposition": "incorporated",
        })
        self.apply("set_objective", 1, payload={
            "statement": "A skill that captures standup notes to a file",
            "desired_outcomes": ["one command per day"],
        })
        return self.apply("prepare_summary", 2)

    def run_full_slice(self):
        result = self.run_to_summary_pending()
        summary_sha = result.manifest["summary"]["canonical_sha256"]
        self.apply("confirm_summary", 3, basis={"summary_sha256": summary_sha})
        return self.apply("record_draft_artifact", 4, payload={
            "artifact_id": "art_001", "kind": "skill",
            "logical_path": "skills/standup-notes/SKILL.md",
            "content": "# Standup Notes\nCapture daily standup notes.\n",
        })


class SinglePhaseLoopTests(EngineFixture):
    def test_loop_reaches_summary_pending(self):
        result = self.run_to_summary_pending()
        self.assertEqual(result.manifest["state"], "SUMMARY_PENDING")
        self.assertEqual(result.manifest["revision"], 3)
        self.assertEqual(len(result.manifest["inputs"]), 1)
        self.assertIsNotNone(result.manifest["summary"]["canonical_sha256"])
        self.assertEqual(result.manifest["summary"]["confirmation"]["status"], "pending")

    def test_restart_preserves_state(self):
        self.run_to_summary_pending()
        # Fresh engine/store over the same on-disk roots — a process restart.
        store2 = ManifestStore(self.root / "store")
        artifacts2 = ArtifactStore(self.root / "artifacts")
        engine2 = PipelineEngine(store2, artifacts2, now=lambda: FIXED_NOW)
        status = engine2.status(PKG)
        self.assertEqual(status["state"], "SUMMARY_PENDING")
        self.assertEqual(status["revision"], 3)
        self.assertEqual(status["inputs"], 1)
        self.assertEqual(status["summary_confirmation"], "pending")

    def test_stale_action_fails(self):
        self.run_to_summary_pending()
        with self.assertRaises(StaleActionError) as cm:
            self.apply("confirm_summary", 2, basis={"summary_sha256": "a" * 64})
        self.assertEqual(cm.exception.expected_revision, 2)
        self.assertEqual(cm.exception.actual_revision, 3)
        # No state change.
        self.assertEqual(self.engine.status(PKG)["revision"], 3)

    def test_illegal_transition_fails(self):
        self.run_to_summary_pending()
        with self.assertRaises(IllegalTransitionError):
            self.apply("record_input", 3, payload={
                "input_id": "in_002", "kind": "text", "content": "x",
                "source": "operator", "disposition": "incorporated",
            })
        self.assertEqual(self.engine.status(PKG)["revision"], 3)

    def test_failed_action_leaves_no_manifest_change(self):
        self.run_to_summary_pending()
        before = self.store.load(PKG)
        before_digest = digest_text(json.dumps(before, sort_keys=True))
        with self.assertRaises(IllegalTransitionError):
            self.apply("record_draft_artifact", 3, payload={
                "artifact_id": "art_001", "kind": "skill",
                "logical_path": "skills/x/SKILL.md", "content": "x",
            })
        after = self.store.load(PKG)
        self.assertEqual(digest_text(json.dumps(after, sort_keys=True)), before_digest)

    def test_no_temp_files_left_behind(self):
        self.run_to_summary_pending()
        leftovers = list((self.root / "store" / "packages").glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_prepare_summary_requires_intent_and_objective(self):
        self.engine.create_package(PKG, "Build a standup-notes skill.")
        self.apply("record_input", 0, payload={
            "input_id": "in_001", "kind": "text", "content": "notes",
            "source": "operator", "disposition": "incorporated",
        })
        with self.assertRaises(GateUnsatisfiedError):
            self.apply("prepare_summary", 1)


class SliceCompletionTests(EngineFixture):
    def test_full_slice_reaches_draft_ready(self):
        result = self.run_full_slice()
        self.assertEqual(result.manifest["state"], "DRAFT_READY")
        self.assertEqual(result.manifest["revision"], 5)
        art = result.manifest["artifacts"][0]
        content = "# Standup Notes\nCapture daily standup notes.\n"
        self.assertEqual(art["sha256"], digest_text(content))
        self.assertEqual(art["byte_count"], len(content.encode("utf-8")))
        self.assertEqual(art["status"], "draft")

    def test_approval_binds_summary_digest(self):
        result = self.run_to_summary_pending()
        real_sha = result.manifest["summary"]["canonical_sha256"]
        with self.assertRaises(StaleActionError):
            self.apply("confirm_summary", 3, basis={"summary_sha256": "b" * 64})
        # Correct digest still works.
        self.apply("confirm_summary", 3, basis={"summary_sha256": real_sha})
        self.assertEqual(self.engine.status(PKG)["state"], "AUTHORING_AUTHORIZED")

    def test_revise_invalidates_approval(self):
        result = self.run_to_summary_pending()
        old_sha = result.manifest["summary"]["canonical_sha256"]
        self.apply("confirm_summary", 3, basis={"summary_sha256": old_sha})
        self.assertEqual(self.engine.status(PKG)["state"], "AUTHORING_AUTHORIZED")
        # Revise → back to intake; approval cleared.
        self.apply("revise_intake", 4)
        self.assertEqual(self.engine.status(PKG)["state"], "INTAKE")
        self.assertIsNone(self.store.load(PKG)["summary"])
        # New objective + new summary.
        self.apply("set_objective", 5, payload={
            "statement": "A DIFFERENT objective",
            "desired_outcomes": [],
        })
        result2 = self.apply("prepare_summary", 6)
        new_sha = result2.manifest["summary"]["canonical_sha256"]
        self.assertNotEqual(new_sha, old_sha)
        # Old approval digest must NOT authorize.
        with self.assertRaises(StaleActionError):
            self.apply("confirm_summary", 7, basis={"summary_sha256": old_sha})
        # New digest authorizes.
        self.apply("confirm_summary", 7, basis={"summary_sha256": new_sha})
        self.assertEqual(self.engine.status(PKG)["state"], "AUTHORING_AUTHORIZED")

    def test_draft_requires_confirmation_transition(self):
        # From SUMMARY_PENDING, authoring is an ILLEGAL transition — you
        # cannot reach a draft without first confirming the summary.
        self.run_to_summary_pending()
        with self.assertRaises(IllegalTransitionError):
            self.apply("record_draft_artifact", 3, payload={
                "artifact_id": "art_001", "kind": "skill",
                "logical_path": "skills/x/SKILL.md", "content": "x",
            })

    def test_tamper_detection(self):
        self.run_full_slice()
        path = self.root / "store" / "packages" / f"{PKG}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["state"] = "CANCELLED"  # adversarial edit outside the engine
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ManifestInvalidError):
            self.store.load(PKG)

    def test_restart_preserves_slice_state(self):
        self.run_full_slice()
        store2 = ManifestStore(self.root / "store")
        artifacts2 = ArtifactStore(self.root / "artifacts")
        engine2 = PipelineEngine(store2, artifacts2, now=lambda: FIXED_NOW)
        status = engine2.status(PKG)
        self.assertEqual(status["state"], "DRAFT_READY")
        self.assertEqual(status["revision"], 5)
        manifest = store2.load(PKG)
        art = manifest["artifacts"][0]
        self.assertTrue(
            artifacts2.verify(art["sha256"])
        )

    def test_no_forward_scope_creep(self):
        self.run_full_slice()
        # No review/trial/ship/deploy behavior exists: unknown future actions
        # and repeat authoring are rejected; state never leaves the slice.
        with self.assertRaises(IllegalTransitionError):
            self.apply("record_draft_artifact", 5, payload={
                "artifact_id": "art_002", "kind": "skill",
                "logical_path": "skills/y/SKILL.md", "content": "y",
            })
        self.assertNotIn(
            self.store.load(PKG)["state"],
            {"REVIEW_PENDING", "TRIAL_PENDING", "SHIP_PENDING", "SHIPPED"},
        )

    def test_action_replay_is_idempotent(self):
        result = self.run_full_slice()
        replay = self.apply("record_draft_artifact", 4, payload={
            "artifact_id": "art_001", "kind": "skill",
            "logical_path": "skills/standup-notes/SKILL.md",
            "content": "# Standup Notes\nCapture daily standup notes.\n",
        })
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.manifest["revision"], result.manifest["revision"])
        self.assertEqual(len(replay.manifest["artifacts"]), 1)

    def test_action_id_reuse_with_different_payload(self):
        self.run_full_slice()
        # run_full_slice used the default action_id act_record_draft_artifact_4.
        # Reusing that SAME action_id with different content is reuse, not replay.
        with self.assertRaises(ActionIdReuseError):
            self.apply(
                "record_draft_artifact", 4,
                action_id="act_record_draft_artifact_4",
                payload={
                    "artifact_id": "art_001", "kind": "skill",
                    "logical_path": "skills/standup-notes/SKILL.md",
                    "content": "DIFFERENT CONTENT",
                },
            )

    def test_duplicate_input_id_rejected(self):
        self.engine.create_package(PKG, "Build a standup-notes skill.")
        self.apply("record_input", 0, payload={
            "input_id": "in_001", "kind": "text", "content": "a",
            "source": "operator", "disposition": "incorporated",
        })
        with self.assertRaises(InvalidPayloadError):
            self.apply("record_input", 1, payload={
                "input_id": "in_001", "kind": "text", "content": "b",
                "source": "operator", "disposition": "incorporated",
            })

    def test_exclusion_requires_reason(self):
        self.engine.create_package(PKG, "Build a standup-notes skill.")
        with self.assertRaises(InvalidPayloadError):
            self.apply("record_input", 0, payload={
                "input_id": "in_001", "kind": "text", "content": "a",
                "source": "operator", "disposition": "excluded",
            })
        self.apply("record_input", 0, payload={
            "input_id": "in_001", "kind": "text", "content": "a",
            "source": "operator", "disposition": "excluded",
            "exclusion_reason": "out of scope",
        })
        self.assertEqual(self.engine.status(PKG)["inputs"], 1)

    def test_cancel_reaches_terminal(self):
        self.run_full_slice()
        self.apply("cancel", 5)
        self.assertEqual(self.engine.status(PKG)["state"], "CANCELLED")
        with self.assertRaises(IllegalTransitionError):
            self.apply("cancel", 6)

    def test_artifact_bytes_stored_and_verifiable(self):
        self.run_full_slice()
        manifest = self.store.load(PKG)
        art = manifest["artifacts"][0]
        self.assertEqual(
            self.artifacts.get(art["sha256"]),
            "# Standup Notes\nCapture daily standup notes.\n",
        )
        self.assertTrue(self.artifacts.verify(art["sha256"]))


if __name__ == "__main__":
    unittest.main()
