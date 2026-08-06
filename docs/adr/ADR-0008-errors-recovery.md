# ADR-0008 — Error, recovery, and stale-write behavior

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

The migrated validator collects errors then fails — correct for repository
linting, wrong for lifecycle mutation, where a partial transition corrupts
state. The migrated manifest contract had no revision counter, lock
strategy, compare-and-swap rule, or stale-action behavior.

## Decision

- **Mutations fail fast, before any write.** Order of checks:
  1. envelope parse + schema validation
  2. manifest load + integrity verification
  3. action-id idempotency/reuse **before** revision check
  4. `expected_revision` comparison
  5. action legality for current state
  6. gate predicates (evidence, digest binding)
  7. build next manifest → validate → **one atomic commit** (CAS) or none

  Idempotency is checked first so an exact retry can replay after a stale-action
  failure — the caller resubmits with updated expected_revision and the same
  action_id, which replays rather than failing.
- **Read-only validation collects all errors** (used by `mf validate` and
  CI): report every schema, digest, and invariant violation without changing
  state.
- Error codes (stable, machine-readable):

| Code | Meaning |
|---|---|
| `INVALID_ENVELOPE` | malformed JSON / schema violation / unknown fields |
| `ILLEGAL_TRANSITION` | valid envelope, action not legal in current state |
| `GATE_UNSATISFIED` | required evidence missing (e.g. no intent before summary) |
| `STALE_ACTION` | `expected_revision` mismatch, or approval digest mismatch |
| `ACTION_ID_REUSE` | action_id reused with a different payload |
| `INVALID_PAYLOAD` | semantic payload violation (e.g. duplicate input_id) |
| `MANIFEST_INVALID` | missing/corrupt manifest or digest-chain break |
| `CONCURRENCY` | could not acquire the package write lock in time |

- **Persistence:** package-scoped lock; validate the new manifest in memory;
  append an event containing the complete `manifest_snapshot`, `fsync` the
  event journal, then write the package JSON snapshot as a cache using a temp
  file, `fsync`, atomic `os.replace`, and parent-directory `fsync`. The event
  journal is canonical; a crash after the event append but before the cache
  update is recovered by replaying the journal. Orphaned artifact blobs are
  retained and harmless until referenced by a committed manifest.
- **Restart/reload** replays and verifies the complete event chain: contiguous
  revisions, state continuity, previous-manifest digests, snapshot digests, and
  referenced artifact digests. Any failure raises `MANIFEST_INVALID`; recovery
  is detection-only in this phase and never infers or auto-repairs state.

## Consequences

- A stale request fails with `STALE_ACTION`; the caller reloads and re-issues.
- No partial writes, no silent overwrites, no self-healing of corrupt state.
- Error surfaces: CLI/API (stable code + context), audit log (full rejected
  action), prompt re-prompt (only exact validation defects for malformed
  model proposals — never reinterpretation authority).

## Amendment (v2.0.0 - 2026-08-06)

- Error-code table completed to the full emitted set:
  `INVALID_ENVELOPE`, `ILLEGAL_TRANSITION`, `GATE_UNSATISFIED`,
  `STALE_ACTION`, `ACTION_ID_REUSE`, `INVALID_PAYLOAD`,
  `MANIFEST_INVALID`, `CONCURRENCY`, `PACKAGE_EXISTS` (duplicate create),
  `FILE_IO` (unreadable/writable file on the CLI surface), `NO_SUMMARY`
  (summary requested but not prepared).
- **Stale-lock recovery:** the package lock records its owner PID and is
  reclaimed when the owner is dead (`os.kill(pid, 0)`) or the lock is older
  than `LOCK_STALE_AGE_S` (60 × the lock timeout, 300s). A crashed writer no longer wedges
  the package.
- **Torn-journal tolerance:** an unterminated final journal line is an
  in-flight append, never corruption; readers retry once and then ignore
  the incomplete line. A terminated non-JSON line remains genuine
  corruption and raises `MANIFEST_INVALID`.
- **CAS tail-verify:** when the engine passes its already-verified manifest,
  `compare_and_swap` tail-checks the last journal digest under the O_EXCL
  lock instead of a second full replay. The lock excludes concurrent
  writers; the digest comparison detects any change or tamper.
- **O(J) artifact verification:** replay collects referenced artifact
  digests and verifies each unique blob once (was O(J²) reads per load).
- **Journal growth:** the append-only journal is O(J²) in bytes (each event
  embeds the cumulative snapshot). Accepted at single-operator scale; a
  warning is emitted past 10 MiB per package. Compaction/checkpointing is a
  future-phase item (ADR-0008 backlog).
