"""SQLite schema creation, identity checks, and append-only guards.

Phase 2 corrections (senior review 4878620791, Finding 1). Applies the
binding first-release SQLite contract exactly as specified:

- every binding connection PRAGMA is applied AND read back; a required mode
  that cannot be established fails typed (StorageError), never silently;
- read-only connections VERIFY PRAGMAs without attempting mutation;
- first initialization is one explicit atomic operation (no implicit
  executescript() commit boundary); only a genuinely new/zero-byte file is
  initialized;
- a non-zero database with application_id MFST and user_version=0 is REJECTED
  (no recovery path is specified yet; ADR-0012 accepts only user_version=1);
- one authoritative schema verifier checks tables, columns, constraints/
  indexes, triggers, metadata, application ID, and exact version;
- read-only SQLite URIs are built with correct path escaping (uri_quote)
  so spaces/Unicode/?/#/% cannot change the target; read-only opens never
  create any file (proven by tests);
- legacy detection requires the complete frozen v0.1.2 layout, not any()
  single directory;
- store-root (0700) and database (0600) modes are enforced or fail typed.

The transactional create/apply, idempotent replay, v0.1.2 migration, and
deterministic export are intentionally NOT implemented here.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from urllib.parse import quote

from .errors import (
    DatabaseEmptyError,
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    LegacyStoreDetectedError,
    SchemaViolationError,
    StorageError,
    UnsupportedSchemaError,
)
from .paths import DB_FILENAME, database_path, validate_store_root

# ── Physical database identity (ADR-0012 §D) ────────────────────────────
APPLICATION_ID = 0x4D465354  # "MFST" — canonical Method Factory application id
USER_VERSION = 1             # accepted schema version; >1 is unsupported
APPLICATION_ID_DECIMAL = int(APPLICATION_ID)  # for documentation/tests

# ── Binding first-release operating mode (ADR-0012 §3) ──────────────────
BINDING_PRAGMAS = {
    "journal_mode": "DELETE",
    "synchronous": "FULL",
    "busy_timeout": 5000,
    "foreign_keys": 1,
}

# ── Binding DDL (ADR-0012 §1, §E) ───────────────────────────────────────
STORE_METADATA_DDL = """
CREATE TABLE store_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""

EVENTS_DDL = """
CREATE TABLE events (
    package_id                  TEXT NOT NULL,
    revision                    INTEGER NOT NULL CHECK (revision >= 0),

    event_id                    TEXT NOT NULL UNIQUE,
    action_id                   TEXT NOT NULL,
    action                      TEXT NOT NULL,
    action_sha256               TEXT NOT NULL,

    state_before                TEXT,
    state_after                 TEXT NOT NULL,

    previous_manifest_sha256    TEXT,
    resulting_manifest_sha256   TEXT NOT NULL,

    created_at                  TEXT NOT NULL,

    action_json                 BLOB NOT NULL,
    manifest_json               BLOB NOT NULL,

    PRIMARY KEY (package_id, revision),
    UNIQUE (package_id, action_id)
) WITHOUT ROWID;
"""

APPEND_ONLY_TRIGGERS_DDL = [
    """
CREATE TRIGGER events_no_update
BEFORE UPDATE ON events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted');
END;
""",
    """
CREATE TRIGGER events_no_delete
BEFORE DELETE ON events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: DELETE not permitted');
END;
""",
]

SCHEMA_DDL = STORE_METADATA_DDL + EVENTS_DDL + "".join(APPEND_ONLY_TRIGGERS_DDL)

# Authoritative schema expectations (Finding 1 item 4).
REQUIRED_TABLES = {
    "store_metadata": {
        "columns": {"key", "value"},
        "without_rowid": True,
    },
    "events": {
        "columns": {
            "package_id", "revision", "event_id", "action_id", "action",
            "action_sha256", "state_before", "state_after",
            "previous_manifest_sha256", "resulting_manifest_sha256",
            "created_at", "action_json", "manifest_json",
        },
        "without_rowid": True,
        "primary_key": ("package_id", "revision"),
        "unique": {("package_id", "action_id"), ("event_id",)},
    },
}

REQUIRED_TRIGGERS = {"events_no_update", "events_no_delete"}

REQUIRED_METADATA = {"schema_version", "created_at"}

# Current-state lookup (indexed by the composite primary key).
LATEST_EVENT_SQL = """
SELECT manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision DESC
LIMIT 1;
"""

