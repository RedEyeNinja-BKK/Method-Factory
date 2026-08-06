"""Regression tests for v2.0.0 round-2 schema/envelope/artifact/cli fixes
(bug-2, bug-4, bug-5, sec-3, sec-4, sec-5, sec-7, q-6, q-7, q-9, q-10, bug-8).
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore, validate_logical_path
from methodfactory.domain.errors import InvalidEnvelopeError, InvalidPayloadError
from methodfactory.manifest.schema import validate_manifest
from methodfactory.protocol.envelope import parse_envelope
from methodfactory.manifest.hashing import digest_bytes


def _valid_manifest(**overrides) -> dict:
    m = {
        "schema_version": "0.1",
        "package_id": "pkg_demo_001",
        "revision": 0,
        "state": "INTAKE",
        "created_at": "2026-08-06T00:00:00+00:00",
        "updated_at": "2026-08-06T00:00:00+00:00",
        "previous_manifest_sha256": None,
        "intent": {"raw": "x", "clarified": None},
        "inputs": [],
        "objective": {"statement": "", "desired_outcomes": []},
        "summary": None,
        "artifacts": [],
        "transition": {"last_event_id": None, "last_action_id": None},
    }
    m.update(overrides)
    return m


class SchemaRobustnessTests(unittest.TestCase):
    def test_objective_none_returns_errors_not_crash(self):
        """bug-2: objective=None must return an errors list, not raise."""
        errors = validate_manifest(_valid_manifest(objective=None))
        self.assertIsInstance(errors, list)
        self.assertTrue(any("objective" in e for e in errors))

    def test_unhashable_ids_return_errors_not_crash(self):
        """bug-8/schema: non-string input_id/artifact_id must not raise
        TypeError (unhashable) inside validate_manifest."""
        m = _valid_manifest(inputs=[{"input_id": ["a"], "kind": "text", "source": "operator",
                                     "disposition": "incorporated", "exclusion_reason": None,
                                     "content_sha256": "0" * 64, "content_size": 1,
                                     "content_path": "inputs/x.txt"}])
        errors = validate_manifest(m)
        self.assertIsInstance(errors, list)
        self.assertTrue(any("input_id" in e for e in errors))

        m2 = _valid_manifest(artifacts=[{"artifact_id": {"x": 1}, "kind": "skill",
                                          "logical_path": "skills/x/SKILL.md", "sha256": "0" * 64,
                                          "byte_count": 1, "status": "draft"}])
        errors2 = validate_manifest(m2)
        self.assertIsInstance(errors2, list)
        self.assertTrue(any("artifact_id" in e for e in errors2))

    def test_bool_size_fields_rejected(self):
        """bug-8: content_size/byte_count bools must be rejected (not accepted
        as ints)."""
        m = _valid_manifest(inputs=[{"input_id": "in_1", "kind": "text", "source": "operator",
                                     "disposition": "incorporated", "exclusion_reason": None,
                                     "content_sha256": "0" * 64, "content_size": True,
                                     "content_path": "inputs/x.txt"}])
        errors = validate_manifest(m)
        self.assertTrue(any("content_size" in e for e in errors))


class LogicalPathControlCharTests(unittest.TestCase):
    def test_nul_and_control_chars_rejected(self):
        """bug-5/sec-7: control characters (incl NUL) must be rejected."""
        for bad in ("skills/x\x00/SKILL.md", "skills/\x1b[31mred", "skills/\x07BEL", "skills/\x1f"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPayloadError):
                    validate_logical_path(bad)

    def test_embedded_control_in_input_id_rejected_at_parse(self):
        """bug-5/sec-3: control chars in input_id must be rejected at the
        envelope boundary."""
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "record_input",
                "basis": {},
                "payload": {"input_id": "in\x1b[31m", "kind": "text", "content": "x",
                            "source": "operator", "disposition": "incorporated"},
            }))


class EnvelopeCapTests(unittest.TestCase):
    def _env(self, **payload) -> dict:
        return {
            "protocol_version": "0.1",
            "action_id": "act_1",
            "package_id": "pkg_demo_001",
            "expected_revision": 0,
            "action": "record_input",
            "basis": {},
            "payload": payload,
        }

    def test_oversized_operator_id_rejected(self):
        """sec-4: operator_id capped."""
        from methodfactory.domain.vocabulary import MAX_ID_CHARS
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "confirm_summary",
                "basis": {"summary_sha256": "0" * 64},
                "payload": {"operator_id": "o" * (MAX_ID_CHARS + 1)},
            }))

    def test_oversized_kind_rejected(self):
        from methodfactory.domain.vocabulary import MAX_ID_CHARS
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(self._env(
                input_id="in_1", kind="k" * (MAX_ID_CHARS + 1), content="x",
                source="operator", disposition="incorporated",
            )))

    def test_oversized_exclusion_reason_rejected(self):
        from methodfactory.domain.vocabulary import MAX_REASON_CHARS
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps(self._env(
                input_id="in_1", kind="text", content="x",
                source="operator", disposition="excluded",
                exclusion_reason="r" * (MAX_REASON_CHARS + 1),
            )))

    def test_overlong_logical_path_rejected_at_parse(self):
        from methodfactory.domain.vocabulary import MAX_LOGICAL_PATH_CHARS
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "record_draft_artifact",
                "basis": {},
                "payload": {"artifact_id": "a_1", "kind": "skill",
                            "logical_path": "x" * (MAX_LOGICAL_PATH_CHARS + 1),
                            "content": "c"},
            }))


class ArtifactStoreRobustnessTests(unittest.TestCase):
    def test_symlink_blob_to_directory_raises_stable_error(self):
        """sec-7: a blob path that is a directory (or symlink to one) must
        raise InvalidPayloadError, not a raw OSError."""
        with tempfile.TemporaryDirectory() as td:
            store = ArtifactStore(Path(td))
            digest, _ = store.put("pkg_a", "skills/x/SKILL.md", "content")
            blob = store._blob_path(digest)
            blob.unlink()
            blob.mkdir()
            with self.assertRaises(InvalidPayloadError):
                store.get(digest)
            with self.assertRaises(InvalidPayloadError):
                store.put("pkg_a", "skills/x/SKILL.md", "content")

    def test_digest_re_shared(self):
        """q-6: ArtifactStore must import SHA256_RE from vocabulary (no local
        DIGEST_RE duplication)."""
        import methodfactory.adapters.artifact_store as mod
        self.assertFalse(hasattr(mod, "DIGEST_RE"), "DIGEST_RE should be removed")
        from methodfactory.domain.vocabulary import SHA256_RE
        self.assertIs(mod.SHA256_RE, SHA256_RE)


if __name__ == "__main__":
    unittest.main()
