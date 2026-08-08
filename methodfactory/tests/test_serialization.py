"""Canonical serialization tests (ADR-0012 §4)."""

from __future__ import annotations

import unittest

from hypothesis import given, strategies as st

from methodfactory.storage.serialization import (
    canonical_bytes,
    canonical_json,
    digest_bytes,
    digest_json,
    digest_text,
)


class CanonicalSerializationTests(unittest.TestCase):
    def test_key_order_invariant(self):
        a = {"z": 1, "a": {"nested": 2, "list": [3, 1]}}
        b = {"a": {"list": [3, 1], "nested": 2}, "z": 1}
        self.assertEqual(digest_json(a), digest_json(b))
        self.assertEqual(canonical_json(a), canonical_json(b))

    def test_compact_separators(self):
        self.assertEqual(canonical_json({"a": 1, "b": [1, 2]}), '{"a":1,"b":[1,2]}')

    def test_ensure_ascii_false(self):
        # Canonical form is UTF-8 (ensure_ascii=False): raw non-ASCII, not \\uXXXX.
        s = canonical_json({"s": "สวัสดี"})
        self.assertIn("สวัสดี", s)
        self.assertNotIn("\\u0e2a", s)
        # ...and the byte form round-trips as UTF-8.
        self.assertEqual(canonical_bytes({"s": "สวัสดี"}).decode("utf-8"), s)

    def test_invalid_numbers_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json({"x": float("nan")})
        with self.assertRaises(ValueError):
            canonical_json({"x": float("inf")})

    def test_digests_are_64_hex(self):
        for d in (digest_bytes(b"x"), digest_text("x"), digest_json({"a": 1})):
            self.assertEqual(len(d), 64)
            int(d, 16)  # hex

    def test_digest_text_stable(self):
        self.assertEqual(digest_text("สวัสดี"), digest_text("สวัสดี"))
        self.assertNotEqual(digest_text("สวัสดี"), digest_text("hello"))

    @given(st.integers(min_value=-10**6, max_value=10**6), st.integers(min_value=-10**6, max_value=10**6))
    def test_key_order_invariant_property(self, x: int, y: int):
        self.assertEqual(
            digest_json({"a": x, "b": y}),
            digest_json({"b": y, "a": x}),
        )


if __name__ == "__main__":
    unittest.main()
