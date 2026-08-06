# Contamination Audit — Process Engine v1.8.2-r1

## Disposition

Evidence integrity review identified contaminated or unverifiable first-response evidence. Every case listed below is marked **FAIL** in its run `summary.json`, and every assertion row belonging to the case is marked **FAIL** in `assertions.jsonl`.

A case-level FAIL is intentional even where an individual behavioral assertion would otherwise pass: the captured evidence is not qualified for this evaluation.

## Run A — `run-a-hermes-exec`

| Case | Defect | Disposition |
|---|---|---|
| `trigger-should-4` | Provenance has `text_chars=0` and omits `ordinal` and `retrieved_ts`, while the transcript is 1,411 characters and is a trial report rather than a first response. | **FAIL — provenance incomplete / contaminated evidence** |
| `trigger-should-5` | Provenance shows ordinal 21, seven approvals, 124.8 seconds, and 10,675 characters; this is later workstream output, not a first response. | **FAIL — later-workstream contamination** |
| `revise-fix-loop` | Provenance ordinal is 37, so the captured response is not a first response. | **FAIL — ordinal contamination** |
| `gate-summary-before-author` | Provenance/transcript character mismatch: 871 vs 800. | **FAIL — PROVENANCE-MISMATCH** |
| `gather-loop-immediate-no` | Provenance/transcript character mismatch: 927 vs 870. | **FAIL — PROVENANCE-MISMATCH** |
| `gov-never-blocker` | Provenance/transcript character mismatch: 616 vs 706. | **FAIL — PROVENANCE-MISMATCH** |
| `gov-ship-deploys` | Provenance/transcript character mismatch: 303 vs 922. | **FAIL — PROVENANCE-MISMATCH** |
| `gray-ambiguous` | Provenance/transcript character mismatch: 395 vs 443. | **FAIL — PROVENANCE-MISMATCH** |
| `input-store-context` | Provenance/transcript character mismatch: 691 vs 1,023. | **FAIL — PROVENANCE-MISMATCH** |
| `intake-upload` | Provenance/transcript character mismatch: 333 vs 334. | **FAIL — PROVENANCE-MISMATCH** |
| `trigger-should-not-1` | Provenance ordinal is 4; the fourth message was captured instead of the second (first assistant response). | **FAIL — ordinal contamination** |
| `trigger-should-6` | Provenance records two approvals, indicating tool interaction before the captured response. | **FAIL — pre-capture interaction contamination** |

**Run A recalculated score: 22 PASS / 12 FAIL / 0 PENDING (34 cases).**

## Run B — `run-b-openclaw-exec`

| Case | Defect | Disposition |
|---|---|---|
| `trigger-should-4` | Provenance has `text_chars=0` and omits `ordinal` and `retrieved_ts`, while the transcript is 1,300 characters. | **FAIL — provenance incomplete / contaminated evidence** |
| `revise-fix-loop` | Provenance has `text_chars=0` and omits `ordinal` and `retrieved_ts`, while the transcript is 1,520 characters. | **FAIL — provenance incomplete / contaminated evidence** |
| `gate-summary-before-author` | Provenance/transcript character mismatch: 735 vs 995. | **FAIL — PROVENANCE-MISMATCH** |
| `gov-pattern-author-emits` | Provenance/transcript character mismatch: 977 vs 661. | **FAIL — PROVENANCE-MISMATCH** |
| `gov-ship-deploys` | Provenance/transcript character mismatch: 377 vs 807. | **FAIL — PROVENANCE-MISMATCH** |
| `gray-ambiguous` | Provenance/transcript character mismatch: 362 vs 535. | **FAIL — PROVENANCE-MISMATCH** |
| `input-store-context` | Provenance/transcript character mismatch: 934 vs 849. | **FAIL — PROVENANCE-MISMATCH** |
| `trigger-should-not-1` | Provenance ordinal is 4; the fourth message was captured instead of the second (first assistant response). | **FAIL — ordinal contamination** |
| `trigger-should-6` | Provenance ordinal is 9, so the captured response follows prior interaction and is not the first response. | **FAIL — ordinal contamination** |

**Run B recalculated score: 25 PASS / 9 FAIL / 0 PENDING (34 cases).**

## Integrity rule applied

A provenance/transcript character mismatch is classified as `PROVENANCE-MISMATCH` and is nonqualified evidence. Missing first-response provenance, non-first ordinal, approvals, or prior tool interaction likewise makes the case nonqualified regardless of the behavioral assertion result.

The audit does not alter transcript files or provenance records; it records the scoring disposition only.
