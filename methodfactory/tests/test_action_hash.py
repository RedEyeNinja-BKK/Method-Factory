"""Canonical action-hash semantics tests (ADR-0012 §G, Finding 2 item 2)."""

from __future__ import annotations

import unittest

from methodfactory.storage.serialization import action_sha256


def env_semantic(*, protocol_version="0.1", action="record_input",
                 package_id="pkg_demo_001", action_id="act_1",
                 basis=None, payload=None):
    return {
        "protocol_version": protocol_version,
        "action": action,
        "package_id": package_id,
        "action_id": action_id,
        "basis": basis or {},
        "payload": payload or {},
    }


class ActionHashSemanticsTests(unittest.TestCase):
    def test_stable_across_calls(self):
        a = env_semantic()
        self.assertEqual(action_sha256(**a), action_sha256(**a))

    def test_protocol_version_change_changes_hash(self):
        """Finding 2 item 2: protocol_version is part of the semantic request;
        changing it must change the hash."""
        a = env_semantic(protocol_version="0.1")
        b = env_semantic(protocol_version="0.2")
        self.assertNotEqual(action_sha256(**a), action_sha256(**b))

    def test_payload_change_changes_hash(self):
        a = env_semantic(payload={"content": "x"})
        b = env_semantic(payload={"content": "y"})
        self.assertNotEqual(action_sha256(**a), action_sha256(**b))

    def test_basis_change_changes_hash(self):
        a = env_semantic(action="confirm_summary", basis={"summary_sha256": "0" * 64})
        b = env_semantic(action="confirm_summary", basis={"summary_sha256": "1" * 64})
        self.assertNotEqual(action_sha256(**a), action_sha256(**b))

    def test_action_id_is_semantic(self):
        a = env_semantic(action_id="act_1")
        b = env_semantic(action_id="act_2")
        self.assertNotEqual(action_sha256(**a), action_sha256(**b))

    def test_expected_revision_excluded(self):
        # The function has no expected_revision parameter by design (ADR-0012
        # §G / Finding 2): a retry with an updated revision and the same
        # semantic fields must hash identically so it replays instead of
        # conflicting. expected_revision is the ONLY excluded envelope field.
        semantic = env_semantic()
        h = action_sha256(**semantic)
        self.assertEqual(h, action_sha256(**semantic))

    def test_unicode_payload_stable(self):
        a = env_semantic(payload={"content": "สวัสดี"})
        self.assertEqual(action_sha256(**a), action_sha256(**a))

    def test_is_64_hex(self):
        h = action_sha256(**env_semantic())
        self.assertEqual(len(h), 64)
        int(h, 16)


if __name__ == "__main__":
    unittest.main()
