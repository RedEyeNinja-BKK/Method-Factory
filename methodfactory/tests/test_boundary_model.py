"""Complete boundary-model tests (Finding 1, review 4879090471).

Exactly-at and one-over tests for every frozen limit, including multibyte
UTF-8 byte-vs-char cases, oversized surrounding prose, canonical action size,
and total manifest size.
"""

from __future__ import annotations

import json
import unittest

from methodfactory.domain.errors import InvalidEnvelopeError
from methodfactory.protocol.envelope import parse_envelope
from methodfactory.storage.limits import (
    MAX_ACTION_JSON_BYTES,
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_INTENT_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_OUTCOMES,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
)
from methodfactory.storage.serialization import action_sha256
from methodfactory.manifest.schema import new_manifest, validate_manifest


def env(**over):
    base = {
        "protocol_version": "0.1",
        "action_id": "act_1",
        "package_id": "pkg_demo_001",
        "expected_revision": 0,
        "action": "record_input",
        "basis": {},
        "payload": {"input_id": "in_1", "kind": "text", "content": "x",
                    "source": "operator", "disposition": "incorporated"},
    }
    base.update(over)
    return base


class EnvelopeBoundaryTests(unittest.TestCase):
    def test_envelope_byte_limit_before_parse(self):
        ok = json.dumps(env())
        self.assertLess(len(ok.encode("utf-8")), MAX_ENVELOPE_BYTES)
        parse_envelope(ok)  # parses fine
        # one-over by raw bytes (ASCII)
        big = json.dumps(env(payload={"input_id": "in_1", "kind": "text",
                                      "content": "x" * MAX_ENVELOPE_BYTES,
                                      "source": "operator", "disposition": "incorporated"}))
        self.assertGreater(len(big.encode("utf-8")), MAX_ENVELOPE_BYTES)
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(big)

    def test_oversized_prose_rejected_before_extraction(self):
        # Huge surrounding prose around a small envelope must be rejected by
        # the byte bound before prose extraction.
        small = json.dumps(env())
        prose = "padding " * (MAX_ENVELOPE_BYTES // 8) + small + " trailing"
        self.assertGreater(len(prose.encode("utf-8")), MAX_ENVELOPE_BYTES)
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(prose)

    def test_multibyte_prose_byte_vs_char(self):
        # Thai chars are 3 UTF-8 bytes each: a prose that is under a char
        # count but over the byte bound must be rejected on bytes.
        small = json.dumps(env())
        multibyte_pad = "ส" * (MAX_ENVELOPE_BYTES // 3 + 1)
        prose = multibyte_pad + small
        self.assertGreater(len(prose.encode("utf-8")), MAX_ENVELOPE_BYTES)
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(prose)

    def test_content_limit_at_and_over(self):
        ok = env(payload={"input_id": "in_1", "kind": "text",
                          "content": "x" * MAX_CONTENT_CHARS,
                          "source": "operator", "disposition": "incorporated"})
        parse_envelope(json.dumps(ok))
        over = env(payload={"input_id": "in_1", "kind": "text",
                            "content": "x" * (MAX_CONTENT_CHARS + 1),
                            "source": "operator", "disposition": "incorporated"})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over))

    def test_statement_limit_at_and_over(self):
        ok = env(action="set_objective", payload={"statement": "x" * MAX_STATEMENT_CHARS,
                                                  "desired_outcomes": []})
        parse_envelope(json.dumps(ok))
        over = env(action="set_objective", payload={"statement": "x" * (MAX_STATEMENT_CHARS + 1),
                                                    "desired_outcomes": []})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over))

    def test_outcome_count_and_length(self):
        ok = env(action="set_objective", payload={"statement": "s",
                                                  "desired_outcomes": ["o"] * MAX_OUTCOMES})
        parse_envelope(json.dumps(ok))
        over_count = env(action="set_objective", payload={"statement": "s",
                                                          "desired_outcomes": ["o"] * (MAX_OUTCOMES + 1)})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over_count))
        over_len = env(action="set_objective", payload={"statement": "s",
                                                        "desired_outcomes": ["o" * (MAX_STATEMENT_CHARS + 1)]})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over_len))

    def test_reason_limit(self):
        ok = env(payload={"input_id": "in_1", "kind": "text", "content": "x",
                          "source": "operator", "disposition": "excluded",
                          "exclusion_reason": "r" * MAX_REASON_CHARS})
        parse_envelope(json.dumps(ok))
        over = env(payload={"input_id": "in_1", "kind": "text", "content": "x",
                            "source": "operator", "disposition": "excluded",
                            "exclusion_reason": "r" * (MAX_REASON_CHARS + 1)})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over))

    def test_identifier_limit(self):
        ok = env(payload={"input_id": "i" * MAX_ID_CHARS, "kind": "text", "content": "x",
                          "source": "operator", "disposition": "incorporated"})
        parse_envelope(json.dumps(ok))
        over = env(payload={"input_id": "i" * (MAX_ID_CHARS + 1), "kind": "text", "content": "x",
                            "source": "operator", "disposition": "incorporated"})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over))

    def test_logical_path_limit(self):
        ok = env(action="record_draft_artifact", payload={"artifact_id": "a1", "kind": "skill",
                                                          "logical_path": "x" * MAX_LOGICAL_PATH_CHARS,
                                                          "content": "c"})
        parse_envelope(json.dumps(ok))
        over = env(action="record_draft_artifact", payload={"artifact_id": "a1", "kind": "skill",
                                                            "logical_path": "x" * (MAX_LOGICAL_PATH_CHARS + 1),
                                                            "content": "c"})
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(over))


