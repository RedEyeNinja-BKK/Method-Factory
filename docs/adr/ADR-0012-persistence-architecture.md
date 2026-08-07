# ADR-0012 — Persistence architecture reset: SQLite canonical store

**Status:** Accepted in principle (2026-08-07 senior-review direction; operator-authorized controlled publication). Implementation pending ADR review from the pushed branch.
**Supersedes:** the JSONL journal-first canonical-store decision in ADR-0008 (and the review-held `8a7e916` remediation branch).
**Applies to:** Method Factory persistence layer, post-v0.1.x overhaul.

---

## Context

Five validation rounds of the v0.1.x JSONL overhaul exposed that `ManifestStore` had become a bespoke database engine: transactions, compare-and-swap, lock ownership and crash recovery, append framing, torn-write classification, tail repair, snapshot caching, full-chain replay, artifact verification, corruption classification, backward compatibility, and performance optimization. Round 5 identified three divergent "is this committed?" classifiers and two unique release-blocking root causes:

1. `MAX_ENVELOPE_BYTES` (2 MiB) was misused as a journal-record limit, so a valid committed record larger than 2 MiB (cumulative snapshots grow unboundedly) could be **destroyed** by append-time repair.
2. The healthy-journal tail reader selected the empty bytes after the terminal newline and fell back to a **full-journal read under the exclusive lock** on every CAS (~430× regression).

The senior reviewer verdict (2026-08-07): the `8a7e916` implementation is permanently review-held and non-releasable; the SQLite architecture is **approved in principle**; controlled branch/PR publication is operator-authorized; the JSONL remediation branch is preserved forensically but not replayed.

**Publication fact (precise):** public v0.1.2 exists — the JSONL store at commit `fb5641c` was publicly tagged `v0.1.2-integrity`. No production user stores are known to the project from available evidence; absence of known real stores is **not** inferred as proof that none exist. Because v0.1.2 was publicly tagged, a legacy migration path is retained (Section 6). The migration cost of the architectural change is effectively zero for known project stores; it is non-zero for any hypothetical real store, which is why migration compatibility is mandatory.

## Decision

**Adopt SQLite as the canonical store** (stdlib `sqlite3`, preserving the stdlib-only core). Deterministic JSON/JSONL become **export** formats, not the transactional database. Artifacts remain in the immutable content-addressed blob store. `PipelineEngine` stays independent behind the `ManifestStore` interface. The append-repair helpers of the JSONL branch are **not** carried into the SQLite implementation.

## 1. SQLite schema (binding properties)

One canonical immutable event table plus schema metadata. No separate historical manifests table, no mutable head table, no event_json duplicating manifest_json, no package lock files, no append framing, no torn-line repair, no manifest-cache file.

```sql
CREATE TABLE store_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

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
```

Exact DDL may evolve in ADR review; these properties are **binding**:

- One event row = one package revision.
- Revision zero = package-creation event.
- `UNIQUE(package_id, action_id)` enforces package-scoped idempotency.
- `event_id` is globally unique.
- `manifest_json` holds the complete resulting manifest for that revision.
- `action_json` holds canonical normalized action bytes.
- No duplicated event_json containing another copy of manifest_json.
- No mutable manifest-cache file, no package lock files, no append framing, no torn-line repair.
- No materialized package-head table unless profiling proves it necessary.

Current-state lookup (indexed; composite PK supports it):

```sql
SELECT manifest_json
FROM events
WHERE package_id = ?
ORDER BY revision DESC
LIMIT 1;
```

A read-only `package_heads` view is acceptable. A mutable projection table is not justified for the first release.

## 2. Transaction and idempotency contract

Every mutation uses an explicit transaction:

```text
BEGIN IMMEDIATE

1. Search for package_id + action_id.
2. If found:
   a. same action_sha256 → return the previously committed result;
   b. different action_sha256 → ACTION_ID_CONFLICT.
3. Read the latest package revision.
4. Compare it with expected_revision.
5. Validate and canonicalize the action and resulting manifest.
6. Verify required artifact blobs exist.
7. Insert exactly one new event row.
8. COMMIT.
```

- There is no separate head update to become inconsistent with the event.
- A competing writer blocks at `BEGIN IMMEDIATE`; after acquiring the transaction it reads the newly committed revision and returns a stale-action result when appropriate.
- Required behavior:
  - Same action ID and same action hash: idempotent success (replay prior result).
  - Same action ID and different action hash: typed `ACTION_ID_CONFLICT`.
  - New action ID and stale revision: typed stale-action failure (`STALE_ACTION`).
  - New action ID and current revision: one atomic event insert.
  - Any exception before commit: no new revision.
  - Any successful commit: the complete new revision exists.
