"""Regression tests for v2.0.0 review round-2 fixes (bug-1, bug-3, bug-7,
q-8, sec-1, sec-2, bug-6, perf-1, sec-6).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import ManifestInvalidError, StaleActionError
from methodfactory.manifest.store import ManifestStore
from methodfactory.manifest.hashing import digest_json

PKG = "pkg_r2_001"


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


class Round2StoreTests(unittest.TestCase):
    def test_write_after_torn_tail_does_not_corrupt(self):
        """bug-1: appending after a crashed writer's torn tail must not corrupt
        the journal; the partial line is uncommitted garbage."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            store.create(PKG, "intent")
            with open(root / "events" / f"{PKG}.events.jsonl", "a", encoding="utf-8") as fh:
                fh.write('{"partial": tru')  # torn tail, no newline
            (root / "events" / f"{PKG}.lock").write_text("999999\n")  # dead owner
            manifest = store.load(PKG)
            next_m = dict(
                manifest,
                revision=1,
                state="CANCELLED",
                previous_manifest_sha256=digest_json(manifest),
            )
            event = {
                "event_id": "evt_x",
                "action": "cancel",
                "action_id": "act_x",
                "revision": 1,
                "state_before": manifest["state"],
                "state_after": "CANCELLED",
            }
            store.compare_and_swap(PKG, manifest["revision"], next_m, event, current_manifest=manifest)
            loaded = store.load(PKG)  # must not raise
            self.assertEqual(loaded["state"], "CANCELLED")

    def test_unicode_line_separator_does_not_corrupt(self):
        """bug-3: raw U+2028/U+2029 in string fields must not split journal
        records (ensure_ascii=False + split('\\n') parsing)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            for bad in ("First\u2028second", "First\u2029second", "A\u0085B", "C\x1cD"):
                pkg = f"pkg_u_{len(bad)}_{abs(hash(bad)) % 100000}"
                store.create(pkg, bad)
                self.assertEqual(store.load(pkg)["intent"]["raw"], bad)

    def test_cross_package_alias_rejected(self):
        """sec-1: a consistent copy of another package's journal+cache must not
        be accepted under a different package_id."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            store.create("pkg_alice_1", "alice intent")
            (root / "events" / "pkg_evil_9.events.jsonl").write_text(
                (root / "events" / "pkg_alice_1.events.jsonl").read_text()
            )
            (root / "packages" / "pkg_evil_9.json").write_text(
                (root / "packages" / "pkg_alice_1.json").read_text()
            )
            with self.assertRaises(ManifestInvalidError):
                store.load("pkg_evil_9")

    def test_symlinked_tmp_manifest_not_followed(self):
        """sec-2: a planted symlink at the manifest tmp path must not be
        followed (victim file must remain untouched)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            store.create(PKG, "intent")
            victim = root / "victim.txt"
            victim.write_text("ORIGINAL")
            # Plant a symlink at the predictable tmp name (pre-fix name).
            tmp_name = root / "packages" / f"{PKG}.json.tmp"
            try:
                tmp_name.symlink_to(victim)
            except (OSError, NotImplementedError):
                self.skipTest("symlink not supported")
            manifest = store.load(PKG)
            event = {
                "event_id": "evt_s",
                "action": "cancel",
                "action_id": "act_s",
                "revision": 1,
                "state_before": manifest["state"],
                "state_after": "CANCELLED",
            }
            store.compare_and_swap(PKG, manifest["revision"], dict(manifest, revision=1, state="CANCELLED"), event, current_manifest=manifest)
            self.assertEqual(victim.read_text(), "ORIGINAL")

    def test_stale_events_cache_mismatch_is_not_corruption(self):
        """bug-6: passing stale events with a newer cache must not raise a
        false MANIFEST_INVALID (a concurrent writer should yield STALE_ACTION
        at CAS, not a corruption alarm)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            store.create(PKG, "intent")
            stale = store.read_events(PKG)
            # Advance the store (newer journal + cache).
            manifest = store.load(PKG)
            event = {
                "event_id": "evt_b",
                "action": "cancel",
                "action_id": "act_b",
                "revision": 1,
                "state_before": manifest["state"],
                "state_after": "CANCELLED",
            }
            store.compare_and_swap(
                PKG,
                manifest["revision"],
                dict(manifest, revision=1, state="CANCELLED", previous_manifest_sha256=digest_json(manifest)),
                event,
                current_manifest=manifest,
            )
            # Now load with the STALE events; the newer cache must not be
            # reported as corruption.
            data = store.load(PKG, events=stale)
            self.assertEqual(data["state"], "CANCELLED")

    def test_compare_and_swap_does_not_touch_path_before_validation(self):
        """sec-6: compare_and_swap must validate package_id before creating any
        lock path."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = ManifestStore(root, artifact_store=ArtifactStore(root / "artifacts"))
            with self.assertRaises(ManifestInvalidError):
                store.compare_and_swap("../escape", 0, _snapshot(), {"event_id": "e"})
            # No escaped lock file may exist OUTSIDE the store root (e.g. the
            # parent dir of root would receive '<root-parent>/escape.lock' if
            # validation were bypassed).
            self.assertFalse((root.parent / "escape.lock").exists())
            self.assertEqual(sorted(p.name for p in (root / "events").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
