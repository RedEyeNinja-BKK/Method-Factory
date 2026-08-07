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
from methodfactory.storage.errors import SerializationError
from methodfactory.storage.limits import (
    MAX_ACTION_JSON_BYTES,
    MAX_ARTIFACT_BODY_BYTES,
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_INPUT_CONTENT_BYTES,
    MAX_INTENT_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_OUTCOMES,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
    MAX_SUMMARY_BYTES,
)
from methodfactory.storage.serialization import action_sha256, canonical_bytes
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

    def test_raw_envelope_exact_at_and_one_over_before_strip(self):
        """MAX_ENVELOPE_BYTES is measured on the ORIGINAL raw UTF-8 BEFORE
        strip()/parse. Trailing whitespace counts toward the bound: exactly-at
        with padding is accepted; one more byte fails."""
        base = json.dumps(env())
        base_len = len(base.encode("utf-8"))
        self.assertLess(base_len, MAX_ENVELOPE_BYTES)
        pad = MAX_ENVELOPE_BYTES - base_len
        at = base + " " * pad
        self.assertEqual(len(at.encode("utf-8")), MAX_ENVELOPE_BYTES)
        self.assertEqual(parse_envelope(at).action_id, "act_1")  # accepted exactly at
        over = base + " " * (pad + 1)
        self.assertEqual(len(over.encode("utf-8")), MAX_ENVELOPE_BYTES + 1)
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(over)

    def test_raw_envelope_multibyte_exact_at_and_one_over(self):
        """Multibyte (3-byte Thai chars) at the raw byte boundary: exactly-at
        accepted, one byte over rejected. Character count is far below the
        byte bound, proving the byte (not char) measurement."""
        base = json.dumps(env())
        remaining = MAX_ENVELOPE_BYTES - len(base.encode("utf-8"))
        thai_chars = remaining // 3
        pad = remaining - 3 * thai_chars
        at = base + "ส" * thai_chars + " " * pad
        self.assertEqual(len(at.encode("utf-8")), MAX_ENVELOPE_BYTES)
        self.assertLess(len(at), MAX_ENVELOPE_BYTES)  # chars < bytes (multibyte)
        self.assertEqual(parse_envelope(at).action_id, "act_1")
        over = at + "x"
        self.assertEqual(len(over.encode("utf-8")), MAX_ENVELOPE_BYTES + 1)
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(over)

    def test_lone_surrogate_raw_envelope_translated(self):
        """A raw envelope containing a literal lone surrogate cannot be encoded
        as UTF-8; the failure must be translated to InvalidEnvelopeError, not
        leak a raw UnicodeEncodeError."""
        raw = ('{"protocol_version":"0.1","action_id":"act_1",'
               '"package_id":"pkg_demo_001","expected_revision":0,'
               '"action":"record_input","basis":{},"payload":'
               '{"input_id":"in_1","kind":"text","content":"\ud800",'
               '"source":"operator","disposition":"incorporated"}}')
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(raw)

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
    def test_action_hash_exact_at_and_one_over(self):
        """MAX_ACTION_JSON_BYTES is enforced on the exact canonical bytes of
        the semantic action: exactly-at hashes, one-over is rejected."""
        semantic = {
            "protocol_version": "0.1",
            "action": "record_input",
            "package_id": "pkg_demo_001",
            "action_id": "act_1",
            "basis": {},
            "payload": {"input_id": "in_1", "kind": "text",
                        "content": "x",
                        "source": "operator", "disposition": "incorporated"},
        }
        base_len = len(canonical_bytes(semantic))
        self.assertLess(base_len, MAX_ACTION_JSON_BYTES)
        # base_len already includes content="x" (1 byte); add MAX-base_len+1
        # 'x' chars so the canonical size lands EXACTLY on the bound.
        k = MAX_ACTION_JSON_BYTES - base_len + 1
        at = dict(semantic)
        at["payload"] = dict(semantic["payload"], content="x" * k)
        self.assertEqual(len(canonical_bytes(at)), MAX_ACTION_JSON_BYTES)
        self.assertEqual(len(action_sha256(**at)), 64)  # exactly-at accepted
        over = dict(semantic)
        over["payload"] = dict(semantic["payload"], content="x" * (k + 1))
        self.assertEqual(len(canonical_bytes(over)), MAX_ACTION_JSON_BYTES + 1)
        with self.assertRaises(SerializationError):
            action_sha256(**over)

    def test_action_hash_unicode_and_recursion_failures_do_not_leak_raw(self):
        """Non-canonicalizable semantic payloads (lone surrogate, deep
        recursion) must surface as typed SerializationError, never a raw
        UnicodeEncodeError/RecursionError (Finding 4)."""
        sur = {
            "protocol_version": "0.1", "action": "record_input",
            "package_id": "pkg_demo_001", "action_id": "act_1",
            "basis": {}, "payload": {"content": "x\ud800"},
        }
        with self.assertRaises(SerializationError) as ctx:
            action_sha256(**sur)
        self.assertEqual(ctx.exception.code, "SERIALIZATION")
        deep_payload: dict = {}
        cur = deep_payload
        for _ in range(20_000):
            nxt: dict = {}
            cur["a"] = nxt
            cur = nxt
        with self.assertRaises(SerializationError):
            action_sha256(**{
                "protocol_version": "0.1", "action": "record_input",
                "package_id": "pkg_demo_001", "action_id": "act_1",
                "basis": {}, "payload": deep_payload,
            })


