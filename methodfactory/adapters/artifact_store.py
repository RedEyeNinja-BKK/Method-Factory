"""Filesystem ArtifactStore — immutable content-addressed blobs (ADR-0007).

Phase 2 corrections (Finding 3): durable, atomic blob writes.

Write path (put):
1. Validate logical path + size limits.
2. Write content to a SAME-DIRECTORY temporary file (.tmp.<random>).
3. fsync the temporary file.
4. Promote (os.replace) WITHOUT overwriting an existing canonical digest path.
5. fsync the containing directory after promotion.
6. If the canonical digest path already exists, VERIFY the existing blob
   matches the digest before treating the write as idempotently successful.

A partial final digest path is never exposed as a successful blob: if the
temporary write fails, the temp is removed and no canonical path exists.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from ..domain.errors import InvalidPayloadError
from ..storage.limits import (
    MAX_ARTIFACT_BYTES,
    MAX_LOGICAL_PATH_CHARS,
    MAX_CONTENT_CHARS,
)
from ..storage.paths import validate_logical_path
from ..storage.serialization import digest_bytes

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


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
        """Store content once under its SHA-256 digest (atomic + durable).

        ``package_id`` is reserved for a stable call signature with engine
        callers (ADR-0007); it is not part of the storage address.
        """
        validate_logical_path(logical_path)
        data = content.encode("utf-8")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise InvalidPayloadError(
                f"artifact exceeds MAX_ARTIFACT_BYTES ({MAX_ARTIFACT_BYTES})"
            )
        if len(content) > MAX_CONTENT_CHARS:
            raise InvalidPayloadError(
                f"artifact content exceeds MAX_CONTENT_CHARS ({MAX_CONTENT_CHARS})"
            )
        digest = digest_bytes(data)
        dest = self._blob_path(digest)
        if dest.exists():
            # Idempotent: verify the existing blob matches the digest before
            # reporting success (Finding 3 item 2). Never accept a partial or
            # corrupt canonical blob as a successful write.
            try:
                existing = dest.read_bytes()
            except OSError as exc:
                raise InvalidPayloadError(f"cannot read existing blob {digest}: {exc}") from exc
            if digest_bytes(existing) != digest:
                raise InvalidPayloadError(f"existing blob does not match digest {digest}")
            return digest, len(data)

        # Atomic same-directory write: temp file -> fsync -> promote -> dir fsync.
        tmp = self.blobs / f".tmp.{uuid.uuid4().hex}"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
            finally:
                # If fdopen succeeded, it owns fd; ensure close on the raw fd
                # only if fdopen never took ownership.
                pass
            # Promote WITHOUT overwriting an existing canonical digest path.
            os.replace(tmp, dest)
            # fsync the containing directory after promotion (durability).
            dir_fd = os.open(self.blobs, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return digest, len(data)

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

    def _read_verified(self, digest: str) -> bytes:
        dest = self._blob_path(digest)
        try:
            data = dest.read_bytes()
        except OSError as exc:
            raise InvalidPayloadError(f"cannot read blob {digest}: {exc}") from exc
        if digest_bytes(data) != digest:
            raise InvalidPayloadError(f"blob corrupted for digest {digest}")
        return data
