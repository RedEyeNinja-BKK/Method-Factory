# ADR-0009 — Legacy Process Engine material isolation

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

The repository is a migration snapshot of Process Engine v1.9.1. Its content
carries Process Engine identities, evaluator-era schemas, Turnstone-specific
prompt rules, conversion assumptions, and historical qualification material.
None of it is authoritative merely because it exists.

## Decision

- Migrated legacy material is quarantined under **`evidence/process-engine/`**
  — a clearly isolated, documented area. **Nothing is deleted.**
- Classification applies to every migrated artifact (inventory in
  `docs/architecture.md` and the Phase-0 audit): active foundation / legacy
  evidence / requirement source / rewrite required / retire-remove.
- Active Method Factory paths (`core/`, `prompts/`, `docs/`, `README.md`)
  must not reference quarantined paths except through explicit, narrow
  pointers (e.g. the migration narrative).
- CI identity sweep (ADR-0010) fails on stale Process Engine identity in
  active paths; quarantined paths are exempt via an explicit path
  allowlist — never a global bypass.
- Process Engine itself remains the philosophical reference at
  `RedEyeNinja-BKK/Process-Engine` (now v1.9.5-prompt-only). The quarantine
  is for this repo's migrated snapshot, not a replacement for the reference.

## Consequences

- Historians get the full record; the active architecture stays clean.
- No accidental inheritance of evaluator semantics, Turnstone coupling, or
  stale version claims.