- **Never infer idempotency from `action_id` alone.**

Note: `ACTION_ID_CONFLICT` supersedes the JSONL-era `ACTION_ID_REUSE` code for the new store; the stable error-code table (ADR-0008) is amended accordingly.

## 3. SQLite operating mode

For the first release:

```sql
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
```

Use explicit `BEGIN IMMEDIATE` transactions. **Do not default to WAL** — single-operator local tooling; WAL adds `-wal`/`-shm` sidecars, checkpoint behavior, more complicated backup, and risk of incomplete evidence capture by copying only the main file. WAL may be reconsidered only after measured reader/writer contention justifies it.

Also required:

- Parent store directory mode `0700`; database file mode `0600`.
- A fixed SQLite `application_id` for the store.
- `PRAGMA user_version = 1`; stable failure (`UNSUPPORTED_SCHEMA`) on unsupported future schema versions.
- One connection per operation or thread (no cross-thread connection reuse).
- Explicit read-only mode for validation commands (`mode=ro`).
- Backups via the SQLite backup API or `VACUUM INTO` — never a live raw file copy.
- If `STRICT` tables are adopted, declare and test the minimum supported SQLite version; do not assume every Python 3.11 build ships the same SQLite version.

## 4. Canonical serialization and size boundaries

Canonical JSON bytes are produced consistently:

```python
json.dumps(
    value,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
```

Hash those exact bytes. (This amends the JSONL-era `ensure_ascii=True` canonical form; digests are recomputed from canonical bytes on migration.)

Separate limits explicitly — never reuse `MAX_ENVELOPE_BYTES` as an event or manifest limit:

- Action Envelope size.
- Action JSON size.
- Manifest size.
- Individual content-field sizes.
- Artifact/blob size.

**Frozen choice for `summary.content`** (amends Manifest Contract v0.1 / ADR-0004):

> **Content-addressed summary body.** The manifest stores `summary: {digest, size, preview?}`; the full summary content lives in the immutable blob store. No unbounded inline string embedded in every historical revision. No implicit hybrid.

## 5. Hash-chain role

Retain the manifest hash chain for semantic audit continuity, with a narrowed claim:

> SQLite provides atomicity and transactional durability. The event hash chain provides **internal consistency evidence** across Method Factory revisions.

The chain is **not** the transaction mechanism.

Path separation:

- **Hot path:** indexed latest-event read and validation of the current operation only.
- **`mf validate`:** current database/schema and current package checks.
- **`mf validate --full`:** complete revision-chain, manifest-hash, action-hash, and artifact verification.
- **Migration and release evidence:** always run full validation.

This prevents an O(J) or O(J²) mutation path. Document that an unkeyed chain:

- does not prove cryptographic authenticity;
- does not detect an attacker replacing and rehashing the whole database;
- does not independently detect rollback to an older internally valid database.

Use "internal consistency evidence," not "tamper-proof."

## 6. Public v0.1.2 migration

The JSONL store at public commit `fb5641c` (tag `v0.1.2-integrity`) was published. A legacy migration path is therefore required, implemented outside the normal SQLite store:

```text
methodfactory/migrations/v012_jsonl.py
```

Required command: `mf migrate-store`

Required behavior:

1. Detect the public v0.1.2 JSONL layout.
2. Open it read-only.
3. Validate the complete legacy chain using a **frozen legacy reader**.
4. Never repair or alter the legacy files.
5. Import into a **temporary** SQLite database.
6. Recompute canonical hashes from imported content.
7. Run SQLite integrity and full Method Factory validation.
8. Atomically rename the completed destination database.
9. Produce a migration receipt: source format; source file SHA-256 values; package count; event count; destination schema version; resulting validation verdict.
10. Preserve the original store until the operator explicitly archives or removes it.

When a legacy store is detected, normal startup must **not** migrate silently — return a stable `LEGACY_STORE_DETECTED` instruction.

Do **not** place experimental `8a7e916` repair logic in the production migration path. Preserve that history forensically.

## 7. Export contract

Do not freeze the failed journal's exact bytes as the primary public contract. Two explicit formats:

**Supported format — `method-factory-events-v1`**

- versioned; deterministic; UTF-8; LF line endings; one event per line; canonical key ordering; exactly one final newline; package/revision ordering documented; generated inside a consistent read transaction.

**Legacy evidence format — `legacy-v012-jsonl`**

- reconstructs the old public event shape for compatibility and evidence comparison.

The supported export promises deterministic output for the same database and exporter version. It does not promise byte identity with every historical journal produced during the abandoned remediation branch. Export does not automatically imply import; any import command must be separately specified, fully validated, and atomic.

