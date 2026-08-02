# Changelog

All notable changes to Process Engine are recorded here.

## 1.9.1 — 2026-08-02

**Evaluator frozen; product trials next** (engine v7.2):

- **Hybrid evaluator:** 14 meaning-based assertions converted to semantic_judge. Structural checks remain deterministic. Evaluator frozen at v1.9.1 — governed by `docs/evaluator-freeze-policy.md`. Three assertion tiers: hard invariants (block qualification), stage correctness (inform product decisions), communication quality (informational only).
- **Prompt-binding enforcement:** `check_prompt_binding()` in validator mechanically verifies all 34 prompt hashes against `evals.json`. Previous r1 run was contaminated by wrong prompts — discovered and marked diagnostic.
- **Evidence sealing:** All hashes populated (package, prompt_set, evaluator_code, assertion_contract). Commit identities separated (capture_package, source_evidence, hybrid_evaluator). Transcript hash standardization (raw + normalized). Re-evaluation artifacts with sealed source-transcript hashes.
- **Manifest model:** `process-engine.toml` distinguishes `latest_qualified_run`, `qualification_candidate_run`, and `latest_candidate_re_evaluation`. Stale claims removed.
- **Negative fixtures:** 6 targeted mutation tests proving restored contracts catch genuine failures.
- **Ci expansion:** All 3 test suites (evaluator self-test, provenance adversarial, evaluator mutations) run on every push.
- **v1.9.0 tag** is immutable at `0860b72`. v1.9.1 is the current development tree.

## 1.9.0 — 2026-08-02

- **Proportional discipline implemented:** three-tier model (lightweight/standard/high-assurance) with tier-selection table in core skill based on risk domain, authority level, reversibility, and external side effects. All tiers retain operator review + at least one behavioral trial before shipping — scaling depth rather than eliminating core guarantees.
- **Evaluator contracts restored:** six over-broadened predicates tightened — governance_posture (tertiary path removed), operator-gate (clarification proxy removed), heads-up-not-block (Generate? proxy removed), provenance-recorded (URL/working-from proxies removed), store-domain-context (ecommerce proxy removed), collect-invites (reopening path removed). Contracts now match the documented discipline.
- **External-user scenario design:** 10 scenarios defined in `evals/scenarios-v1.9.0.yaml` across non-coding domains. License verification fields (user_claimed/verified/verification_status) added to all fixtures. Transcripts captured via Hermes + OpenClaw with gpt-5.6-terra; formal evaluation pending — scenario report marked PENDING HUMAN REVIEW.
- **CI expanded:** provenance adversarial tests and evaluator mutation tests now run alongside the release validator and evaluator self-test on every push.
- **First-response evidence (v1.8.2-era):** 30/34 both runs under restored evaluator contracts. 4 honest gaps per run (2 semantic judge, 2 contract). Evaluator replay matches committed evidence 86/86 both runs. Provenance enforcement clean (0 failures).
- **Product positioning:** README leads with concrete promise; honest Superpowers acknowledgment as complementary methodology; methodology-factory distinction documented; non-coding domains showcased.
- **Known gaps (pending v1.9.0-r1):** scenario evaluator is regex prototype (needs capture/evaluate/finalize split); no end-to-end package trials; fresh v1.9.0 bundle needed after frozen content commit.
- **v1.8.2 historical bundle** preserved at `evals/runs/release-v1.8.2-r1/`.

## 1.8.2 — 2026-08-02

**Semantic evidence integrity — QUALIFIED** (engine v7.1):

- Adds `scripts/evaluate.py`, a schema-bound assertion evaluator that derives
  PASS/FAIL from transcripts (regex_all / predicate / semantic_judge, with
  proof payloads and evaluator versions). No caller-supplied PASS values.
- Adds `scripts/evaluate_self_test.py` (conservative semantic fails, known
  passes, mutation tests).
