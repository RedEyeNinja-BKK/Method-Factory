# Public Surface and Stable Error Contract

Phase 2 foundation closure (review 4879440857, Finding 4). This table is the
authoritative public error boundary for the currently supported package and
storage APIs.

**Boundary rule:** every supported public operation surfaces **only**
`methodfactory.domain.errors.MethodFactoryError` subclasses (stable
machine-readable `code` per ADR-0008 / ADR-0012 §B). Raw
JSON/Unicode/recursion/type/sqlite3/OS exceptions are translated at the
public boundary. Internal primitives are documented below with their native
exception contract and are not part of the supported surface.

## Supported public surface

| Operation | Accepted inputs | Success result | Stable errors (code) | Native exceptions translated |
|---|---|---|---|---|
| `parse_envelope(raw)` | `str` (raw envelope, optional prose) | `ActionEnvelope` | `InvalidEnvelopeError` (`INVALID_ENVELOPE`) | `UnicodeEncodeError` (lone surrogate), `json.JSONDecodeError`, `RecursionError`, `TypeError` (non-string) |
| `envelope_from_dict(d)` | `dict` | `ActionEnvelope` | `InvalidEnvelopeError` (`INVALID_ENVELOPE`) | `TypeError` (non-dict), plus every envelope field failure |
| `validate_manifest(manifest)` | `dict` | `list[str]` of violations (`[]` = valid) | none raised; failures collected | `TypeError`, `RecursionError`, `UnicodeEncodeError`, `ValueError` (canonicalization -> collected error) |
| `action_sha256(**semantic)` | str/str/str/str + `dict` basis + `dict` payload | `str` (64-hex digest) | `SerializationError` (`SERIALIZATION`) | `TypeError`, `RecursionError`, `UnicodeEncodeError`, `ValueError` (over `MAX_ACTION_JSON_BYTES`) |
| `ArtifactStore(root)` | `str`/`os.PathLike` root | store object | `InvalidPayloadError` (`INVALID_PAYLOAD`), `InvalidStoreRootError` via path helpers | `TypeError`/`ValueError` (root type), `OSError` (mkdir) |
| `ArtifactStore.put(package_id, logical_path, content)` | str/str/str | `(digest: str, size_bytes: int)` | `InvalidPayloadError` (`INVALID_PAYLOAD`), `InvalidPackageIdError` (`INVALID_PACKAGE_ID`) | `UnicodeEncodeError` (lone surrogate), `OSError` (open/write/fsync/link/unlink/dir-fsync/close) |
| `ArtifactStore.get(digest)` | str (64-hex) | `str` (decoded UTF-8) | `InvalidPayloadError` (`INVALID_PAYLOAD`) | `OSError` (read), `UnicodeDecodeError`, `ValueError` (bad digest) |
| `ArtifactStore.artifact_bytes(digest)` | str (64-hex) | `bytes` | `InvalidPayloadError` (`INVALID_PAYLOAD`) | `OSError` (read), `ValueError` (bad digest) |
| `ArtifactStore.verify(digest)` | str (64-hex) | `bool` (never raises) | — | all failures collapse to `False` |
| `open_database(root, read_only=False)` | `str`/`Path` root + bool | `sqlite3.Connection` (via `close_database`) | `DatabaseNotFoundError` (`DATABASE_NOT_FOUND`), `DatabaseEmptyError` (`DATABASE_EMPTY`), `DatabaseIdMismatchError` (`DATABASE_ID_MISMATCH`), `UnsupportedSchemaError` (`UNSUPPORTED_SCHEMA`), `LegacyStoreDetectedError` (`LEGACY_STORE_DETECTED`), `SchemaViolationError` (`SCHEMA_VIOLATION`), `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error`, `OSError`, `ValueError`, `TypeError` -> `StorageError`; invalid root -> `InvalidStoreRootError` (`INVALID_STORE_ROOT`) |
| `latest_event(conn, package_id)` | `sqlite3.Connection` (from `open_database`) + str | `dict | None` | `ManifestInvalidError` (`MANIFEST_INVALID`), `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error` (query), `UnicodeDecodeError`/`UnicodeEncodeError`, `json.JSONDecodeError`, `TypeError`, `ValueError`, `RecursionError`, non-bytes/str stored type, non-object JSON |
| `explain_latest_event_plan(conn, package_id)` | `sqlite3.Connection` + str | `list[tuple]` | `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error` |
| `close_database(conn)` | `sqlite3.Connection` | `None` | `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error` |

## Internal primitives (documented native contract, NOT public)

| Primitive | Native contract |
|---|---|
| `storage.serialization.canonical_json` / `canonical_bytes` | Raise `TypeError` (unsupported types), `ValueError` (NaN/Infinity), `RecursionError` (deep nesting); `canonical_bytes` additionally `UnicodeEncodeError` (lone surrogate) |
| `storage.serialization.canonical_bytes_bounded` | As above plus `ValueError` when canonical bytes exceed the bound |
| `storage.serialization.try_canonical_bytes_bounded` | Returns `(bytes, None)` or `(None, error_str)` — never raises |
| `storage.serialization.digest_*` | SHA-256 helpers; native contract inherited from `canonical_bytes`/encoding |
| `storage.sqlite._connect` / `_apply_or_verify_pragmas` / `_identity` / `_verify_schema` / `initialize_database` / `detect_presence` / `_open_database_impl` | Internal to `open_database`; sqlite3 errors may surface if called directly. `_connect` closes its connection on PRAGMA failure. |

## Consistency rule

Validation failure handling is deliberate and split by surface:

- `validate_manifest()` **collects** violations into a `list[str]` (read-only
  validator; caller-friendly).
- `parse_envelope()` / `envelope_from_dict()` / `action_sha256()` /
  `ArtifactStore` / storage helpers **raise** typed errors (first failure
  aborts the operation).

Both surfaces are stable; neither leaks raw native exceptions.
