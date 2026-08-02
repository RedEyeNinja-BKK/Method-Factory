# ADR-0004 — Manifest Contract v0.1

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

The migrated `docs/package-manifest-schema.md` mixes durable domain state,
runtime adapter data, evidence records, and evaluator-era qualification
fields. It also lacks the integrity primitives a code-owned lifecycle
requires: a canonical `state`, a monotonic revision, write lineage, approval
digest binding, and code-computed artifact hashes.

## Decision

- **Code alone creates, updates, hashes, and persists the manifest.** The
  model proposes validated data via the action envelope; it never writes
  manifest state.
- The full schema is defined in `docs/manifest-contract-v0.1.md`. Essentials:
  - `schema_version: "0.1"`, `package_id`, monotonic integer `revision`
  - `state` — from the transition table only
  - `previous_manifest_sha256` — write lineage link
  - `intent`, `inputs` (each with code-computed `content_sha256`),
    `objective`
  - `summary` — `content`, `canonical_sha256 = sha256(content bytes)`,
    `presented_at`, `confirmation {status, confirmed_at, operator_id,
    confirmed_summary_sha256}`
  - `artifacts` — each with code-computed `sha256` and `byte_count`
  - `transition {last_event_id, last_action_id}`
- **Serialization is JSON**, canonical for hashing via
  `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
  The YAML block in the contract document is the logical schema; JSON is the
  byte form. JSON gives deterministic hashing without a YAML dependency in
  core.
- The migrated schema is **requirements evidence only**, quarantined under
  `evidence/process-engine/`. It is never validated as the active contract.

## Consequences

- Operator approval binds to an exact digest of the exact summary the
  operator saw.
- Stale writes and silent overwrites are structurally prevented
  (ADR-0008, optimistic concurrency).
- Evaluator, semantic-judge, assurance-tier, and Turnstone deployment fields
  are absent from v0.1 by design.
