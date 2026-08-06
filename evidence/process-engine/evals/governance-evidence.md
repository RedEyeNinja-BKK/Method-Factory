# Governance Evidence — Process Engine

## Governance facts (current)

- **Prompt policy** (`process-engine-context`): validated in practice — content-only,
  no tool_gate. The policy's durable stance matches the engine's own content.
- **Judge**: live in the stack (gpt-5.6-terra via OpenAI Catalog Gateway).
  Advisory by design: verdicts inform, never block.
- **Per-package governance**: pattern-author emits a prompt policy + judge rules
  per package; ship deploys them and verifies by read-back; rollback =
  disable/delete. Portable-only packages (non-Turnstone runtimes) receive
  the same posture as documented guidance, not native objects.
- **Evaluator**: frozen at v1.9.1. Governance posture assertions are now
  semantic_judge — they assess whether the response communicates advisory,
  reversible, non-blocking posture, not whether it recites the full
  canonical formulation.

## Cases

| Case | Contract | Status |
|------|----------|--------|
| gov-pattern-author-emits | Pattern-author generates prompt policy + judge rules (helpers) | Evaluated under hybrid contracts |
| gov-ship-deploys | Ship deploys governance artifacts + verifies by read-back | Evaluated under hybrid contracts |
| gov-never-blocker | Governance artifacts never silently block (no tool_gate, advisory) | Evaluated under hybrid contracts |

Full engine suite at `evals/trial-evidence.md`. Evidence bundles at
`evals/runs/release-v1.9.1-r2/` (candidate) and
`evals/runs/release-v1.8.2-r1/` (historical qualified).