## 8. Salvage versus discard from `8a7e916`

Preserve the entire forensic branch; do not replay it wholesale.

**Port or reimplement:**

- `core` → `methodfactory` package rename.
- `pyproject.toml` and `mf` entry point.
- Immutable content-addressed artifact store.
- Logical-path protections.
- Stable CLI error codes.
- Envelope bounds and control-character validation.
- Schema type hardening.
- Stale Process Engine quarantine.
- Pinned GitHub Actions and least-privilege workflow permissions.
- `.mf/`, egg-info, database, and build-artifact ignores.
- Packaging smoke tests.
- Documentation improvements that remain true under SQLite.

**Do not port:**

- Lock-file ownership or stale-lock recovery.
- Append repair.
- Tail classifiers.
- Newline framing.
- Tail-size heuristics.
- `_read_last_event`.
- Manifest cache reconciliation.
- JSONL CAS implementation.
- Round-number tests whose only purpose is the abandoned storage mechanics.

Rename surviving tests by invariant (e.g. `test_sqlite_transactions.py`, `test_store_idempotency.py`, `test_store_concurrency.py`, `test_store_migration_v012.py`, `test_event_export.py`, `test_store_fault_injection.py`, `test_store_security_boundaries.py`).

## 9. CI and test evidence

Canonical release-gate command (single, used everywhere):

```bash
python -m unittest discover -s methodfactory/tests -t .
```

Hypothesis supports unittest; no pytest conversion required.

Test dependencies (central):

```toml
[project.optional-dependencies]
test = [
    "hypothesis>=6",
    "PyYAML>=6",
]
```

CI:

```bash
pip install -e ".[test]"
python -m unittest discover -s methodfactory/tests -t .
```

Test Python 3.11 and 3.12 (if both remain declared supported).

Required test classes:

1. Reference-model/state-machine property tests.
2. Transaction interruption before and after commit.
3. Separate-process concurrency and stale revision.
4. Idempotent action retry.
5. Conflicting action-ID reuse.
6. Public v0.1.2 migration fixtures.
7. Deterministic export fixtures.
8. Unsupported schema-version behavior.
9. Corrupt/truncated SQLite database behavior.
10. Missing or corrupt artifact blobs.
11. Large input and manifest bounds.
12. Clean-install CLI tests.
13. No committed `.mf`, SQLite, WAL, SHM, journal, egg-info, or build output.
14. Indexed latest-event query proof and representative performance test.

Do not use a fragile sub-second CI latency threshold as the only performance gate. Also assert the query plan uses the package/revision index and does not scan the complete history.

## 10. Versioning

Vincent retains the `2.0.0` generation branding, with honest prerelease progression:

```text
pyproject: 2.0.0a1        Git tag later: v2.0.0-alpha.1
pyproject: 2.0.0rc1       Git tag later: v2.0.0-rc.1
final only after trials:  2.0.0 / v2.0.0
```

No tag is authorized now. The eventual release notes must explain that "2.0" denotes the Process Engine → Method Factory architectural generation, rather than implying an earlier released Method Factory 1.x API.

## 11. Cumulative review lanes

One cumulative review of the clean candidate over `fb5641c..release-candidate`, lanes:

1. Storage and transaction correctness.
2. Fault injection and recovery.
3. Public v0.1.2 migration, export, backup, and restore.
4. State-machine legality.
5. Security and resource boundaries.
6. CLI/API compatibility and stable error model.
7. Performance, packaging, and documentation.

Review the resulting candidate architecture, not removed JSONL code preserved only on the forensic branch.

Release requires: zero unresolved critical or major durability, concurrency, integrity, migration, or security defects; exact GitHub candidate SHA; all required checks green on that SHA; full validation green; clean-install proof; migration proof; docs and ADRs matching code; no runtime/build artifacts; operator approval. A review-round count never overrides an open release blocker.

## 12. Controlled publication scope (2026-08-07)

Operator-authorized, evidence and development-visibility only:

- Push `review/jsonl-overhaul-8a7e916` at exact `8a7e9167d6ff77b3ccd32722683c9b42e4390687` (forensic; no PR required).
- Push `feat/sqlite-persistence-reset` from `origin/main` (`fb5641c`); open a **draft PR** into `main` (DO NOT MERGE).
- Do not push local `main`; do not change remote `main`; do not merge; do not create a release; do not create any final or release-candidate tag; do not force-push published branches; do not commit the `.bundle`, SQLite databases, `.mf/`, secrets, runtime stores, or local operational facts into the product repository.

## Threat model

