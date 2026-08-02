---
name: process-engine-pattern-author
description: Generate the project/persona/skills package for an intent — to the engine's standard (spec-valid SKILL.md, Osmani anatomy, evidence-named, scope-honest, safeguard-aware, acceptance-criteria'd).
compatibility: Turnstone 1.8.x or any Agent Skills-compatible client
metadata:
  author: RedEyeNinja-BKK
  version: "1.9.1"
  engine: process-engine 1.9.1
---
## Overview
Turns an operator intent into the engine's final product shape — a
**project / persona / skills package** (a project, a persona, a single skill,
multiple skills, or not an artifact at all, per the eligibility gate). The
artifact SHAPE is decided up front by the eligibility gate. The package is
generated from the development-engineering best-practices basis
(references/best-practices.md —
full Osmani catalog + Agent Skills spec index): personas as system prompts,
skills as spec-valid SKILL.md following the engine's anatomy
(references/skill-anatomy.md), session
templates, and the project scaffolding. Output is a DRAFT package — always
handed to review.

## When to Use
- New artifact requested (persona, skill, template, doc, repo content).
- Revisions after a review or trial found issues.

## Core Process
1. **Eligibility gate** — decide the artifact shape deliberately: is this a
   project, a persona, a single skill, or multiple skills — or not an
   artifact at all (decline or route elsewhere)? If the shape is unclear,
   ask ONE shape-deciding question (project / persona / skill(s) / not an
   artifact) — never a generic material question; never assume. The shape
   drives everything downstream. When declining (out of scope), decline
   cleanly: state the boundary and route, and do NOT offer to do the
   off-scope work yourself — the engine generates packages, not the domain
   content.
2. **Interpret intent** — use the clarified intent, the collected-input
   summary, and the user's vision of what "good" looks like (the objective
   seed) from core. One clarifying question at a time if still ambiguous;
   never guess scope.
3. **Design the package** — determine the package shape from the intent and the
   best-practices basis (references/best-practices.md):
   - Project scaffolding (name, visibility, owner)
   - Persona → system-prompt shape (identity, scope, standards, style, boundaries)
   - Skills → SKILL.md: spec-valid frontmatter (name ≤64 chars, lowercase
     letters/digits/hyphens, matches the directory name; description ≤1024
     chars, what + when, imperative, user-intent phrasing; optional license,
     compatibility, metadata incl. provenance — source URL/date when known)
     + Osmani anatomy body: Overview · When to Use · Core Process · Examples ·
     Common Rationalizations · Red Flags · Verification
   - Design rules: add what the agent lacks, omit what it knows; coherent
     units; moderate detail; progressive disclosure (SKILL.md is the entry
     point, references load on demand)
   - Session templates (initial prompts)
   - Governance artifacts (per-package, derived — see step 7): a prompt
     policy (the package's operating stance, content-only, no tool_gate)
     and judge rules (the package's risk posture, advisory, on its own
     tool family). These are HELPERS, never silent blockers: content-only,
     advisory, operator-visible, always reversible.
   - Objective + desired outcomes — formed from the user's vision of "good":
     the problem being solved and why it matters (objective), and 2–4
     observable end states from the user's perspective (outcomes). If the
     vision was vague or absent, propose a concrete objective in the draft
     for correction at review.
   - **Target runtime** — classify the deployment target:
     - `turnstone`: generate native governance objects (prompt policy + judge rules)
     - `portable`: generate advisory governance documentation only (no native objects)
     - `both`: generate both forms
     Default to `turnstone` when the operator uses Turnstone; default to
     `portable` when the operator specifies a non-Turnstone agent client.
4. **Synthesize from collected material** — extract techniques, domain
   specifics, and intent from ALL user-provided material (any form: skill
   links, text blocks, files, store links, docs — per references/intake.md);
   combine into a best-of-all-worlds design; author ORIGINAL instructions —
   never copy input content verbatim.
5. **Name the evidence** — every technique cites its real source; add to the
   package's evidence library (generated per-package) if new. Bake
   provenance (source URL/date) into each generated SKILL.md metadata when
   the source is known.
6. **Safeguard pass** — if the intent touches a risk-relevant domain (domains
   involving people, regulated activities, or safety-critical systems) or the
   operator designates one, flag it and build per-package safeguards and scope
   limits from the package's own named evidence library and operator direction.
   The engine presets none (references/safety.md). Surfacing is proactive:
   when the intent or material touches a policy-relevant surface (e.g.
   marketplace claim restrictions on wellness products), state the heads-up
   plainly with a suggestion in the response — then proceed. Never wait for
   the operator to discover it. Heads-up, never block.
7. **Governance artifacts** — generate per-package governance objects based on
   the target runtime classification (from step 3):
   - When target_runtime includes `turnstone`:
     - **Prompt policy** (content-only, priority 1, no tool_gate): the
       package's durable operating stance (its heads-up posture, its
       operator-gate rule, its evidence-naming) so sessions on the package
       start aligned. Never restricts tools.
     - **Judge rules** (advisory heuristic rules on the package's own tool
       family, risk=low, recommendation=review): so the package's actions
       surface intent verdicts for the operator's awareness. Never blocks.
   - When target_runtime is `portable` only:
     - Generate advisory governance documentation (a governance.md section
       in the package describing recommended policies and risk posture) but
       do NOT generate native Turnstone API objects.
   Both forms are operator-visible, documented in the package, and reversible
   (disable/delete for native objects; edit/delete for documentation).
   Reference: references/governance.md.
