# Process Engine v1.8.2 mirrored release bundle

This bundle `release-v1.8.2-r1` records two independently sourced final-release
sub-runs under the mirrored-dual-source protocol, bound to the v1.8.2 release
commit `043a887360617769a0919fee780d769e7149527a`.

| Sub-run (executor=Turnstone) | Verifier | Model | Window (Asia/Bangkok) | Result |
|---|---|---|---|---|
| run-a-hermes-exec | openclaw-main | gpt-5.6-terra | 2026-08-02 05:54:25 → 07:45:47 | 34 PASS / 0 FAIL |
| run-b-openclaw-exec | hermes-gateway | gpt-5.6-terra | 2026-08-02 06:06:31 → 07:53:57 | 34 PASS / 0 FAIL |

Every assertion is derived by the schema-bound evaluator (`scripts/evaluate.py`)
from the immutable `actual/` transcripts: deterministic assertions (regex /
predicate) replay mechanically; semantic assertions (`no-assumption`,
`plain-answer`) carry judge proof payloads (model, rubric hash, prompt hash,
confidence, rationale). All 86/86 assertions per sub-run PASS
(172/172 across both). `hashes.json` seals transcript SHA-256 values;
`manifest.json` binds each run to the release commit, engine version 1.8.2,
measured per-run timestamps, and the sealed package hash
`7f57444b29cc14ffb44c6efdd67e5adddc43df3c36f0c5fac24c2010b7ca7d05`.

Baseline: `not-executed` for this run; the v1.8.2 behavior comparison uses the
preserved v1.8.1-era generic baseline (see trial-evidence.md).

Evidence layout: `actual/` write-once transcripts, `hashes.json` SHA-256 seals,
`assertions.jsonl` evaluator-derived results, `cases.json` evaluated prompts,
`summary.json` per-case verdicts with bundle-relative evidence links,
`environment.json` model/hash snapshot.
