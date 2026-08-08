"""Engine transition unit tests — pure manifest transformation rules.

Covers the deterministic apply rule (legality -> gate -> mutation ->
revision/lineage) without any storage. Each action's manifest mutation,
blob requirements, illegal transitions, and gate failures are asserted
directly.
"""

from __future__ import annotations

import unittest

from methodfactory.domain.errors import (
    GateUnsatisfiedError,
    IllegalTransitionError,
    InvalidPayloadError,
    StaleActionError,
)
from methodfactory.engine.apply import next_manifest
from methodfactory.manifest.render import render_summary
from methodfactory.manifest.schema import new_manifest
from methodfactory.protocol.envelope import envelope_from_dict
from methodfactory.storage.serialization import digest_bytes, digest_json


def _env(action, *, package_id="pkg_demo_001", action_id="act_1",
         expected_revision=0, basis=None, payload=None):
    return envelope_from_dict({
        "protocol_version": "0.1",
        "action_id": action_id,
        "package_id": package_id,
        "expected_revision": expected_revision,
        "action": action,
        "basis": basis or {},
        "payload": payload or {},
    })


def _intake(revision=0, **over):
    m = new_manifest("pkg_demo_001", "Build a skill", "2026-08-07T00:00:00+00:00")
    m["revision"] = revision
    m.update(over)
    return m


def _summary_pending(revision=3):
    m = _intake(revision=revision)
    m["state"] = "SUMMARY_PENDING"
    m["objective"] = {"statement": "Build a skill", "desired_outcomes": []}
    m["summary"] = {
        "digest": "0" * 64,
        "size": 1,
        "preview": "p",
        "presented_at": "2026-08-07T00:00:00+00:00",
        "confirmation": {"status": "pending", "confirmed_at": None,
                         "operator_id": None, "confirmed_summary_sha256": None},
    }
    return m


class RecordInputTests(unittest.TestCase):
    def test_appends_input_with_digest_size_path(self):
        m, blobs = next_manifest(
            _intake(), _env("record_input", payload={
                "input_id": "in_1", "kind": "text", "content": "hello",
                "source": "operator", "disposition": "incorporated"}),
            event_id="evt_1", created_at="2026-08-07T01:00:00+00:00",
        )
        self.assertEqual(m["revision"], 1)
        self.assertEqual(m["state"], "INTAKE")
        self.assertEqual(len(m["inputs"]), 1)
        entry = m["inputs"][0]
        self.assertEqual(entry["input_id"], "in_1")
        self.assertEqual(entry["content_sha256"], digest_bytes(b"hello"))
        self.assertEqual(entry["content_size"], 5)
        self.assertEqual(entry["content_path"], "inputs/in_1.txt")
        self.assertEqual(blobs, [("inputs/in_1.txt", "hello")])

    def test_excluded_input_keeps_reason(self):
        m, _ = next_manifest(
            _intake(), _env("record_input", payload={
                "input_id": "in_1", "kind": "url", "content": "https://x",
                "source": "operator", "disposition": "excluded",
                "exclusion_reason": "duplicate"}),
            event_id="evt_1", created_at="2026-08-07T01:00:00+00:00",
        )
        self.assertEqual(m["inputs"][0]["exclusion_reason"], "duplicate")

    def test_duplicate_input_id_rejected_by_gate(self):
        cur = _intake()
        cur["inputs"] = [{
            "input_id": "in_1", "kind": "text", "source": "operator",
            "disposition": "incorporated", "exclusion_reason": None,
            "content_sha256": "0" * 64, "content_size": 1,
            "content_path": "inputs/in_1.txt"}]
        with self.assertRaises(InvalidPayloadError):
            next_manifest(
                cur, _env("record_input", payload={
                    "input_id": "in_1", "kind": "text", "content": "x",
                    "source": "operator", "disposition": "incorporated"}),
                event_id="evt_1", created_at="2026-08-07T01:00:00+00:00",
            )


class SetObjectiveTests(unittest.TestCase):
    def test_sets_objective(self):
        m, blobs = next_manifest(
            _intake(), _env("set_objective", payload={
                "statement": "Build a skill", "desired_outcomes": ["a", "b"]}),
            event_id="evt_1", created_at="2026-08-07T01:00:00+00:00",
        )
        self.assertEqual(m["objective"]["statement"], "Build a skill")
        self.assertEqual(m["objective"]["desired_outcomes"], ["a", "b"])
        self.assertEqual(blobs, [])

    def test_empty_statement_rejected(self):
        with self.assertRaises(InvalidPayloadError):
            next_manifest(
                _intake(), _env("set_objective", payload={
                    "statement": "  ", "desired_outcomes": []}),
                event_id="evt_1", created_at="2026-08-07T01:00:00+00:00",
            )


