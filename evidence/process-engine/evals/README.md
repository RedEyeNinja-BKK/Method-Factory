# evals — Process Engine self-trial set

The engine's own adversarial case set, per the trial skill's standard
(process-engine-trial): the package proves itself before it ships.

## Case map (trial doctrine)

| Case id | Case type | What it proves |
|---|---|---|
| happy-pattern | happy path | pattern-author produces a DRAFT package, handed to review, never auto-shipped |
| gray-ambiguous | gray zone | ambiguous intent → one clarifying question, no guessing |
| escalation-risk | escalation | risk-relevant intent → per-package safeguard path engaged |
| boundary-nonpackage | boundary | out-of-scope request → decline/route, never guess |
| trigger-should-1..6 | trigger set | description activates on in-scope intents (author/review/trial/ship/triage routes) |
| trigger-should-not-1..3 | trigger set (near-misses) | no activation on out-of-scope tasks (plain chat, file work, ops) |
| intake-link | intake | shared skill link → fetch/validate/license/classify/operator gate |
| intake-upload | intake | uploaded skill file → recognize/validate/classify/operator gate |
| intake-license-flag | intake | license info = provenance, not a gate; extraction proceeds (never copy) |
| intake-find | intake | request to find an existing skill → search/fetch/shortlist/gate |
| intake-text-dump | intake | pasted text (no link/source) → provenance unknown, extract, author original |
| gather-loop-yes-yes-no | collection loop | multiple inputs collected, exits on decline, summary gate shown |
| gather-loop-immediate-no | collection loop | first decline skips collection entirely |
| gather-loop-non-skill-reply | collection loop | non-material reply exits the loop |
| clarify-material-informed | collection loop | clarify references collected material (match vs improve) |
| gate-summary-before-author | collection loop | summary gate (material + intent) before authoring |
| input-store-context | input-agnostic | store/product link = domain context: used, never published, heads-up surfaced |
| input-mixed-anything | input-agnostic | any mix of material accepted and used; nothing rejected by type |
| heads-up-not-block | input-agnostic | risk/policy surface → heads-up as information; operator decides; never blocks |
| eligibility-shape | eligibility gate | shape decided deliberately (project/persona/skill(s)/none) — never assumed |
| revise-fix-loop | review | REVISE → formal diagnose/rewrite/audit loop + regression trial |
| stocktake-audit | maintenance | periodic quality audit of deployed skills → findings routed |
| provenance-metadata | evidence | generated SKILL.md carries source URL/date metadata when known |
| objective-what-good-looks-like | objective | "what does good look like" — vague vision → objective + outcomes; underspecified flagged |
| gov-pattern-author-emits | governance | pattern-author generates prompt policy + judge rules (helpers) |
| gov-ship-deploys | governance | ship deploys governance artifacts + verifies by read-back |
| gov-never-blocker | governance | governance artifacts never silently block (no tool_gate, advisory) |

## How to run

Per the trial skill: run each case with clean context, with-package vs
without-package, record actual vs expected result, capture token/timing,
score PASS/FAIL per case. Evidence recorded in the project before any ship.

## Run bundles (self-contained evidence)

Each release re-run writes a self-contained dual-sub-run bundle to
`evals/runs/release-v1.9.1-rN/`. Turnstone is the executor in both runs; the
verifiers differ (Run A: OpenClaw; Run B: Hermes):

```
release-v1.8.2-rN/
├── manifest.json
├── run-a-hermes-exec/
│   ├── cases/
│   ├── actual/
│   ├── provenance.json     # single file keyed by case_id (canonical)
│   ├── raw-history/         # per-case .json files (cluster-API capture)
│   ├── baseline/            # without-package baseline transcripts
│   ├── assertions.jsonl
│   ├── summary.json
│   ├── hashes.json
│   ├── environment.json
│   └── README.md
└── run-b-openclaw-exec/
    └── (same structure)
```

`provenance.json` contains the canonical per-case provenance records.
Raw histories in `raw-history/` are present when the cluster-API capture
tool (`scripts/capture_workstream.py`) is used; MCP-gateway capture may
omit raw-history files while producing identical provenance records.
Verdict evidence is in `assertions.jsonl` and `summary.json`.
`judgments.jsonl` is not part of the canonical layout.

Evidence links in `summary.json` are **bundle-relative** (`actual/<case-id>.txt`)
and validated by `scripts/validate.py` — no link points outside the bundle
unless explicitly absolute. The manifest records the exact model identity
(no external-file placeholders), full commit, and hashes.

## Status

- Added 2026-07-31 (v5.2 audit remediation, finding M4) — historical origin.
- Current: release-aligned **v1.9.1** (engine lineage v7.2) · 34 cases · 86
  assertion contracts (derived dynamically from `evals.json`).
- **Evaluator frozen at v1.9.1** — hybrid architecture (semantic_judge for
  meaning-based assertions, deterministic for structural). See
  `docs/evaluator-freeze-policy.md` for change policy and assertion tiers.
- **Historical qualified**: `release-v1.8.2-r1` (v1.8.2-era content, 30/34 A,
  32/34 B under restored contracts).
- **Qualification candidate**: `release-v1.9.1-r2` (prompt-bound transcripts,
  frozen). Hybrid re-evaluation at `evals/re-evaluations/v1.9.1-hybrid-re-evaluation/`.
- **v1.8.1 bundle** — preserved at `evals/runs/release-v1.8.1-9062b07-r1/`;
  behavioral 34/34 claim withdrawn.
- **v1.8.2 bundle** — preserved at `evals/runs/release-v1.8.2-r1/`; original
  34/34 under former contracts; 30/34 A, 32/34 B under restored contracts.
- CI enforces committed-evidence replay (`PE_STRICT_EVALUATE=1`); judge-backed
  semantic re-derivation is the protected release-process step.
