"""ManifestStore — event-journal-first, revisioned persistence (ADR-0008).

Layout under the store root:
    packages/<package_id>.json            latest manifest cache
    events/<package_id>.events.jsonl      append-only canonical transition log
    events/<package_id>.lock              write lock (O_EXCL)

The event journal is the source of truth.  The package JSON is only a cache
and can lag behind the journal after a crash between the two writes.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from ..domain.errors import (
    ConcurrencyError,
    DuplicatePackageError,
    ManifestInvalidError,
    StaleActionError,
)
from .hashing import digest_json, utcnow
from .schema import new_manifest, validate_manifest

LOCK_TIMEOUT_S = 5.0
LOCK_RETRY_S = 0.05


class ManifestStore:
    def __init__(self, root: Path | str, artifact_store=None) -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.events_dir = self.root / "events"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_store = artifact_store

    # ── paths ──────────────────────────────────────────────────────────
    def _manifest_path(self, package_id: str) -> Path:
        return self.packages_dir / f"{package_id}.json"

    def _events_path(self, package_id: str) -> Path:
        return self.events_dir / f"{package_id}.events.jsonl"

    def _lock_path(self, package_id: str) -> Path:
        return self.events_dir / f"{package_id}.lock"

    # ── create ─────────────────────────────────────────────────────────
    def create(self, package_id: str, intent_raw: str, created_at: Optional[str] = None) -> dict:
        created_at = created_at or utcnow()
        manifest = new_manifest(package_id, intent_raw, created_at)
        errors = validate_manifest(manifest)
        if errors:
            raise ManifestInvalidError("new manifest invalid: " + "; ".join(errors))

        with self._lock(package_id):
            path = self._manifest_path(package_id)
            if path.exists() or self._events_path(package_id).exists():
                raise DuplicatePackageError(f"package {package_id} already exists")
            event = {
                "event_id": "evt_" + uuid.uuid4().hex,
                "action": "create_package",
                "action_id": "act_create_package",
                "revision": 0,
                "state_before": None,
                "state_after": manifest["state"],
                "resulting_manifest_sha256": digest_json(manifest),
                "previous_manifest_sha256": None,
                "action_sha256": digest_json({"action": "create_package", "package_id": package_id}),
                "at": created_at,
                "manifest_snapshot": manifest,
            }
            self._append_event(package_id, event)
            self._atomic_write(path, manifest)
        return manifest

    # ── load ───────────────────────────────────────────────────────────
    def load(self, package_id: str) -> dict:
        events = self.read_events(package_id)
        path = self._manifest_path(package_id)

        if events and all("manifest_snapshot" in event for event in events):
            data = self._verify_and_replay(package_id, events)
            self._validate_cache_if_present(package_id, path, data, events)
            return data

        # Backward compatibility for pre-Phase-4.1 journals: use the snapshot
        # when events do not carry reconstructable manifest snapshots.
        data = self._read_snapshot(package_id, path)
        if events:
            last = events[-1].get("resulting_manifest_sha256")
            if last and digest_json(data) != last:
                raise ManifestInvalidError(
                    f"manifest digest mismatch for {package_id}: file does not match legacy event chain",
                    package_id=package_id,
                )
        return data

    def _verify_and_replay(self, package_id: str, events: list[dict]) -> dict:
        previous = None
        for index, event in enumerate(events):
            snapshot = event.get("manifest_snapshot")
            if not isinstance(snapshot, dict):
                self._chain_error(package_id, index, "missing manifest_snapshot")
            assert isinstance(snapshot, dict)
            expected_revision = index
            if event.get("revision") != expected_revision:
                self._chain_error(
                    package_id,
                    index,
                    f"revision gap: expected {expected_revision}, got {event.get('revision')!r}",
                )
            if event.get("state_before") != (None if previous is None else previous["state"]):
                self._chain_error(
                    package_id,
                    index,
                    f"state_before does not match prior state_after: expected "
                    f"{None if previous is None else previous['state']!r}, got {event.get('state_before')!r}",
                )
            if event.get("state_after") != snapshot.get("state"):
                self._chain_error(package_id, index, "state_after does not match manifest_snapshot.state")
            if snapshot.get("revision") != expected_revision:
                self._chain_error(package_id, index, "manifest_snapshot revision does not match event revision")
            expected_previous = None if previous is None else previous["digest"]
            if snapshot.get("previous_manifest_sha256") != expected_previous:
                self._chain_error(
                    package_id,
                    index,
                    f"previous_manifest_sha256 chain break: expected {expected_previous!r}, "
                    f"got {snapshot.get('previous_manifest_sha256')!r}",
                )
            digest = digest_json(snapshot)
            if event.get("resulting_manifest_sha256") != digest:
                self._chain_error(package_id, index, "resulting_manifest_sha256 does not match manifest_snapshot")
            errors = validate_manifest(snapshot)
            if errors:
                self._chain_error(package_id, index, "invalid manifest_snapshot: " + "; ".join(errors))
            self._verify_artifacts(package_id, index, snapshot)
            previous = {"state": snapshot["state"], "digest": digest}
        return events[-1]["manifest_snapshot"]

    def _verify_artifacts(self, package_id: str, index: int, manifest: dict) -> None:
        if self.artifact_store is None:
            return
        digests = [item.get("content_sha256") for item in manifest.get("inputs", [])]
        digests += [item.get("sha256") for item in manifest.get("artifacts", [])]
        for digest in digests:
            if not self.artifact_store.verify(digest):
                self._chain_error(
                    package_id,
                    index,
                    f"referenced artifact digest missing or invalid: {digest}",
                )

    def _validate_cache_if_present(
        self, package_id: str, path: Path, canonical: dict, events: list[dict]
    ) -> None:
        if not path.exists():
            return
        cache = self._read_snapshot(package_id, path)
        known = {event["resulting_manifest_sha256"] for event in events}
        if digest_json(cache) not in known:
            raise ManifestInvalidError(
                f"manifest cache corrupt for {package_id}: does not match any journal snapshot",
                package_id=package_id,
            )

    def _read_snapshot(self, package_id: str, path: Path) -> dict:
        if not path.exists():
            raise ManifestInvalidError(f"manifest missing for {package_id}", package_id=package_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ManifestInvalidError(
                f"manifest corrupt for {package_id}: {exc}", package_id=package_id
            ) from exc
        errors = validate_manifest(data)
        if errors:
            raise ManifestInvalidError(
                f"manifest invalid for {package_id}: " + "; ".join(errors), package_id=package_id
            )
        return data

    def _chain_error(self, package_id: str, index: int, detail: str) -> None:
        raise ManifestInvalidError(
            f"event chain break for {package_id} at event index {index}: {detail}",
            package_id=package_id,
        )

    # ── compare-and-swap ───────────────────────────────────────────────
    def compare_and_swap(
        self, package_id: str, expected_revision: int, next_manifest: dict, event: dict
    ) -> None:
        with self._lock(package_id):
            current = self.load(package_id)
            if current["revision"] != expected_revision:
                raise StaleActionError(
                    "concurrent revision change detected",
                    package_id=package_id,
                    expected_revision=expected_revision,
                    actual_revision=current["revision"],
                )
            event["manifest_snapshot"] = next_manifest
            event["previous_manifest_sha256"] = digest_json(current)
            event["resulting_manifest_sha256"] = digest_json(next_manifest)
            self._append_event(package_id, event)
            self._atomic_write(self._manifest_path(package_id), next_manifest)

    # ── events ─────────────────────────────────────────────────────────
    def read_events(self, package_id: str) -> list[dict]:
        path = self._events_path(package_id)
        if not path.exists():
            return []
        rows = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                if line.strip():
                    rows.append(json.loads(line))
        except (json.JSONDecodeError, OSError) as exc:
            raise ManifestInvalidError(
                f"event journal corrupt for {package_id}: {exc}", package_id=package_id
            ) from exc
        return rows

    def find_event(self, package_id: str, action_id: str) -> Optional[dict]:
        for event in self.read_events(package_id):
            if event.get("action_id") == action_id:
                return event
        return None

    def _append_event(self, package_id: str, event: dict) -> None:
        path = self._events_path(package_id)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # ── internals ──────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, data: dict) -> None:
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, sort_keys=True, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _lock(self, package_id: str):
        return _PackageLock(self._lock_path(package_id))


class _PackageLock:
    """Advisory package-scoped lock via O_CREAT|O_EXCL with timeout."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ConcurrencyError(f"could not acquire lock {self.path}")
                time.sleep(LOCK_RETRY_S)

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False
        return False
