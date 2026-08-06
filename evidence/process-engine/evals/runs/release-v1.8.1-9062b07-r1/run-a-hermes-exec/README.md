# run-a-hermes-exec evidence

This immutable release-evidence sub-run is `release-v1.8.1-9062b07-r1-run-a-hermes-exec` for Process Engine v1.8.1. It follows the mirrored-dual-source protocol: executor `turnstone-orchestrator` performed the case work and verifier `openclaw-main` recorded the final judgments using model `gpt-5.6-terra`. The recorded window is 2026-08-01T19:21:55+00:00 through 2026-08-01T21:13:07+00:00; final result: 34 PASS / 0 FAIL / 0 PENDING.

Evidence layout: `actual/` holds write-once transcripts, `hashes.json` seals their SHA-256 values, `judgments.jsonl` preserves judgment history, `assertions.jsonl` records deterministic checks, `cases.json` preserves evaluated prompts, and `summary.json` exposes the final per-case evidence links. The manifest binds this run to the passed commit and hashes the exact prompt and package inputs. Transcript files are immutable: recorder attempts to replace an existing transcript fail loudly.
