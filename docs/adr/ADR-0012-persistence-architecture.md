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
| Accidental file corruption | `integrity_check` on open; typed `MANIFEST_INVALID`; no auto-repair |
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
