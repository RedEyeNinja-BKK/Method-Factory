---
name: process-engine-trial
description: Adversarial trial harness — scripted scenario cases, trigger sets, and fixtures that prove an artifact performs correctly and earns its context cost before it ships.
compatibility: Turnstone 1.8.x or any Agent Skills-compatible client
metadata:
  author: RedEyeNinja-BKK
  version: "1.9.1"
  engine: process-engine 1.9.1
---
## Overview
Trials are the engine's proof. Trial depth scales with the package's
assurance tier (recorded in the manifest at `assurance_tier.selected`):

- **Lightweight:** 2–3 deterministic cases from the acceptance criteria only.
  No gray zone, no escalation, no full trigger set. No baseline. Operator
  review of case results is the acceptance gate.
- **Standard:** Full case suite (happy path, gray zone, escalation, boundary) +
  trigger set (8–10 should-trigger + 8–10 shouldn't-trigger near-misses).
  With-package vs without-package baseline recommended but not required.
- **High-Assurance:** Standard + baseline IS mandatory + semantic judge for all
  semantic assertions. Rollback plan verified before ship.

Risk-relevant packages additionally get safeguard-specific drills per their
per-package spec, regardless of tier.

## When to Use
- After review PASS, before ship.
- When an artifact is revised in ways that change its performance or scope.
- Regression: re-run cases after any change.

## Core Process
1. **Define cases** from the artifact's acceptance criteria and scope surface:
   - happy path (e.g. normal use of the package)
   - gray zone (e.g. input near the scope boundary — must be handled per
     package scope, not guessed)
   - escalation (e.g. input beyond the declared scope — must engage the
     package's own handling path)
   - boundary (e.g. input that clearly exceeds scope → decline/route per
     package scope)
   - trigger set (8–10 should-trigger queries + 8–10 shouldn't-trigger
     near-misses): varied phrasing, explicitness, detail, complexity —
     exercises the package's descriptions, which carry the activation burden
2. **Define fixtures** — setup stubs: model config, persona, skill, scenario
   input. Emit case sets in the portable Agent Skills eval format
   (evals/evals.json: id, prompt, expected_output, optional files).
3. **Run** each case with clean context; record actual vs expected result.
4. **Instrument each run** in a machine-readable record. For every case and
   condition, capture `run_id`, `case_id`, `condition` (`with_package`,
   `without_package`, or `previous_version`), model identifier, package
   version/hash, started/ended timestamps, duration in milliseconds, input
   tokens, output tokens, total tokens, actual output, expected output, and
   PASS/FAIL. If a field is unavailable, write `UNAVAILABLE` and the reason;
   never infer or estimate it. Store records under the project evidence path.
5. **Baseline** — High-Assurance: run each case with-package and without-package
   (or against a previous version); record token count and duration. A package
   must prove it earns its context cost. Standard: baseline recommended but
   optional. Lightweight: no baseline required. Do not claim a cost comparison
   unless both conditions have complete measurements for the compared cases.
6. **Score**: PASS / FAIL per case; document failures precisely. Activation
   results must separately report should-trigger recall and shouldn't-trigger
   precision; do not collapse an unrun set into a score.
7. **Mirrored dual-source protocol** (release qualification) — for a
   release-candidate run, produce TWO independent run records:
   - **Run A**: one executor (e.g. Hermes) runs the full case suite
     case-by-case; a different verifier (e.g. OpenClaw) independently checks
     each output against the case's expected behavior.
   - **Run B (mirror)**: the roles swap — the second executor runs the full
     suite; the first verifies.
   Each run records its own transcripts under an immutable per-run path
   (`iterations/<N>/actual/`), its own judgments, and its own model identity.
   The release verdict derives only from the final-release iteration's
   judgments, never from a mix of iteration outcomes.
8. **Manifest update**: link the trial run (`run_id`, total/passed/failed,
   verdict) and `evidence_path` (run bundle) into the package manifest; store
   package-content hashes. The manifest must identify missing instrumentation
   as incomplete, not successful.
9. **Hand back**: trial evidence → pattern-author (revisions) or review
   (re-verify) or ship (all pass).

## Examples
- Case: out-of-scope request → input outside the package's declared domain →
  expected: decline and route, never guess. Actual recorded.
- Trigger case: near-miss query sharing keywords with the package's domain
  but needing something else → expected: no activation. Actual recorded.
- Safeguard drill (risk-relevant packages only) → input crossing the package's
  declared scope boundary → expected: the package's per-package safeguard path
  engages per its spec. Actual recorded.

## Common Rationalizations
- "I know it works, I tried it once." → One informal try is not a trial.
- "Real users are the trial." → For risk-relevant packages, real users are the
  LAST step, after adversarial cases pass.
- "The description will activate fine; I wrote it well." → Trigger sets exist
  because activation is the failure mode. Prove it.
- "It costs more tokens but it's better." → Prove the trade-off: baseline
  comparison makes the cost explicit.

## Red Flags
- Shipping an artifact with no trial evidence.
- Trials that only test the happy path.
- No trigger set for a package with activation-dependent skills.
- Ignoring a FAIL case ("edge case, won't happen").
- Reporting a qualitative or partial baseline as a measured comparison.

## Verification
- [ ] Cases defined for all acceptance criteria + scope surface
- [ ] Trigger set run (should/shouldn't + near-misses) recorded
- [ ] Baseline comparison recorded (with vs without, token cost)
- [ ] Every case run, actual vs expected recorded
- [ ] All PASS (or failures routed back to author/review)
- [ ] Trial evidence recorded in the project
