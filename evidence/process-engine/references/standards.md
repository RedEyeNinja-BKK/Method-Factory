# references/standards.md — Engine standards checklist

Applied to EVERY generated artifact/package. Load before authoring and before review.

1. **Evidence-naming** — every technique labeled with its real, named source.
   Never "research shows" without a source. Never borrow authority you don't have.
   Bake provenance (source URL/date) into generated SKILL.md metadata when the
   source is known.
2. **Scope honesty** — a package never claims capabilities or validity its named
   sources don't support. When the intent touches a risk-relevant domain
   (domains involving people, regulated activities, safety-critical systems,
   or any domain the operator designates), the
   generated package carries explicit, evidence-named scope limits and
   per-package safeguards built at generation time (references/safety.md) —
   the engine presets no domain doctrine.
3. **Review gates** — nothing ships without operator review. Draft → sign-off →
   create/deploy → verify. Never self-approve. A REVISE verdict returns the
   artifact through a formal diagnose → rewrite → audit loop before re-review.
4. **Acceptance criteria** — every artifact carries explicit exit criteria.
   "Seems right" is never sufficient.
5. **Privacy** — sensitive content is processed locally when a local model is
   available and verified; otherwise the limitation is disclosed and operator
   approval obtained before any external processing. Templates/patterns ship
   publicly, user/operator data never does.
6. **Anatomy** — skills follow the SKILL.md anatomy
   (references/skill-anatomy.md): spec-valid frontmatter + 7 body sections.
7. **Verification culture** — evidence requirements at every step; trials before ship.
8. **Format compliance** — generated skills follow the Agent Skills open standard:
   name (lowercase letters/digits/hyphens, ≤64 chars, matches directory),
   description (≤1024 chars, what + when, imperative), allowed frontmatter
   fields only (license, compatibility, metadata, allowed-tools); package
   folders mirror the spec layout (SKILL.md, references/, optional scripts/
   and assets/). Spec-valid by construction; checked at review.
9. **Intake** — user-provided material is extracted and incorporated:
   techniques and domain specifics are pulled from all provided sources,
   original instructions are authored (never verbatim copying), and
   influence is attributed when the source is known. License info is
   provenance, not a gate. The generated package still passes the
   normal review/operator gates (references/intake.md).
10. **Input-agnostic** — the engine accepts ANY user-provided material
    (skill links, text, files, store links, docs, examples) and uses it
    all; nothing is rejected by type (references/intake.md).
11. **Heads-up, not police** — the engine surfaces useful considerations
    (platform policy, claim checks, edge cases) as heads-ups; heads-ups
    inform and never obstruct. The operator is the only gate
    (references/safety.md).
12. **Eligibility gate** — before authoring, every intent is shaped
    deliberately: is this a project, a persona, a single skill, multiple
    skills, or not an artifact at all? Never assume the shape.
13. **Per-package governance** — every generated package carries a prompt
    policy + judge rules as HELPER artifacts: advisory, operator-visible,
    reversible (disable/delete), and never silent blockers (no tool_gate,
    no deny/high-risk defaults) (references/governance.md).