def _valid_input(input_id: str = "in_1", **over) -> dict:
    entry = {
        "input_id": input_id,
        "kind": "text",
        "source": "operator",
        "disposition": "incorporated",
        "exclusion_reason": None,
        "content_sha256": "0" * 64,
        "content_size": 1,
        "content_path": f"inputs/{input_id}.txt",
    }
    entry.update(over)
    return entry


def _manifest_with_inputs(n: int, *, reason_len: int = 1) -> dict:
    """Build a manifest with n valid EXCLUDED input entries, each carrying an
    exclusion_reason of exactly `reason_len` bytes. All entries are uniform so
    canonical size grows linearly and can be tuned to an exact byte count."""
    m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
    m["inputs"] = [
        _valid_input(
            input_id=f"in_{i:06d}",
            disposition="excluded",
            exclusion_reason="x" * reason_len,
        )
        for i in range(n)
    ]
    return m


def _valid_summary(**over) -> dict:
    summary = {
        "digest": "0" * 64,
        "size": 1,
        "preview": None,
        "presented_at": "2026-08-07T00:00:00+00:00",
        "confirmation": {"status": "pending"},
    }
    summary.update(over)
    return summary


def _valid_artifact(**over) -> dict:
    art = {
        "artifact_id": "art_1",
        "kind": "skill",
        "logical_path": "skills/x/SKILL.md",
        "sha256": "0" * 64,
        "byte_count": 1,
        "status": "draft",
    }
    art.update(over)
    return art


