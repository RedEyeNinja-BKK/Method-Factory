"""Frozen public v0.1.2 legacy reader for migration (ADR-0012 amendment).

Deliberately frozen compatibility component for exact public:

    fb5641cc1a3f1f54b96bba3af88ec5a1b010f4e5  (tag v0.1.2-integrity)

This module reproduces ONLY the public validation semantics required to
prove a legacy source and expose immutable normalized records to the
migration layer. It is NOT a storage engine:

- read-only; never repairs, truncates, reconciles, or rewrites;
- never acquires locks, never performs CAS, tail repair, tail classification,
  stale-lock recovery, or PID ownership;
- never mutates artifacts or source files;
- fails closed on ambiguous or unsafe evidence.

Canonical source of history:  events/<package_id>.events.jsonl
Latest-manifest cache:        packages/<package_id>.json
Artifact blobs:               artifacts/blobs/<sha256>

Cache semantics (frozen ADR): absent cache is acceptable where the journal is
reconstructable; a lagging cache is acceptable if its digest matches ANY
committed journal snapshot; a cache matching no committed snapshot fails;
the journal always owns history.

Legacy `.lock` files (events/<package_id>.lock) are transient coordination
state. If present, migration must refuse to start (the caller raises the
existing CONCURRENCY error) — the reader never deletes, repairs, inspects PID,
or acquires them, and never includes them in semantic source identity.

Legacy serializers (public v0.1.2):
- hash canonicalization: json.dumps(value, sort_keys=True,
  separators=(",",":"), ensure_ascii=True).encode("utf-8")
- journal-line serialization: json.dumps(event, sort_keys=True) + "\\n"
  (Python default spacing and ASCII escaping)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..storage.errors import (
    LegacyChainInvalidError,
    LegacySourceInvalidError,
)

# Exact public v0.1.2 identity (ADR-0012 amendment §1).
LEGACY_COMMIT = "fb5641cc1a3f1f54b96bba3af88ec5a1b010f4e5"
LEGACY_TAG = "v0.1.2-integrity"
LEGACY_SCHEMA_VERSION = "0.1"
LEGACY_ACTION_CREATE = "act_create_package"

PACKAGE_ID_RE = re.compile(r"^pkg_[A-Za-z0-9_-]{1,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def legacy_canonical_json(value: Any) -> bytes:
    """Public v0.1.2 HASH canonicalization (ensure_ascii=True, compact)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def legacy_digest_json(value: Any) -> str:
    return hashlib.sha256(legacy_canonical_json(value)).hexdigest()


def legacy_line_json(event: dict) -> str:
    """Public v0.1.2 JOURNAL-LINE serialization (default spacing, ASCII)."""
    return json.dumps(event, sort_keys=True)


def legacy_digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def legacy_digest_text(content: str) -> str:
    return legacy_digest_bytes(content.encode("utf-8"))


