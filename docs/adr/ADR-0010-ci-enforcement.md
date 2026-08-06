# ADR-0010 — CI and deterministic testing

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1 (Phase 4 rollout)

## Context

Current CI runs `python3 scripts/validate.py --repo . --no-diff || true`:
every validator failure is converted into success. Verified locally:
`validate.py --no-diff` exits 1 with 4 FAILs (eval run bundles reference
Process Engine commits absent from the fresh history). CI green is
bootstrap evidence, not integrity evidence.

## Decision

- The first real Method Factory gate **hard-fails** on at least:
  - invalid manifest or action-envelope schema
  - illegal state transition
  - state mutation outside the owning component (engine)
  - digest mismatch (manifest chain, artifact digests)
  - missing approval binding
  - stale active Process Engine identities in active paths
  - nondeterministic generated output (regenerate → diff must be empty)
- Test runner: stdlib `unittest` over `core/tests/` — no new runtime
  dependencies. CI: `python -m unittest discover -s core/tests -t .`.
- **No global `|| true`.** Legacy Process Engine evidence checks, if any
  remain, are explicitly quarantined or advisory with a named path
  allowlist.
- Real LLM runs never gate determinism. Core correctness is decided by
  deterministic tests with mock LLM / fixture envelopes; real-LLM behavior
  is a separate, non-blocking conformance channel.

## Consequences

- A red run means the repo genuinely violates a contract — not that a check
  was skipped.
- The identity sweep keeps the "clean slate" honest as content is rewritten
  in Phase 3.

## Amendment (v2.0.0 - 2026-08-06)

- Test runner path updated: `python -m unittest discover -s methodfactory/tests -t .`
  (package renamed from `core`).
- **Determinism gate** (see ADR-0002 amendment): while no generator exists,
  CI hard-fails on stray generated output (`workspace/`, `iteration-*/`)
  instead of regenerate→diff-empty. The drift check is restored when a
  generator lands.
- **Identity sweep** is a single case-insensitive pass over active paths
  (`methodfactory/`, `prompts/`, `docs/`, `README.md`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `.github/`) with `evidence/` exempt via explicit
  allowlist (never a global bypass). README/CHANGELOG intentional Process
  Engine pointer references are allowlisted line-by-line.
- **Supply chain:** actions pinned by full commit SHA; `permissions:
  contents: read`; pyyaml pinned via `requirements-dev.txt`.
