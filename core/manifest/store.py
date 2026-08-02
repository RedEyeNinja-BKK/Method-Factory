"""ManifestStore — atomic, revisioned, chain-verified persistence (ADR-0008).

Layout under the store root:
    packages/<package_id>.json            latest manifest snapshot
    events/<package_id>.events.jsonl      append-only transition log
    events/<package_id>.lock              write lock (O_EXCL)
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
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.events_dir = self.root / "events"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)

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
            if path.exists():
                raise DuplicatePackageError(f"package {package_id} already exists")
            event = {
                "event_id": "evt_" + uuid.uuid4().hex,
                "action": "create_package",
                "action_id": "act_create_package",
                "revision": 0,
                "state_before": None,
                "state_after": manifest["state"],
                "resulting_manifest_sha256": digest_json(manifest),
                "action_sha256": digest_json({"action": "create_package", "package_id": package_id}),
                "at": created_at,
            }
            self._atomic_write(path, manifest)
            self._append_event(package_id, event)
        return manifest

    # ── load ───────────────────────────────────────────────────────────
    def load(self, package_id: str) -> dict:
        path = self._manifest_path(package_id)
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
        events = self.read_events(package_id)
        if events:
            last = events[-1].get("resulting_manifest_sha256")
            if last and digest_json(data) != last:
                raise ManifestInvalidError(
                    f"manifest digest mismatch for {package_id}: file does not match event chain",
                    package_id=package_id,
                )
        return data

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
            self._atomic_write(self._manifest_path(package_id), next_manifest)
            self._append_event(package_id, event)

    # ── events ─────────────────────────────────────────────────────────
    def read_events(self, package_id: str) -> list[dict]:
        path = self._events_path(package_id)
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
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
