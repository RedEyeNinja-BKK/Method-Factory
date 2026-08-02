# Contributing

Feedback and contributions are welcome. This project is managed by the engine's own process: **Pattern → Review → Trial → Ship**, and every change to the engine itself is gated the same way.

## How feedback is triaged

Incoming feedback is categorized by the `process-engine-triage` skill:

| Category | Meaning | Action |
|---|---|---|
| **BUG** | A generated package performs wrong, or the engine violates its own standards | Route to pattern-author (fix) + trial (regression) |
| **DESIGN** | An experience flaw in the engine or its output | Draft a process/artifact revision → review |
| **IDEA** | A new capability or generated package idea | Log to roadmap; propose to the maintainer |
| **SAFETY** | A risk/scope/safeguard-adjacent report | Highest priority; reviewed immediately |

## The bar for changes

- **Evidence-named** — every technique cites its real source; never "research shows" without a citation.
- **Scope-honest** — no claims beyond what named sources support.
- **Acceptance criteria** — every artifact carries explicit exit criteria; "seems right" is never sufficient.
- **Spec-valid** — generated skills comply with the Agent Skills open format standard.
- **Tried before shipped** — case sets, baselines, recorded evidence. No trial, no ship.

## Review gates

- Nothing ships without operator review. Draft → sign-off → create/deploy → verify.
- No public reply to feedback without maintainer sign-off.
- No self-approval.

## Getting started

1. Open an issue or discussion describing what you're building or what broke.
2. The engine (or a maintainer) will route it and work it through the pipeline.
3. If you're submitting code or content directly: fork, branch, open a PR — and be ready to show evidence (tests, trials, read-back) that the change meets the bar above.
