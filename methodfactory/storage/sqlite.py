"""SQLite schema creation, identity checks, and append-only guards.

Phase 2 (ADR-0012 commits 2–4 scope; §1 schema, §3 operating mode, §D physical
database identity, §E append-only). Implements only:

- database creation/opening;
- canonical filename/location;
- parent mode 0700, database mode 0600;
- fixed application_id and user_version=1;
- journal_mode=DELETE, synchronous=FULL, busy_timeout, foreign_keys;
- binding store_metadata + events DDL with append-only triggers;
- database-state detection (missing, zero-byte, wrong-ID, future-version,
  corrupt, legacy-only, sqlite-only, neither, both);
- read-only URI opening with no accidental creation;
- schema initialization transaction;
- latest-event query + EXPLAIN QUERY PLAN helper.

The transactional create/apply, idempotent replay, v0.1.2 migration, and
deterministic export are intentionally NOT implemented here (later Phase 2
commits).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .errors import (
    DatabaseEmptyError,
    DatabaseIdMismatchError,
    DatabaseNotFoundError,
    LegacyStoreDetectedError,
    StorageError,
    UnsupportedSchemaError,
)
from .paths import DB_FILENAME, database_path, validate_store_root

# ── Physical database identity (ADR-0012 §D) ────────────────────────────
APPLICATION_ID = 0x4D465354  # "MFST" — canonical Method Factory application id
USER_VERSION = 1             # accepted schema version; >1 is unsupported
APPLICATION_ID_DECIMAL = int(APPLICATION_ID)  # for documentation/tests

# ── Binding DDL (ADR-0012 §1, §E) ───────────────────────────────────────
STORE_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS store_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;
"""

EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
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

APPEND_ONLY_TRIGGERS_DDL = """
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: UPDATE not permitted');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: DELETE not permitted');
END;
"""

SCHEMA_DDL = STORE_METADATA_DDL + EVENTS_DDL + APPEND_ONLY_TRIGGERS_DDL

# Current-state lookup (indexed by the composite primary key).
LATEST_EVENT_SQL = """
SELECT manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision DESC
LIMIT 1;
"""

# Public v0.1.2 legacy layout directories (ADR-0012 §I).
LEGACY_DIRS = ("packages", "events", "artifacts")


class StorePresence(str, Enum):
    NO_STORE = "no_store"
    LEGACY_ONLY = "legacy_only"
    SQLITE_ONLY = "sqlite_only"
    BOTH = "both"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def detect_presence(root: Path | str) -> StorePresence:
    """Classify the store root by physical presence (ADR-0012 §D)."""
    r = validate_store_root(root)
    db = r / DB_FILENAME
    has_db = db.exists()
    legacy = any((r / d).exists() for d in LEGACY_DIRS)
    if has_db and legacy:
        return StorePresence.BOTH
    if has_db:
        return StorePresence.SQLITE_ONLY
    if legacy:
        return StorePresence.LEGACY_ONLY
    return StorePresence.NO_STORE


def _connect(db: Path, read_only: bool, timeout: float = 5.0) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=timeout)
    else:
        conn = sqlite3.connect(str(db), timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _identity(conn: sqlite3.Connection) -> tuple[int, int]:
    app_id = conn.execute("PRAGMA application_id").fetchone()[0]
    user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    return int(app_id), int(user_version)


def initialize_database(conn: sqlite3.Connection) -> None:
    """Initialize the schema and identity in one transaction (idempotent)."""
    with conn:  # implicit BEGIN ... COMMIT / ROLLBACK
        conn.executescript(SCHEMA_DDL)
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


def open_database(root: Path | str, read_only: bool = False) -> sqlite3.Connection:
    """Open (and, on the read-write path, create/initialize) the canonical DB.

    Contract (ADR-0012 §D):

    - read-write + NO_STORE: create parent (0700), create DB (0600), initialize.
    - read-write + LEGACY_ONLY: raise LegacyStoreDetectedError (never migrate
      silently; instruct `mf migrate-store`).
    - read-write + SQLITE_ONLY/BOTH: open, verify identity; zero-byte initializes;
      wrong application_id -> DatabaseIdMismatchError; user_version > 1 ->
      UnsupportedSchemaError.
    - read-only: never creates; NO_STORE -> DatabaseNotFoundError; LEGACY_ONLY
      -> LegacyStoreDetectedError; zero-byte -> DatabaseEmptyError; identity
      checks as above.
    """
    r = validate_store_root(root)
    db = r / DB_FILENAME
    presence = detect_presence(r)

    if read_only:
        if presence == StorePresence.LEGACY_ONLY:
            raise LegacyStoreDetectedError(
                "v0.1.2 JSONL store detected; run `mf migrate-store`",
            )
        if presence in (StorePresence.NO_STORE,):
            raise DatabaseNotFoundError(
                f"no database at {db}",
            )
        try:
            conn = _connect(db, read_only=True)
        except sqlite3.OperationalError as exc:
            raise DatabaseNotFoundError(f"cannot open {db} read-only: {exc}") from exc
        _verify_identity(conn, db, allow_zero_byte=False)
        return conn

    # read-write path
    if presence == StorePresence.LEGACY_ONLY:
        raise LegacyStoreDetectedError(
            "v0.1.2 JSONL store detected; run `mf migrate-store`",
        )
    if presence in (StorePresence.NO_STORE,):
        r.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(r, 0o700)
        except OSError:
            pass
        conn = _connect(db, read_only=False)
        initialize_database(conn)
        try:
            os.chmod(db, 0o600)
        except OSError:
            pass
        return conn

    # SQLITE_ONLY or BOTH: SQLite is canonical and used (ADR-0012 §D).
    conn = _connect(db, read_only=False)
    _verify_identity(conn, db, allow_zero_byte=True)
    return conn


def _verify_identity(conn: sqlite3.Connection, db: Path, allow_zero_byte: bool) -> None:
    size = db.stat().st_size if db.exists() else 0
    if size == 0:
        if allow_zero_byte:
            initialize_database(conn)
            try:
                os.chmod(db, 0o600)
            except OSError:
                pass
            return
        conn.close()
        raise DatabaseEmptyError(f"database {db} is zero bytes")

    app_id, user_version = _identity(conn)
    if app_id != APPLICATION_ID:
        conn.close()
        raise DatabaseIdMismatchError(
            f"database {db} has application_id {app_id}, expected {APPLICATION_ID}",
        )
    if user_version > USER_VERSION:
        conn.close()
        raise UnsupportedSchemaError(
            f"database {db} has user_version {user_version}, supported <= {USER_VERSION}",
        )
    if user_version == 0:
        # Partially initialized (identity set but version not): initialize.
        initialize_database(conn)
        return


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
