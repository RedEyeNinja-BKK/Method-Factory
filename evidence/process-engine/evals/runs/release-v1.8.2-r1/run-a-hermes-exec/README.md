# run-a-hermes-exec evidence

This immutable release-evidence sub-run is `release-v1.8.2-r1-run-a-hermes-exec` for
Process Engine v1.8.2. Mirrored-dual-source protocol: executor
`turnstone-orchestrator` performed the case work; verifier `openclaw-main` recorded
the final judgments using model `gpt-5.6-terra`. Measured window
2026-08-02T05:54:25+07:00 through 2026-08-02T07:45:47+07:00 (Asia/Bangkok, from transcript file timestamps); final
result: 34 PASS / 0 FAIL / 0 PENDING (86/86 derived assertions, judge-backed
semantic rows).

Evidence layout: `actual/` holds write-once transcripts, `hashes.json` seals
their SHA-256 values, `assertions.jsonl` records evaluator-derived assertion
results with proof payloads, `cases.json` preserves evaluated prompts, and
`summary.json` exposes per-case verdicts with bundle-relative evidence links.
The manifest binds this run to commit 043a887 (v1.8.2) and hashes the exact
prompt and package inputs. Transcript files are immutable: recorder attempts
to replace an existing transcript fail loudly.