- Integrates `--evaluate` into `record_release_run.py` finalize (rejects unless
  every assertion declared by the current contract passes) and `validate.py` strict mode (`--evaluate` /
  `PE_STRICT_EVALUATE=1`). CI now runs strict mode (committed-evidence replay)
  and the evaluator self-test on every push.
- **Withdraws the v1.8.1 behavioral PASS claim**: independent review found
  recorded PASS rows whose transcripts fail the assertion contract; the
  corrected evaluator confirmed the mismatch.
- **Qualified 2026-08-02:** release-qualification re-run `release-v1.8.2-r1` —
  **86/86 derived PASS in both sub-runs** (172/172; schema-bound evaluator,
  assertions mechanically derived or judge-verified with proof payloads).
  Bundle bound to release commit 043a887 (engine 1.8.2), measured per-run
  timestamps from transcript file times, bundle-relative evidence paths,
  package-hash seal. Convergence: 63/81 (v1.8.1) → 81/86 → 84/86 → 86/86 both
  runs.
- **Validator hardened:** version-driven strict enforcement for all
  release-v1.8.1+ bundles (replaces a hardcoded v1.8.1 prefix), timestamp
  sanity (completion must precede seal commit time), and committed-evidence
  replay (regenerated rows must match committed assertions.jsonl).
- Discipline v11: summary gate is the operator checkpoint before authoring
  (terminal "Working from … Generate?" when collection is complete);
  governance canonical phrasing in every artifact-authoring first response.
- Assertion contracts corrected (Option A, operator-approved):
  operator-checkpoint semantics for summary-gate; ship-gate confirmation;
  identity-vs-domain no-assumption rubric; exactly-one-question for
  asks-clarification; canonical governance phrasing for helper-posture.
  Evaluator predicates fixed (routing, scope, checkpoint, provenance).

## 1.8.1 — 2026-08-01

**Discipline v6 and release-boundary repair** (engine v7.0):

- Preserves discipline-v6 first-response phrasing and aligns persona terminology with artifact-specific, runtime-aware operation.
- Completes mirrored-bundle evidence: measured timestamps, immutable transcript SHA-256 hashes, 81 assertion records, baseline status, substantive bundle documentation, and conservative missing-judgment FAIL handling.
- Hardens `run_trials.py`: local-only default guard, parameterized dependencies, TOML-derived engine version, meaningful assertion token matching, and runnable without-package baselines.
- Extends `record_release_run.py` with run-id parameterization, immutable transcript recording, assertion recording, and finalization that seals package/prompt hashes.
- Enforces the complete v1.8.1 mirrored release contract in `validate.py`, while retaining legacy compatibility for the sealed v1.8.0 r6 bundle.
- Sets `release-v1.8.1-PENDING` as the intentional pre-seal boundary; no new run identifier or PASS result is invented before orchestration.
- **Status correction (2026-08-02):** the v1.8.1 bundle is structurally sealed; the behavioral 34/34 PASS claim was withdrawn and re-qualified under the v1.8.2 schema-bound evaluator (see 1.8.2 entry).

## 1.8.0 — 2026-08-01

**Release-integrity & executable-evidence overhaul** (engine v6.0):

- **Canonical release manifest** — `process-engine.toml` is now the single
  source of truth for version, lineage, and artifact counts
  (skill_count/reference_count/template_count/eval_case_count/latest_eval_run).
- **Release-state alignment** — README, evals README, evals.json package
  descriptor, run manifest, changelog, and docs all agree on v1.8.0 / v6.0 /
  34 cases / 7 references / 6 templates (previously four competing truths).
- **Canonical-source precedence fixed** — `convert.py` now refuses to
  overwrite newer repository content with older draft lineage (stale-guard),
  generates in staging, and atomically replaces output only after full
  validation. The Phase 5 regression (stale v1.7.0/31 evals metadata
  regenerated over newer repo content) is structurally impossible now.
