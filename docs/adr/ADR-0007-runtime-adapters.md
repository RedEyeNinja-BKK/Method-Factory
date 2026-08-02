# ADR-0007 — Runtime adapter boundary

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

Process Engine's migrated runtime is Turnstone-bound: `run_trials.py` embeds
a local API URL, token file, project/persona/skill IDs, and
`references/governance.md` embeds Turnstone API endpoints. "Platform-agnostic"
would remain documentation-only if core logic depended on any of that.

## Decision

- The portable core depends only on narrow interfaces:

| Interface | Responsibility |
|---|---|
| `ManifestStore` | `load(package_id)`, `compare_and_swap(...)`, `append_event(...)` |
| `ArtifactStore` | `put(content) -> digest`, `get(digest)`, `verify(digest)` |
| `ConversationAdapter` | request a structured action envelope from a model (host binding) |
| `RuntimeAdapter` | `prepare_artifact`, `deploy`, `read_back` (future phases) |

- **Core owns:** domain types, transition table, manifest validation and
  revisioning, gate predicates, envelope validation, artifact-digest
  verification, audit event construction.
- **Adapters own:** operator interaction surface, LLM/tool transport,
  filesystem/git materialization, Turnstone/Hermes/OpenClaw invocation,
  credentials, model selection, deployment read-back.
- Turnstone governance is a **Turnstone adapter capability**, never a
  portable package requirement. Migrated `references/governance.md` content
  is quarantined as reference-only until an adapter owns it.

## Consequences

- The same package lifecycle runs identically on filesystem, git, Turnstone,
  Hermes, or OpenClaw by swapping adapters.
- Adapter success is never treated as domain truth: a transition completes
  only when the core has verified the recorded outcome (e.g. read-back
  verification in Ship).
