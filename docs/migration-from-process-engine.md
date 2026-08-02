# Migration from Process Engine

**Date:** 2026-08-03  
**Source:** [Process Engine](https://github.com/RedEyeNinja-BKK/Process-Engine) at tag `v1.9.1` — commit `240520e`  
**Split point:** Process Engine at commit `69de7bc` — the version behind the [Etsy store case study](https://github.com/RedEyeNinja-BKK/Process-Engine/blob/main/evals/case-study-first-run.md)

---

## Why the split?

Process Engine was built as a prompt-only system. The core skill began at 92 lines — a clean pipeline: Orient → Collect → Clarify → Objective → Summary Gate → Route. That version produced a successful end-to-end package for an Etsy store.

What followed was the evaluator era. The core skill grew to 220 lines — most of that growth was enforcement logic: First-Response Discipline rules, governance boilerplate, manifest mechanics, tier systems. The prompts were doing the code's job.

The split separates two concerns:

1. **Process Engine** — stripped back to its early essence. Prompts only, Turnstone-native. The philosophical reference.
2. **Method Factory** — takes the domain knowledge from the full evaluator-era Process Engine and adds a code layer for deterministic enforcement, lighter prompts, and platform-agnostic operation.

---

## What migrated

| From Process Engine | Purpose in Method Factory |
|---|---|
| All 6 skills | Source material for prompt+code design |
| All 7 references | Portable knowledge — unchanged |
| All 6 templates | Adapted for new paradigm |
| `scripts/convert.py` | Code — pipeline foundation |
| `scripts/validate.py` | Code — deterministic enforcement |
| `scripts/evaluate*.py` | Reference for code-based evaluation design |
| `scripts/test_*.py` | Reference for deterministic test patterns |
| `evals/` (34 cases, runs) | Historical evidence |
| `docs/portability-test-*` | Portability design reference |
| `docs/package-manifest-schema.md` | Becomes code-enforced manifest schema |
| `docs/evaluator-freeze-policy.md` | Historical record |
| `docs/provenance-schema.md` | Design reference |
| `docs/spec-compliance.md` | Design reference |
| `.github/workflows/release-gate.yml` | CI foundation (adapted for Method Factory) |
| `CHANGELOG.md` | Full history preserved |
| `persona.md` | Reoptimized for new paradigm |

---

## What stayed in Process Engine

Process Engine was stripped back to its early core — the pipeline, routing, and gate. No First-Response Discipline, no governance canon, no manifest mechanics, no tier system, no evaluator. All enforcement responsibility moved to Turnstone's native governance mechanisms (prompt policy, advisory judge). The case study remains as the origin story.

---

## Design principles

1. **Code owns the state machine** — phase transitions, gate checks, manifest I/O
2. **Prompts own the conversation** — tone, clarifying questions, content generation
3. **Platform-agnostic** — not bound to Turnstone governance
4. **Clean slate** — fresh git history, no evaluator baggage
5. **Process Engine is the reference** — always go back to it when in doubt
