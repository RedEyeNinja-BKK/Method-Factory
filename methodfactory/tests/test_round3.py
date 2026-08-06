"""Regression tests for v2.0.0 round-3 fixes (bug-1/2/3, sec-1/2/3/5/8,
perf-1, q-1/2, sec-4, perf-2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import ManifestInvalidError
from methodfactory.manifest.hashing import digest_json
from methodfactory.manifest.store import ManifestStore

PKG = "pkg_r3_001"


def _snapshot(pkg: str = PKG) -> dict:
    return {
        "schema_version": "0.1",
        "package_id": pkg,
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


class Round3StoreTests(unittest.TestCase):
    def _make_store(self, root: Path) -> ManifestStore:
        return ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))

    def test_append_after_single_byte_torn_tail(self):
        """bug-1: a 1-byte torn tail must be truncated, not glued onto the next
        record."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            ev_path = root / "events" / f"{PKG}.events.jsonl"
            with open(ev_path, "a", encoding="utf-8") as fh:
                fh.write("{")  # 1-byte torn tail appended, not overwriting
            m = store.load(PKG)
            nm = dict(m, revision=1, state="CANCELLED", previous_manifest_sha256=digest_json(m))
            store.compare_and_swap(
                PKG, m["revision"], nm,
                {"event_id": "e1", "action": "cancel", "action_id": "a1",
                 "revision": 1, "state_before": m["state"], "state_after": "CANCELLED"},
                current_manifest=m,
            )
            self.assertEqual(store.load(PKG)["state"], "CANCELLED")

    def test_append_after_parseable_unterminated_record(self):
        """bug-2/q-1: a complete JSON record missing only its trailing newline
        is COMMITTED and must not be truncated (would delete it and cause a
        revision gap)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            ev_path = root / "events" / f"{PKG}.events.jsonl"
            ev_path.write_bytes(ev_path.read_bytes().rstrip(b"\n"))  # drop final \n
            self.assertEqual(len(store.read_events(PKG)), 1)  # still committed
            m = store.load(PKG)
            nm = dict(m, revision=1, state="CANCELLED", previous_manifest_sha256=digest_json(m))
            store.compare_and_swap(
                PKG, m["revision"], nm,
                {"event_id": "e1", "action": "cancel", "action_id": "a1",
                 "revision": 1, "state_before": m["state"], "state_after": "CANCELLED"},
                current_manifest=m,
            )
            self.assertEqual(store.load(PKG)["state"], "CANCELLED")
            self.assertEqual(store.load(PKG)["revision"], 1)

    def test_deep_nested_journal_line_is_clean_error(self):
        """sec-3: a deeply nested journal line raises ManifestInvalidError,
        not a raw RecursionError."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            ev_path = root / "events" / f"{PKG}.events.jsonl"
            with open(ev_path, "a", encoding="utf-8") as fh:
                fh.write("[" * 100000 + "]" * 100000 + "\n")
            with self.assertRaises(ManifestInvalidError):
                store.read_events(PKG)

    def test_deep_nested_cache_is_clean_error(self):
        """sec-3/q-2: a deeply nested cache raises ManifestInvalidError via
        _cache_moved_ahead, not a raw RecursionError."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            (root / "packages" / f"{PKG}.json").write_text("[" * 100000 + "]" * 100000)
            with self.assertRaises(ManifestInvalidError):
                store.load(PKG)

    def test_torn_tail_truncation_is_chunked(self):
        """perf-1: truncating a large torn tail must not do one syscall per
        byte (chunked backward scan). Behavior: large torn tail then append
        must still repair the journal."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            ev_path = root / "events" / f"{PKG}.events.jsonl"
            with open(ev_path, "a", encoding="utf-8") as fh:
                fh.write("x" * 200_000)  # 200KB torn tail, no newline
            m = store.load(PKG)
            nm = dict(m, revision=1, state="CANCELLED", previous_manifest_sha256=digest_json(m))
            store.compare_and_swap(
                PKG, m["revision"], nm,
                {"event_id": "e1", "action": "cancel", "action_id": "a1",
                 "revision": 1, "state_before": m["state"], "state_after": "CANCELLED"},
                current_manifest=m,
            )
            self.assertEqual(store.load(PKG)["state"], "CANCELLED")

    def test_failed_atomic_write_cleans_tmp_and_raises_stable(self):
        """sec-5: _atomic_write failure removes the tmp and raises a
        MethodFactoryError (not raw OSError). Trigger a real os.replace
        failure by making the target path a non-empty directory."""
        from methodfactory.domain.errors import MethodFactoryError

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create(PKG, "intent")
            m = store.load(PKG)
            # Make the manifest target a non-empty dir so os.replace fails.
            pkg_json = root / "packages" / f"{PKG}.json"
            pkg_json.unlink()
            pkg_json.mkdir()
            (pkg_json / "blocker").write_text("x")
            nm = dict(m, revision=1, state="CANCELLED", previous_manifest_sha256=digest_json(m))
            event = {"event_id": "e1", "action": "cancel", "action_id": "a1",
                     "revision": 1, "state_before": m["state"], "state_after": "CANCELLED"}
            with self.assertRaises(MethodFactoryError):
                store.compare_and_swap(PKG, m["revision"], nm, event, current_manifest=m)
            # No orphaned tmp files left behind.
            leftovers = [p for p in (root / "packages").iterdir() if ".tmp." in p.name]
            self.assertEqual(leftovers, [])

    def test_lone_surrogate_rejected(self):
        """sec-8: a lone surrogate in a string value is rejected at the
        envelope boundary (not a crash in the persistence layer)."""
        from methodfactory.domain.errors import InvalidEnvelopeError
        from methodfactory.protocol.envelope import parse_envelope
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "set_objective",
                "basis": {},
                "payload": {"statement": "x\ud800y", "desired_outcomes": []},
            }))

    def test_control_chars_in_reason_and_intent_rejected(self):
        """sec-2: exclusion_reason, cancel reason, and intent.raw with C1
        control chars must be rejected at the envelope/parse boundary."""
        from methodfactory.domain.errors import InvalidEnvelopeError
        from methodfactory.protocol.envelope import parse_envelope

        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "record_input",
                "basis": {},
                "payload": {"input_id": "in_1", "kind": "text", "content": "x",
                            "source": "operator", "disposition": "excluded",
                            "exclusion_reason": "bad \u009b]0;Hijacked\u0007"},
            }))
        with self.assertRaises(InvalidEnvelopeError):
            parse_envelope(json.dumps({
                "protocol_version": "0.1",
                "action_id": "act_1",
                "package_id": "pkg_demo_001",
                "expected_revision": 0,
                "action": "cancel",
                "basis": {},
                "payload": {"reason": "bad \u009b]0;Hijacked\u0007"},
            }))

    def test_journal_cache_ascii_escaped(self):
        """sec-2: journal + cache must be written ensure_ascii=True so C1/DEL/
        U+2028 bytes never appear raw in the evidence files (a valid non-ASCII
        char like Thai must be \\uXXXX-escaped, not raw UTF-8)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = self._make_store(root)
            store.create("pkg_ascii_1", "สวัสดี")
            raw = (root / "events" / "pkg_ascii_1.events.jsonl").read_bytes()
            self.assertNotIn("สวัสดี".encode("utf-8"), raw)  # no raw UTF-8
            self.assertIn(b"\\u0e2a", raw)  # escaped as \uXXXX
            cache = (root / "packages" / "pkg_ascii_1.json").read_bytes()
            self.assertNotIn("สวัสดี".encode("utf-8"), cache)


if __name__ == "__main__":
    unittest.main()