# Public v0.1.2 legacy layout directories (ADR-0012 §I). ALL must be present
# for a legacy store (Finding 1 item 6).
LEGACY_DIRS = ("packages", "events", "artifacts")


class StorePresence(str, Enum):
    NO_STORE = "no_store"
    LEGACY_ONLY = "legacy_only"
    SQLITE_ONLY = "sqlite_only"
    BOTH = "both"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_presence(root: Path | str) -> StorePresence:
    """Classify the store root by physical presence (ADR-0012 §D).

    A legacy store is detected only when the COMPLETE frozen v0.1.2 layout is
    present (packages/ AND events/ AND artifacts/), not any single directory
    (Finding 1 item 6).
    """
    r = validate_store_root(root)
    db = r / DB_FILENAME
    has_db = db.exists()
    legacy = all((r / d).is_dir() for d in LEGACY_DIRS)
    if has_db and legacy:
        return StorePresence.BOTH
    if has_db:
        return StorePresence.SQLITE_ONLY
    if legacy:
        return StorePresence.LEGACY_ONLY
    return StorePresence.NO_STORE


def _readonly_uri(db: Path) -> str:
    """Build a read-only SQLite URI that correctly escapes path-significant
    characters (spaces, Unicode, ?, #, %) — Finding 1 item 5."""
    # quote() with safe='' percent-encodes everything including ? # %;
    # sqlite3 URI parsing then unquotes the path component. The 'file:' scheme
    # requires an absolute path with forward slashes for the authority form.
    path_part = str(db.resolve())
    if os.sep == "\\":
        path_part = path_part.replace("\\", "/")
    return f"file:{quote(path_part, safe='/')}?mode=ro"