class LegacyEvent:
    """Immutable normalized record from a public v0.1.2 journal line."""

    __slots__ = (
        "package_id", "event_id", "action", "action_id", "revision",
        "state_before", "state_after", "resulting_manifest_sha256",
        "previous_manifest_sha256", "action_sha256", "at", "manifest_snapshot",
        "line_number",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class LegacyPackage:
    """A validated public v0.1.2 package: ordered events + cache status."""

    def __init__(self, package_id: str, events: list[LegacyEvent]) -> None:
        self.package_id = package_id
        self.events = events
        self.cache_manifest: dict | None = None  # parsed packages/<id>.json
        self.cache_status: str | None = None  # "absent" | "valid" | "invalid"


class LegacySource:
    """Frozen reader over one public v0.1.2 store root.

    Exposes validated packages in deterministic order (sorted package IDs)
    plus the semantic source inventory for source-immutability proofs.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.packages_dir = self.root / "packages"
        self.events_dir = self.root / "events"
        self.artifacts_dir = self.root / "artifacts"
        self._validate_layout()
        self.packages: dict[str, LegacyPackage] = {}
        self._read_packages()

    # ── layout / safety ────────────────────────────────────────────────
    def _validate_layout(self) -> None:
        """Require the exact public v0.1.2 layout and safe paths."""
        for d in (self.packages_dir, self.events_dir, self.artifacts_dir):
            if not d.is_dir():
                raise LegacySourceInvalidError(
                    f"legacy store missing required directory {d}"
                )
            if d.is_symlink():
                raise LegacySourceInvalidError(
                    f"legacy store directory must not be a symlink: {d}"
                )
        # Source root itself must not be a symlink (avoid escaping).
        if self.root.is_symlink():
            raise LegacySourceInvalidError(
                f"legacy store root must not be a symlink: {self.root}"
            )

    def _check_within(self, p: Path) -> None:
        """Reject paths that escape the explicit source root."""
        try:
            resolved = p.resolve()
        except OSError as exc:  # pragma: no cover - defensive
            raise LegacySourceInvalidError(f"cannot resolve {p}: {exc}") from exc
        root_resolved = self.root.resolve()
        if root_resolved not in resolved.parents and resolved != root_resolved:
            raise LegacySourceInvalidError(
                f"legacy source path escapes store root: {p}"
            )

    # ── package discovery ──────────────────────────────────────────────
    def _read_packages(self) -> None:
        for events_path in sorted(self.events_dir.glob("*.events.jsonl")):
            # Filename grammar: <package_id>.events.jsonl
            name = events_path.name
            if not name.endswith(".events.jsonl"):
                continue
            package_id = name[: -len(".events.jsonl")]
            if not PACKAGE_ID_RE.match(package_id):
                raise LegacySourceInvalidError(
                    f"legacy event filename has invalid package_id: {name}"
                )
            self._check_within(events_path)
            if events_path.is_symlink():
                raise LegacySourceInvalidError(
                    f"legacy event file must not be a symlink: {events_path}"
                )
            events = self._read_journal(package_id, events_path)
            pkg = LegacyPackage(package_id, events)
            self._read_cache(pkg)
            self.packages[package_id] = pkg

    def _read_journal(self, package_id: str, path: Path) -> list[LegacyEvent]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LegacySourceInvalidError(
                f"cannot read legacy journal {path}: {exc}"
            ) from exc
        events: list[LegacyEvent] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue  # tolerate blank lines (public reader ignored them)
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LegacyChainInvalidError(
                    f"legacy journal {package_id} line {i} is not valid JSON: {exc}"
                ) from exc
            if not isinstance(obj, dict):
                raise LegacyChainInvalidError(
                    f"legacy journal {package_id} line {i} is not a JSON object"
                )
            event = self._normalize_event(package_id, obj, i)
            events.append(event)
        return events

    def _normalize_event(self, package_id: str, obj: dict, line: int) -> LegacyEvent:
        required = (
            "event_id", "action", "action_id", "revision", "state_before",
            "state_after", "resulting_manifest_sha256",
            "previous_manifest_sha256", "action_sha256", "at",
            "manifest_snapshot",
        )
        missing = [f for f in required if f not in obj]
        if missing:
            raise LegacyChainInvalidError(
                f"legacy journal {package_id} line {line} missing fields: {missing}"
            )
        snapshot = obj["manifest_snapshot"]
        if not isinstance(snapshot, dict):
            raise LegacyChainInvalidError(
                f"legacy journal {package_id} line {line} manifest_snapshot not object"
            )
        ev = LegacyEvent(
            package_id=package_id,
            event_id=obj["event_id"],
            action=obj["action"],
            action_id=obj["action_id"],
            revision=obj["revision"],
            state_before=obj["state_before"],
            state_after=obj["state_after"],
            resulting_manifest_sha256=obj["resulting_manifest_sha256"],
            previous_manifest_sha256=obj["previous_manifest_sha256"],
            action_sha256=obj["action_sha256"],
            at=obj["at"],
            manifest_snapshot=snapshot,
            line_number=line,
        )
        return ev

    # ── cache handling ─────────────────────────────────────────────────
    def _cache_path(self, package_id: str) -> Path:
        return self.packages_dir / f"{package_id}.json"

    def _read_cache(self, pkg: LegacyPackage) -> None:
        path = self._cache_path(pkg.package_id)
        if not path.exists():
            pkg.cache_status = "absent"
            return
        self._check_within(path)
        if path.is_symlink():
            raise LegacySourceInvalidError(
                f"legacy cache file must not be a symlink: {path}"
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LegacySourceInvalidError(
                f"legacy cache corrupt for {pkg.package_id}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LegacySourceInvalidError(
                f"legacy cache not an object for {pkg.package_id}"
            )
        pkg.cache_manifest = data
        # Cache is valid iff its digest matches ANY committed journal snapshot.
        known = {
            e.resulting_manifest_sha256
            for e in pkg.events
            if isinstance(e.resulting_manifest_sha256, str)
        }
        digest = legacy_digest_json(data)
        if digest in known:
            pkg.cache_status = "valid"
        else:
            pkg.cache_status = "invalid"

    # ── artifact helpers ───────────────────────────────────────────────
    def artifact_bytes(self, digest: str) -> bytes:
        """Read + verify a legacy blob (never follows symlinks out of root)."""
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            raise LegacySourceInvalidError(f"invalid artifact digest {digest!r}")
        path = self.artifacts_dir / "blobs" / digest
        self._check_within(path)
        if path.is_symlink():
            raise LegacySourceInvalidError(
                f"legacy artifact blob must not be a symlink: {path}"
            )
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise LegacySourceInvalidError(
                f"cannot read legacy artifact blob {digest}: {exc}"
            ) from exc
        if legacy_digest_bytes(data) != digest:
            raise LegacyChainInvalidError(
                f"legacy artifact blob {digest} content does not match digest"
            )
        return data

    # ── validation ─────────────────────────────────────────────────────
    def validate(self) -> None:
        """Validate every package chain using public v0.1.2 semantics.

        Raises LegacyChainInvalidError on the first violation. Source remains
        byte-identical (read-only).
        """
        if not self.packages:
            raise LegacySourceInvalidError(
                "legacy store contains no event journals"
            )
        for pkg in self.packages.values():
            self._validate_package(pkg)

    def _validate_package(self, pkg: LegacyPackage) -> None:
        previous: dict | None = None
        previous_digest: str | None = None
        for index, ev in enumerate(pkg.events):
            if ev.revision != index:
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: revision {ev.revision!r}"
                )
            if ev.state_before != (None if previous is None else previous["state"]):
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: state_before does not match prior state_after"
                )
            snap = ev.manifest_snapshot
            if snap.get("state") != ev.state_after:
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: state_after does not match manifest_snapshot.state"
                )
            if snap.get("revision") != ev.revision:
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: snapshot revision mismatch"
                )
            expected_prev = None if previous is None else previous_digest
            if snap.get("previous_manifest_sha256") != expected_prev:
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: previous_manifest_sha256 chain break"
                )
            digest = legacy_digest_json(snap)
            if ev.resulting_manifest_sha256 != digest:
                raise LegacyChainInvalidError(
                    f"legacy chain break for {pkg.package_id} at event index "
                    f"{index}: resulting_manifest_sha256 does not match snapshot"
                )
            # Validate referenced blobs exist + match digest (public semantics).
            for item in snap.get("inputs", []):
                d = item.get("content_sha256")
                if d:
                    self.artifact_bytes(d)
            for art in snap.get("artifacts", []):
                d = art.get("sha256")
                if d:
                    self.artifact_bytes(d)
            previous = {"state": snap["state"], "digest": digest}
            previous_digest = digest
        if pkg.cache_status == "invalid":
            raise LegacyChainInvalidError(
                f"legacy cache for {pkg.package_id} matches no committed "
                "journal snapshot"
            )

    # ── semantic source inventory (immutability proof) ─────────────────
    def source_inventory(self) -> dict[str, dict[str, Any]]:
        """Deterministic inventory over the frozen semantic source set.

        Excludes `.lock` files (transient coordination state). Keys are
        relative paths; values are {sha256, size, type}.
        """
        inventory: dict[str, dict[str, Any]] = {}
        for pattern, base in (
            ("*.events.jsonl", self.events_dir),
            ("*.json", self.packages_dir),
        ):
            for p in sorted(base.glob(pattern)):
                if p.is_symlink():
                    continue  # already rejected during read
                rel = str(p.relative_to(self.root))
                inventory[rel] = self._file_entry(p)
        blobs = self.artifacts_dir / "blobs"
        if blobs.is_dir():
            for p in sorted(blobs.iterdir()):
                if p.is_file() and not p.is_symlink():
                    rel = str(p.relative_to(self.root))
                    inventory[rel] = self._file_entry(p)
        return inventory

    @staticmethod
    def _file_entry(p: Path) -> dict[str, Any]:
        data = p.read_bytes()
        return {
            "sha256": legacy_digest_bytes(data),
            "size": len(data),
            "type": "file",
        }
