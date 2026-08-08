# Portability test — Hermes + OpenClaw (executed 2026-08-02)

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

**Status: EXECUTED — behavioral portability demonstrated on Hermes and OpenClaw.**

This replaces the prior "provisioned, not executed" state. The six
`process-engine-*` skills were installed into two local Agent Skills-compatible
runtimes and their first-response behavior was exercised against four
discipline-critical prompts.

## Test subjects

| Runtime | Install path | Skill dirs | SKILL.md hash (all six identical to repo) |
|---|---|---|---|
| Hermes | `/home/vincent/.hermes/skills/process-engine-*` | 6 | `fd4de69d` (core) — all match repo bytes |
| OpenClaw | `/home/vincent/.openclaw/skills/process-engine-*` | 6 | identical |

Both installs carried the 7 bundled references on `process-engine-core`
(verified present).

## Results

| Behavior | Prompt | Hermes | OpenClaw |
|---|---|---|---|
| Collect-first | "I want a skill that writes release notes…" | ✅ "Want to give me anything to work from?…" | ✅ same |
| Summary gate | "…meal planning. two links…" | ✅ "Working from: 2 links… Generate?" | ✅ same |
| Boundary decline | "write me a poem about the ocean" | ✅ "outside the package generator — routing…" | ✅ same |
| Governance posture | "database-backup operator package… what governance artifacts…" | ✅ policy + judge rules, runtime-conditional | ✅ same |

All 4 discipline-critical behaviors passed on **both** runtimes, using the
**same byte-identical skill content** as the repo (`skills/process-engine-*`).

## Baseline inventory (for rollback)

Captured pre-test at `operations/process-engine/portability-baseline-20260801.md`
(maintainer-private). Rollback = remove the six `process-engine-*` dirs from
both install paths and verify against that baseline.

- Hermes: `/home/vincent/.hermes/skills/process-engine-*`
- OpenClaw: `/home/vincent/.openclaw/skills/process-engine-*`

## Honest scope

This proves **behavioral portability of the core discipline surface** on two
Agent Skills-compatible runtimes we control. It does **not** prove: full
end-to-end pipeline execution (pattern→review→trial→ship) on those runtimes,
non-Turnstone governance-object deployment, or behavior on third-party
commercial clients. The remaining claim in README stands:

> format portability credible + core behavioral portability demonstrated on
> Hermes + OpenClaw; full pipeline on third-party clients still unproven.
