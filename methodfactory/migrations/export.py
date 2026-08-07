"""Deterministic event exports (ADR-0012 amendment §12-§13).

Two formats:

1. `method-factory-events-v1` — supported evidence export. One JSON object
   per line with the frozen field set, current canonical UTF-8 JSON,
   `ORDER BY package_id, revision`.

2. `legacy-v012-jsonl` — evidence/compatibility export reconstructing the
   PUBLIC v0.1.2 event SHAPE using public v0.1.2 semantics:
   - inline summary content;
   - legacy canonical manifest hashes (ensure_ascii=True, compact);
   - legacy predecessor hashes (event-level AND snapshot-level, both in the
     legacy hash space, so the exported journal re-validates under the
     frozen v0.1.2 reader);
   - legacy rev>0 action hashes using legacy canonical hash serialization;
   - legacy special rev0 action hash;
   - journal-line serialization `json.dumps(event, sort_keys=True) + "\\n"`
     (Python default spacing, ASCII escaping).

   LIMITATION (honest): the export reconstructs the public v0.1.2 event
   SHAPE and line serializer, not byte identity with the original journal:
   summary timestamps are the normalized current-era values (ADR-0012 §9),
   and lineage/action hashes are recomputed over the reconstructed shapes.
   It is an evidence stream, not a byte-for-byte replay of the source
   journal.

Both are read-only and deterministic: same DB + same exporter version ->
byte-identical output. Export never mutates the store; it uses a read-only
SQLite connection with a consistent read transaction.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from ..storage.errors import StorageError
from ..storage.sqlite import (
    APPLICATION_ID,
    USER_VERSION,
    close_database,
    open_database,
)
from .v012_jsonl import (
    legacy_digest_json,
    legacy_hash_semantic,
    legacy_line_json,
    legacy_rev0_hash,
)

EVENTS_V1_FORMAT = "method-factory-events-v1"
EVENTS_V1_VERSION = 1

LEGACY_JSONL_FORMAT = "legacy-v012-jsonl"
LEGACY_JSONL_VERSION = 1

EXPORT_SQL = """
SELECT package_id, revision, event_id, action_id, action, action_sha256,
       state_before, state_after, previous_manifest_sha256,
       resulting_manifest_sha256, created_at, action_json, manifest_json
