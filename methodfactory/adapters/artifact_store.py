"""Filesystem ArtifactStore — immutable content-addressed blobs (ADR-0007).

Phase 2 corrections (Finding 2, review 4879090471; closure review 4879440857):
blob publication is genuinely immutable via a no-clobber hard-link primitive,
with narrow injection seams and complete failure translation.

Publication algorithm (put):
1. Validate logical path, package ID, and size limits.
2. Write content to a same-directory temporary file (.tmp.<uuid>).
3. fsync the temporary file.
4. Publish it to the digest path via os.link(tmp, dest) — an atomic
   no-overwrite primitive. On FileExistsError, treat it as a publication
   race and VERIFY the existing canonical blob matches the digest.
5. Remove the temporary link/file (failure here is NOT silent after
   publication).
6. fsync the containing directory.

An existing canonical digest path is NEVER replaced, even when the expected
content is identical. A partial final digest path is never exposed as
success.

Failure translation (Finding 2 / Finding 4):
- content.encode() Unicode failures (lone surrogates) -> InvalidPayloadError;
- invalid artifact-store root types -> InvalidPayloadError;
- directory close failures -> InvalidPayloadError;
- temporary unlink failure after publication -> InvalidPayloadError (never
  silent success);
- every OS/Unicode/type failure is raised as InvalidPayloadError (a public
  MethodFactoryError) with the original exception retained via `raise ... from
  exc`.

Injection seams: every OS primitive used by publication is a module-level
function (_open_tmp, _write_all, _fsync_file, _hardlink, _unlink_tmp,
_open_dir, _fsync_dir, _close_fd). Tests inject precise faults at a single
seam without mocking put() itself; the production path is unchanged.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

from ..domain.errors import InvalidPayloadError
from ..storage.limits import MAX_ARTIFACT_BYTES, MAX_CONTENT_CHARS
from ..storage.paths import validate_logical_path, validate_package_id
from ..storage.serialization import digest_bytes

# Strict canonical digest grammar (local review): exactly 64 lowercase hex
# chars, matching the manifest validator (SHA256_RE). 0x-prefixed, uppercase,
# and underscore forms are rejected so the store and the manifest never
# disagree about what a digest is.
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


# ── Narrow injection seams (Finding 2) ──────────────────────────────────
def _open_tmp(blobs_dir: Path) -> tuple[int, Path]:
    tmp = blobs_dir / f".tmp.{uuid.uuid4().hex}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return fd, tmp


def _write_all(fh, data: bytes) -> None:
    fh.write(data)
    fh.flush()


def _fsync_file(fd: int) -> None:
    os.fsync(fd)


def _hardlink(src: Path, dst: Path) -> None:
    os.link(src, dst)


def _unlink_tmp(path: Path) -> None:
    path.unlink(missing_ok=True)


def _open_dir(path: Path) -> int:
    return os.open(path, os.O_RDONLY)


def _fsync_dir(fd: int) -> None:
    os.fsync(fd)


def _close_fd(fd: int) -> None:
    os.close(fd)


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        if not isinstance(root, (str, os.PathLike)):
            raise InvalidPayloadError(
                f"artifact store root must be a path, got {type(root).__name__}"
            )
        try:
            self.root = Path(root)
            # Private modes on root AND blobs (local review, sec-2): a
            # umask-inherited group/world-writable blobs dir would let other
            # local users unlink blobs or plant symlinks in the digest
            # namespace, defeating the immutable-store guarantees.
            os.makedirs(self.root, mode=0o700, exist_ok=True)
            self.blobs = self.root / "blobs"
            os.makedirs(self.blobs, mode=0o700, exist_ok=True)
            os.chmod(self.root, 0o700)
            os.chmod(self.blobs, 0o700)
        except OSError as exc:
            raise InvalidPayloadError(
                f"cannot initialize artifact store at {root}: {exc}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise InvalidPayloadError(
                f"invalid artifact store root {root!r}: {exc}"
            ) from exc

    def _blob_path(self, digest: str) -> Path:
        if not isinstance(digest, str) or not _HEX64_RE.match(digest):
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
        try:
            data = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise InvalidPayloadError(
                "artifact content is not valid UTF-8 (lone surrogate?)"
            ) from exc
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

        # Idempotency fast path (local review, perf-1): if the canonical blob
        # already exists, verify it and return WITHOUT any temp write/fsync.
        # The os.link/FileExistsError path remains the mid-publication race
        # backstop; a corrupt existing blob fails typed exactly as before.
        try:
            if dest.is_file():
                existing = dest.read_bytes()
                if digest_bytes(existing) != digest:
                    raise InvalidPayloadError(
                        f"existing blob does not match digest {digest}"
                    )
                return digest, len(data)
        except OSError as exc:
            raise InvalidPayloadError(
                f"cannot read existing blob {digest}: {exc}"
            ) from exc

        fd: int | None = None
        tmp: Path | None = None
        dir_fd: int | None = None
        try:
            # 1. Same-directory temporary file.
            try:
                fd, tmp = _open_tmp(self.blobs)
            except OSError as exc:
                raise InvalidPayloadError(f"cannot create temp blob: {exc}") from exc
            try:
                with os.fdopen(fd, "wb") as fh:
                    _write_all(fh, data)
                    _fsync_file(fh.fileno())
            except InvalidPayloadError:
                raise
            except OSError as exc:
                raise InvalidPayloadError(f"write temp blob failed: {exc}") from exc

            # 2. No-clobber publication via hard link (atomic; never replaces
            #    an existing canonical digest path).
            try:
                _hardlink(tmp, dest)
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

            # 3. Remove the temporary link/file. After publication this MUST
            #    not silently fail: a leftover temp would mask success.
            try:
                _unlink_tmp(tmp)
            except OSError as exc:
                raise InvalidPayloadError(
                    f"cannot remove temp blob {tmp.name}: {exc}"
                ) from exc

            # 4. fsync the containing directory after publication.
            try:
                dir_fd = _open_dir(self.blobs)
            except OSError as exc:
                raise InvalidPayloadError(
                    f"cannot open blobs dir for fsync: {exc}"
                ) from exc
            try:
                _fsync_dir(dir_fd)
            except OSError as exc:
                raise InvalidPayloadError(f"fsync blobs dir failed: {exc}") from exc
            finally:
                if dir_fd is not None:
                    # Capture the in-flight exception BEFORE closing (the
                    # close-error handler's own sys.exc_info() is the close
                    # error, not the pre-existing one).
                    in_flight = sys.exc_info()[0]
                    try:
                        _close_fd(dir_fd)
                    except OSError as exc:
                        # Do not mask an in-flight durability error (local
                        # review, bug-5): a close failure is only reported when
                        # no other exception is already propagating.
                        if in_flight is None:
                            raise InvalidPayloadError(
                                f"cannot close blobs dir: {exc}"
                            ) from exc
        except BaseException:
            if tmp is not None:
                try:
                    _unlink_tmp(tmp)
                except OSError:
                    pass
            raise
        return digest, len(data)

    def get(self, digest: str) -> str:
        data = self._read_verified(digest)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InvalidPayloadError(
                f"blob {digest} is not valid UTF-8"
            ) from exc

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
