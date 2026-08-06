---
name: process-engine-review
description: The engine's review gate — spec compliance, standards, scope, evidence, safeguards, and acceptance-criteria check before anything ships. Operator sign-off is mandatory.
compatibility: Turnstone 1.8.x or any Agent Skills-compatible client
metadata:
  author: RedEyeNinja-BKK
  version: "1.9.1"
  engine: process-engine 1.9.1
---
## Overview
Reviews a draft against the engine's standards. Produces a verdict (PASS /
REVISE / REJECT) with evidence. NEVER auto-ships — the operator's sign-off is
the gate.

## When to Use
- Any artifact after pattern-author produces a draft.
- Re-review after revisions.

## Core Process
1. **Standards checklist** (references/standards.md): evidence-named? scope
   honest? acceptance criteria present?
2. **Spec compliance check**: validate generated skills against the Agent
   Skills open standard — name lowercase-hyphen ≤64 matching the directory,
   description ≤1024 with triggering language, allowed frontmatter fields only,
   SKILL.md present. Use the native parse endpoint (POST /v1/api/admin/skills/
   parse) where available; otherwise manual check.
3. **Safeguard review** (risk-relevant intents only): per-package safeguards
   present, evidence-named, sized to the domain — no preset doctrine
   (references/safety.md).
4. **Anatomy check**: all sections complete and load-bearing
   (references/skill-anatomy.md).
5. **Coverage check**: does the package cover the phases its intent requires
   (references/best-practices.md catalog)?
6. **Adversarial pass**: try to break it — edge cases, gray zones,
   rationalizations a user/agent would make.
7. **Verdict + evidence**: PASS / REVISE (specific) / REJECT (why). A REVISE
   verdict returns the artifact through the formal fix loop below — never
   straight to ship.
8. **Manifest update**: read the package manifest; append structured findings
   (id, severity, location, requirement, evidence, required_correction);
   record reviewer isolation level and operator approval. Refuse review
   without a manifest (missing manifest = missing intent/input record).
9. **Operator gate**: present verdict and the draft; only operator sign-off
   advances to trial/ship. Log the verdict.

## REVISE loop (formal)

1. **Diagnose** — the verdict names each specific finding (what, where, why).
2. **Rewrite** — pattern-author revises the artifact against the findings,
   preserving intent.
3. **Audit** — the artifact returns to review; the re-review confirms each
   finding is addressed and the result is materially better than before.
   Regression trial re-runs after any change that affects its performance
   or scope (process-engine-trial).

## Examples
- Generated package review: frontmatter spec-valid? acceptance criteria
  present? evidence named? scope limits explicit? safeguards (if risk-relevant)
  present and sourced? → PASS-with-notes or REVISE.
- Skill review: is the Red Flags section real or decorative?

## Common Rationalizations
- "The operator already saw it informally." → Informal ≠ review. Formal
  verdict + sign-off is the record.
- "It passed the checklist, ship it." → Checklist is necessary, not
  sufficient; the operator gate is the sufficient part.
- "The name is fine even if it doesn't match the folder." → Spec requires the
  match; a portable skill must validate anywhere.

## Red Flags
- Shipping without a recorded verdict.
- A verdict that ignores the safeguard pass for risk-relevant intents.
- A spec violation waved through ("clients won't notice").
- "PASS" without evidence.

## Verification
- [ ] Standards checklist completed
- [ ] Spec compliance checked (frontmatter, name/description rules)
- [ ] Safeguard review completed (risk-relevant intents only)
- [ ] Coverage check completed against the catalog
- [ ] Verdict recorded with evidence
- [ ] REVISE loop followed when verdict is REVISE (diagnose → rewrite → audit)
- [ ] Operator sign-off obtained and logged
