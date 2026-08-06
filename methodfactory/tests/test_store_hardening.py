"""Store hardening regression tests — remediation of code-review findings
F0 (stale lock), F1 (torn journal tail), F2 (package_id traversal),
F3 (O(J^2) artifact verification), and the crash-mode coverage gap (bug-5).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from methodfactory.adapters.artifact_store import ArtifactStore
from methodfactory.domain.errors import ConcurrencyError, ManifestInvalidError
from methodfactory.engine import PipelineEngine
from methodfactory.manifest.store import ManifestStore

PKG = "pkg_hardening_001"

VALID_SNAPSHOT = {
    "schema_version": "0.1",
    "package_id": PKG,
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


def _writer_event(i: int) -> str:
    snap = dict(VALID_SNAPSHOT)
    snap["package_id"] = PKG
    return json.dumps(
        {
            "event_id": f"evt_w{i}",
            "action": "noop",
            "action_id": f"act_w{i}",
            "revision": 0,
            "state_before": "INTAKE",
            "state_after": "INTAKE",
            "resulting_manifest_sha256": "0" * 64,
            "previous_manifest_sha256": None,
            "action_sha256": "0" * 64,
            "at": "2026-08-06T00:00:00+00:00",
            "manifest_snapshot": snap,
        }
    )


class CountingArtifactStore(ArtifactStore):
    def __init__(self, root: Path | str) -> None:
        super().__init__(root)
        self.verify_calls = 0

    def verify(self, digest: str) -> bool:
        self.verify_calls += 1
        return super().verify(digest)


class StoreHardeningTests(unittest.TestCase):
    def test_stale_lock_reclaimed_when_owner_dead(self):
        """F0: a lock file whose owner PID is dead must be reclaimed, not wedge the package."""
        with tempfile.TemporaryDirectory() as td:
            store = ManifestStore(Path(td))
            lock = store._lock_path("pkg_stale_dead")
            lock.write_text("999999999\n")  # beyond pid_max -> dead
            store.create("pkg_stale_dead", "intent")  # must not raise
            self.assertEqual(store.load("pkg_stale_dead")["state"], "INTAKE")

    def test_stale_lock_reclaimed_when_old(self):
        """F0: a very old lock file is reclaimed by age even if its PID looks alive."""
        with tempfile.TemporaryDirectory() as td:
            store = ManifestStore(Path(td))
            lock = store._lock_path("pkg_stale_old")
            lock.write_text(f"{os.getpid()}\n")
            ancient = time.time() - 1000
            os.utime(lock, (ancient, ancient))
            store.create("pkg_stale_old", "intent")  # must not raise
            self.assertEqual(store.load("pkg_stale_old")["state"], "INTAKE")

    def test_torn_final_line_tolerated(self):
        """F1: an unterminated final journal line (writer mid-append) must not
        mislabel a healthy store as corrupt."""
        with tempfile.TemporaryDirectory() as td:
            store = ManifestStore(Path(td))
            store.create("pkg_torn_001", "intent")
            with open(store._events_path("pkg_torn_001"), "a", encoding="utf-8") as fh:
                fh.write('{"event_id": "evt_partial"')  # no newline, incomplete
            manifest = store.load("pkg_torn_001")  # must not raise
            self.assertEqual(manifest["state"], "INTAKE")

    def test_terminated_garbage_line_is_real_corruption(self):
        """F1: a terminated non-JSON line is genuine corruption and must raise."""
        with tempfile.TemporaryDirectory() as td:
            store = ManifestStore(Path(td))
            store.create("pkg_torn_002", "intent")
            with open(store._events_path("pkg_torn_002"), "a", encoding="utf-8") as fh:
                fh.write("this is not json\n")
            with self.assertRaises(ManifestInvalidError):
                store.load("pkg_torn_002")

    def test_traversal_package_id_rejected(self):
        """F2: package_id must never escape the store root on read or write paths."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            decoy = root / "decoy.json"
            decoy.write_text(json.dumps(VALID_SNAPSHOT))
            store = ManifestStore(root)
            with self.assertRaises(ManifestInvalidError):
                store.load("../decoy")
            with self.assertRaises(ManifestInvalidError):
                store.read_events("../decoy")
            with self.assertRaises(ManifestInvalidError):
                store.find_event("../decoy", "act_1")
            with self.assertRaises(ManifestInvalidError):
                store.create("../decoy", "intent")

    def test_artifact_verification_is_linear(self):
        """F3: replay verifies each unique artifact digest once (O(J)), not once
        per snapshot (O(J^2))."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = CountingArtifactStore(root / "artifacts")
            store = ManifestStore(root, artifact_store=artifacts)
            engine = PipelineEngine(store, artifacts)
            pkg = "pkg_lin_001"
            engine.create_package(pkg, "intent")
            for i in range(30):
                engine.apply_json(
                    json.dumps(
                        {
                            "protocol_version": "0.1",
                            "action_id": f"act_{i}",
                            "package_id": pkg,
                            "expected_revision": i,
                            "action": "record_input",
                            "basis": {},
                            "payload": {
                                "input_id": f"in_{i}",
                                "kind": "text",
                                "content": f"material {i}",
                                "source": "operator",
                                "disposition": "incorporated",
                            },
                        }
                    )
                )
            artifacts.verify_calls = 0
            store.load(pkg)
            self.assertLessEqual(artifacts.verify_calls, 30)

    def test_concurrent_append_read_no_spurious_corruption(self):
        """bug-5c: a reader must never observe a spurious MANIFEST_INVALID while
        a writer appends journal lines."""
        with tempfile.TemporaryDirectory() as td:
            store = ManifestStore(Path(td))
            store.create(PKG, "intent")
            events_path = store._events_path(PKG)
            stop = threading.Event()
            errors: list[str] = []

            def writer() -> None:
                i = 0
                while not stop.is_set():
                    with open(events_path, "a", encoding="utf-8") as fh:
                        fh.write(_writer_event(i) + "\n")
                        fh.flush()
                    i += 1

            def reader() -> None:
                while not stop.is_set():
                    try:
                        store.read_events(PKG)
                    except ManifestInvalidError as exc:
                        errors.append(str(exc))

            t1 = threading.Thread(target=writer)
            t2 = threading.Thread(target=reader)
            t1.start()
            t2.start()
            time.sleep(1.0)
            stop.set()
            t1.join()
            t2.join()
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
