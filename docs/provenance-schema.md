# Canonical Provenance Schema

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

**Version:** 1.9.0

This document defines the single authoritative provenance contract for an
individual evaluation case. A release bundle contains one `provenance.json`
object per sub-run, keyed by `case_id`; each key has exactly one provenance
record. The file is JSON, and all paths in records are relative to the
containing sub-run bundle.

## Record

```json
{
  "case_id": "trigger-should-4",
  "run_id": "<unique-run-id>",
  "workstream_id": "<runtime-workstream-id>",
  "prompt_path": "cases/<case-id>.json",
  "prompt_sha256": "<sha256>",
  "prompt_submitted_at": "<ISO-8601>",
  "assistant_message_id": "<message-id>",
  "assistant_message_ordinal": 2,
  "assistant_text_path": "actual/<case-id>.txt",
  "assistant_text_sha256": "<sha256>",
  "assistant_text_chars": 412,
  "assistant_received_at": "<ISO-8601>",
  "prior_user_message_count": 1,
  "prior_assistant_message_count": 0,
  "tool_calls_before_response": 0,
  "raw_history_path": "raw-history/<case-id>.json",
  "raw_history_sha256": "<sha256>",
  "capture_status": "PASS"
}
```

The checked-in v1.9.1 capture uses the equivalent compact field names
`msg_ordinal`, `text_chars`, `retrieved_ts`, and `ws_id`; these are aliases for
`assistant_message_ordinal`, `assistant_text_chars`, `assistant_received_at`,
and `workstream_id`, respectively. New captures should use the canonical names;
the validator accepts the release-compatible aliases.

## Semantics and capture rules

- **First response:** the evaluated artifact is the first assistant text
  message, at message ordinal **2**: one user prompt followed by the assistant
  response in a clean-context session. `assistant_message_ordinal` is the
  ordinal of that first assistant message, not the number of tool events.
- **Assistant text:** `assistant_text_path` points to the exact text captured
  from ordinal 2. It is the artifact evaluated by assertions. Tool-call
  arguments and tool results are not assistant text and must not be silently
  concatenated into it.
- **Tools and raw history:** tool calls and their results are represented in
  the per-case raw history JSON (`raw-history/<case-id>.json`) as the original
  ordered message/event objects. `tool_calls_before_response` counts calls
  before the ordinal-2 text response. Raw histories are JSON, and their
  SHA-256 is recorded.
- **Approvals:** operator approvals are represented by approval events in raw
  history and counted/recorded by the capture system; they do not change which
  assistant message is evaluated.
- **Retries:** a retry is a new unique `run_id` and a new provenance capture.
  It must not overwrite the prior run or reuse its workstream identity. If a
  case is retried within an operational session, preserve each attempt in raw
  history and identify the selected evaluated attempt explicitly; the bundle's
  one record remains the attempt whose ordinal-2 response is evaluated.
- **Failed or empty response:** record the attempt with `capture_status` set to
  `FAIL` (known capture/evaluation failure) or `INCOMPLETE` (missing evidence).
  Preserve raw history when available, use zero for `assistant_text_chars` when
  no text exists, and do not manufacture a transcript. An empty/placeholder
  response cannot qualify as PASS.
- **Identity:** `run_id` is unique per sub-run capture and `workstream_id` is
  present and unique across all cases in that sub-run. Duplicate workstream IDs
  are rejected because they make case isolation and provenance attribution
  unverifiable.
- **Immutability:** all provenance fields are immutable after capture,
  including hashes, IDs, paths, ordinals, counts, status, and message times.
  Only retrieval timestamps (`retrieved_ts`, or the canonical
  `assistant_received_at` when it is explicitly a retrieval timestamp) may be
  refreshed by evidence collection; refreshes must not alter captured content
  or identity.
- **Bundle-relative paths:** `prompt_path`, `assistant_text_path`, and
  `raw_history_path` are bundle-relative and must resolve inside the sub-run.
  Absolute paths and traversal outside the bundle are invalid.

## Completeness statuses

`PASS` requires one record for every case in the eval set, ordinal 2, non-empty
text, matching transcript size and hash, present retrieval timestamp, unique
workstream ID, and available raw-history evidence. Use `INCOMPLETE` when one or
more required capture fields/evidence are missing. Use `FAIL` when capture
occurred but the response or integrity check failed. Use `UNVERIFIABLE` when
the evidence exists but cannot establish that the text is the ordinal-2
response (for example, a missing/invalid raw history or ambiguous duplicate
identity). The validator rejects incomplete, mismatched, failed, and
unverifiable case records from a strict release bundle.

A provenance file must contain exactly one entry per eval `case_id`; extra,
missing, or duplicate entries are invalid. The validator independently checks
the transcript file size and identity constraints rather than trusting the
provenance claims.

## Example location

```text
evals/runs/release-v1.9.1-rN/run-a-hermes-exec/provenance.json
```

`provenance.json` is a single file at the sub-run root, keyed by `case_id`.
When the cluster-API capture tool (`scripts/capture_workstream.py`) is used,
raw histories are stored at `raw-history/<case-id>.json`; when MCP-gateway
capture is used (Hermes `hermes_chat` / OpenClaw `openclaw_agent_run`), raw
histories are preserved in the capture metadata but raw-history files may not
be present in the bundle. Both paths produce identical provenance records.

Run A and Run B have different verifier roles: the executor is Turnstone, while
Run A is verified by OpenClaw and Run B by Hermes. This role separation is
recorded in each sub-run `manifest.json` and is not inferred from directory
names alone.

> Provenance is evidence, not a verdict. Assertions and summary verdicts remain
> separate artifacts; provenance establishes which response was evaluated and
> whether that response can be independently traced.

## Field mapping

| Canonical field | v1.9.1 compact field | Meaning |
|---|---|---|
| `workstream_id` | `ws_id` | Runtime workstream identity; unique per case |
| `assistant_message_ordinal` | `msg_ordinal` | Must be `2` |
| `assistant_text_chars` | `text_chars` | Exact captured transcript file size |
| `assistant_received_at` | `retrieved_ts` | Evidence retrieval timestamp |

All hashes are lowercase hexadecimal SHA-256 values over the referenced bytes.
Timestamps are ISO-8601, preferably with an explicit UTC offset.

