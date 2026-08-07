"""Size-bound constant tests (ADR-0012 §4): limits separated by object type."""

from __future__ import annotations

import unittest

from methodfactory.storage.limits import (
    MAX_ACTION_JSON_BYTES,
    MAX_ARTIFACT_BODY_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_CONTENT_CHARS,
    MAX_ENVELOPE_BYTES,
    MAX_ID_CHARS,
    MAX_INPUT_CONTENT_BYTES,
    MAX_INTENT_CHARS,
    MAX_LOGICAL_PATH_CHARS,
    MAX_MANIFEST_BYTES,
    MAX_OUTCOMES,
    MAX_PREVIEW_CHARS,
    MAX_REASON_CHARS,
    MAX_STATEMENT_CHARS,
    MAX_SUMMARY_BYTES,
)


class LimitsTests(unittest.TestCase):
    def test_all_positive(self):
        for v in (
            MAX_ENVELOPE_BYTES,
            MAX_ACTION_JSON_BYTES,
            MAX_MANIFEST_BYTES,
            MAX_ARTIFACT_BYTES,
            MAX_INPUT_CONTENT_BYTES,
            MAX_SUMMARY_BYTES,
            MAX_ARTIFACT_BODY_BYTES,
            MAX_CONTENT_CHARS,
            MAX_INTENT_CHARS,
            MAX_STATEMENT_CHARS,
            MAX_ID_CHARS,
            MAX_LOGICAL_PATH_CHARS,
            MAX_REASON_CHARS,
            MAX_PREVIEW_CHARS,
            MAX_OUTCOMES,
        ):
            self.assertGreater(v, 0, f"{v} must be positive")

    def test_byte_versus_char_limits_are_distinct(self):
        """A persisted byte field must never be compared against a character
        constant: the new *_BYTES ceilings are separate constants, and the
        artifact byte ceiling is aliased to the storage ceiling so they cannot
        drift (Finding 1)."""
        self.assertNotEqual(MAX_INPUT_CONTENT_BYTES, MAX_CONTENT_CHARS)
        self.assertNotEqual(MAX_SUMMARY_BYTES, MAX_PREVIEW_CHARS)
        self.assertEqual(MAX_ARTIFACT_BODY_BYTES, MAX_ARTIFACT_BYTES)
        self.assertEqual(MAX_INPUT_CONTENT_BYTES, MAX_ARTIFACT_BYTES)
        self.assertEqual(MAX_SUMMARY_BYTES, MAX_ARTIFACT_BYTES)

    def test_envelope_limit_never_reused_for_event_or_manifest(self):
        # ADR-0012 §4: never reuse MAX_ENVELOPE_BYTES as an event/manifest limit.
        self.assertNotEqual(MAX_ENVELOPE_BYTES, MAX_MANIFEST_BYTES)
        self.assertNotEqual(MAX_ENVELOPE_BYTES, MAX_ACTION_JSON_BYTES)
        self.assertLess(MAX_ENVELOPE_BYTES, MAX_MANIFEST_BYTES)

    def test_ordering_by_object_type(self):
        # Action JSON is smaller than a cumulative manifest; artifacts are
        # separately bounded and can be the largest object.
        self.assertLessEqual(MAX_ACTION_JSON_BYTES, MAX_MANIFEST_BYTES)
        self.assertGreaterEqual(MAX_ARTIFACT_BYTES, MAX_MANIFEST_BYTES)

    def test_content_field_limits_are_sane(self):
        self.assertLess(MAX_ID_CHARS, MAX_STATEMENT_CHARS)
        self.assertLess(MAX_STATEMENT_CHARS, MAX_CONTENT_CHARS)
        self.assertLess(MAX_LOGICAL_PATH_CHARS, MAX_ID_CHARS * 3)


if __name__ == "__main__":
    unittest.main()
