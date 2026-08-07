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
| `SqliteManifestStore(root, *, artifact_store=None)` | `str`/`Path` root, optional `ArtifactStore` | store object | `InvalidStoreRootError` (`INVALID_STORE_ROOT`), `StorageError` (`STORAGE_ERROR`) | `TypeError`/`ValueError` (root), `OSError`, `sqlite3.Error` |
| `SqliteManifestStore.create(package_id, intent_raw, created_at=None)` | str + str + optional str | complete revision-0 manifest `dict` | `DuplicatePackageError` (`PACKAGE_EXISTS`, non-replay duplicate), `InvalidPayloadError` (`INVALID_PAYLOAD`), `InvalidPackageIdError` (`INVALID_PACKAGE_ID`), `ManifestInvalidError` (`MANIFEST_INVALID`), `ConcurrencyError` (`CONCURRENCY`), `StorageError` (`STORAGE_ERROR`) | `TypeError`/`ValueError`/`UnicodeError`/`RecursionError`, `OSError`, `sqlite3.Error` (incl. locked -> `CONCURRENCY`) |

> **Create identity (senior review 4882624484, A1):** `created_at` is SEMANTIC.
> It is normalized to UTC ISO-8601 (naive/offset-less timestamps rejected) and
> included in the canonical `create_package` action payload, so it is part of
> `action_sha256`. Exact replay requires the same normalized instant; a repeat
> with an explicitly DIFFERENT instant is `PACKAGE_EXISTS`; a retry that omits
> `created_at` replays using the stored creation time. This is a deliberate
> pre-release breaking change to the SQLite store format (revision-0
> `action_json` payload now carries `created_at`); no released stores exist
> (PR #1 Draft, v2.0.0a1), so no migration is required — any pre-A1 test store
> must be recreated. The authoritative chain validator binds
> `payload.created_at` to the indexed row `created_at`.
| `SqliteManifestStore.apply(envelope)` | `dict` (parsed Action Envelope) | complete resulting manifest `dict` | `InvalidEnvelopeError` (`INVALID_ENVELOPE`), `InvalidPayloadError` (`INVALID_PAYLOAD`), `PackageNotFoundError` (`PACKAGE_NOT_FOUND`), `StaleActionError` (`STALE_ACTION`), `IllegalTransitionError` (`ILLEGAL_TRANSITION`), `GateUnsatisfiedError` (`GATE_UNSATISFIED`), `ActionIdConflictError` (`ACTION_ID_CONFLICT`), `SerializationError` (`SERIALIZATION`), `ArtifactVerificationError` (`ARTIFACT_VERIFICATION`), `ManifestInvalidError` (`MANIFEST_INVALID`), `ConcurrencyError` (`CONCURRENCY`), `StorageError` (`STORAGE_ERROR`) | `TypeError`/`ValueError`/`UnicodeError`/`RecursionError`, `OSError`, `sqlite3.Error` (incl. locked -> `CONCURRENCY`) |
| `SqliteManifestStore.load(package_id)` | str | complete current manifest `dict` | `PackageNotFoundError` (`PACKAGE_NOT_FOUND`), `ManifestInvalidError` (`MANIFEST_INVALID`), `StorageError` (`STORAGE_ERROR`) | `TypeError`/`ValueError`/`UnicodeError`/`RecursionError`, `sqlite3.Error` |
| `SqliteManifestStore.read_events(package_id)` | str | ordered `list[dict]` (decoded action/manifest) | `ManifestInvalidError` (`MANIFEST_INVALID`), `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error`, decode/JSON errors |
| `SqliteManifestStore.validate_chain(package_id, *, verify_artifacts=False)` | str + bool | `{package_id, events, valid}` | `ChainViolationError` (`CHAIN_VIOLATION`), `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error`, decode/JSON errors |
| `SqliteManifestStore.explain_latest_plan(package_id)` | str | `list[tuple]` (query plan) | `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error` |
| `SqliteManifestStore.close()` | — | `None` | `StorageError` (`STORAGE_ERROR`) | `sqlite3.Error` |

## Internal primitives (documented native contract, NOT public)

| Primitive | Native contract |
|---|---|
| `storage.serialization.canonical_json` / `canonical_bytes` | Raise `TypeError` (unsupported types), `ValueError` (NaN/Infinity), `RecursionError` (deep nesting); `canonical_bytes` additionally `UnicodeEncodeError` (lone surrogate) |
| `storage.serialization.canonical_bytes_bounded` | As above plus `ValueError` when canonical bytes exceed the bound |
| `storage.serialization.try_canonical_bytes_bounded` | Returns `(bytes, None)` or `(None, error_str)` — never raises |
| `storage.serialization.digest_*` | SHA-256 helpers; native contract inherited from `canonical_bytes`/encoding |
| `storage.sqlite._connect` / `_apply_or_verify_pragmas` / `_identity` / `_verify_schema` / `initialize_database` / `detect_presence` / `_open_database_impl` | Internal to `open_database`; sqlite3 errors may surface if called directly. `_connect` closes its connection on PRAGMA failure. |
| `storage.store._begin` / `_insert_event` / `_commit` / `_rollback` / `FAULT_HOOK` | Transaction seams for fault injection; internal. `FAULT_HOOK` is a test-only injection point (`stage`-keyed) |

## Transaction algorithm (SqliteManifestStore.apply)

One bounded `BEGIN IMMEDIATE` transaction:

1. Validate the incoming Action Envelope (`envelope_from_dict`) and compute the canonical semantic action bytes once (`canonical_action_bytes`).
2. Compute `action_sha256` = hash of those exact bytes.
3. Look up `(package_id, action_id)` BEFORE stale-revision rejection.
4. If the action ID exists: same hash → return the previously committed result (no insert); different hash → `ACTION_ID_CONFLICT`.
5. Load the indexed latest event (primary-key lookup, never a history scan).
6. Compare `expected_revision` to the authoritative current revision → `STALE_ACTION` on mismatch.
7. Apply the deterministic transition (engine.next_manifest: legality → gate → mutation → revision/lineage).
8. Produce the complete resulting manifest.
9. Validate the manifest and chain invariants (single kernel).
10. Write and verify every newly referenced artifact blob (immutable, content-addressed).
11. Canonicalize stored action + manifest once.
12. Insert exactly one immutable event row.
13. `COMMIT`.

On any pre-commit failure: rollback, no event inserted, no historical row
mutated, prewritten content-addressed blobs are NOT deleted.

## Consistency rule

Validation failure handling is deliberate and split by surface:

- `validate_manifest()` **collects** violations into a `list[str]` (read-only
  validator; caller-friendly).
- `parse_envelope()` / `envelope_from_dict()` / `action_sha256()` /
  `ArtifactStore` / storage helpers **raise** typed errors (first failure
  aborts the operation).

Both surfaces are stable; neither leaks raw native exceptions.

## Accepted residuals (closure A, senior review 4882624484)

Recorded here so the acceptance is repository-durable (verified by the
code-review verify lane on 2026-08-07; each is genuine in the code):

1. **Action payload → manifest consequence cross-binding (A3)**: for
   revisions > 0 the semantic-action binding anchors the frozen field set,
   `protocol_version`, `package_id`, `action_id`, `action`, and basis/payload
   object types, but NOT payload content against manifest consequence digests
   (e.g. `record_input` content vs `inputs[].content_sha256`). A store-writer
   who recomputes `action_sha256` could rewrite action payload content and
   still pass `validate_chain`; the manifest's own digests are independently
   verified against the blob store. Not in the reviewer's explicit A3
   "at minimum" list; recommended for the next invariant slice.

   > **CLOSED by the invariant closure (senior review 4885538290, Lane 1).**
   > `validate_chain` now reconstructs the normal internal ActionEnvelope
   > from the stored canonical `action_json` and replays the SINGLE
   > deterministic transition engine (`engine.apply.next_manifest`) over the
   > predecessor manifest with the indexed `event_id` and row `created_at`;
   > canonical equality with the stored resulting manifest proves every
   > consequence-bearing field (input digest/size/path, objective,
   > summary digest/size/preview/presented_at/confirmation incl.
   > confirmed_at/operator_id/confirmed digest, artifact digest/byte_count/
   > path, state/revision/lineage, updated_at) with one rule — no per-action
   > consequence validators. Adversarial tests recompute all immediate
   > hashes so only the replay invariant can fail.

2. **Manifest created_at/updated_at ↔ row binding**: `_bind_manifest_fields`
   binds package_id/revision/state and rev>0 lineage, but not the manifest's
   own `created_at`/`updated_at` to row timestamps (correct binding for
   `created_at` requires threading the revision-0 row timestamp through the
   kernel walk). Residual; recommended with the above.

   > **CLOSED by the invariant closure (senior review 4885538290, Lane 1).**
   > Revision 0: `created_at == updated_at == row created_at == action
   > payload.created_at`. Revision > 0: `updated_at == row created_at` and
   > `created_at == revision-0 row created_at` (threaded through the walk).
   > Action-specific timestamps (`presented_at`, `confirmed_at`) are derived
   > from the event timestamp by the transition and proven by replay — not
   > bound indiscriminately.

3. **`validate_chain` double canonicalization (audit path)**: with
   `check_schema=True`, each event's manifest is canonicalized once by the A2
   decode and again inside the schema validator. Bounded to the explicit audit
   path (not load/apply); the perf-1 single-pass fix covered
   `check_current_row_consistency` only. **Retained as an accepted
   performance residual** (senior review 4885538290 §8: the audit-path double
   canonicalization may remain unless measurements show a meaningful problem).

4. **Test tamper-pattern duplication (nit)**: `test_transactional_store.py`
   and `test_chain_validator.py` each carry an inline drop-triggers/UPDATE
   tamper pattern rather than a shared helper; cosmetic. **Retained** (the
   replay module keeps a self-contained local helper).
