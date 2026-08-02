"""Filesystem ArtifactStore — digest-addressed content (ADR-0007).

Content is stored under <root>/<package_id>/<logical_path>. The manifest
references artifacts by code-computed digest; the store never trusts a
caller-supplied hash.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.errors import InvalidPayloadError
from ..manifest.hashing import digest_bytes, digest_text

LOGICAL_PATH_BLOCKED = ("..", "/", "\\")


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

    def _dest(self, package_id: str, logical_path: str) -> Path:
        return self.root / package_id / validate_logical_path(logical_path)

    def put(self, package_id: str, logical_path: str, content: str) -> tuple[str, int]:
        data = content.encode("utf-8")
        dest = self._dest(package_id, logical_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return digest_bytes(data), len(data)

    def get(self, package_id: str, logical_path: str) -> str:
        dest = self._dest(package_id, logical_path)
        return dest.read_text(encoding="utf-8")

    def verify(self, package_id: str, logical_path: str, digest: str) -> bool:
        try:
            dest = self._dest(package_id, logical_path)
            return digest_bytes(dest.read_bytes()) == digest
        except (OSError, InvalidPayloadError):
            return False

    def artifact_bytes(self, package_id: str, logical_path: str) -> bytes:
        dest = self._dest(package_id, logical_path)
        return dest.read_bytes()
