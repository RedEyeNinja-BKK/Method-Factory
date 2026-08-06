"""ManifestStore — event-journal-first, revisioned persistence (ADR-0008).

Layout under the store root:
    packages/<package_id>.json            latest manifest cache
    events/<package_id>.events.jsonl      append-only canonical transition log
    events/<package_id>.lock              write lock (O_EXCL)

The event journal is the source of truth.  The package JSON is only a cache
and can lag behind the journal after a crash between the two writes.

Hardening notes (v2.0.0 review remediation):
    - package_id is allowlist-validated at every public entry point so the
      store defends itself regardless of caller (path-traversal read oracle).
    - an unterminated final journal line (a writer mid-append) is tolerated
      and never mislabels a healthy store as corrupt; a terminated non-JSON
      line is genuine corruption and still fails.
    - the O_EXCL lock records its owner PID and is reclaimed when the owner
      is dead or the lock is far older than any legitimate critical section
      (crash recovery; no permanent wedge).
    - chain replay verifies each referenced artifact digest exactly once
      (O(J) blob reads instead of O(J^2)).
"""

from __future__ import annotations

import json
import os
import time
import uuid
import warnings
from pathlib import Path
from typing import Optional

from ..domain.errors import (
    ConcurrencyError,
    DuplicatePackageError,
    ManifestInvalidError,
    StaleActionError,
)
from ..domain.vocabulary import PACKAGE_ID_RE
from .hashing import digest_json, utcnow
from .schema import new_manifest, validate_manifest

LOCK_TIMEOUT_S = 5.0
LOCK_RETRY_S = 0.05
# A lock this old is stale even if its recorded PID looks alive (PID reuse,
# dead-but-untestable owner). No legitimate critical section approaches it.
LOCK_STALE_AGE_S = LOCK_TIMEOUT_S * 60
# Journal growth is O(J^2) in bytes (every event embeds the cumulative
# snapshot). Accepted at single-operator scale; warn past this size so the
# operator can checkpoint (ADR-0008 v2.0.0 amendment).
JOURNAL_WARN_BYTES = 10 * 1024 * 1024


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


