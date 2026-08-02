# references/best-practices.md — Generation basis: Osmani catalog + Agent Skills spec

The engine's generation basis: the development-engineering best practices every
generated package conforms to. Two named sources: (1) addyosmani/agent-skills
(MIT), the 24-skill engineering discipline catalog; (2) agentskills/agentskills
(code Apache-2.0, docs CC-BY-4.0), the Agent Skills open format standard and
its authoring/eval guidance. Reviewed 2026-07-31. pattern-author uses this to
design packages, review uses it to check coverage and compliance, trial uses
it to build cases.

## Why this basis

Agent skills encode "the workflows, quality gates, and best practices senior
engineers use" as step-by-step processes agents follow. The Agent Skills
standard defines a portable, cross-client format for those skills. The Process
Engine generates packages that carry this discipline into any domain — in a
format that validates anywhere.

## The Agent Skills open format (spec essentials)

- A skill is a folder containing a `SKILL.md` file: YAML frontmatter + Markdown
  body. Optional `scripts/` (executable code), `references/` (documentation),
  `assets/` (templates, data).
- Frontmatter: `name` (required, lowercase letters/digits/hyphens, ≤64 chars,
  must match the directory name) and `description` (required, ≤1024 chars,
  what + when, imperative phrasing). Optional: `license`, `compatibility`
  (≤500 chars), `metadata`, `allowed-tools` (experimental).
- Body: no format restrictions; recommended <500 lines / <5,000 tokens. Split
  longer content into referenced files.
- Loading is progressive disclosure: Discovery (name + description only) →
  Activation (full SKILL.md) → Execution (scripts/references on demand).
