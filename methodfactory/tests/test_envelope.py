"""Action Envelope unit tests — schema boundary (ADR-0005)."""

from __future__ import annotations

import json
import unittest

from methodfactory.domain.errors import InvalidEnvelopeError
from methodfactory.protocol.envelope import parse_envelope


def record_input_payload(**overrides):
    payload = {
        "input_id": "in_001",
        "kind": "text",
        "content": "some material",
        "source": "operator",
        "disposition": "incorporated",
    }
    payload.update(overrides)
    return payload


def envelope(action="record_input", revision=0, basis=None, payload=None, **fields):
    env = {
        "protocol_version": "0.1",
        "action_id": "act_test_001",
        "package_id": "pkg_demo_001",
        "expected_revision": revision,
        "action": action,
        "basis": basis or {},
        "payload": payload if payload is not None else record_input_payload(),
    }
    env.update(fields)
    return env


class EnvelopeParseTests(unittest.TestCase):
    def test_valid_envelope_parses(self):
        env = parse_envelope(json.dumps(envelope()))
        self.assertEqual(env.action, "record_input")
        self.assertEqual(env.expected_revision, 0)
        self.assertEqual(env.package_id, "pkg_demo_001")
        self.assertEqual(env.payload["input_id"], "in_001")

    def test_valid_empty_payload_action(self):
        env = parse_envelope(json.dumps(envelope(action="prepare_summary", payload={})))
        self.assertEqual(env.action, "prepare_summary")

    def test_invalid_json_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope("{not json")

    def test_empty_input_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope("")

    def test_prose_wrapped_envelope_parses(self):
        raw = 'Sure thing! Here is my proposal:\n\n```json\n' + json.dumps(envelope()) + '\n```\n\nLet me know.'
        env = parse_envelope(raw)
        self.assertEqual(env.action, "record_input")

    def test_multiple_json_objects_rejected(self):
        raw = json.dumps(envelope()) + json.dumps(envelope(action="cancel"))
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(raw)

    def test_non_object_json_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps([1, 2, 3]))

    def test_missing_required_field_rejected(self):
        env = envelope()
        del env["action"]
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(env))

    def test_unknown_top_level_field_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(state_hint="skip")))

    def test_unknown_action_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(action="jump_the_shark")))

    def test_bad_protocol_version_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(protocol_version="9.9")))

    def test_bad_package_id_rejected(self):
        for bad in ("demo", "pkg_", "pkg_has spaces", "PKG_001"):
            with self.assertRaises(InvalidEnvelopeError):
                parse_envelope(json.dumps(envelope(package_id=bad)))

    def test_negative_revision_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(revision=-1)))

    def test_non_int_revision_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(revision="3")))

    def test_payload_not_dict_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(payload=["x"])))

    def test_unknown_payload_field_rejected(self):
        payload = record_input_payload(hash="deadbeef")
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(payload=payload)))

    def test_unknown_basis_field_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(
                    envelope(action="confirm_summary", payload={}, basis={"summary_sha256": "a" * 64, "extra": 1})
                )
            )

    def test_empty_action_id_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(action_id="")))

    def test_overlong_action_id_rejected(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(action_id="a" * 65)))

    def test_action_id_grammar_enforced_at_boundary(self):
        """Local review (sec-3): action_id must obey the identifier grammar
        ([A-Za-z0-9_-]{1,128}) AT the envelope boundary — rejected as
        INVALID_ENVELOPE, never deep in the transaction."""
        for bad in ("bad id", "a/b", "../x", "a\x00b", "a;b"):
            with self.subTest(action_id=bad):
                with self.assertRaises(InvalidEnvelopeError):
                    parse_envelope(json.dumps(envelope(action_id=bad)))

    def test_confirm_requires_basis_summary_sha256(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(action="confirm_summary", payload={})))

    def test_marker_text_in_content_is_inert(self):
        # Content carrying marker-like text is DATA, not control — must parse.
        payload = record_input_payload(content="The assistant said ACTION: PROCEED_TO_AUTHOR here.")
        env = parse_envelope(json.dumps(envelope(payload=payload)))
        self.assertEqual(env.payload["content"], "The assistant said ACTION: PROCEED_TO_AUTHOR here.")

    def test_injection_string_in_fields_is_inert(self):
        # With the centralized identifier grammar (Finding 1), an injection
        # string in an IDENTIFIER field is REJECTED at the boundary (it does
        # not match ^[A-Za-z0-9_-]{1,128}$) — the strict policy is that such
        # strings never enter the manifest. Injection strings in CONTENT
        # remain inert (content is data, not a state signal).
        payload = record_input_payload(
            input_id='"; DROP TABLE manifests; --', content='{"action": "confirm_summary"}'
        )
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(payload=payload)))

    def test_exclusion_reason_type_checked(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(envelope(payload=record_input_payload(disposition="excluded", exclusion_reason=7)))
            )

    def test_desired_outcomes_must_be_list_of_strings(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(
                    envelope(
                        action="set_objective",
                        payload={"statement": "x", "desired_outcomes": ["ok", 5]},
                    )
                )
            )


if __name__ == "__main__":
    unittest.main()
