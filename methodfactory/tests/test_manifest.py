"""Manifest Contract v0.1 unit tests (ADR-0004)."""

from __future__ import annotations

import json
import unittest

from methodfactory.domain.states import State
from methodfactory.manifest.hashing import canonical_json, digest_json
from methodfactory.manifest.schema import new_manifest, validate_manifest


def valid_manifest(**overrides):
    m = new_manifest("pkg_demo_001", "Build a standup-notes skill", "2026-08-03T04:00:00+00:00")
    m.update(overrides)
    return m


class ManifestSchemaTests(unittest.TestCase):
    def test_new_manifest_is_valid(self):
        self.assertEqual(validate_manifest(valid_manifest()), [])

    def test_unknown_top_level_field(self):
        errors = validate_manifest(valid_manifest(evaluator_version="1.9.1"))
        self.assertTrue(any("unknown top-level field" in e for e in errors))

    def test_missing_required_field(self):
        m = valid_manifest()
        del m["revision"]
        errors = validate_manifest(m)
        self.assertTrue(any("revision" in e for e in errors))

    def test_bad_state(self):
        errors = validate_manifest(valid_manifest(state="AUTHORING"))
        self.assertTrue(any("invalid state" in e for e in errors))

    def test_bool_revision_rejected(self):
        errors = validate_manifest(valid_manifest(revision=True))
        self.assertTrue(any("revision" in e for e in errors))

    def test_negative_revision_rejected(self):
        errors = validate_manifest(valid_manifest(revision=-1))
        self.assertTrue(any("revision" in e for e in errors))

    def test_bad_previous_digest(self):
        errors = validate_manifest(valid_manifest(previous_manifest_sha256="nothex"))
        self.assertTrue(any("previous_manifest_sha256" in e for e in errors))

    def test_input_entry_missing_digest(self):
        m = valid_manifest()
        m["inputs"] = [
            {"input_id": "in_001", "kind": "text", "source": "operator",
             "disposition": "incorporated", "content_sha256": "zz",
             "content_size": 3, "content_path": "inputs/in_001.txt"}
        ]
        errors = validate_manifest(m)
        self.assertTrue(any("content_sha256" in e for e in errors))

    def test_input_exclusion_requires_reason(self):
        m = valid_manifest()
        m["inputs"] = [
            {"input_id": "in_001", "kind": "text", "source": "operator",
             "disposition": "excluded", "exclusion_reason": None,
             "content_sha256": "a" * 64, "content_size": 3,
             "content_path": "inputs/in_001.txt"}
        ]
        errors = validate_manifest(m)
        self.assertTrue(any("exclusion_reason" in e for e in errors))

    def test_artifact_bad_sha256(self):
        m = valid_manifest()
        m["artifacts"] = [
            {"artifact_id": "art_001", "kind": "skill",
             "logical_path": "skills/x/SKILL.md", "status": "draft",
             "sha256": "bad", "byte_count": 1}
        ]
        errors = validate_manifest(m)
        self.assertTrue(any("sha256" in e for e in errors))

    def test_summary_confirmation_bad_status(self):
        m = valid_manifest()
        m["summary"] = {
            "content": "s", "canonical_sha256": "a" * 64,
            "presented_at": "2026-08-03T04:00:00+00:00",
            "confirmation": {"status": "approved", "confirmed_at": None,
                             "operator_id": None, "confirmed_summary_sha256": None},
        }
        errors = validate_manifest(m)
        self.assertTrue(any("confirmation.status" in e for e in errors))

    def test_confirmed_requires_operator_and_time(self):
        m = valid_manifest()
        m["summary"] = {
            "content": "s", "canonical_sha256": "a" * 64,
            "presented_at": "2026-08-03T04:00:00+00:00",
            "confirmation": {"status": "confirmed", "confirmed_at": None,
                             "operator_id": None, "confirmed_summary_sha256": "a" * 64},
        }
        errors = validate_manifest(m)
        self.assertTrue(any("confirmed_at" in e or "operator_id" in e for e in errors))

    def test_invalid_timestamp(self):
        errors = validate_manifest(valid_manifest(created_at="yesterday"))
        self.assertTrue(any("created_at" in e for e in errors))

    def test_transition_field_type(self):
        errors = validate_manifest(
            valid_manifest(transition={"last_event_id": 5, "last_action_id": None})
        )
        self.assertTrue(any("transition.last_event_id" in e for e in errors))

    def test_canonical_digest_key_order_invariant(self):
        a = {"z": 1, "a": {"nested": 2, "list": [3, 1]}}
        b = {"a": {"list": [3, 1], "nested": 2}, "z": 1}
        self.assertEqual(digest_json(a), digest_json(b))
        self.assertEqual(canonical_json(a), canonical_json(b))

    def test_revision_increments_once(self):
        m1 = valid_manifest(revision=3)
        m2 = valid_manifest(revision=4)
        self.assertEqual(validate_manifest(m1), [])
        self.assertEqual(validate_manifest(m2), [])


if __name__ == "__main__":
    unittest.main()