| Threat | Guarantee |
|---|---|
| Process crash | SQLite ACID; uncommitted work lost, committed work intact |
| Host power loss | SQLite durable commits (journal_mode DELETE + synchronous FULL); same as above |
| Concurrent sanctioned writers | SQLite write serialization + revision predicate → typed `STALE_ACTION` |
| Accidental file corruption | Typed `MANIFEST_INVALID` on detected mismatch; hot path does **not** run `integrity_check` (only `mf validate --full` does); no auto-repair |
| External local tampering | Hash chain in export = **internal consistency evidence only**, not cryptographic authenticity without an anchored/signed root |
| Malicious local writers | Out of scope for single-operator local tool; documented (a local attacker with store write access can rewrite the DB and recompute ordinary hashes) |

## Consequences

- Deletes the bespoke JSONL failure surface (torn writes, framing, stale locks, tail repair, full-file mutation reads, divergent classifiers).
- Keeps `PipelineEngine` independent; `SQLiteManifestStore` implements the `ManifestStore` interface (create/apply, idempotent replay, read_events for export).
- Export formats preserve the audit/evidence story; `method-factory-events-v1` is the supported public contract.
- Amends: ADR-0004 (summary.content → content-addressed body), ADR-0008 (persistence mechanics + error-code table). ADR-0001..0003, 0005..0007, 0009..0010 remain in force.
- The `8a7e916` branch is preserved forensically on `review/jsonl-overhaul-8a7e916`; its reuse is limited to the Section 8 port list.

---

## Amendment - Phase 2 finalization (2026-08-07)

Closes the twelve review items from senior review `4878235332` on PR #1. This amendment is binding before implementation proceeds to commits 2-4.

### A. Publication fact and migration posture (item 1)

Public v0.1.2 exists (`v0.1.2-integrity` at `fb5641c`). No production user stores are known to the project from available evidence; this is stated as an evidence limitation, **not** as proof none exist. Migration compatibility is therefore mandatory (Section 6) and unchanged.

### B. Open and validation modes (item 2)

| Mode | Checks |
|---|---|
| Normal hot-path open | Schema/application-ID/user-version checks; errors naturally raised by SQLite on use. **No `PRAGMA integrity_check`.** |
| `mf validate` | Bounded: `PRAGMA quick_check` + current database/schema checks + current-package checks (latest manifest, artifact digests for the current package). |
| `mf validate --full` | `PRAGMA integrity_check` + full event-chain, manifest-hash, action-hash, and artifact verification across every revision. |

The hot path must never run an O(DB) integrity scan; this preserves the ADR's own O(J)-avoidance goal.

### C. Durability qualification (item 3)

SQLite with `journal_mode=DELETE` + `synchronous=FULL` provides transactional durability subject to the honesty of the OS, filesystem, and storage hardware. It cannot override lying hardware, filesystem faults, or hostile host administration. All durability claims are qualified accordingly; the threat model in Section 12 is the limit of the guarantee.

### D. Physical database identity and open contract (item 4)

- Canonical filename: `methodfactory.sqlite3`.
- Canonical location: directly beneath the store root (`<store_root>/methodfactory.sqlite3`).
- Fixed `application_id`: `0x4D465354` (decimal `1297248084`, ASCII "MFST").
- Accepted `user_version`: `1`. Any other value is unsupported.

| Store-root state | Normal open (rw) | Validation (ro) |
|---|---|---|
| Missing DB, no legacy | Create + initialize new database | `DATABASE_NOT_FOUND` (no creation) |
| Zero-byte `methodfactory.sqlite3` | Initialize (SQLite empty-file semantics; documented as indistinguishable from first creation) | `DATABASE_EMPTY` (no creation) |
| Wrong application ID (foreign/uninitialized DB) | `DATABASE_ID_MISMATCH` | `DATABASE_ID_MISMATCH` |
| Future `user_version` (>1) | `UNSUPPORTED_SCHEMA` | `UNSUPPORTED_SCHEMA` |
| Corrupt DB (fails `quick_check`) | SQLite raises naturally on use; typed `MANIFEST_INVALID` in validate | `MANIFEST_INVALID` |
| Legacy-only (v0.1.2 `packages/`+`events/`, no SQLite) | `LEGACY_STORE_DETECTED` → instruct `mf migrate-store` | `LEGACY_STORE_DETECTED` |
| SQLite-only | Open normally | Open read-only |
| Neither | Create + initialize | `DATABASE_NOT_FOUND` |
| Both present | SQLite is canonical and used; legacy preserved untouched | Same; validate may note legacy presence |

- Read-only validation opens via URI `file:<path>?mode=ro` and must never create or modify the database.
- No validation or read-only command may create a database accidentally; any path that would create one fails with the appropriate typed error.

