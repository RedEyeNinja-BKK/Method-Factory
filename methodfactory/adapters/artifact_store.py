"""Filesystem ArtifactStore — immutable content-addressed blobs (ADR-0007).

Blobs are stored once under their SHA-256 digest. Reads and duplicate writes
verify content against the digest so a partial or corrupted blob can never
silently satisfy a digest (v2.0.0 review remediation, F11).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..domain.errors import InvalidPayloadError
from ..domain.vocabulary import MAX_LOGICAL_PATH_CHARS
from ..manifest.hashing import digest_bytes

LOGICAL_PATH_BLOCKED_SEGMENTS = frozenset({"..", "."})
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def validate_logical_path(logical_path: str) -> str:
    """Validate an artifact logical path (contract: relative, '/'-separated,
    no '..', no absolute, no backslash, no percent-encoding)."""
    lp = logical_path.strip()
    if not lp:
        raise InvalidPayloadError("logical_path is empty")
    if lp.startswith("/") or lp.startswith("\\"):
        raise InvalidPayloadError(f"logical_path must be relative: {logical_path!r}")
    if _WINDOWS_DRIVE_RE.match(lp):
        raise InvalidPayloadError(f"logical_path must be relative: {logical_path!r}")
    if "\\" in lp:
        raise InvalidPayloadError(f"logical_path must use '/' separators: {logical_path!r}")
    if "%" in lp:
        raise InvalidPayloadError(f"logical_path must not contain percent-encoding: {logical_path!r}")
    parts = lp.split("/")
    if any(p in LOGICAL_PATH_BLOCKED_SEGMENTS for p in parts):
        raise InvalidPayloadError(f"logical_path contains blocked segment: {logical_path!r}")
    if len(lp) > MAX_LOGICAL_PATH_CHARS:
        raise InvalidPayloadError("logical_path too long")
    return lp


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, digest: str) -> Path:
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise InvalidPayloadError(f"invalid artifact digest: {digest!r}")
        return self.blobs / digest

    def put(self, package_id: str, logical_path: str, content: str) -> tuple[str, int]:
        """Store content once under its SHA-256 digest.

        ``package_id`` and ``logical_path`` remain API context for callers, but
        are deliberately not part of the storage address.
        """
        del package_id
        validate_logical_path(logical_path)
        data = content.encode("utf-8")
        digest = digest_bytes(data)
        dest = self._blob_path(digest)
        try:
            fd = dest.open("xb")
        except FileExistsError:
            if digest_bytes(dest.read_bytes()) != digest:
                raise InvalidPayloadError(f"artifact blob poisoned for digest {digest}")
            return digest, len(data)
        with fd:
            fd.write(data)
            fd.flush()
            os.fsync(fd.fileno())
        return digest, len(data)

    def _read_verified(self, digest: str) -> bytes:
        dest = self._blob_path(digest)
        data = dest.read_bytes()
        if digest_bytes(data) != digest:
            raise InvalidPayloadError(f"artifact blob corrupted for digest {digest}")
        return data

    def get(self, digest: str) -> str:
        return self._read_verified(digest).decode("utf-8")

    def verify(self, digest: str) -> bool:
        try:
            dest = self._blob_path(digest)
            return dest.is_file() and digest_bytes(dest.read_bytes()) == digest
        except (OSError, InvalidPayloadError):
            return False

    def artifact_bytes(self, digest: str) -> bytes:
        return self._read_verified(digest)
