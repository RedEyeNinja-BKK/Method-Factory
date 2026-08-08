"""Content-addressed summary manifest tests (Finding 2 item 3)."""

from __future__ import annotations

import unittest

from methodfactory.manifest.schema import (
    SCHEMA_VERSION,
    SUMMARY_PREVIEW_MAX_CHARS,
    new_manifest,
    validate_manifest,
)


def _base_manifest(**overrides):
    m = new_manifest("pkg_demo_001", "Build a skill.", "2026-08-07T00:00:00+00:00")
    m.update(overrides)
    return m


def _valid_summary(**overrides):
    s = {
        "digest": "0" * 64,
        "size": 123,
        "presented_at": "2026-08-07T00:00:00+00:00",
        "confirmation": {
            "status": "pending",
            "confirmed_at": None,
            "operator_id": None,
            "confirmed_summary_sha256": None,
        },
    }
    s.update(overrides)
    return s


class ContentAddressedSummaryTests(unittest.TestCase):
    def test_valid_content_addressed_summary(self):
        m = _base_manifest(summary=_valid_summary(preview="short preview"))
        self.assertEqual(validate_manifest(m), [])

    def test_inline_content_rejected(self):
        """The manifest must NOT carry an unbounded inline summary body."""
        m = _base_manifest(summary=_valid_summary(content="entire body..."))
        errors = validate_manifest(m)
        self.assertTrue(any("summary.content" in e for e in errors))

    def test_digest_required(self):
        m = _base_manifest(summary=_valid_summary(digest="not-a-digest"))
        errors = validate_manifest(m)
        self.assertTrue(any("summary.digest" in e for e in errors))

    def test_size_required_nonnegative(self):
        m = _base_manifest(summary=_valid_summary(size=-1))
        errors = validate_manifest(m)
        self.assertTrue(any("summary.size" in e for e in errors))

    def test_preview_optional_and_bounded(self):
        m = _base_manifest(summary=_valid_summary(preview="x" * (SUMMARY_PREVIEW_MAX_CHARS + 1)))
        errors = validate_manifest(m)
        self.assertTrue(any("summary.preview" in e for e in errors))
        # no preview is fine
        self.assertEqual(validate_manifest(_base_manifest(summary=_valid_summary())), [])

    def test_schema_version_still_0_1(self):
        self.assertEqual(SCHEMA_VERSION, "0.1")


if __name__ == "__main__":
    unittest.main()