class ManifestBoundaryTests(unittest.TestCase):
    def test_total_manifest_bytes_exact_at_and_one_over(self):
        """MAX_MANIFEST_BYTES is enforced on the exact canonical bytes of the
        complete manifest. The at-limit manifest is tuned to land EXACTLY on
        the bound (and validates clean); one entry more is one byte over."""
        base = _manifest_with_inputs(0)
        base_len = len(canonical_bytes(base))
        one = _manifest_with_inputs(1, reason_len=1)
        two = _manifest_with_inputs(2, reason_len=1)
        first_entry = len(canonical_bytes(one)) - base_len
        extra_entry = len(canonical_bytes(two)) - len(canonical_bytes(one))
        need = MAX_MANIFEST_BYTES - base_len
        # total(q) = base_len + first_entry + (q-1)*extra_entry
        q_minus_1, r = divmod(need - first_entry, extra_entry)
        q = q_minus_1 + 1
        at = _manifest_with_inputs(q, reason_len=1)
        if r:
            at["inputs"][-1]["exclusion_reason"] = "x" * (1 + r)
        self.assertEqual(len(canonical_bytes(at)), MAX_MANIFEST_BYTES)
        self.assertEqual(validate_manifest(at), [])  # exactly-at accepted
        over = _manifest_with_inputs(q + 1, reason_len=1)
        self.assertEqual(
            len(canonical_bytes(over)), MAX_MANIFEST_BYTES + (extra_entry - r)
        )
        errors = validate_manifest(over)
        self.assertTrue(any("exceeds" in e and "manifest" in e for e in errors))

    def test_persisted_input_content_size_bytes_at_and_over(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["inputs"] = [_valid_input(content_size=MAX_INPUT_CONTENT_BYTES)]
        self.assertEqual(validate_manifest(m), [])
        m["inputs"][0]["content_size"] = MAX_INPUT_CONTENT_BYTES + 1
        errors = validate_manifest(m)
        self.assertTrue(any("content_size" in e and "bytes" in e for e in errors))

    def test_persisted_summary_size_bytes_at_and_over(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["summary"] = _valid_summary(size=MAX_SUMMARY_BYTES)
        self.assertEqual(validate_manifest(m), [])
        m["summary"]["size"] = MAX_SUMMARY_BYTES + 1
        errors = validate_manifest(m)
        self.assertTrue(any("summary.size" in e and "bytes" in e for e in errors))

    def test_persisted_artifact_byte_count_bytes_at_and_over(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["artifacts"] = [_valid_artifact(byte_count=MAX_ARTIFACT_BODY_BYTES)]
        self.assertEqual(validate_manifest(m), [])
        m["artifacts"][0]["byte_count"] = MAX_ARTIFACT_BODY_BYTES + 1
        errors = validate_manifest(m)
        self.assertTrue(any("byte_count" in e and "bytes" in e for e in errors))

    def test_manifest_canonicalization_failures_collected(self):
        """validate_manifest() must never leak raw TypeError/RecursionError/
        UnicodeEncodeError from canonicalization; they become manifest errors."""
        # TypeError: non-JSON-serializable value
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["objective"]["desired_outcomes"] = [set()]
        errors = validate_manifest(m)
        self.assertTrue(any("cannot be canonicalized" in e for e in errors))
        # RecursionError: deeply nested value (depth 20000 is above the
        # CPython 3.11/3.12 C-encoder RecursionError threshold; local review:
        # depth 5000 serializes fine on 3.12 and would not exercise the path).
        deep = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        node: dict = {}
        cur = node
        for _ in range(20_000):
            nxt: dict = {}
            cur["a"] = nxt
            cur = nxt
        deep["inputs"] = [_valid_input(exclusion_reason=node)]
        errors = validate_manifest(deep)
        self.assertTrue(any("cannot be canonicalized" in e for e in errors))
        # UnicodeEncodeError: lone surrogate in a string field
        sur = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        sur["intent"]["raw"] = "x\ud800"
        errors = validate_manifest(sur)
        self.assertTrue(any("cannot be canonicalized" in e for e in errors))

    def test_intent_clarified_rules(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["intent"]["clarified"] = "c" * MAX_INTENT_CHARS
        self.assertEqual(validate_manifest(m), [])
        m["intent"]["clarified"] = "c" * (MAX_INTENT_CHARS + 1)
        self.assertTrue(any("intent.clarified" in e and "exceeds" in e for e in validate_manifest(m)))
        m["intent"]["clarified"] = "bad\u2028clarified"
        self.assertTrue(any("intent.clarified" in e and "control" in e for e in validate_manifest(m)))
        m["intent"]["clarified"] = 5
        self.assertTrue(any("intent.clarified" in e for e in validate_manifest(m)))

    def test_exclusion_reason_rules(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["inputs"] = [_valid_input(disposition="excluded", exclusion_reason="r" * MAX_REASON_CHARS)]
        self.assertEqual(validate_manifest(m), [])
        m["inputs"][0]["exclusion_reason"] = "r" * (MAX_REASON_CHARS + 1)
        self.assertTrue(any("exclusion_reason" in e and "exceeds" in e for e in validate_manifest(m)))
        m["inputs"][0]["exclusion_reason"] = "bad\x01reason"
        self.assertTrue(any("exclusion_reason" in e and "control" in e for e in validate_manifest(m)))
        m["inputs"][0]["exclusion_reason"] = 5
        self.assertTrue(any("exclusion_reason" in e for e in validate_manifest(m)))

    def test_summary_preview_control_chars(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["summary"] = _valid_summary(preview="ok preview")
        self.assertEqual(validate_manifest(m), [])
        m["summary"]["preview"] = "bad\u2028preview"
        self.assertTrue(any("preview" in e and "control" in e for e in validate_manifest(m)))

    def test_operator_id_identifier_rule(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["summary"] = _valid_summary(
            confirmation={
                "status": "confirmed",
                "confirmed_summary_sha256": "0" * 64,
                "confirmed_at": "2026-08-07T00:00:00+00:00",
                "operator_id": "op_alice-1",
            }
        )
        self.assertEqual(validate_manifest(m), [])
        m["summary"]["confirmation"]["operator_id"] = "../evil"
        self.assertTrue(any("operator_id" in e for e in validate_manifest(m)))
        m["summary"]["confirmation"]["operator_id"] = 5
        self.assertTrue(any("operator_id" in e for e in validate_manifest(m)))

    def test_transition_identifiers(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["transition"] = {"last_event_id": "evt_1", "last_action_id": "act_1"}
        self.assertEqual(validate_manifest(m), [])
        m["transition"]["last_event_id"] = "bad id"
        self.assertTrue(any("last_event_id" in e for e in validate_manifest(m)))
        m["transition"]["last_action_id"] = 5
        self.assertTrue(any("last_action_id" in e for e in validate_manifest(m)))

    def test_artifact_kind_identifier(self):
        m = new_manifest("pkg_demo_001", "x", "2026-08-07T00:00:00+00:00")
        m["artifacts"] = [_valid_artifact()]
        self.assertEqual(validate_manifest(m), [])
        m["artifacts"][0]["kind"] = "bad kind!"
        self.assertTrue(any("kind" in e and "identifier" in e for e in validate_manifest(m)))

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