def _connect(db: Path, read_only: bool, timeout: float = 5.0) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(_readonly_uri(db), uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(str(db), timeout=timeout)
    conn.row_factory = sqlite3.Row
    _apply_or_verify_pragmas(conn, read_only=read_only)
    return conn


def _apply_or_verify_pragmas(conn: sqlite3.Connection, *, read_only: bool) -> None:
    """Apply (rw) or verify (ro) the binding first-release PRAGMAs.

    A required mode that cannot be established raises StorageError (typed),
    never silently proceeds. Read-only connections only verify: attempting to
    set a PRAGMA on a read-only connection would mutate or fail, so we read
    back and compare. busy_timeout/foreign_keys are per-connection; journal
    and synchronous are database-level and must match the binding values.
    """
    for pragma, expected in BINDING_PRAGMAS.items():
        if pragma == "journal_mode":
            if read_only:
                # Verify only: cannot set on ro; the binding value must already
                # hold (a WAL DB fails typed rather than being silently accepted).
                actual = conn.execute("PRAGMA journal_mode").fetchone()[0]
                if str(actual).lower() != "delete":
                    raise StorageError(
                        f"binding journal_mode=DELETE not established (got {actual!r})"
                    )
            else:
                # Actively establish DELETE (a previously-WAL DB must be reset).
                conn.execute("PRAGMA journal_mode = DELETE")
                actual = conn.execute("PRAGMA journal_mode").fetchone()[0]
                if str(actual).lower() != "delete":
                    raise StorageError(
                        f"binding journal_mode=DELETE not established (got {actual!r})"
                    )
            continue
        if pragma == "synchronous":
            if read_only:
                actual = conn.execute("PRAGMA synchronous").fetchone()[0]
                if int(actual) != 2:  # FULL == 2
                    raise StorageError(
                        f"binding synchronous=FULL not established (got {actual!r})"
                    )
            else:
                conn.execute("PRAGMA synchronous = FULL")
                actual = conn.execute("PRAGMA synchronous").fetchone()[0]
                if int(actual) != 2:
                    raise StorageError(
                        f"binding synchronous=FULL not established (got {actual!r})"
                    )
            continue
        if pragma == "busy_timeout":
            if read_only:
                actual = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                if int(actual) != 5000:
                    raise StorageError(
                        f"binding busy_timeout=5000 not established (got {actual!r})"
                    )
            else:
                conn.execute("PRAGMA busy_timeout = 5000")
                actual = conn.execute("PRAGMA busy_timeout").fetchone()[0]
                if int(actual) != 5000:
                    raise StorageError(
                        f"binding busy_timeout=5000 not established (got {actual!r})"
                    )
            continue
        if pragma == "foreign_keys":
            if read_only:
                # foreign_keys is per-connection and defaults OFF; a ro
                # connection cannot set it. It is not a database property, so
                # verification accepts the per-connection default (the binding
                # applies to rw connections which set it explicitly).
                pass
            else:
                conn.execute("PRAGMA foreign_keys = ON")
                actual = conn.execute("PRAGMA foreign_keys").fetchone()[0]
                if int(actual) != 1:
                    raise StorageError(
                        f"binding foreign_keys=ON not established (got {actual!r})"
                    )
            continue


def _identity(conn: sqlite3.Connection) -> tuple[int, int]:
    app_id = conn.execute("PRAGMA application_id").fetchone()[0]
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    return int(app_id), int(user_version)


def initialize_database(conn: sqlite3.Connection) -> None:
    """Initialize the schema and identity in ONE explicit atomic operation.

    Uses individual execute() calls inside an explicit transaction (no
    executescript(), which has an implicit commit boundary). Any failure
    rolls back so no partially initialized schema is accepted.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(STORE_METADATA_DDL)
        conn.execute(EVENTS_DDL)
        for trigger_ddl in APPEND_ONLY_TRIGGERS_DDL:
            conn.execute(trigger_ddl)
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {USER_VERSION}")
        conn.execute(
            "INSERT OR IGNORE INTO store_metadata (key, value) VALUES ('schema_version', ?)",
            (str(USER_VERSION),),
        )
        conn.execute(
            "INSERT OR IGNORE INTO store_metadata (key, value) VALUES ('created_at', ?)",
            (_utcnow(),),
        )
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def _verify_schema(conn: sqlite3.Connection) -> None:
    """Authoritative schema verifier (Finding 1 item 4).

    Checks required tables + columns, WITHOUT ROWID, primary key, unique
    constraints, append-only triggers, metadata, application ID, and exact
    user_version. Raises SchemaViolationError on any drift.
    """
    app_id, user_version = _identity(conn)
    if app_id != APPLICATION_ID:
        raise DatabaseIdMismatchError(
            f"database application_id {app_id}, expected {APPLICATION_ID}"
        )
    if user_version != USER_VERSION:
        raise UnsupportedSchemaError(
            f"database user_version {user_version}, supported {USER_VERSION}"
        )

    tables = {}
    for row in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'"
    ):
        tables[row["name"]] = row["sql"] or ""
    for tname, spec in REQUIRED_TABLES.items():
        if tname not in tables:
            raise SchemaViolationError(f"required table {tname!r} missing")
        # columns
        cols = {
            r["name"]
            for r in conn.execute(f"PRAGMA table_info({tname})")
        }
        missing_cols = spec["columns"] - cols
        if missing_cols:
            raise SchemaViolationError(
                f"table {tname!r} missing columns {sorted(missing_cols)}"
            )
        # WITHOUT ROWID
        if spec.get("without_rowid") and "WITHOUT ROWID" not in tables[tname].upper():
            raise SchemaViolationError(f"table {tname!r} is not WITHOUT ROWID")

    # primary key + unique constraints (via PRAGMA index_list / table_info)
    for tname, spec in REQUIRED_TABLES.items():
        pk = spec.get("primary_key")
        if pk is not None:
            pk_cols = [
                r["name"]
                for r in conn.execute(f"PRAGMA table_info({tname})")
                if r["pk"] > 0
            ]
            if tuple(pk_cols) != pk:
                raise SchemaViolationError(
                    f"table {tname!r} primary key {tuple(pk_cols)!r} != expected {pk!r}"
                )
        for uniq in spec.get("unique", ()):
            indexes = conn.execute(f"PRAGMA index_list({tname})").fetchall()
            found = False
            for idx in indexes:
                if idx["unique"] != 1:
                    continue
                idx_cols = tuple(
                    r["name"]
                    for r in conn.execute(f"PRAGMA index_info({idx['name']})")
                )
                # SQLite stores UNIQUE column constraints as autoindexes;
                # compare as sets for single-col event_id, exact for composite.
                if uniq == ("event_id",):
                    if idx_cols == uniq or idx_cols == ("event_id",):
                        found = True
                elif set(idx_cols) == set(uniq):
                    found = True
            if not found:
                raise SchemaViolationError(
                    f"table {tname!r} missing unique constraint {uniq!r}"
                )

    triggers = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    missing_triggers = REQUIRED_TRIGGERS - triggers
    if missing_triggers:
        raise SchemaViolationError(
            f"missing append-only triggers {sorted(missing_triggers)}"
        )

    meta = {
        r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM store_metadata"
        )
    }
    missing_meta = REQUIRED_METADATA - set(meta)
    if missing_meta:
        raise SchemaViolationError(f"missing metadata keys {sorted(missing_meta)}")
    if meta.get("schema_version") != str(USER_VERSION):
        raise SchemaViolationError(
            f"store_metadata schema_version {meta.get('schema_version')!r} != {USER_VERSION}"
        )


def _enforce_modes(root: Path, db: Path) -> None:
    """Enforce store-root 0700 and database 0600, or fail typed.

    chmod failures are NOT silently ignored (Finding 1 item 7): a mode that
    cannot be established raises StorageError rather than claiming success.
    """
    try:
        os.chmod(root, 0o700)
    except OSError as exc:
        raise StorageError(f"cannot set store root mode 0700: {exc}") from exc
    if db.exists():
        try:
            os.chmod(db, 0o600)
        except OSError as exc:
            raise StorageError(f"cannot set database mode 0600: {exc}") from exc


def open_database(root: Path | str, read_only: bool = False) -> sqlite3.Connection:
    """Open (and, on the read-write path, create/initialize) the canonical DB.

    Contract (ADR-0012 §D, Finding 1):
    - read-write + NO_STORE: create parent (0700), create DB (0600), initialize
      atomically, verify schema, enforce modes.
    - read-write + LEGACY_ONLY: LegacyStoreDetectedError (no silent migration).
    - read-write + SQLITE_ONLY/BOTH: open, enforce modes, verify identity +
      schema; zero-byte initializes (genuinely new file).
    - read-only: never creates; NO_STORE -> DatabaseNotFoundError; LEGACY_ONLY
      -> LegacyStoreDetectedError; zero-byte -> DatabaseEmptyError; verify
      PRAGMAs + identity + schema without mutation.
    """
    r = validate_store_root(root)
    db = r / DB_FILENAME
    presence = detect_presence(r)

    if read_only:
        if presence == StorePresence.LEGACY_ONLY:
            raise LegacyStoreDetectedError(
                "v0.1.2 JSONL store detected; run `mf migrate-store`",
            )
        if presence == StorePresence.NO_STORE:
            raise DatabaseNotFoundError(f"no database at {db}")
        try:
            conn = _connect(db, read_only=True)
        except sqlite3.OperationalError as exc:
            raise DatabaseNotFoundError(f"cannot open {db} read-only: {exc}") from exc
        if db.stat().st_size == 0:
            conn.close()
            raise DatabaseEmptyError(f"database {db} is zero bytes")
        _verify_schema(conn)
        return conn

    # read-write path
    if presence == StorePresence.LEGACY_ONLY:
        raise LegacyStoreDetectedError(
            "v0.1.2 JSONL store detected; run `mf migrate-store`",
        )
    if presence == StorePresence.NO_STORE:
        r.mkdir(parents=True, exist_ok=True)
        conn = _connect(db, read_only=False)
        initialize_database(conn)
        try:
            os.chmod(db, 0o600)
        except OSError as exc:
            conn.close()
            raise StorageError(f"cannot set database mode 0600: {exc}") from exc
        _enforce_modes(r, db)
        _verify_schema(conn)
        return conn

    # SQLITE_ONLY or BOTH: SQLite canonical, legacy preserved (ADR-0012 §D).
    conn = _connect(db, read_only=False)
    if db.stat().st_size == 0:
        # Genuinely new/empty file: initialize atomically.
        initialize_database(conn)
        _enforce_modes(r, db)
        _verify_schema(conn)
        return conn
    _enforce_modes(r, db)
    _verify_schema(conn)
    return conn


def latest_event(conn: sqlite3.Connection, package_id: str) -> dict | None:
    """Return the latest manifest for a package (indexed latest-event read)."""
    row = conn.execute(LATEST_EVENT_SQL, (package_id,)).fetchone()
    if row is None:
        return None
    import json

    return json.loads(row["manifest_json"])


def explain_latest_event_plan(conn: sqlite3.Connection, package_id: str) -> list[tuple]:
    """EXPLAIN QUERY PLAN for the latest-event lookup (ADR-0012 §9 item 14)."""
    rows = conn.execute(
        f"EXPLAIN QUERY PLAN {LATEST_EVENT_SQL}", (package_id,)
    ).fetchall()
    return [tuple(r) for r in rows]


def close_database(conn: sqlite3.Connection) -> None:
    conn.close()