class ManifestStore:
    def __init__(self, root: Path | str, artifact_store=None) -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.events_dir = self.root / "events"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_store = artifact_store

    # ── validation ─────────────────────────────────────────────────────
    def _validate_package_id(self, package_id: str) -> None:
        if not isinstance(package_id, str) or not PACKAGE_ID_RE.match(package_id):
            raise ManifestInvalidError(
                f"invalid package_id {package_id!r}", package_id=package_id
            )

    # ── paths ──────────────────────────────────────────────────────────
    def _manifest_path(self, package_id: str) -> Path:
        return self.packages_dir / f"{package_id}.json"

    def _events_path(self, package_id: str) -> Path:
        return self.events_dir / f"{package_id}.events.jsonl"

    def _lock_path(self, package_id: str) -> Path:
        return self.events_dir / f"{package_id}.lock"

    # ── create ─────────────────────────────────────────────────────────
    def create(self, package_id: str, intent_raw: str, created_at: Optional[str] = None) -> dict:
        self._validate_package_id(package_id)
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
    def load(self, package_id: str, events: Optional[list] = None) -> dict:
        self._validate_package_id(package_id)
        if events is None:
            events = self.read_events(package_id)
        path = self._manifest_path(package_id)
        events_path = self._events_path(package_id)
        if events_path.exists() and events_path.stat().st_size > JOURNAL_WARN_BYTES:
            warnings.warn(
                f"event journal for {package_id} exceeds {JOURNAL_WARN_BYTES} bytes; "
                "consider checkpointing (ADR-0008)",
                stacklevel=2,
            )

        if events and all("manifest_snapshot" in event for event in events):
            data = self._verify_and_replay(package_id, events)
            if self._cache_moved_ahead(package_id, path, data, events):
                # The caller's events were stale relative to the cache (a
                # concurrent writer committed). Re-read fresh and confirm the
                # cache digest appears in the fresh journal: if it does, the
                # caller sees current state and any racing writer surfaces as
                # STALE_ACTION at CAS; if it does not, the cache was tampered
                # and must still be flagged (bug-6 + tamper detection).
                events = self.read_events(package_id)
                if events and all("manifest_snapshot" in event for event in events):
                    fresh_known = {e.get("resulting_manifest_sha256") for e in events}
                    try:
                        cache_digest = digest_json(json.loads(path.read_text(encoding="utf-8")))
                    except (json.JSONDecodeError, OSError):
                        cache_digest = None
                    if cache_digest is not None and cache_digest not in fresh_known:
                        raise ManifestInvalidError(
                            f"manifest cache corrupt for {package_id}: does not match any journal snapshot",
                            package_id=package_id,
                        )
                    data = self._verify_and_replay(package_id, events)
            else:
                self._validate_cache_if_present(package_id, path, data, events)
            return data

        # Backward compatibility for pre-Phase-4.1 journals: use the snapshot
        # when events do not carry reconstructable manifest snapshots.
        data = self._read_snapshot(package_id, path)
        if data.get("package_id") != package_id:
            raise ManifestInvalidError(
                f"manifest package_id mismatch for {package_id}: cache is for {data.get('package_id')!r}",
                package_id=package_id,
            )
        if events:
            last = events[-1].get("resulting_manifest_sha256")
            if last and digest_json(data) != last:
                raise ManifestInvalidError(
                    f"manifest digest mismatch for {package_id}: file does not match legacy event chain",
                    package_id=package_id,
                )
        return data

    def _cache_moved_ahead(
        self, package_id: str, path: Path, canonical: dict, events: list[dict]
    ) -> bool:
        """True when the on-disk cache digest is not among the caller's events
        (a concurrent writer committed after the caller's read_events)."""
        if not path.exists():
            return False
        try:
            cache = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        known = {event.get("resulting_manifest_sha256") for event in events}
        return digest_json(cache) not in known

    def _verify_and_replay(self, package_id: str, events: list[dict]) -> dict:
        previous = None
        artifact_digests: dict[str, int] = {}
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
            if snapshot.get("package_id") != package_id:
                self._chain_error(
                    package_id,
                    index,
                    f"manifest_snapshot.package_id does not match requested package_id "
                    f"({snapshot.get('package_id')!r} != {package_id!r})",
                )
            self._collect_artifact_digests(package_id, index, snapshot, artifact_digests)
            previous = {"state": snapshot["state"], "digest": digest}
        self._verify_artifact_digests(package_id, artifact_digests)
        return events[-1]["manifest_snapshot"]

    def _collect_artifact_digests(
        self, package_id: str, index: int, manifest: dict, collected: dict[str, int]
    ) -> None:
        """Record every referenced artifact digest once, remembering the first
        chain index that referenced it (for error context)."""
        if self.artifact_store is None:
            return
        digests = [item.get("content_sha256") for item in manifest.get("inputs", [])]
        digests += [item.get("sha256") for item in manifest.get("artifacts", [])]
        for digest in digests:
            if digest and digest not in collected:
                collected[digest] = index

    def _verify_artifact_digests(self, package_id: str, collected: dict[str, int]) -> None:
        """Verify each unique referenced digest once (O(J) blob reads)."""
        if self.artifact_store is None:
            return
        for digest, index in collected.items():
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
        if cache.get("package_id") != package_id:
            raise ManifestInvalidError(
                f"manifest cache package_id mismatch for {package_id}: cache is for {cache.get('package_id')!r}",
                package_id=package_id,
            )
        known = {event["resulting_manifest_sha256"] for event in events}
        if digest_json(cache) not in known:
            # A concurrent writer may have committed between the caller's
            # read_events and this load. Re-read the journal before declaring
            # the cache corrupt (bug-6): a racing writer should surface as
            # STALE_ACTION at CAS, not a false corruption alarm.
            fresh = self.read_events(package_id)
            if not fresh or digest_json(cache) not in {e.get("resulting_manifest_sha256") for e in fresh}:
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
        self,
        package_id: str,
        expected_revision: int,
        next_manifest: dict,
        event: dict,
        *,
        current_manifest: Optional[dict] = None,
    ) -> None:
        """Commit under the package lock.

        ``current_manifest`` is an optimization for engine callers that have
        already run a full chain verification: under the O_EXCL lock the only
        change possible is a concurrent writer, which is detected by comparing
        the last journal digest to the caller's manifest (no second full
        replay). When omitted, the store falls back to a full verified load.
        """
        self._validate_package_id(package_id)  # before any path/lock is touched
        with self._lock(package_id):
            if current_manifest is not None:
                current = self._tail_verified(package_id, current_manifest)
            else:
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

    def _tail_verified(self, package_id: str, manifest: dict) -> dict:
        """Cheap under-lock check: the journal tail must still match the
        caller's already-verified manifest. Reads only the last committed
        record instead of the whole journal (perf-1); under the O_EXCL lock no
        writer can be mid-append, so only the last committed line matters."""
        last = self._read_last_event(package_id)
        if last is None:
            raise StaleActionError(
                "journal empty during CAS",
                package_id=package_id,
                expected_revision=manifest.get("revision"),
                actual_revision=None,
            )
        if digest_json(manifest) != last.get("resulting_manifest_sha256"):
            raise StaleActionError(
                "manifest changed or tampered during apply",
                package_id=package_id,
                expected_revision=manifest.get("revision"),
                actual_revision=last.get("revision"),
            )
        return manifest

    def _read_last_event(self, package_id: str) -> Optional[dict]:
        """Read only the final committed journal record (O(1) in file size).
        Falls back to a full read when the tail is torn or unparseable."""
        path = self._events_path(package_id)
        if not path.exists():
            return None
        try:
            size = path.stat().st_size
            if size == 0:
                return None
            with open(path, "rb") as fh:
                window = min(size, 64 * 1024)
                fh.seek(size - window)
                chunk = fh.read()
            text = chunk.decode("utf-8", errors="replace")
            # The last committed record is the final complete line.
            idx = text.rstrip("\n").rfind("\n")
            candidate = text[idx + 1 :] if idx >= 0 else text
            candidate = candidate.strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass  # torn tail: fall through to full read
            return self._last_event_full(package_id)
        except OSError as exc:
            raise ManifestInvalidError(
                f"event journal corrupt for {package_id}: {exc}", package_id=package_id
            ) from exc

    def _last_event_full(self, package_id: str) -> Optional[dict]:
        events = self.read_events(package_id)
        return events[-1] if events else None

    # ── events ─────────────────────────────────────────────────────────
    def read_events(self, package_id: str) -> list[dict]:
        self._validate_package_id(package_id)
        path = self._events_path(package_id)
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestInvalidError(
                f"event journal corrupt for {package_id}: {exc}", package_id=package_id
            ) from exc
        try:
            return self._parse_events(package_id, raw)
        except ManifestInvalidError:
            if not raw.endswith("\n"):
                # A writer may be mid-append; give it one retry before treating
                # the unterminated tail as an in-flight line rather than corruption.
                time.sleep(LOCK_RETRY_S * 2)
                try:
                    raw = path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise ManifestInvalidError(
                        f"event journal corrupt for {package_id}: {exc}", package_id=package_id
                    ) from exc
                return self._parse_events(package_id, raw)
            raise

    def _parse_events(self, package_id: str, raw: str) -> list[dict]:
        rows: list[dict] = []
        # Records are separated by '\n' (json.dumps never emits raw '\r'
        # inside strings, and ensure_ascii=False may emit raw Unicode line
        # separators like U+2028 that splitlines() would split mid-record).
        lines = raw.split("\n")
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if index == len(lines) - 1 and not raw.endswith("\n"):
                    break  # writer mid-append: line is not committed yet
                raise ManifestInvalidError(
                    f"event journal corrupt for {package_id}: {exc}", package_id=package_id
                ) from exc
        return rows

    def find_event(
        self, package_id: str, action_id: str, events: Optional[list] = None
    ) -> Optional[dict]:
        self._validate_package_id(package_id)
        if events is None:
            events = self.read_events(package_id)
        for event in events:
            if event.get("action_id") == action_id:
                return event
        return None

    def _append_event(self, package_id: str, event: dict) -> None:
        path = self._events_path(package_id)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o644)
        try:
            # A crashed writer may have left an unterminated partial line;
            # truncate back to the last newline (uncommitted garbage) so the
            # next record stays a clean line (bug-1). Use a separate read fd:
            # the append fd's read position is unreliable under O_APPEND.
            if os.fstat(fd).st_size:
                with open(path, "rb") as rf:
                    rf.seek(0, os.SEEK_END)
                    if rf.seek(-1, os.SEEK_END) and rf.read(1) != b"\n":
                        # Scan back to the last newline boundary.
                        pos = rf.seek(0, os.SEEK_END)
                        while pos > 0:
                            pos = rf.seek(pos - 1, os.SEEK_SET)
                            if rf.read(1) == b"\n":
                                os.ftruncate(fd, pos + 1)
                                break
                            if pos == 0:
                                os.ftruncate(fd, 0)
                                break
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        except BaseException:
            os.close(fd)
            raise

    # ── internals ──────────────────────────────────────────────────────
    def _atomic_write(self, path: Path, data: dict) -> None:
        # Random suffix + O_EXCL so a pre-planted symlink at a predictable tmp
        # name cannot redirect the write (sec-2).
        tmp = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(tmp, flags, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
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
    """Advisory package-scoped lock via O_CREAT|O_EXCL with stale recovery.

    The lock file records the owner PID. On contention the contender reclaims
    the lock when the recorded owner is dead (os.kill(pid, 0)) or the lock is
    older than LOCK_STALE_AGE_S. O_EXCL is kept for the normal uncontended
    path so concurrent writers cannot both hold the lock.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.write(fd, f"{os.getpid()}\n".encode())
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                if self._reclaim_if_stale():
                    continue
                if time.monotonic() >= deadline:
                    raise ConcurrencyError(
                        f"could not acquire lock {self.path} "
                        f"(remove the file manually if it appears stale)"
                    )
                time.sleep(LOCK_RETRY_S)

    def _reclaim_if_stale(self) -> bool:
        try:
            content = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        pid = None
        if content:
            try:
                pid = int(content.split()[0])
            except ValueError:
                pid = None
        if pid is not None and not _pid_alive(pid):
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return False
        if age > LOCK_STALE_AGE_S:
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        return False

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.acquired = False
        return False
