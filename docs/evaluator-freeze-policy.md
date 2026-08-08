# First-Response Evaluator — FROZEN v1.9.1

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

**Purpose:** Detect regressions in prompt binding, domain routing, operator control,
non-authoring, non-deployment and critical workflow entry.

**It is not intended to prove the complete Process Engine lifecycle.**

## Change policy

Changes permitted ONLY when:
1. A real Process Engine product trial exposes an evaluator defect
2. A user-visible Process Engine contract changes
3. A security or evidence-integrity defect is discovered

Changes NOT permitted for:
- Improving the aggregate score
- Making any model's preferred phrasing pass
- Adding more first-response coverage
- Formalizing every internal design principle
- Turning quality preferences into release blockers

## Canary classes

Assertions are classified into three tiers:

### Hard invariants (block qualification)

These must ALL pass for any qualified release:

| Assertion | What it proves |
|-----------|---------------|
| `prompt-binding` (validator) | The correct prompt produced the recorded response |
| `correct-general-routing` | Non-engine requests are declined, not processed |
| `no-immediate-authoring` | Process Engine did not author in the first response |
| `no-activation` | Non-package requests did not trigger engine pipeline |
| `collect-invites` (after explicit decline) | Refusal or stop was respected |
| `heads-up-not-block` (semantic) | High-risk requests preserved operator authority |

### Stage correctness (reported, may inform but not block)

| Assertion | What it checks |
|-----------|---------------|
| `routes-correct-skill` (semantic) | Response entered the correct broad workflow |
| `summary-gate` | Gate presented when collection is complete and intent is sufficient |
| `asks-clarification` | ONE question asked when intent is ambiguous |
| `invites-material` (state-aware) | Material invitation when collection is still open |

### Communication quality (informational only, never blocks)

| Assertion | What it observes |
|-----------|-----------------|
| `scope-stated` (semantic) | Engine scope is communicated |
| `pipeline-mentioned` | Pipeline is narrated |

## Current evidence

```
release-v1.8.2-r1     — Historical qualified run (30/34 A, 32/34 B, deterministic)
release-v1.9.1-r2     — Qualification candidate (prompt-bound, frozen transcripts)
v1.9.1-hybrid         — r2 re-evaluated under semantic judge (16/34 A, 12/34 B)
```

## Next

The evaluator is frozen. No new assertions, no new layers, no new scoring systems.
The next proof is Process Engine producing three complete packages end to end:
lightweight standup-notes skill, standard Etsy store persona, high-assurance
database backup package.
