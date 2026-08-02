# Run Bundle — run-20260731-001 (development history)

This bundle is the **development-history** evidence for the Process Engine
v1.8.0 evaluation campaign. It is superseded for release qualification by
`evals/runs/release-v1.8.0-d2e6bc4/` (the sealed release-candidate run against
commit `d2e6bc4`).

## What this bundle contains

- **`manifest.json`** — run metadata: engine version, executor + judge models,
  commit binding, counts, iteration history.
- **`cases.json`** — the 34 case prompts + expected behaviors.
- **`actual/`** — per-case executor transcripts (`<case-id>.txt`).
- **`assertions.jsonl`** — per-case assertion results (81 rows, 34 cases).
- **`judgments.jsonl`** — per-case judgments across iterations (executor +
  judge + reasoning).
- **`summary.json`** — final per-case verdicts (34 PASS / 0 FAIL / 0 PENDING)
  with evidence links.
- **`environment.json`** — executor model + repo head at capture time.

## How to read it

- **Final verdicts** come from `summary.json` (the last judgment per case).
- **Iteration history** (16/14/4 → 26/8/0 → 34/0/0) is preserved in the
  manifest and `judgments.jsonl` — earlier FAIL/PENDING rows are historical,
  not final.
- **Known limitation:** this bundle's recorded commit (`cc549f6`) predates
  the v1.8.0 release commits; transcripts were captured as the content
  evolved. It is development evidence, not a release seal.

## For release qualification

See the sealed run at `evals/runs/release-v1.8.0-d2e6bc4/` — a fresh,
immutable, dual-source (Run A / Run B mirrored) 34-case evaluation against
the exact release commit, with per-iteration transcripts and independent
judge verification.