class PrepareSummaryTests(unittest.TestCase):
    def test_produces_content_addressed_summary(self):
        cur = _intake(revision=2)
        cur["objective"] = {"statement": "Build a skill", "desired_outcomes": []}
        m, blobs = next_manifest(
            cur, _env("prepare_summary"),
            event_id="evt_3", created_at="2026-08-07T03:00:00+00:00",
        )
        self.assertEqual(m["state"], "SUMMARY_PENDING")
        summary = m["summary"]
        body = render_summary(cur)
        self.assertEqual(summary["digest"], digest_bytes(body.encode("utf-8")))
        self.assertEqual(summary["size"], len(body.encode("utf-8")))
        self.assertTrue(summary["preview"])
        self.assertEqual(summary["presented_at"], "2026-08-07T03:00:00+00:00")
        self.assertEqual(summary["confirmation"]["status"], "pending")
        self.assertEqual(blobs, [("summaries/r3.txt", body)])

    def test_missing_objective_rejected(self):
        with self.assertRaises(GateUnsatisfiedError):
            next_manifest(
                _intake(), _env("prepare_summary"),
                event_id="evt_1", created_at="2026-08-07T03:00:00+00:00",
            )


class ConfirmSummaryTests(unittest.TestCase):
    def test_confirms_with_default_operator(self):
        cur = _summary_pending()
        m, _ = next_manifest(
            cur, _env("confirm_summary", basis={"summary_sha256": "0" * 64},
                      payload={}),
            event_id="evt_4", created_at="2026-08-07T04:00:00+00:00",
        )
        self.assertEqual(m["state"], "AUTHORING_AUTHORIZED")
        conf = m["summary"]["confirmation"]
        self.assertEqual(conf["status"], "confirmed")
        self.assertEqual(conf["operator_id"], "operator")
        self.assertEqual(conf["confirmed_summary_sha256"], "0" * 64)
        self.assertEqual(conf["confirmed_at"], "2026-08-07T04:00:00+00:00")

    def test_wrong_digest_is_stale(self):
        with self.assertRaises(StaleActionError):
            next_manifest(
                _summary_pending(), _env("confirm_summary",
                                         basis={"summary_sha256": "1" * 64},
                                         payload={}),
                event_id="evt_4", created_at="2026-08-07T04:00:00+00:00",
            )

    def test_missing_summary_rejected(self):
        with self.assertRaises(GateUnsatisfiedError):
            next_manifest(
                _intake(revision=1, state="SUMMARY_PENDING"),
                _env("confirm_summary", basis={"summary_sha256": "0" * 64},
                     payload={}),
                event_id="evt_4", created_at="2026-08-07T04:00:00+00:00",
            )


class ReviseIntakeTests(unittest.TestCase):
    def test_clears_summary_and_artifacts(self):
        cur = _summary_pending()
        cur["artifacts"] = [{
            "artifact_id": "art_1", "kind": "skill",
            "logical_path": "skills/x/SKILL.md", "sha256": "0" * 64,
            "byte_count": 1, "status": "draft"}]
        cur["inputs"] = [{
            "input_id": "in_1", "kind": "text", "source": "operator",
            "disposition": "incorporated", "exclusion_reason": None,
            "content_sha256": "0" * 64, "content_size": 1,
            "content_path": "inputs/in_1.txt"}]
        m, _ = next_manifest(
            cur, _env("revise_intake"),
            event_id="evt_5", created_at="2026-08-07T05:00:00+00:00",
        )
        self.assertEqual(m["state"], "INTAKE")
        self.assertIsNone(m["summary"])
        self.assertEqual(m["artifacts"], [])
        # intake material (inputs + objective) is preserved
        self.assertEqual(len(m["inputs"]), 1)
        self.assertEqual(m["inputs"][0]["input_id"], "in_1")
        self.assertEqual(m["objective"]["statement"], "Build a skill")


