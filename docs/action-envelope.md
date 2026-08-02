# Action Envelope — Prompt/Code Protocol v0.1

**Status:** Accepted (2026-08-03, operator approval)
**Authority:** The envelope is the **only** way the model (or any caller)
proposes a state-changing action. Prose is never parsed for state-changing
intent. Typed tool calls are adapter bindings of the same envelope.

## Envelope

```json
{
  "protocol_version": "0.1",
  "action_id": "act_01HXYZ...",
  "package_id": "pkg_demo_001",
  "expected_revision": 7,
  "action": "confirm_summary",
  "basis": {
    "summary_sha256": "abc123..."
  },
  "payload": {
    "operator_id": "vincent"
  }
}
```

## Parsing rules

- Exactly **one JSON object**. Strict parse of the whole string first; if
  that fails, the text between the first `{` and the last `}` is tried
  (tolerates conversational prose around the structured block from
  transports that mix prose and structure). Multiple JSON objects,
  unparseable text, or a non-object → `INVALID_ENVELOPE`.
- **Strict schema:** the seven fields are required; unknown top-level,
  `basis`, or `payload` fields are rejected (`INVALID_ENVELOPE`).
- `protocol_version` must equal `"0.1"`.
- `action_id`: non-empty string, ≤64 chars.
- `package_id`: `^pkg_[A-Za-z0-9_-]{1,63}$`.
- `expected_revision`: non-negative integer.
- `action`: one of the fixed vocabulary (below). Unknown value →
  `INVALID_ENVELOPE`.
- `basis`, `payload`: objects (may be empty). Field allowlists per action
  below.

## Action vocabulary (v0.1 slice)

| Action | From → To | `basis` fields | `payload` fields |
|---|---|---|---|
| `record_input` | INTAKE → INTAKE | — | `input_id`, `kind` (`text\|url\|file-reference\|constraint`), `content` (str), `source` (`operator\|adapter`), `disposition` (`incorporated\|excluded`), `exclusion_reason` (required if excluded) |
| `set_objective` | INTAKE → INTAKE | — | `statement` (str, required), `desired_outcomes` (list[str]) |
| `prepare_summary` | INTAKE → SUMMARY_PENDING | — | — |
| `confirm_summary` | SUMMARY_PENDING → AUTHORING_AUTHORIZED | `summary_sha256` (required, must equal `summary.canonical_sha256`) | `operator_id` (optional, default `"operator"`) |
| `revise_intake` | SUMMARY_PENDING \| AUTHORING_AUTHORIZED → INTAKE | — | — |
| `record_draft_artifact` | AUTHORING_AUTHORIZED → DRAFT_READY | — | `artifact_id`, `kind`, `logical_path` (relative, no `..`, no absolute), `content` (str) |
| `cancel` | any non-terminal → CANCELLED | — | `reason` (optional) |

`prepare_summary` is how the code freezes the canonical summary: it renders
deterministic text from manifest state, computes `canonical_sha256`, sets
`presented_at`, and transitions to `SUMMARY_PENDING`.

## Gate predicates (checked before any write)

- `record_input`: `input_id` unique; excluded input requires a reason.
- `set_objective`: non-empty statement.
- `prepare_summary`: intent present **and** objective present.
- `confirm_summary`: a summary exists and `basis.summary_sha256` equals
  `summary.canonical_sha256` (else `STALE_ACTION`).
- `record_draft_artifact`: confirmation is `confirmed` and bound to the
  current summary digest (else `GATE_UNSATISFIED`); valid `logical_path`.
- `revise_intake` / `cancel`: no additional gate.

## Idempotency and reuse

- Reapplying an envelope with an already-seen `action_id` and identical
  content replays the recorded outcome (no state change).
- Reusing `action_id` with different content → `ACTION_ID_REUSE`.

## Error semantics (summary)

| Code | When |
|---|---|
| `INVALID_ENVELOPE` | malformed JSON, schema violation, unknown field/action |
| `ILLEGAL_TRANSITION` | action not legal in current state |
| `GATE_UNSATISFIED` | required evidence missing |
| `STALE_ACTION` | `expected_revision` mismatch or approval digest mismatch |
| `ACTION_ID_REUSE` | action_id reused with different payload |
| `INVALID_PAYLOAD` | semantic payload violation |

Full error and recovery behavior: ADR-0008.
