# ADR-0002 — Committed source-of-truth and generated-output model

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

Process Engine used a private `../drafts` directory as authoring source, with
`scripts/convert.py` regenerating committed content. The clean-slate decision
removes the private drafts model: source is committed, contributors and users
can reproduce everything from the repository alone.

## Decision

- **Committed source is the single source of truth.** No `../drafts`
  directory, no private authoring store.
- Generated content exists only where something is legitimately derived
  (e.g. rendered docs, aggregated indexes). Every generated artifact must be
  reproducible by a deterministic command, and CI enforces regeneration
  idempotence (regenerate → diff must be empty).
- The migrated `scripts/convert.py` drafts pipeline is **retired** and
  quarantined under `evidence/process-engine/` as historical reference. It is
  not part of Method Factory's active tooling.

## Consequences

- The repository is self-contained: clone → validate → test reproduces the
  state.
- No stale-guard complexity against an external drafts tree.
- The Phase-4 CI drift check becomes meaningful: regeneration must be a no-op
  on a clean tree.