8. **Acceptance criteria** — write explicit exit criteria into each artifact,
   derived from the objective: the vision of "good" becomes observable exit
   criteria.
9. **Assemble the package** — project/persona/skills/templates/governance as
   one bundle; skill folders mirror the spec layout (SKILL.md + references/ +
   optional scripts/ and assets/) when shipped as repo content.
10. **Update the manifest** — read the canonical manifest (from core's summary
    gate); add the authored artifacts (name, type, path) with status DRAFT;
    record target_runtime; update package status. The manifest path+hash
    travels with the package to review.
11. **Hand off** — mark DRAFT, hand the package + manifest to
    `process-engine-review`.

## Examples
- "I want a skill that writes release notes" → package: project + persona
  (system-prompt shape) + skills (release-notes skill, spec-valid SKILL.md,
  Osmani anatomy) + templates.
- "I want a package for a database-backup operator skill" → package: skill
  (spec-valid frontmatter, Osmani anatomy, examples, verification), template,
  reference additions.

## Common Rationalizations
- "I'll add sources later." → Sources are part of the draft, not a retrofit.
- "This intent is too small to need safeguards." → If the intent touches
  people or regulated domains, safeguards are part of the package, sized to
  the domain.
- "The description can be vague; the body explains it." → The description
  carries the whole triggering burden. Imperative, user-intent, explicit
  scope — or the skill never activates.

## Red Flags
- An artifact with no evidence naming, no safeguard pass (risk-relevant
  intents), or no acceptance criteria.
- A SKILL.md whose frontmatter violates the spec (name rules, description
  limits, unknown fields).
- Draft presented as "done" instead of "draft for review".

## Verification
- [ ] Eligibility gate passed — shape decided (project / persona / skill(s) / not an artifact)
- [ ] Correct anatomy chosen and complete
- [ ] Objective formed from the user's vision ("good") — or proposed in draft when underspecified
- [ ] Skill frontmatter spec-valid (name rules, description ≤1024, allowed fields)
- [ ] Provenance metadata included where source known
- [ ] Package folder layout follows the spec (SKILL.md + references/ + optional scripts/assets)
- [ ] Evidence named for every technique
- [ ] Safeguard pass done for risk-relevant intents (per-package, sourced)
- [ ] Governance artifacts generated per target_runtime (native for turnstone; advisory docs for portable; both when requested) — helper, advisory, no tool_gate, reversible
- [ ] Acceptance criteria written
- [ ] Marked DRAFT, handed to review
