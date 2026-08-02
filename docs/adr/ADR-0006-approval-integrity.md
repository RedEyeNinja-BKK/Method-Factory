# ADR-0006 — Artifact identity, hashes, and operator-approval binding

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

The evaluator-era model let the LLM read/write manifests and trusted supplied
hashes. For Method Factory, an operator approval is only meaningful if it is
bound to an exact, immutable artifact — and hashes must be evidence, not
assertions.

## Decision

- **All hashes are computed by code from canonical bytes.** Hash values in
  payloads are rejected as unknown fields; the code recomputes and compares.
- **Operator confirmation binds the summary digest.** `confirm_summary`
  requires `basis.summary_sha256 == summary.canonical_sha256`, where
  `canonical_sha256 = sha256(summary.content bytes)`. The operator confirms
  exactly the text that is hashed.
- **Editing intent/objective after confirmation invalidates authorization.**
  From `SUMMARY_PENDING` or `AUTHORING_AUTHORIZED`, `revise_intake` returns
  to `INTAKE` and clears the confirmation; a new summary must be prepared and
  confirmed before any authoring action.
- Artifact identity: `artifact_id` + `logical_path` + `kind` + code-computed
  `sha256` + `byte_count`. The manifest references artifacts by digest;
  artifact content is stored via the ArtifactStore adapter.

## Consequences

- A stale approval can never authorize a different summary or artifact.
- Tampering with a manifest or artifact is detectable on load (digest chain,
  ADR-0008).
- The model cannot launder its own output into "approved" state by supplying
  hashes.