### E. Append-only is executable (item 5)

The binding DDL includes `BEFORE UPDATE` and `BEFORE DELETE` triggers on `events` that `RAISE(ABORT, ...)`. Immutability is enforced by the database, not only by repository discipline. Schema migrations create a new database/table version rather than mutating historical rows.

### F. Revision and chain invariants (item 6)

One authoritative validator (owned by the storage layer, exercised on every transactional apply) enforces:

- Revision 0 is the package-creation event; its action is `create_package` and `state_before IS NULL`.
- Revision > 0 has exactly one predecessor (revision − 1) present.
- `state_before` equals the predecessor's `state_after`.
- `previous_manifest_sha256` equals the predecessor's `resulting_manifest_sha256`.
- Manifest `package_id`, `revision`, and `state` fields agree with the indexed SQL columns.
- These may be application-validated transaction invariants (not SQL triggers), but there is exactly one authoritative validator and it is tested.

### G. Canonical action hash semantics (item 7)

`action_sha256` covers the complete normalized semantic request used for idempotency:

```python
action_sha256 = sha256_hex(canonical_json({
    "action": action,
    "package_id": package_id,
    "action_id": action_id,
    "basis": basis,
    "payload": payload,
}))
```

- It includes every field that could change the requested outcome.
- It excludes **only** `expected_revision` (optimistic-concurrency/transport metadata, not part of the requested outcome).
- Same `action_id` + same hash → idempotent replay. Same `action_id` + different hash → `ACTION_ID_CONFLICT`. Never infer idempotency from `action_id` alone.

### H. Artifact write boundary and orphan safety (item 8)

- Blob writes occur before the SQLite transaction, are content-addressed, immutable, and verified to exist before the event referencing them is inserted.
- Orphaned blobs (written but never referenced by a committed event) are harmless and retained.
- **No automatic blob deletion during mutation.**
- Any future garbage collection is a separate, conservative process that must prove a digest is unreachable from every committed event before deletion.

### I. Migration source selection and atomic destination (item 9)

- Accepted v0.1.2 layout: `<store_root>/packages/`, `<store_root>/events/`, `<store_root>/artifacts/`.
- `mf migrate-store` accepts explicit `--source` and `--dest`; deterministic defaults are source = the detected legacy store root and destination = `<source>/methodfactory.sqlite3`.
- Destination behavior is fail-closed: if the destination already exists, migration refuses (typed error) - no overwrite of source or destination.
- The destination must be on the same filesystem as its directory for the atomic rename; cross-device rename fails with a typed error.
- The migration receipt (source format, source file SHA-256s, package count, event count, destination schema version, validation verdict) is written durably (fsync) and is part of migration success - migration is not considered successful until the receipt is durable.
- The original store is preserved until the operator explicitly archives or removes it.

### J. Evidence checksum convention (item 10)

Evidence packages use archive-root-relative paths in `SHA256SUMS`. The single verification command, run from the archive root, exits zero:

```bash
cd <archive-root> && sha256sum -c SHA256SUMS
```

The next evidence capture follows this convention.

### K. Clean worktree for evidence capture (item 11)

Before any evidence capture, the local worktree must be clean: the `.gitignore` is in force (Section 8 port list), generated artifacts (`.mf/`, egg-info, build output, test caches, SQLite sidecars) are removed, and `git status --short` is empty.

### L. Architecture CI honesty (item 12)

As of this amendment, architecture CI is **unproven**: run `31127787460` was cancelled without executing steps. It is neither failed nor passed. CI is considered evidence only after a run executes successfully on the exact branch SHA. The Phase 2 submission runs CI on the exact final head SHA and reports the run URL and conclusion.

---

## Amendment - invariant closure (senior review 4885538290, 2026-08-08)