FROM events
ORDER BY package_id, revision
"""


def _read_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(EXPORT_SQL).fetchall()
    return [dict(r) for r in rows]


def _current_event_object(row: dict) -> dict:
    """Frozen `method-factory-events-v1` per-line object."""
    return {
        "format": EVENTS_V1_FORMAT,
        "format_version": EVENTS_V1_VERSION,
        "package_id": row["package_id"],
        "revision": row["revision"],
        "event_id": row["event_id"],
        "action_id": row["action_id"],
        "action": row["action"],
        "state_before": row["state_before"],
        "state_after": row["state_after"],
        "action_sha256": row["action_sha256"],
        "previous_manifest_sha256": row["previous_manifest_sha256"],
        "resulting_manifest_sha256": row["resulting_manifest_sha256"],
        "created_at": row["created_at"],
        "semantic_action": _decode_json(row["action_json"]),
        "manifest": _decode_json(row["manifest_json"]),
    }


def _decode_json(raw: Any) -> dict:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise StorageError("stored JSON is not an object")
    return data


# ── legacy-v012-jsonl reconstruction ─────────────────────────────────
def _legacy_event_object(row: dict, prev_legacy_hash: str | None) -> dict:
    """Reconstruct the public v0.1.2 EVENT OBJECT shape.

    Uses legacy canonical hashing and inline summary content.
    """
    semantic = _decode_json(row["action_json"])
    manifest = _decode_json(row["manifest_json"])

    # Reconstruct inline summary content: content-addressed digest == legacy
    # canonical_sha256. The summary body is stored as a blob; we need its
    # bytes. We recompute the summary body via the deterministic renderer
    # (byte-identical to public v0.1.2) when summary present.
    legacy_manifest = _to_legacy_manifest(manifest, prev_legacy_hash)

    # Legacy manifest hashes (ensure_ascii=True).
    resulting = legacy_digest_json(legacy_manifest)
    # Legacy predecessor hash: the legacy canonical hash of the PREVIOUS
    # exported line's reconstructed manifest (rows process in package_id,
    # revision order). This keeps the exported chain fully consistent in the
    # LEGACY hash space, even when the current-era stored previous hash
    # differs (non-ASCII content; ensure_ascii divergence). The snapshot's
    # previous_manifest_sha256 is set to the same value (see
    # _to_legacy_manifest) so the exported journal re-validates under the
    # frozen v0.1.2 reader.
    prev = prev_legacy_hash

    # Legacy action hash: rev0 special reduced; rev>0 legacy canonical of
    # semantic action (six fields).
    if row["revision"] == 0:
        action_hash = legacy_rev0_hash(row["package_id"])
    else:
        action_hash = legacy_hash_semantic(semantic)

    return {
        "event_id": row["event_id"],
        "action": row["action"],
        "action_id": row["action_id"],
        "revision": row["revision"],
        "state_before": row["state_before"],
        "state_after": row["state_after"],
        "resulting_manifest_sha256": resulting,
        "previous_manifest_sha256": prev,
        "action_sha256": action_hash,
        "at": row["created_at"],
        "manifest_snapshot": legacy_manifest,
    }


def _to_legacy_manifest(manifest: dict, prev_legacy_hash: str | None = None) -> dict:
    """Convert current manifest to public v0.1.2 manifest shape.

    - summary inline content: regenerate via the deterministic renderer.
    - summary canonical_sha256 = digest of inline content (== current digest).
    - drop content-addressed digest/size/preview; add content + canonical.
    - previous_manifest_sha256: recomputed in the LEGACY hash space when the
      predecessor hash is threaded in (rev>0). Revision 0 stays None.
    """
    import copy

    m = copy.deepcopy(manifest)
    if prev_legacy_hash is not None:
        m["previous_manifest_sha256"] = prev_legacy_hash
    summary = m.get("summary")
    if isinstance(summary, dict):
        body = _render_summary(m)
        m["summary"] = {
            "content": body,
            "canonical_sha256": summary.get("digest") or _legacy_digest_text(body),
            "presented_at": summary.get("presented_at"),
            "confirmation": summary.get("confirmation"),
        }
    return m


def _render_summary(manifest: dict) -> str:
    from ..manifest.render import render_summary

    return render_summary(manifest)


def _legacy_digest_text(content: str) -> str:
    from .v012_jsonl import legacy_digest_text

    return legacy_digest_text(content)


# ── public API ────────────────────────────────────────────────────────
def export_events(
    store_root: str | Path,
    output: str | Path | None,
    *,
    fmt: str = EVENTS_V1_FORMAT,
) -> int:
    """Deterministically export events. Returns number of events written.

    `output` None -> write to stdout. Otherwise atomic temp+rename to the
    output path (fail closed if destination exists).
    """
    if fmt not in (EVENTS_V1_FORMAT, LEGACY_JSONL_FORMAT):
        raise StorageError(f"unsupported export format {fmt!r}")

    conn = open_database(store_root, read_only=True)
    try:
        # Verify identity before export.
        app = int(conn.execute("PRAGMA application_id").fetchone()[0])
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if app != APPLICATION_ID or ver != USER_VERSION:
            raise StorageError(
                f"database identity mismatch (app {app}, version {ver})"
            )
        rows = _read_rows(conn)
    finally:
        close_database(conn)

    lines = []
    prev_legacy: dict[str, str | None] = {}
    for row in rows:
        if fmt == EVENTS_V1_FORMAT:
            obj = _current_event_object(row)
            line = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
        else:
            # legacy-v012-jsonl: PUBLIC v0.1.2 journal-line serializer
            # (Python default spacing + ASCII escaping), NOT the compact
            # current serializer. The HASH serializer remains legacy
            # canonical (ensure_ascii compact) for action/manifest digests.
            obj = _legacy_event_object(
                row, prev_legacy.get(row["package_id"])
            )
            prev_legacy[row["package_id"]] = obj["resulting_manifest_sha256"]
            line = legacy_line_json(obj)
        lines.append(line)

    payload = ("\n".join(lines) + "\n").encode("utf-8") if lines else b""

    if output is None:
        import sys

        sys.stdout.buffer.write(payload)
        return len(rows)

    out = Path(output)
    if out.exists():
        raise StorageError(f"export destination exists: {out}")
    # Unique same-directory temp (O_EXCL) then atomic no-clobber publication:
    # a raced destination is never overwritten (CWE-377 / no-clobber).
    import uuid

    tmp = out.with_name(f".{out.name}.tmp.{uuid.uuid4().hex}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise StorageError(f"cannot create export temp file: {exc}") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, out)
        except FileExistsError:
            raise StorageError(
                f"export destination appeared during export: {out}"
            ) from None
        except OSError as exc:
            raise StorageError(f"cannot publish export: {exc}") from exc
        try:
            tmp.unlink()
        except OSError as exc:
            raise StorageError(f"cannot remove export temp: {exc}") from exc
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(out.parent)
    return len(rows)


def _fsync_dir(path: Path) -> None:
    dir_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