- **Self-contained run bundle** — `evals/runs/run-20260731-001/` now includes
  `cases.json`, `actual/` + `baseline/` outputs, `assertions.jsonl`,
  `judgments.jsonl`, `environment.json`, and a bundle README; evidence links
  are bundle-relative and validated. Exact model identity recorded (no
  "see facts file" placeholder).
- **Atomic assertions** — all 34 eval cases carry assertion arrays
  (deterministic + judge-based), with machine-readable PASS/FAIL results.
- **Manifest as pipeline state spine** — core initializes the package
  manifest at the summary gate; pattern-author, review, trial, ship, and
  triage all read/write it (refuse-review-without-manifest, link-trial-run,
  ship-gate checks, rollback record). Schema at
  `docs/package-manifest-schema.md`.
- **Portable provisioning** — end-to-end external-client test harness
  documented/provisioned (not executed; deferred per operator).
- **Release-gating validator** — `scripts/validate.py` + CI workflow check
  version/lineage/counts, evidence links, embedded↔root reference equality,
  frontmatter, and generated-diff drift.

## 1.7.1 — 2026-08-01

Per-package governance wiring (engine v5.9):

- pattern-author: generates per-package governance artifacts — a prompt
  policy (operating stance, content-only, priority 1, no tool_gate) and
  judge rules (advisory, risk=low, review) — as helpers, never silent
  blockers.
- ship: deploys the governance artifacts (POST prompt-policies + heuristic-
  rules) and verifies by read-back.
- New reference `references/governance.md` — the per-package governance
  artifact spec (helper posture, non-negotiables).
- skill-anatomy + best-practices + standards §13 aligned.
- README references (7) + convert.py updated.

## 1.7.0 — 2026-08-01

**First public release.** Governance live + release alignment (no engine
content change beyond metadata):

- **Judge now active** in the stack (removed `--skip-permissions` from the
  node systemd units — the real blanket switch). Fresh sessions show
  `smart_approval` verdicts in audit; the intent-validation judge fires and
  records evidence. Prompt policy `process-engine-context` + heuristic rule
  `process-engine-authoring` live, advisory.
- **Governance trial**: 31/31 PASS against the governance-enabled engine
  (`evals/governance-trial-evidence.md`).
- README aligned: governance-layer emphasis, release line, package anatomy
  highlights governance artifacts (Project / Persona / Prompts / Judge /
  Skills).
- Case study moved to `evals/case-study-first-run.md`; trial evidence
  genericized (no domain anchors).
- Release version stamped **1.7.0** across all visible surfaces.

## 1.6.1 — 2026-08-01

Governance-layer trial + README alignment + judge now live (no engine
content change; content release stays 1.6.0):

- **Judge now live in the stack**: removed `--skip-permissions` from the node
  systemd units (the real blanket switch, which outranked config + DB). A
  fresh stock session now shows `smart_approval` verdicts in audit — the
  intent-validation judge fires and records evidence. Prompt policy
  `process-engine-context` + heuristic rule `process-engine-authoring`
  remain live and advisory.
- **Governance trial**: full 31-case suite re-run against the
  governance-enabled engine (fresh workstream per case) — **31/31 PASS**,
  trigger 9/9, baselines 9/9. Evidence: `evals/governance-trial-evidence.md`.
- **README alignment**: governance-layer emphasis (Why Turnstone, during
  development we used it), release line condensed, self-hosted/cost columns
  dropped, package anatomy highlights governance artifacts (Project /
  Persona / Prompts / Judge / Skills).
- **trial-evidence.md**: cost note genericized (no domain-specific anchors).
- **case study moved** to `evals/case-study-first-run.md` (README links
  updated).

## 1.6.0 — 2026-08-01

Release alignment + docs (no engine content change):

- Add `docs/case-study-first-run.md` — anonymized, evidence-forward account of
  the first live run (a shop package built end to end: collect → clarify →
  objective → gates → trial evidence → ship). Store identity and figures
  anonymized; original run stays private.
