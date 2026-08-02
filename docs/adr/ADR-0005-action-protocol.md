# ADR-0005 — Structured prompt/code action protocol

**Status:** Accepted (2026-08-03, operator approval)
**Applies to:** Method Factory v0.1

## Context

Early drafts proposed free-form text markers like `ACTION: PROCEED_TO_AUTHOR`
parsed by regex as the model→code handoff. That is a direction, not a safe
interface: markers are vulnerable to accidental occurrence in user content,
instruction injection, parser ambiguity across markdown/code blocks, and
cannot bind an action to a package, revision, summary digest, or idempotency
key.

## Decision

- The prompt/code boundary is a **schema-validated JSON Action Envelope**,
  defined in `docs/action-envelope.md`. Essentials:
  - `protocol_version`, `action_id`, `package_id`, `expected_revision`,
    `action`, `basis`, `payload`
  - **Strict schema**: unknown top-level, `basis`, or `payload` fields are
    rejected; exactly one JSON object; malformed or multi-object input is
    `INVALID_ENVELOPE`.
  - `action_id` is idempotent: identical replay returns the recorded outcome
    without state change; reuse with a different payload is
    `ACTION_ID_REUSE`.
  - Prose is **never parsed** for state-changing intent. Model prose is
    conversation; transitions require the envelope.
- Typed tool calls (where a host supports them) are an **adapter binding of
  the same envelope**, not a separate domain protocol.
- The action vocabulary is a fixed enum: `record_input`, `set_objective`,
  `prepare_summary`, `confirm_summary`, `revise_intake`,
  `record_draft_artifact`, `cancel`.

## Consequences

- The LLM can never cause a transition by saying the right words; it can only
  propose a well-formed, revision-bound, schema-valid request.
- Injection strings and marker-like text inside content payloads are inert
  data (explicitly tested).
- Prompt reoptimization targets a stable interface and happens **after** the
  protocol is frozen.
