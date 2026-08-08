"""Cross-import canonical serialization tests (Finding 2 item 1).

The package root, manifest.hashing, and storage.serialization must all hash
the same UTF-8 canonical bytes for the same value, regardless of import path.
"""

from __future__ import annotations

import unittest

from methodfactory import canonical_bytes as root_canonical_bytes
from methodfactory import digest_json as root_digest_json
from methodfactory.manifest.hashing import (
    canonical_bytes as mh_canonical_bytes,
    digest_json as mh_digest_json,
)
from methodfactory.storage.serialization import (
    canonical_bytes as st_canonical_bytes,
    digest_json as st_digest_json,
)

UNICODE_FIXTURES = [
    {"s": "สวัสดี"},
    {"s": "日本語テキスト"},
    {"s": "héllo wörld — emoji 🎉"},
    {"a": [1, 2, 3], "nested": {"z": "żółć", "y": "中文"}},
]


class CrossImportCanonicalTests(unittest.TestCase):
    def test_cross_import_bytes_identical(self):
        for fix in UNICODE_FIXTURES:
            with self.subTest(fix=fix):
                self.assertEqual(
                    root_canonical_bytes(fix),
                    mh_canonical_bytes(fix),
                )
                self.assertEqual(
                    mh_canonical_bytes(fix),
                    st_canonical_bytes(fix),
                )

    def test_cross_import_digests_identical(self):
        for fix in UNICODE_FIXTURES:
            with self.subTest(fix=fix):
                self.assertEqual(root_digest_json(fix), mh_digest_json(fix))
                self.assertEqual(mh_digest_json(fix), st_digest_json(fix))

    def test_unicode_is_utf8_not_escaped(self):
        # The canonical form is UTF-8 (ensure_ascii=False): raw bytes, not
        # \\uXXXX. The legacy ensure_ascii=True variant is gone (Finding 2).
        raw = st_canonical_bytes({"s": "สวัสดี"})
        self.assertIn("สวัสดี".encode("utf-8"), raw)
        self.assertNotIn(b"\\u0e2a", raw)


if __name__ == "__main__":
    unittest.main()
