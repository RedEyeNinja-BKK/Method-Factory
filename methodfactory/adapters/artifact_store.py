"""Filesystem ArtifactStore — immutable content-addressed blobs (ADR-0007).

Phase 2 corrections (Finding 2, review 4879090471): blob publication is
genuinely immutable via a no-clobber hard-link primitive.

Publication algorithm (put):
1. Validate logical path, package ID, and size limits.
2. Write content to a same-directory temporary file (.tmp.<uuid>).
3. fsync the temporary file.
4. Publish it to the digest path via os.link(tmp, dest) — an atomic
   no-overwrite primitive. On FileExistsError, treat it as a publication
   race and VERIFY the existing canonical blob matches the digest.
5. Remove the temporary link/file.
6. fsync the containing directory.

An existing canonical digest path is NEVER replaced, even when the expected
content is identical. A partial final digest path is never exposed as
success.

All artifact OS/Unicode/type failures are translated into the public Method
Factory error hierarchy (InvalidPayloadError), with the original exception
retained as the cause (Finding 2 / Finding 4).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from ..domain.errors import InvalidPayloadError
from ..storage.limits import MAX_ARTIFACT_BYTES, MAX_CONTENT_CHARS
from ..storage.paths import validate_logical_path, validate_package_id
from ..storage.serialization import digest_bytes


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        try:
            self.root = Path(root)
            self.root.mkdir(parents=True, exist_ok=True)
            self.blobs = self.root / "blobs"
            self.blobs.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise InvalidPayloadError(f"cannot initialize artifact store at {root}: {exc}") from exc

    def _blob_path(self, digest: str) -> Path:
        if not isinstance(digest, str) or len(digest) != 64:
            raise InvalidPayloadError(f"invalid artifact digest: {digest!r}")
        try:
            int(digest, 16)
        except ValueError:
            raise InvalidPayloadError(f"invalid artifact digest: {digest!r}")
        return self.blobs / digest

    def put(self, package_id: str, logical_path: str, content: str) -> tuple[str, int]:
        """Store content once under its SHA-256 digest (atomic, no-clobber).

        ``package_id`` is validated (Finding 2) and reserved for a stable call
        signature with engine callers; it is not part of the storage address.
        """
        validate_package_id(package_id)
        validate_logical_path(logical_path)
        if not isinstance(content, str):
            raise InvalidPayloadError("artifact content must be a string")
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

        # Same-directory temporary file.
        tmp = self.blobs / f".tmp.{uuid.uuid4().hex}"
        try:
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except OSError as exc:
                raise InvalidPayloadError(f"cannot create temp blob: {exc}") from exc
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError as exc:
                        raise InvalidPayloadError(f"fsync temp blob failed: {exc}") from exc
            except InvalidPayloadError:
                raise
            except OSError as exc:
                raise InvalidPayloadError(f"write temp blob failed: {exc}") from exc

            # No-clobber publication via hard link (atomic; never replaces an
            # existing canonical digest path).
            try:
                os.link(tmp, dest)
            except FileExistsError:
                # Publication race: verify the existing canonical blob matches
                # the digest. Never replace it.
                try:
                    existing = dest.read_bytes()
                except OSError as exc:
                    raise InvalidPayloadError(
                        f"cannot read raced destination blob {digest}: {exc}"
                    ) from exc
                if digest_bytes(existing) != digest:
                    raise InvalidPayloadError(
                        f"raced destination does not match digest {digest}"
                    )
            except OSError as exc:
                raise InvalidPayloadError(f"publish blob failed: {exc}") from exc
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

            # fsync the containing directory after publication.
            try:
                dir_fd = os.open(self.blobs, os.O_RDONLY)
            except OSError as exc:
                raise InvalidPayloadError(f"cannot open blobs dir for fsync: {exc}") from exc
            try:
                try:
                    os.fsync(dir_fd)
                except OSError as exc:
                    raise InvalidPayloadError(f"fsync blobs dir failed: {exc}") from exc
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
