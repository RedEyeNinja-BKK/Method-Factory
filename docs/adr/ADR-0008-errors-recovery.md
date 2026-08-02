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
  3. `expected_revision` comparison
  4. action legality for current state
  5. action-id idempotency / reuse
  6. gate predicates (evidence, digest binding)
  7. build next manifest → validate → **one atomic commit** (CAS) or none
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

- **Persistence:** package-scoped lock; validate new manifest in memory;
  write temp file in same filesystem; `fsync`; atomic `os.replace`; `fsync`
  parent dir; release lock. Append-only event log alongside the snapshot,
  each event carrying `resulting_manifest_sha256`.
- **Restart/reload** verifies schema, event-chain continuity, snapshot
  digest, and referenced artifact digests. Any failure opens **read-only
  recovery mode** — never infer or auto-repair state.

## Consequences

- A stale request fails with `STALE_ACTION`; the caller reloads and re-issues.
- No partial writes, no silent overwrites, no self-healing of corrupt state.
- Error surfaces: CLI/API (stable code + context), audit log (full rejected
  action), prompt re-prompt (only exact validation defects for malformed
  model proposals — never reinterpretation authority).