class RecordDraftArtifactTests(unittest.TestCase):
    def test_appends_artifact(self):
        cur = _summary_pending()
        cur["state"] = "AUTHORING_AUTHORIZED"
        cur["summary"]["confirmation"] = {
            "status": "confirmed", "confirmed_at": "2026-08-07T04:00:00+00:00",
            "operator_id": "operator", "confirmed_summary_sha256": "0" * 64}
        m, blobs = next_manifest(
            cur, _env("record_draft_artifact", payload={
                "artifact_id": "art_1", "kind": "skill",
                "logical_path": "skills/x/SKILL.md", "content": "body"}),
            event_id="evt_6", created_at="2026-08-07T06:00:00+00:00",
        )
        self.assertEqual(m["state"], "DRAFT_READY")
        art = m["artifacts"][0]
        self.assertEqual(art["sha256"], digest_bytes(b"body"))
        self.assertEqual(art["byte_count"], 4)
        self.assertEqual(art["status"], "draft")
        self.assertEqual(blobs, [("skills/x/SKILL.md", "body")])

    def test_unconfirmed_authoring_rejected(self):
        cur = _summary_pending()
        cur["state"] = "AUTHORING_AUTHORIZED"
        with self.assertRaises(GateUnsatisfiedError):
            next_manifest(
                cur, _env("record_draft_artifact", payload={
                    "artifact_id": "art_1", "kind": "skill",
                    "logical_path": "skills/x/SKILL.md", "content": "body"}),
                event_id="evt_6", created_at="2026-08-07T06:00:00+00:00",
            )


class CancelTests(unittest.TestCase):
    def test_cancel_transitions_only(self):
        cur = _intake(revision=1)
        cur["inputs"] = [{
            "input_id": "in_1", "kind": "text", "source": "operator",
            "disposition": "incorporated", "exclusion_reason": None,
            "content_sha256": "0" * 64, "content_size": 1,
            "content_path": "inputs/in_1.txt"}]
        m, blobs = next_manifest(
            cur, _env("cancel", payload={"reason": "no longer needed"}),
            event_id="evt_2", created_at="2026-08-07T02:00:00+00:00",
        )
        self.assertEqual(m["state"], "CANCELLED")
        self.assertEqual(len(m["inputs"]), 1)
        self.assertEqual(blobs, [])


class CommonLineageTests(unittest.TestCase):
    def test_revision_state_lineage(self):
        cur = _intake(revision=7)
        m, _ = next_manifest(
            cur, _env("record_input", payload={
                "input_id": "in_9", "kind": "text", "content": "x",
                "source": "operator", "disposition": "incorporated"}),
            event_id="evt_8", created_at="2026-08-07T08:00:00+00:00",
        )
        self.assertEqual(m["revision"], 8)
        self.assertEqual(m["updated_at"], "2026-08-07T08:00:00+00:00")
        self.assertEqual(m["previous_manifest_sha256"], digest_json(cur))
        self.assertEqual(m["transition"]["last_event_id"], "evt_8")
        self.assertEqual(m["transition"]["last_action_id"], "act_1")

    def test_illegal_transition(self):
        with self.assertRaises(IllegalTransitionError):
            next_manifest(
                _summary_pending(), _env("record_input", payload={
                    "input_id": "in_1", "kind": "text", "content": "x",
                    "source": "operator", "disposition": "incorporated"}),
                event_id="evt_9", created_at="2026-08-07T09:00:00+00:00",
            )

    def test_malformed_revision_rejected(self):
        """Local review (q-3): a non-int/bool revision is rejected typed, not
        coerced or leaked."""
        for bad in (None, "abc", [1], 1.5, True):
            with self.subTest(revision=bad):
                with self.assertRaises(InvalidPayloadError):
                    next_manifest(
                        _intake(revision=bad), _env("record_input", payload={
                            "input_id": "in_1", "kind": "text", "content": "x",
                            "source": "operator", "disposition": "incorporated"}),
                        event_id="evt_9", created_at="2026-08-07T09:00:00+00:00",
                    )

    def test_malformed_manifest_render_translated(self):
        """Local review (bug-3): a structurally malformed current manifest
        cannot leak a raw KeyError from render_summary — it is translated."""
        cur = _intake(revision=2)
        cur["objective"] = {"statement": "Build a skill", "desired_outcomes": []}
        cur["inputs"] = [{"input_id": "in_1", "kind": "text"}]  # missing fields
        with self.assertRaises(InvalidPayloadError):
            next_manifest(
                cur, _env("prepare_summary"),
                event_id="evt_3", created_at="2026-08-07T03:00:00+00:00",
            )


class MutatorCoverageTests(unittest.TestCase):
    def test_every_legal_action_has_a_mutator(self):
        """Local review (q-4): the mutator registry is structurally linked to
        the Action vocabulary so a future transition-table addition cannot
        silently lack an implementation."""
        from methodfactory.domain.transitions import Action
        from methodfactory.engine import apply as apply_mod

        registered = set(apply_mod._ACTION_MUTATORS)
        self.assertEqual(registered, set(Action))


if __name__ == "__main__":
    unittest.main()
