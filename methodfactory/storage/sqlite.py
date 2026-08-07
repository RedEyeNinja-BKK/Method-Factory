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

# Authoritative schema expectations (Finding 1 item 4; Finding 3 exact column
# contract). Columns are ORDERED (name, decltype, notnull, default).
REQUIRED_TABLES = {
    "store_metadata": {
        "columns": [
            ("key", "TEXT", 1, None),
            ("value", "TEXT", 1, None),
        ],
        "without_rowid": True,
    },
    "events": {
        "columns": [
            ("package_id", "TEXT", 1, None),
            ("revision", "INTEGER", 1, None),
            ("event_id", "TEXT", 1, None),
            ("action_id", "TEXT", 1, None),
            ("action", "TEXT", 1, None),
            ("action_sha256", "TEXT", 1, None),
            ("state_before", "TEXT", 0, None),
            ("state_after", "TEXT", 1, None),
            ("previous_manifest_sha256", "TEXT", 0, None),
            ("resulting_manifest_sha256", "TEXT", 1, None),
            ("created_at", "TEXT", 1, None),
            ("action_json", "BLOB", 1, None),
            ("manifest_json", "BLOB", 1, None),
        ],
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
                # foreign_keys is connection-local and CAN be enabled on a
                # read-only connection (Finding 3). Enable + read back.
                conn.execute("PRAGMA foreign_keys = ON")
                actual = conn.execute("PRAGMA foreign_keys").fetchone()[0]
                if int(actual) != 1:
                    raise StorageError(
                        f"binding foreign_keys=ON not established (got {actual!r})"
                    )
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
        # columns (name-level early check; exact contract below)
        expected_names = {c[0] for c in spec["columns"]}
        cols = {
            r["name"]
            for r in conn.execute(f"PRAGMA table_info({tname})")
        }
        missing_cols = expected_names - cols
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

    # ── Exact column contract (Finding 3) ──────────────────────────────
    # Verify, per table, the EXACT ordered column list with declared type,
    # nullability, and default (None where none). This catches changed
    # type/nullability and column-order drift that name-only checks miss.
    for tname, spec in REQUIRED_TABLES.items():
        cols = conn.execute(f"PRAGMA table_info({tname})").fetchall()
        expected = spec["columns"]  # list of (name, decltype, notnull, default)
        if len(cols) != len(expected):
            raise SchemaViolationError(
                f"table {tname!r} has {len(cols)} columns, expected {len(expected)}"
            )
        for actual, (name, decltype, notnull, default) in zip(cols, expected):
            if actual["name"] != name:
                raise SchemaViolationError(
                    f"table {tname!r} column {actual['name']!r} at wrong position (expected {name!r})"
                )
            # Normalize declared types: upper-case, strip whitespace/parens
            # (e.g. "TEXT", "INTEGER", "BLOB").
            norm = (actual["type"] or "").strip().upper().split("(")[0].strip()
            if norm != decltype.upper():
                raise SchemaViolationError(
                    f"table {tname!r}.{name} type {norm!r} != expected {decltype.upper()!r}"
                )
            if bool(actual["notnull"]) != notnull:
                raise SchemaViolationError(
                    f"table {tname!r}.{name} notnull {actual['notnull']} != expected {notnull}"
                )
            if actual["dflt_value"] != default:
                raise SchemaViolationError(
                    f"table {tname!r}.{name} default {actual['dflt_value']!r} != expected {default!r}"
                )

    # ── CHECK constraint (Finding 3) ───────────────────────────────────
    # revision >= 0 must be present on events. Parse the CREATE TABLE SQL for
    # the CHECK constraint (normalized: strip whitespace / case-insensitive).
    events_sql = tables["events"].upper().replace(" ", "")
    if "CHECK(REVISION>=0)" not in events_sql:
        raise SchemaViolationError("events table missing CHECK (revision >= 0)")

    triggers = {
        r["name"]: (r["sql"] or "")
        for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
    }
    missing_triggers = REQUIRED_TRIGGERS - set(triggers)
    if missing_triggers:
        raise SchemaViolationError(
            f"missing append-only triggers {sorted(missing_triggers)}"
        )

    # ── Trigger body verification (Finding 3) ──────────────────────────
    # Exact or equivalently normalized trigger definitions. A no-op trigger
    # (e.g. bodies that no longer RAISE ABORT) must fail. We normalize by
    # removing whitespace and lowercasing, then require the RAISE(ABORT,
    # 'events are append-only: ...') marker in both triggers.
    for tname in REQUIRED_TRIGGERS:
        body = triggers[tname]
        if "RAISE(ABORT" not in body.upper().replace(" ", ""):
            raise SchemaViolationError(
                f"trigger {tname!r} does not RAISE(ABORT) (no-op or weakened)"
            )
        if "APPEND-ONLY" not in body.upper().replace(" ", "").replace("_", "-"):
            raise SchemaViolationError(
                f"trigger {tname!r} message is not the append-only marker"
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


def _verify_readonly_modes(root: Path, db: Path) -> None:
    """Verify store-root 0700 and database 0600 WITHOUT mutating them (Finding
    3). A permissive mode on a read-only open is a typed failure."""
    try:
        root_mode = os.stat(root).st_mode & 0o777
        db_mode = os.stat(db).st_mode & 0o777
    except OSError as exc:
        raise StorageError(f"cannot stat store modes: {exc}") from exc
    if root_mode != 0o700:
        raise StorageError(f"store root mode is {oct(root_mode)}, expected 0700")
    if db_mode != 0o600:
        raise StorageError(f"database mode is {oct(db_mode)}, expected 0600")


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

    Raw sqlite3 exceptions are translated into typed StorageError at this
    public boundary (Finding 2 item 4) so no sqlite3/OS/type error escapes.
    """
    r = validate_store_root(root)
    db = r / DB_FILENAME
    presence = detect_presence(r)

    try:
        return _open_database_impl(root, db, presence, read_only)
    except StorageError:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        from .errors import StorageError as _SE
        raise _SE(f"storage open failed for {db}: {exc}") from exc


def _open_database_impl(
    root: Path,
    db: Path,
    presence: "StorePresence",
    read_only: bool,
) -> sqlite3.Connection:
    if read_only:
        if presence == StorePresence.LEGACY_ONLY:
            raise LegacyStoreDetectedError(
                "v0.1.2 JSONL store detected; run `mf migrate-store`",
            )
        if presence == StorePresence.NO_STORE:
            raise DatabaseNotFoundError(f"no database at {db}")
        conn = _connect(db, read_only=True)
        try:
            if db.stat().st_size == 0:
                raise DatabaseEmptyError(f"database {db} is zero bytes")
            # Verify required filesystem modes WITHOUT mutating them (Finding 3).
            _verify_readonly_modes(root, db)
            _verify_schema(conn)
        except BaseException:
            close_database(conn)
            raise
        return conn

    # read-write path
    if presence == StorePresence.LEGACY_ONLY:
        raise LegacyStoreDetectedError(
            "v0.1.2 JSONL store detected; run `mf migrate-store`",
        )
    if presence == StorePresence.NO_STORE:
        root.mkdir(parents=True, exist_ok=True)
        conn = _connect(db, read_only=False)
        try:
            initialize_database(conn)
            _enforce_modes(root, db)
            _verify_schema(conn)
        except BaseException:
            close_database(conn)
            raise
        return conn

    # SQLITE_ONLY or BOTH: SQLite canonical, legacy preserved (ADR-0012 §D).
    conn = _connect(db, read_only=False)
    try:
        if db.stat().st_size == 0:
            # Genuinely new/empty file: initialize atomically.
            initialize_database(conn)
            _enforce_modes(root, db)
            _verify_schema(conn)
            return conn
        _enforce_modes(root, db)
        _verify_schema(conn)
    except BaseException:
        close_database(conn)
        raise
    return conn


def latest_event(conn: sqlite3.Connection, package_id: str) -> dict | None:
    """Return the latest manifest for a package (indexed latest-event read).

    Public boundary (Finding 4): a malformed/invalid-UTF-8 manifest_json BLOB
    surfaces as a typed StorageError (code MANIFEST_INVALID), never a raw
    json/Unicode/type exception.
    """
    try:
        row = conn.execute(LATEST_EVENT_SQL, (package_id,)).fetchone()
    except sqlite3.Error as exc:
        raise StorageError(f"latest_event query failed: {exc}") from exc
    if row is None:
        return None
    import json

    raw = row["manifest_json"]
    try:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        from .errors import ManifestInvalidError as _MIV

        raise _MIV(f"manifest_json corrupt for {package_id}: {exc}") from exc


def explain_latest_event_plan(conn: sqlite3.Connection, package_id: str) -> list[tuple]:
    """EXPLAIN QUERY PLAN for the latest-event lookup (ADR-0012 §9 item 14)."""
    rows = conn.execute(
        f"EXPLAIN QUERY PLAN {LATEST_EVENT_SQL}", (package_id,)
    ).fetchall()
    return [tuple(r) for r in rows]


def close_database(conn: sqlite3.Connection) -> None:
    conn.close()
