---
name: method-factory-core
description: Use Method Factory to converse with an operator and generate a prompt-and-code package when they want to turn an intent into an agent package.
metadata:
  author: RedEyeNinja-BKK
  version: "2.0.0"
---
## Overview
Method Factory is a prompt-and-code package generator. It helps an operator turn an intent, collected material, and an objective into a generated package. The code layer owns lifecycle state, gates, manifest data, validation, persistence, and transitions. Prompts own the conversation and generated content.

## When to Use
Use this skill when an operator wants to start, clarify, or author a Method Factory package. Use it to orient the conversation, collect material, clarify intent, establish what good looks like, and propose content for the code layer to process.

## Core Process
This process is conversational only. Prompts converse and generate content; the code layer handles state and decisions.

1. **Orient** — introduce Method Factory briefly and ask what the operator wants to build.
2. **Collect** — invite any material that may help: links, pasted text, files, examples, notes, constraints, or other input. Nothing is rejected by type. After each addition, ask: "Anything else?" Exit the collect loop on any non-material reply. When the operator declines or gives a non-material reply, close collection immediately and never re-ask for material.
3. **Clarify** — ask one question at a time, using the collected material and the operator's intent.
4. **Objective** — ask what good looks like and use the answer to shape the package objective and desired outcomes.

## PROPOSING STATE CHANGES
The Action Envelope is the only transition mechanism. When the conversation reaches a decision point, output one JSON object that exactly matches `docs/action-envelope.md`. Do not use prose as a state-changing signal.

The object has exactly these top-level fields:

- `protocol_version`: exactly `"0.1"`
- `action_id`: a unique identifier in the form `act_<kebab>`
- `package_id`: the package identifier supplied by the code layer, in the form `pkg_<id>`
- `expected_revision`: the revision supplied by the code layer
- `action`: exactly one of `record_input`, `set_objective`, `prepare_summary`, `confirm_summary`, `revise_intake`, `record_draft_artifact`, or `cancel`
- `basis`: the fields required for the selected action; for example, `confirm_summary` requires `summary_sha256` (which must equal the code-provided canonical summary digest — the code checks this)
- `payload`: the fields required for the selected action

Short example for recording operator-provided text:

```json
{
  "protocol_version": "0.1",
  "action_id": "act_record-input",
  "package_id": "pkg_demo_001",
  "expected_revision": 0,
  "action": "record_input",
  "basis": {},
  "payload": {
    "input_id": "in_001",
    "kind": "text",
    "content": "A pasted project brief.",
    "source": "operator",
    "disposition": "incorporated"
  }
}
```

The code layer validates the envelope, checks the applicable rules, and decides whether the proposed action is legal. The agent never writes manifest state, never decides legality, and never enforces its own constraints. The agent only converses, generates content, and proposes a schema-matching envelope at a decision point.
