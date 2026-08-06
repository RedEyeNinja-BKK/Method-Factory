# Contributing

Feedback and contributions are welcome. Method Factory v2.0.0 is a clean
slate: the active tree is `methodfactory/` (code), `prompts/` (conversation
content), and `docs/` (contracts + ADRs). The migrated Process Engine
snapshot is historical evidence under `evidence/process-engine/` and is not
part of active development.

## How feedback is triaged

| Category | Meaning | Action |
|---|---|---|
| **BUG** | The core performs wrong, or violates its own contracts | Regression test first, then fix (ADR-0008 fail-fast discipline) |
| **CONTRACT** | A proposal changes a frozen contract (ADR, manifest, envelope) | ADR amendment or new ADR + operator approval before implementation |
| **IDEA** | A new capability or generated-package idea | Roadmap proposal; review before scope |
| **SAFETY** | Risk/scope/security-adjacent report | Highest priority; reviewed immediately |

## The bar for changes

- **Contracts precede implementation.** Contract changes require
  documentation, tests, migration consideration, and operator approval
  (ADR-0011).
- **Tests as proof.** Behavior changes and defect fixes are test-first;
  the full `unittest` suite must stay green.
- **Code review.** Every code-bearing change passes the code-review family
  before merge (bug/security/performance/quality → verify → dedupe →
  sanity).
- **No enforcement in prompts.** Prompts converse and propose via Action
  Envelopes; code validates, authorizes, persists, and verifies.
- **Scope-honest docs.** README/CHANGELOG/architecture describe exactly what
  the current slice does; Review/Trial/Ship/Triage are marked future.

## Review gates

- Nothing ships without operator review. In v2.0.0 the operator confirmation
  of the canonical summary is the enforceable gate (digest-bound approval).
- Publication (push) is operator-gated (ADR-0011).
- No self-approval.

## Getting started

```bash
python -m unittest discover -s methodfactory/tests -t .   # full suite
pip install -e .                                          # installs mf
```