- README: Docs section linking architecture, spec-compliance, and the case
  study; case-study link added at the bottom of "What it does".
- Release alignment: store version fields + convert.py CONTENT_VERSION
  bumped to **1.6.0** across all skills/templates (version-only; content
  unchanged). Content lineage stays v5.8 internally.
- Release stamp on every visible surface: README header (Release v1.6.0),
  evals package descriptor, SKILL.md `engine:` metadata (process-engine
  1.6.0). Historical changelog entries left as the record.
- Git tag `v1.6.0` created on this commit.

## 1.5.9 — 2026-07-31

Objective elicitation (engine v5.8, intent engineering):

- New core step before the summary gate: the engine asks "What does 'good'
  look like to you?" — accepting even a vague vision, seeding the package's
  objective and desired outcomes. No answer → objective marked
  underspecified and proposed in the draft for correction at review.
- Summary gate now confirms intent + vision together ("Intent: X. Good
  looks like: <vision>.").
- pattern-author: objective + desired outcomes formed from the vision;
  acceptance criteria derive from it (vision → observable exit criteria).
- starter-author carries the question; README (Using + quickstart +
  pipeline) updated.
- evals: +1 case (objective-what-good-looks-like); summary-gate case
  updated — 31 total.
- Versions: 1.5.9 / process-engine v5.8.

## 1.5.8 — 2026-07-31

Surgical adaptations (engine v5.7), aligned with ecosystem best practice:

- Eligibility gate (augmented): pattern-author step 1 decides the artifact
  shape deliberately — project / persona / single or multiple skills / not
  an artifact; never assumed (adapted from SkillForge eligibility gate).
- Formal REVISE loop: review returns REVISE artifacts through diagnose →
  rewrite → audit before re-review; regression trial re-runs (adapted from
  SkillForge fix mode).
- Provenance metadata: generated SKILL.md frontmatter carries source
  URL/date when known (adapted from agent-skills-generator).
- Stocktake: triage gains periodic quality audit of deployed skills
  (adapted from ECC skill-stocktake).
- standards §1/§3/§12, skill-anatomy, core routing, starter-author shape
  confirm, best-practices engine additions updated for alignment.
- evals: 4 new cases (eligibility-shape, revise-fix-loop, stocktake-audit,
  provenance-metadata) — 30 total.
- README: shape confirmation + eligibility gate in the flow.
- Versions: 1.5.8 / process-engine v5.7.

## 1.5.7 — 2026-07-31

Input-agnostic intake + heads-up posture (engine v5.6):

- intake.md rewritten: ANY user-provided material is accepted and used
  (skill links, text, files, store links, docs, examples) — nothing rejected
  by type; domain context is fetched, extracted into package context, and
  never published; heads-up posture embedded.
- safety.md reframed as heads-up practice: surface what's worth knowing,
  never block; operator is the only gate.
- standards §10 input-agnostic, §11 heads-up-not-police.
- persona: input-agnostic scope + heads-up working style.
- core/pattern-author/templates: collection language broadened to
  "anything that helps".
- evals: 3 new cases (store-context, mixed-anything, heads-up-not-block) —
  26 total.
- README: "Using Process Engine" updated (any material, helper-not-police).
- Versions: 1.5.7 / process-engine v5.6.

## 1.5.6 — 2026-07-31

Collection loop — proactive intake (engine v5.5):

- core: new front-door flow — Orient → Collect (invite skill material, loop
  until non-material reply) → material-informed Clarify → Summary gate →
  Route.
- pattern-author: synthesize step — extracts from ALL user-provided material
  (links/text), authors original, never copies.
- intake.md: collection-loop protocol (conversational, exit on any
  non-material reply, summary gate).
- Templates: orientation invites skill material; starter-author runs the
  collect loop before drafting.
- evals: 5 new cases (gather-loop ×3, material-informed clarify, summary
  gate) — 23 total.
- README: "Using Process Engine" (prescribed session shape) + "Deploying
  Process Engine" (replaces the maintainer-only regenerating-content
  section; convert.py moved under "For maintainers").
