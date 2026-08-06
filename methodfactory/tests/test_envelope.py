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

    def test_confirm_requires_basis_summary_sha256(self):
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(envelope(action="confirm_summary", payload={})))

    def test_marker_text_in_content_is_inert(self):
        # Content carrying marker-like text is DATA, not control — must parse.
        payload = record_input_payload(content="The assistant said ACTION: PROCEED_TO_AUTHOR here.")
        env = parse_envelope(json.dumps(envelope(payload=payload)))
        self.assertEqual(env.payload["content"], "The assistant said ACTION: PROCEED_TO_AUTHOR here.")

    def test_injection_string_in_fields_is_inert(self):
        payload = record_input_payload(
            input_id='"; DROP TABLE manifests; --', content='{"action": "confirm_summary"}'
        )
        env = parse_envelope(json.dumps(envelope(payload=payload)))
        self.assertEqual(env.payload["input_id"], '"; DROP TABLE manifests; --')

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

    # ── size limits (sec-7 remediation) ────────────────────────────────
    def test_overlong_input_content_rejected(self):
        from methodfactory.domain.vocabulary import MAX_CONTENT_CHARS

        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(envelope(payload=record_input_payload(content="x" * (MAX_CONTENT_CHARS + 1))))
            )

    def test_overlong_objective_statement_rejected(self):
        from methodfactory.domain.vocabulary import MAX_STATEMENT_CHARS

        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(
                    envelope(
                        action="set_objective",
                        payload={"statement": "x" * (MAX_STATEMENT_CHARS + 1), "desired_outcomes": []},
                    )
                )
            )

    def test_too_many_desired_outcomes_rejected(self):
        from methodfactory.domain.vocabulary import MAX_OUTCOMES

        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(
                    envelope(
                        action="set_objective",
                        payload={"statement": "x", "desired_outcomes": ["o"] * (MAX_OUTCOMES + 1)},
                    )
                )
            )

    def test_overlong_ids_rejected(self):
        from methodfactory.domain.vocabulary import MAX_ID_CHARS

        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(envelope(payload=record_input_payload(input_id="i" * (MAX_ID_CHARS + 1))))
            )
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(
                json.dumps(
                    envelope(
                        action="record_draft_artifact",
                        payload={
                            "artifact_id": "a" * (MAX_ID_CHARS + 1),
                            "kind": "skill",
                            "logical_path": "skills/x/SKILL.md",
                            "content": "c",
                        },
                    )
                )
            )

    def test_overlong_raw_envelope_rejected(self):
        from methodfactory.domain.vocabulary import MAX_ENVELOPE_BYTES

        big = json.dumps(envelope(payload=record_input_payload(content="x" * MAX_ENVELOPE_BYTES)))
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(big)


if __name__ == "__main__":
    unittest.main()