Pre-migration invariant closure (Lane 1). Closes the two accepted residuals
from closure A (`public-surface.md` #1 and #2) WITHOUT reopening the
persistence architecture, changing the state representation, or adding a new
event format.

### Deterministic action → resulting-manifest validation

The authoritative full-chain validator (`storage.chain.validate_chain` - the
`mf validate --full` / migration / release-evidence path) now proves that the
recorded resulting manifest is exactly the deterministic result Method
Factory would have produced:

```text
replay(predecessor_manifest, stored_action, event_id, event_created_at)
    == stored resulting manifest        (canonical bytes equal)
```

- Stored-action reconstruction reuses the normal envelope validator
  (`envelope_from_dict`) on the canonical stored `action_json` with
  `expected_revision = revision - 1` injected (the only field the
  semantic-action form omits by contract). Fail-closed: unsupported protocol
  version, unknown action, malformed basis/payload, invalid IDs, or invalid
  payload structure are rejected even though the bytes were persisted.
- The transition is the SINGLE existing deterministic engine
  (`engine.apply.next_manifest`). No per-action consequence validators are
  created; there is still exactly one transition implementation.
- Replay is side-effect free: the engine's `blobs_to_write` are discarded and
  nothing is persisted during validation. Blob metadata is proven by
  canonical equality; committed-blob integrity is verified only by the
  optional artifact-verification mode.
- Replay re-evaluates the same legality and gate rules from persisted
  evidence (all gates are self-contained: predecessor manifest + stored
  action; no external runtime state). A historical event that could not
  legally have been produced fails full-chain validation.
- No recursive validator dependencies: the validator calls the pure engine
  with decoded, validated persisted evidence; it never calls the
  transactional mutation path (`store.apply`).
- The replay check lives ONLY on the explicit full-chain/audit path.
  `load()` remains indexed latest-row; transaction apply remains bounded and
  does not replay history.

### Timestamp contract

Derived from the deterministic transition implementation, not a blanket rule:

| Revision | Contract |
|---|---|
| 0 | manifest `created_at == updated_at == row created_at == action payload.created_at` |
| > 0 | manifest `updated_at == row created_at`; manifest `created_at == revision-0 row created_at` (threaded through the walk) |

`summary.presented_at` (`prepare_summary`) and
`summary.confirmation.confirmed_at` (`confirm_summary`) are derived from the
event timestamp by the transition and are therefore proven by deterministic
replay - they are not bound indiscriminately. Independent corruption tests
cover each binding.

### Threat-model note (unchanged)

These checks detect internally inconsistent history, writer defects, malformed
migration output, and partial/coherent-enough tampering that violates
deterministic semantics. They are internal-consistency evidence, not
cryptographic authenticity: an attacker capable of coherently rewriting and
rehashing the entire database remains out of scope.

---

## Amendment - migration/export contract correction (design-freeze review 4886392385, 2026-08-08)

Documentation-only contract correction. Freezes the exact public v0.1.2
compatibility contract that a future migration/export implementation must
honor. Does not implement migration/export and does not alter the accepted
SQLite persistence architecture.

### 1. Legacy action-hash semantics (binding)

Public v0.1.2 (`v0.1.2-integrity`, commit `fb5641c`) used two action-hash
rules:

- **Revision 0** (`create_package`):
  `sha256(legacy_canonical_json({"action": "create_package", "package_id": <pkg>}))`
  - a special reduced create hash.
- **Revision > 0**:
  `sha256(legacy_canonical_json(envelope_as_dict minus "expected_revision"))`,
  i.e. the six fields
  `{protocol_version, action_id, package_id, action, basis, payload}`.

The migration reader must reconstruct each rev>0 semantic action from
snapshot + blob + predecessor evidence, then **require** the stored legacy
`action_sha256` to equal the legacy canonical hash of the unique candidate.
A recovered action is accepted only when the evidence determines exactly one
candidate. No hash inversion, no invented payload.

### 2. Canonical-serializer relationship (exact wording)

Legacy canonical hashing used:

- `sort_keys=True`;
- `separators=(",", ":")`;
- `ensure_ascii=True`;
- Python's **default** `allow_nan` behavior.

Current canonical hashing uses:

- `sort_keys=True`;
- `separators=(",", ":")`;
- `ensure_ascii=False`;
- `allow_nan=False`.

The relevant public v0.1.2 action/manifest schemas do not contain arbitrary
floating-point semantic fields, so the observed migration compatibility
difference is the **ASCII-escape/UTF-8 representation**, not a floating-point
conversion rule. Do not overclaim equivalence of serializer options.

Legacy digests are therefore not preserved as current canonical digests;
migration recomputes current hashes from imported content (ADR-0012 §4).

### 3. Public-valid / current-valid compatibility contract

Where a public-valid v0.1.2 value is now current-invalid, migration fails
closed with `MIGRATION_INCOMPATIBLE` (package_id, revision, action_id,
reason). Current validation is never weakened; historical IDs are never
renamed; no truncation, whitespace rewriting, control-character stripping, or
silent normalization.

| Surface | Public v0.1.2 | Current | Classification |
|---|---|---|---|
| `package_id` | `^pkg_[A-Za-z0-9_-]{1,63}$` | identical | A (identical) |
| `action_id` | non-empty str ≤64, no grammar | ≤64 + `validate_identifier` + control-char | C if legacy used invalid chars, else A |
| `input_id` / `artifact_id` / `kind` | non-empty str, no grammar | `validate_identifier` + control-char | C if legacy used invalid chars, else A |
| `operator_id` | any str (or None) | `validate_identifier` | C if legacy used invalid chars, else A |
| `logical_path` | legacy: lstrip `/`, block `{..,/,\}`, ≤255 | strict relative, no backslash/`%`/control/empty-segment/`.`/`..`, ≤255 | C for `a//b`, leading/trailing `/`, `%2f`, backslash; else A |
| `intent.raw` | any string, no length/control boundary | `MAX_INTENT_CHARS = 65,536` + control-char validation | C if legacy outside boundary |
| `intent.clarified` | engine does not populate it (remains `None`) | must be string or null | Non-null legacy `clarified` is **non-reconstructable historical state** → fail closed (see §5) |
| `record_input.content` | any string, no length limit | `MAX_CONTENT_CHARS` (characters) + persisted UTF-8 blob byte limit (`MAX_ARTIFACT_BYTES`) | C if legacy exceeds either applicable boundary |
| `record_draft_artifact.content` | any string, no length limit | `MAX_CONTENT_CHARS` (characters) + artifact/blob byte limit (`MAX_ARTIFACT_BYTES`) | C if legacy exceeds either applicable boundary |
| `statement` | any string | `MAX_STATEMENT_CHARS` (16 KiB) | C if legacy exceeds |
| `desired_outcomes` | list of str, no count/length limit | `MAX_OUTCOMES` (100) + ≤16 KiB each | C if legacy exceeds |
| `reason` (exclusion/cancel) | str or None, no length limit | `MAX_REASON_CHARS` (1 KiB) + control-char | C if legacy exceeds |
| control characters | not validated in legacy envelope | validated on ids/kinds/reasons/statements/outcomes/preview | C where legacy carried control chars in a now-checked field |
| Unicode / lone surrogate | legacy accepted any str | current rejects lone surrogates at several boundaries | A for well-formed Unicode (hash differs - recomputed); C only if legacy persisted a lone surrogate |
| `event_id` | `evt_<uuid4hex>` (36 chars) | `validate_identifier` + global UNIQUE | A for legacy format |

`record_input.content` and `record_draft_artifact.content` are frozen as
**separate** compatibility rows because their current semantic character
limits and persisted blob byte limits are the same constants but apply to
different storage boundaries.

### 4. Frozen v0.1.2 journal/cache semantics

- `events/<package_id>.events.jsonl` is the **canonical** public v0.1.2
  history source.
- `packages/<package_id>.json` is a **latest-manifest cache**.

The frozen migration reader preserves the public crash-tolerance semantics:

- cache absent while reconstructable journal snapshots exist is acceptable;
- cache need not equal the latest journal snapshot;
- a lagging cache is valid if its digest matches **any** committed journal
  snapshot (matching public `_validate_cache_if_present()` behavior);
- a cache that matches no committed journal snapshot is invalid;
- migration derives canonical package history from the **journal**, never from
  a newer-looking cache.

Do not tighten this into `cache == last event`; that would reject legitimate
public v0.1.2 crash states.

### 5. Non-reconstructable historical state

Migration compatibility is for histories that can be validated and
semantically reconstructed - not arbitrary hand-rehashed/tampered structures
merely tolerated by the old loader. A non-null legacy `intent.clarified`
(which the public engine never produces) is non-reconstructable and fails
closed. Arbitrary unrecoverable `cancel.reason` → `MIGRATION_INCOMPATIBLE`.

### 6. Timestamp normalization (advancing-clock evidence)

Public v0.1.2 calls `now()` separately for `summary.presented_at`,
`summary.confirmation.confirmed_at`, manifest `updated_at`, and event `at`.
Advancing-clock archaeology at `fb5641c` proved: event `at` is the latest
timestamp in each event; `updated_at` is 1 tick earlier; `presented_at` /
`confirmed_at` are 2-3 ticks earlier; rev-0 has all equal.

Frozen normalization rule:

- rev-0 current timestamp = legacy event `at` (creation timestamp);
- rev>0 current row `created_at` = legacy event `at`;
- current `next_manifest(..., created_at=legacy_event.at)` deterministically
  sets modern `updated_at`, `presented_at`, `confirmed_at`.

Original distinct v0.1.2 internal timestamps remain in the untouched legacy
source/evidence and are **not** copied into current fields whose
deterministic contract differs.

### 7. Current-engine-as-transformer architecture

Migration must not hand-author rev>0 modern manifests. The architectural path:

```
legacy validation
→ exact action reconstruction
→ current-valid ActionEnvelope
→ CURRENT next_manifest
→ modern manifest + blobs
→ semantic equivalence check
→ SQLite insertion
```

No second current state machine. Fields excluded from equivalence because they
intentionally change representation: canonical-serializer-dependent hashes,
summary inline-content representation, normalized timestamps, current lineage
hashes. All other semantics must match the legacy snapshot exactly.

### 8. ID preservation rule

Preserve legacy `event_id` exactly if current-valid and globally unique;
preserve legacy `action_id` exactly if current-valid; preserve rev-0
`act_create_package`. Duplicate legacy `event_id` across packages →
`MIGRATION_INCOMPATIBLE`. The current `store.create()` ID-generation
convention is not retroactively imposed on migration rows. No silent
historical-ID renaming.

### 9. Source-stability-before-publication

```
initial source identity/hash
→ legacy validation
→ temporary modern store construction
→ complete modern validation
→ FINAL source identity/hash
→ require exact equality
→ ONLY THEN destination publication
```

No final SQLite database becomes visible before the source-stability proof
succeeds. The residual post-check TOCTOU window is documented honestly; legacy
locks are not revived to eliminate it.

### 10. Artifact publication boundary (honest)

Current immutable blobs may become visible before canonical DB publication.
They are content-addressed, immutable, verified, and orphan-safe. Migration is
therefore **not** claimed to make every filesystem write atomically invisible;
only canonical SQLite DB publication is atomic. No automatic orphan deletion
during migration.

### 11. Receipt/database success semantics

Preferred publication order: (1) publish/fsync final receipt; (2) publish/
fsync final database; (3) final read-only verification.

**A receipt by itself is NOT successful migration.** Migration is successful
only when:

- final database exists;
- matching final receipt exists;
- their identities correspond to the same migration;
- final read-only database validation succeeds.

Crash state "receipt present + DB absent" is incomplete/ambiguous migration
evidence, not success. Fail closed with explicit operator recovery
instructions. No recovery daemon or transaction journal to make two files
atomically appear together.

### 12. `method-factory-events-v1` (supported export)

Unique per-line field set (no duplicate keys):

```
format, format_version, package_id, revision, event_id, action_id, action,
state_before, state_after, action_sha256, previous_manifest_sha256,
resulting_manifest_sha256, created_at, semantic_action, manifest
```

One event per line; current canonical UTF-8 JSON (sorted keys, compact
separators, `ensure_ascii=False`); exactly one LF after each line; exactly one
final newline. Explicit SQL ordering: `ORDER BY package_id, revision`.

### 13. `legacy-v012-jsonl` - hash canonicalization vs journal-line serialization

These are two different public serializations and must not be conflated.

- Public v0.1.2 **hash canonicalization**:
  `json.dumps(value, sort_keys=True, separators=(",",":"), ensure_ascii=True)`.
- Public v0.1.2 **journal-line serialization**:
  `json.dumps(event, sort_keys=True) + "\n"` - Python's default JSON spacing
  and `ensure_ascii=True`.

`legacy-v012-jsonl` is a deterministic stream of **reconstructed public
v0.1.2 event objects** serialized using the public v0.1.2 **event-line writer
semantics**. It reconstructs the public event SHAPE and byte serializer.

It does NOT promise:

- reproduction of an original historical machine's exact journal;
- reproduction of original internal timestamp distinctions lost during
  migration;
- reconstruction of the entire legacy directory/filesystem layout.

For multi-package output, deterministic ordering is `package_id`, then
`revision`. This is one evidence stream, whereas the old canonical store used
one journal file per package.

### 14. Semantic receipt identity posture

Receipt identity is semantic: exact legacy source identity/inventory; exact
source commit/tag identifier; package count; event count; destination schema
version; resulting package/event count; migration tool/version identity; full
validation result. Raw SQLite file bytes are **not** frozen as the public
semantic compatibility identity.

### 15. Error taxonomy

Small actionable taxonomy, no redundant subclasses per command:

| Code | Condition |
|---|---|
| `LEGACY_STORE_DETECTED` (existing) | detect-migration-required on normal open |
| `LEGACY_SOURCE_INVALID` | unrecognized/unsupported legacy source |
| `LEGACY_CHAIN_INVALID` | invalid legacy chain |
| `MIGRATION_INCOMPATIBLE` | unreconstructable historical semantics, or public-valid value now current-invalid |
| `SOURCE_CHANGED` | source changed during migration (fail before publication) |
| `MIGRATION_PUBLISH_FAILED` | atomic publication failure |
| `DESTINATION_EXISTS` | final destination already exists (dedicated stable identity; a CLI caller must distinguish "cannot overwrite" from generic storage failure) |

Reuse current storage/path/manifest errors where their semantics are already
exact. No alias proliferation.
