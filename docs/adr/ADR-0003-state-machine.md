# ADR-0003 — State machine and transition ownership

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

Process Engine described its lifecycle in prompts (core skill 220 lines of
prose enforcement). Method Factory must make the state machine deterministic
and code-owned: prompts propose, code transitions.

## Decision

- A **pure transition table** in code is the sole authority for what may
  happen next. Prompt wording never defines legality.
- v0.1 slice states (implemented now):

| State | Meaning | Legal actions |
|---|---|---|
| `INTAKE` | Intent recorded; inputs/objective being formed | `record_input`, `set_objective`, `prepare_summary`, `cancel` |
| `SUMMARY_PENDING` | Canonical summary frozen; operator confirmation required | `confirm_summary`, `revise_intake`, `cancel` |
| `AUTHORING_AUTHORIZED` | Summary confirmed and bound; authoring permitted | `record_draft_artifact`, `revise_intake`, `cancel` |
| `DRAFT_READY` | At least one digest-recorded draft artifact | `cancel` |
| `CANCELLED` | Terminal — operator cancellation | — |

- Declared for future phases (in the vocabulary, **not reachable in v0.1**):
  `REVIEW_PENDING`, `TRIAL_PENDING`, `SHIP_PENDING`, `SHIPPED`, `REJECTED`.
- **Triage is modeled separately** as a post-release workflow that references
  an immutable shipped package version. It is not a forward pipeline stage
  and never mutates released lifecycle state retrospectively.
- Confirmation is itself the authorization: `confirm_summary` both records
  the operator's binding to the summary digest and enters
  `AUTHORING_AUTHORIZED`.
- Re-opening after confirmation (`revise_intake` from `SUMMARY_PENDING` or
  `AUTHORING_AUTHORIZED`) returns to `INTAKE` and invalidates any approval —
  a new summary must be prepared and confirmed.

## Consequences

- Transition legality is unit-testable in isolation (no filesystem, no LLM).
- Skipped gates and out-of-order actions are impossible by construction.
- The assurance-tier concept from the evaluator era is excluded from v0.1.
