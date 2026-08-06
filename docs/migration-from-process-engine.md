# Migration from Process Engine

This document records how Method Factory came to exist and how the Process
Engine material in this repository is treated. It is historical narrative,
not a contract. Contracts live in `docs/adr/`.

## Origin

Method Factory is the prompt+code successor to Process Engine. Process
Engine proved a gated authoring pipeline through prompt-only experimentation
(split point: v1.6.0 at `69de7bc`) and a real end-to-end case study. The
evaluator era (v1.7.0 → v1.9.1) became the specification for the code layer.

On 2026-08-03 this repository was seeded from the Process Engine v1.9.1
snapshot (`240520e`) as `v0.1.0-migration` (`cd2767f`). Method Factory was
developed from that snapshot: contracts frozen (ADR-0001..0010), vertical
slice built (`b7d5dca`), prompts reoptimized (`49b6756`), CI hard gate
(`6c2fc58`), integrity reconciliation (`fb5641c`, tagged `v0.1.2-integrity`).

## v2.0.0 clean slate (2026-08-06)

A full code-review of the generated-and-pushed surface produced 29 verified
findings (6 blocking). The operator directed a wholesale clean-slate update:

- version reset to **2.0.0**, signalling a clean break from Process Engine
  development (ADR-0011);
- all 29 findings remediated with regression tests;
- legacy quarantine executed (ADR-0009);
- documentation aligned (this document, README, CHANGELOG, architecture,
  action-envelope spec, prompts).

The v0.1.x tags remain in git history as the pre-clean-slate record.

## What was quarantined

All migrated Process Engine material now lives under
[`evidence/process-engine/`](../evidence/process-engine/), **nothing was
deleted**:

| Path | What it is |
|---|---|
| `evals/` | 34 historical cases + runs (evaluator-era evidence) |
| `scripts/` | convert/validate/evaluate/trial tooling (historical reference) |
| `skills/` | six Process Engine skills (reference content) |
| `templates/` | six session starters |
| `references/` | seven reference docs incl. governance |
| `persona.md`, `process-engine.toml` | PE identity and release manifest |
| `docs/` (subset) | package-manifest-schema, provenance-schema, evaluator-freeze-policy, governance-usage, spec-compliance, standards, portability tests |

Active Method Factory content does not reference quarantined paths except
through this narrative (ADR-0009).

## Process Engine remains the reference

Process Engine itself continues at
[`RedEyeNinja-BKK/Process-Engine`](https://github.com/RedEyeNinja-BKK/Process-Engine)
(v1.9.5-prompt-only) as the philosophical anchor. This repo's quarantine is
for the migrated snapshot, not a replacement for the reference.
