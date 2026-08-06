# ADR-0011 — v2.0.0 clean slate: version reset and review remediation

**Status:** Accepted (2026-08-06, operator decision)
**Applies to:** Method Factory v2.0.0

## Context

Method Factory began as a migration snapshot of Process Engine v1.9.1
(`v0.1.0-migration`) and was developed through `v0.1.x` tags while Process
Engine legacy content still occupied the active tree. By 2026-08-06 the code
layer (state machine, journal-first manifest store, strict Action Envelope,
digest-addressed artifact store, CLI) was proven (97+ tests) but a full
code-review of the generated-and-pushed surface surfaced 29 verified findings
(6 blocking): stale-lock availability DoS, torn-journal read race, package_id
path-traversal read oracle, O(J²) artifact verification, a silently dropped
CI contract gate, and ADR-0001 packaging drift.

The operator decided to use this review as the basis for a **wholesale
clean-slate update** that signals a clean break from Process Engine
development, rather than another incremental v0.1.x release.

## Decision

- **Version reset to 2.0.0.** Method Factory is no longer a Process Engine
  derivation under its versioning; `2.0.0` signals the clean break. Tag:
  `v2.0.0`.
- **All 29 verified review findings are remediated** (test-first where
  behavior changes; regression tests committed with the fixes).
- **Legacy quarantine executed** (ADR-0009 amendment): all migrated Process
  Engine material lives under `evidence/process-engine/`; nothing deleted.
- **Documentation aligned** across README, CHANGELOG, architecture,
  migration narrative, action-envelope contract, prompts, and ADRs so the
  repo describes exactly what v2.0.0 does (INTAKE → DRAFT_READY slice) and
  clearly marks Review/Trial/Ship/Triage as future phases.
- **Packaging implemented** (ADR-0001 amendment): `methodfactory` package,
  `mf` CLI entry point, `pyproject.toml`.
- **Process Engine remains the philosophical reference** at
  `RedEyeNinja-BKK/Process-Engine`; this repo's quarantine preserves the
  migrated snapshot as historical evidence.
- Publication (push to GitHub) is **operator-gated**: the tag exists locally
  and the operator reviews before deciding to publish.

## Consequences

- The v0.1.x tags (`v0.1.0-migration`, `v0.1.1-slice`, `v0.1.2-integrity`)
  remain in history as the pre-clean-slate record.
- Future lifecycle phases (Review/Trial/Ship/Triage, adapters, generator)
  build on a reviewed, packaged, quarantine-clean base.
- Versioning from here is Method Factory's own (`2.x`); Process Engine
  version numbers are historical only.
