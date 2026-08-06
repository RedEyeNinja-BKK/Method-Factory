# ADR-0001 — System boundary and executable form

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

Method Factory is the prompt+code successor to Process Engine. The code layer
must own state, transitions, gates, manifest persistence, integrity checks,
and eventually trial execution — deterministically and platform-agnostically.
The prior Process Engine release tooling lives in `scripts/` and is evaluator
era; it must not be the boundary for the new code layer.

## Decision

- Method Factory ships as a **Python package `methodfactory`** plus a thin
  **`mf` CLI** and a **library API**. No long-running service in v0.1.
- The **core is stdlib-only** (dataclasses, json, hashlib, pathlib). No
  third-party runtime dependencies. This is a portability guarantee, not a
  convenience.
- The CLI is a thin adapter over the engine; all behavior lives in the
  library so tests drive the engine directly.
- Runtime adapters (filesystem, git, Turnstone, Hermes, OpenClaw) attach
  through defined interfaces (ADR-0007). Adapters are never required by the
  core.

## Consequences

- Deterministic, dependency-light, testable on any Python 3.11+.
- CLI surface can evolve without changing core semantics.
- A service (HTTP/daemon) is explicitly deferred; if needed later it is an
  adapter, not a core change.

## Amendment (v2.0.0 - 2026-08-06)

- Packaging implemented: `pyproject.toml` with console_scripts entry
  `mf = methodfactory.cli:main`; the top-level package is `methodfactory`
  (renamed from the staging name `core` to remove the collision-prone
  import name). `methodfactory.__version__ == "2.0.0"`.
- No third-party runtime dependencies confirmed; tests remain stdlib
  `unittest` (pyyaml is a CI-only dev dependency for prompt frontmatter
  fixtures).