- Versions: 1.5.6 / process-engine v5.5.

## 1.5.5 — 2026-07-31

Intake stance correction (engine v5.4):

- License checks removed as blocking gates. Intake's intent is extraction and
  incorporation (adapt, never copy); license info is recorded as provenance
  when visible, never used to block or classify.
- intake.md rewritten: recognize → fetch/no-fetch → extract → author
  original → attribute → provenance → operator gate on the package (normal
  Pattern → Review → Trial → Ship gates remain).
- standards §9 reframed; core red flag now "verbatim copying"; evals
  intake-license-flag updated.
- Versions: 1.5.5 / process-engine v5.4.

## 1.5.4 — 2026-07-31

Content: skill intake path (engine v5.3):

- New `references/intake.md` — intake of user-provided / discovered skill
  artifacts: recognize, fetch, spec-validate, license check, language sweep,
  classify, provenance, operator gate, attribution.
- core: intake routing rule + red flag (no silent adoption of external
  skills).
- triage: cross-ref to intake path.
- standards: new §9 Intake checklist item.
- evals: 4 new intake cases (link, upload, license-flag, find) — 17 total.
- All skill metadata version → 1.5.4 / process-engine v5.3.
- Tested live against a real external skill (proprietary license): spec-valid,
  sweep-clean → classified adaptation input per operator model (extract
  techniques, author original, no copying).

## 1.5.3 — 2026-07-31

Dev tooling only (no content change; store content version stays 1.5.2):

- Add `scripts/convert.py` — deterministic regeneration of repo content from
the authoring drafts (turnstone-native format → spec-valid SKILL.md),
validated on every run.
- README: add "Development — regenerating content" section documenting the
one-way content flow (drafts → repo → GitHub) and the convert command.

## 1.5.2 — 2026-07-31

Audit remediation (dry-run findings C1–C3, M1–M5):

- **Descriptions synced**: skill API descriptions aligned to SKILL.md frontmatter descriptions (frontmatter is the single source of truth); sweep scope extended to API description fields.
- **Versioning**: store version bumped to 1.5.2 across all skills and templates.
- **Anatomy phrasing** standardized (references/skill-anatomy.md is authoritative).
- **Persona description** cites both bases (Osmani agent-skills + Agent Skills open standard).
- **Self-evals added**: the engine's own case set at `evals/` (13 cases: happy/gray/escalation/boundary + trigger set).
- **Bootstrap workstream** state corrected (idle = expected steady state).

## 1.5.1 — 2026-07-31

Agent Skills spec compliance layer adopted (`agentskills/agentskills` as second named basis):

- pattern-author: spec-valid frontmatter (name/description rules, license/compatibility/metadata), authoring doctrine (add-what-agent-lacks, coherent units, moderate detail, trigger-optimized descriptions).
- review: spec-compliance check step.
- trial: trigger sets (should/shouldn't + near-misses), with/without baseline + token cost, evals.json portable format.
- references updated (standards, skill-anatomy, evidence-library, best-practices).

## 1.5.0 — 2026-07-31

Domain-agnostic refinement (v5):

- Engine declared domain-agnostic / intent-agnostic / platform-agnostic; sole basis = development-engineering best practices (Osmani agent-skills).
- Contamination sweep removed all domain-specific content that had leaked from the engine's first intended artifact into the generic layer.
- Full Osmani catalog (24 skills, 4 personas, 7 checklists, 8 commands) indexed in references/best-practices.md.
- DRAFT markers stripped from deployed content.

## 1.0.0 — 2026-07-31

Initial deployment (v4):

- Project, persona, 6 skills, 5 references, 6 templates deployed via native turnstone mechanisms.
- Bootstrap workstream created on the Process Engine project.