- The description carries the entire activation burden — write it imperative,
  focused on user intent, explicit about scope ("even if the user doesn't
  mention X"), concise.
- Eval methodology: trigger query sets (should/shouldn't + near-miss
  negatives), with-skill vs without-skill baseline runs, token/timing cost
  capture, case files in `evals/evals.json` (id, prompt, expected_output,
  optional files).

## The catalog — 24 skills (Osmani)

### Meta
- **using-agent-skills** — Maps incoming work to the right skill workflow; defines shared operating rules.

### Define — clarify what to build
- **interview-me** — One-question-at-a-time interview until ~95% confidence in what the user wants.
- **idea-refine** — Structured divergent/convergent thinking: vague ideas → concrete proposals.
- **spec-driven-development** — Write a PRD (objectives, structure, testing, boundaries) before any code.

### Plan — break it down
- **planning-and-task-breakdown** — Decompose specs into small verifiable tasks with acceptance criteria and dependency ordering.

### Build — write the thing
- **incremental-implementation** — Thin vertical slices; feature flags, safe defaults, rollback-friendly changes.
- **test-driven-development** — Red-Green-Refactor; test pyramid (80/15/5); DAMP over DRY; Beyonce Rule.
- **context-engineering** — Feed agents the right information at the right time (rules files, context packing, MCP).
- **source-driven-development** — Ground every framework decision in official docs; verify, cite, flag unverified.
- **doubt-driven-development** — Adversarial fresh-context review: CLAIM → EXTRACT → DOUBT → RECONCILE → STOP.
- **frontend-ui-engineering** — Component architecture, design systems, state management, responsive design, WCAG 2.1 AA.
- **api-and-interface-design** — Contract-first design; Hyrum's Law; One-Version Rule; error semantics.

### Verify — prove it works
- **browser-testing-with-devtools** — Chrome DevTools MCP for live runtime data (DOM, console, network, performance).
- **debugging-and-error-recovery** — Five-step triage: reproduce, localize, reduce, fix, guard; stop-the-line rule.

### Review — quality gates before merge
- **code-review-and-quality** — Five-axis review; change sizing (~100 lines); severity labels (Nit/Optional/FYI).
- **code-simplification** — Chesterton's Fence; Rule of 500; reduce complexity while preserving functionality.
- **security-and-hardening** — OWASP Top 10 prevention; auth patterns; secrets; dependency auditing.
- **performance-optimization** — Measure-first; Core Web Vitals; profiling; bundle analysis.

### Ship — deploy with confidence
- **git-workflow-and-versioning** — Trunk-based development; atomic commits; commit-as-save-point.
- **ci-cd-and-automation** — Shift Left; Faster is Safer; feature flags; quality-gate pipelines.
- **deprecation-and-migration** — Code-as-liability; compulsory vs advisory deprecation; zombie-code removal.
- **documentation-and-adrs** — Architecture Decision Records; API docs; inline documentation standards.
- **observability-and-instrumentation** — Structured logging; RED metrics; OpenTelemetry tracing; signals-based alerting.
- **shipping-and-launch** — Pre-launch checklists; feature-flag lifecycle; staged rollouts; rollback procedures.

## Supporting assets in the catalog

- **4 reviewer personas:** code-reviewer, test-engineer, security-auditor, web-performance-auditor.
- **7 reference checklists:** definition-of-done, testing-patterns, security-checklist, performance-checklist, accessibility-checklist, observability-checklist, orchestration-patterns.
- **8 slash-command entry points:** /spec, /plan, /build, /test, /review, /webperf, /code-simplify, /ship.

## Authoring doctrine (generation rules)

- **Add what the agent lacks, omit what it knows** — every piece of content
  must be something the agent would get wrong without the instruction.
- **Coherent units** — a skill encapsulates one coherent unit of work that
  composes well; not too narrow (forces many skills per task), not too broad
  (hard to activate precisely).
- **Moderate detail** — concise stepwise guidance with a working example beats
  exhaustive coverage; leave edge cases to the agent's judgment unless the
  skill's domain makes them load-bearing.
- **Progressive disclosure** — SKILL.md is the entry point; references load on
  demand (token economy).
- **Context-aware loading** — load the relevant skill, not all skills.
- **Trigger-optimized descriptions** — imperative, user-intent-focused, explicit
  scope, concise; the description is the activation mechanism.

## Engineering-culture principles (translated into generation rules)

- "Process, not prose" — skills are workflows agents follow, not reference docs.
- Anti-rationalization — every skill includes the excuses agents use to skip steps, with counter-arguments.
- "Verification is non-negotiable — 'seems right' is never sufficient."
- Evals before ship — cases, baselines, recorded evidence.

## Eval methodology (trial-phase standard)

- Case types: happy path, gray zone, escalation, boundary, trigger set
  (should/shouldn't + near-miss negatives).
- Baseline: run each case with-package and without-package (or vs previous
  version); record token count and duration; a package must earn its context
  cost.
- Case files in the portable format: evals/evals.json (id, prompt,
  expected_output, optional files).
- Every generated package carries a case set before it ships.

## Contribution bar (what a professional generated skill looks like)

Specific (actionable steps) · Verifiable (clear exit criteria with evidence) ·
Battle-tested (based on real workflows) · Minimal (only what guides the agent).

## Engine additions (beyond the two sources — our standards)

- Evidence-naming: cite named sources; never "research shows".
- Review gates: nothing ships without operator review.
- Eligibility gate: the artifact shape (project / persona / single or
  multiple skills / not an artifact) is decided deliberately before authoring.
- Formal REVISE loop: diagnose → rewrite → audit; periodic stocktake audits
  deployed skills for quality.
- Per-package governance: each package carries a prompt policy + judge rules
  (helper, advisory, never blockers — references/governance.md).
- Scope honesty: packages never claim capability/validity their sources don't
  support; risk-relevant intents get per-package safeguards (references/safety.md).
- Format compliance: generated skills are spec-valid by construction
  (references/standards.md §8).
- Privacy: templates/patterns ship publicly; user data never does.

## When to load

- pattern-author: load when generating any package.
- review: load when checking a generated package's coverage and compliance.
- trial: load when designing case sets and baselines.
