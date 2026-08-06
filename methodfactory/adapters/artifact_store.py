"""Filesystem ArtifactStore — immutable content-addressed blobs (ADR-0007)."""

from __future__ import annotations

from pathlib import Path
import re

from ..domain.errors import InvalidPayloadError
from ..manifest.hashing import digest_bytes

LOGICAL_PATH_BLOCKED = ("..", "/", "\\")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_logical_path(logical_path: str) -> str:
    lp = logical_path.strip().lstrip("/")
    if not lp:
        raise InvalidPayloadError("logical_path is empty")
    parts = lp.split("/")
    if any(p in LOGICAL_PATH_BLOCKED for p in parts):
        raise InvalidPayloadError(f"logical_path contains blocked segment: {logical_path!r}")
    if len(lp) > 255:
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
            return digest, len(data)
        with fd:
            fd.write(data)
            fd.flush()
        return digest, len(data)

    def get(self, digest: str) -> str:
        return self._blob_path(digest).read_text(encoding="utf-8")

    def verify(self, digest: str) -> bool:
        try:
            dest = self._blob_path(digest)
            return dest.is_file() and digest_bytes(dest.read_bytes()) == digest
        except (OSError, InvalidPayloadError):
            return False

    def artifact_bytes(self, digest: str) -> bytes:
        return self._blob_path(digest).read_bytes()