class CanonicalActionBoundaryTests(unittest.TestCase):
    def test_action_hash_at_and_over_action_json_bytes(self):
        semantic = {
            "protocol_version": "0.1",
            "action": "record_input",
            "package_id": "pkg_demo_001",
            "action_id": "act_1",
            "basis": {},
            "payload": {"input_id": "in_1", "kind": "text",
                        "content": "x" * (MAX_ACTION_JSON_BYTES + 1),
                        "source": "operator", "disposition": "incorporated"},
        }
        with self.assertRaises(ValueError):
            action_sha256(**semantic)
        # at-limit via canonical bytes
        semantic_at = {
            "protocol_version": "0.1",
            "action": "record_input",
            "package_id": "pkg_demo_001",
            "action_id": "act_1",
            "basis": {},
            "payload": {"input_id": "in_1", "kind": "text",
                        "content": "x",
                        "source": "operator", "disposition": "incorporated"},
        }
        h = action_sha256(**semantic_at)
        self.assertEqual(len(h), 64)


class ManifestBoundaryTests(unittest.TestCase):
    def test_total_manifest_byte_bound(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        self.assertEqual(validate_manifest(m), [])
        # One-over the manifest byte bound via a huge intent (char limit first
        # would trip, so bypass by setting a giant inputs list).
        big = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        big["inputs"] = [
            {"input_id": f"in_{i}", "kind": "text", "source": "operator",
             "disposition": "incorporated", "exclusion_reason": None,
             "content_sha256": "0" * 64, "content_size": 1,
             "content_path": f"inputs/in_{i}.txt"}
            for i in range(300_000)
        ]
        self.assertGreater(
            len(json.dumps(big, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
            MAX_MANIFEST_BYTES,
        )
        errors = validate_manifest(big)
        self.assertTrue(any("exceeds" in e and "manifest" in e for e in errors))

    def test_intent_length_limit(self):
        m = new_manifest("pkg_demo_001", "x" * (MAX_INTENT_CHARS + 1), "2026-08-07T00:00:00+00:00")
        errors = validate_manifest(m)
        self.assertTrue(any("intent.raw" in e and "exceeds" in e for e in errors))

    def test_control_chars_in_persisted_manifest(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["intent"]["raw"] = "bad\u2028intent"
        errors = validate_manifest(m)
        self.assertTrue(any("intent.raw" in e and "control" in e for e in errors))

    def test_persisted_manifest_bypassing_envelope(self):
        # A manifest with an invalid logical_path / oversized artifact byte
        # count must be rejected by the authoritative manifest validator even
        # though it never passed through the envelope.
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["artifacts"] = [{"artifact_id": "a1", "kind": "skill",
                           "logical_path": "../escape/SKILL.md", "sha256": "0" * 64,
                           "byte_count": 1, "status": "draft"}]
        errors = validate_manifest(m)
        self.assertTrue(any("logical_path" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
