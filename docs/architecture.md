# Architecture

> **Historical / superseded.** This document describes the Process Engine era. Current Method Factory architecture and release state: see [architecture-reset-status.md](architecture-reset-status.md) and [ADR-0012](adr/ADR-0012-persistence-architecture.md).

Process Engine is an agent-skill framework: a persona, six skills, seven
references, and six session templates that drive a gated authoring pipeline.
It is **runtime-aware**: the same core content deploys three ways.

1. **Portable logical architecture** — the skills + references are
   Agent Skills-compatible content that runs on any compliant client
   (Claude Code, Codex, Cursor, Gemini CLI, …). Core is self-contained
   (references embedded). No native platform objects required.
2. **Turnstone deployment architecture** — the same content deploys as a
   native Turnstone project: persona, skills + templates in the prompt
   store, references as skill resources, plus governance wiring
   (prompt policy + advisory judge rules).
3. **Filesystem / Git deployment architecture** — the portable content ships
   as files (a skills directory, a Git repository) with hash-verified
   installation and rollback.

Everything the pipeline produces has the same shape — a project/persona/skills
package — and goes through the same gated pipeline.

## Components

```
Process Engine (project)
├── persona: process-engine        # identity, standards, working style
├── skills/ (6)
│   ├── process-engine-core        # entry + routing
│   ├── process-engine-pattern-author
│   ├── process-engine-review
│   ├── process-engine-trial
│   ├── process-engine-ship
│   └── process-engine-triage
├── references/ (7, on core)       # loaded on demand
│   ├── standards.md               # standards checklist
│   ├── safety.md                  # heads-up practice
│   ├── evidence-library.md        # named basis sources
│   ├── skill-anatomy.md           # SKILL.md anatomy
│   ├── best-practices.md          # catalog + spec index
│   ├── intake.md                  # input-agnostic intake
│   └── governance.md              # Turnstone governance objects
└── templates/ (6)                 # session initial prompts
```

## The pipeline

```
intent ─▶ COLLECT ─▶ CLARIFY ─▶ OBJECTIVE ─▶ GATE ─▶ PATTERN ─▶ REVIEW ─▶ TRIAL ─▶ SHIP
             │           │           │          │        │         │         │        │
             │           │           │          │        │         ▼         ▼        ▼
             │           │           │          │        │     verdict   PASS/FAIL  read-back
             │           │           │          │        │     (PASS/     per case  verification
             │           │           │          │        │      REVISE/
             │           │           │          │        │       REJECT)
             └───────────┴───────────┴──────────┴────────┴── summary / review / trial / ship gates
```

**Manifest state spine** (v1.9.1): every package carries a canonical manifest
(`docs/package-manifest-schema.md`) initialized at the Gate stage and updated
at every stage — Pattern (artifacts DRAFT), Review (findings + verdict),
Trial (run link + verdict), Ship (deployment objects + rollback). The
manifest is the durable state record: no manifest, no package.

- **Collect** — the engine invites material (links, text, files, docs) and
  routes each item through intake (input-agnostic, extract-author-original).
- **Clarify** — one question at a time, informed by the collected material.
- **Objective** — the engine asks what "good" looks like; the vision seeds
  the package's objective and outcomes.
- **Gate** — summary of material + intent + vision; operator confirms.
  Initializes the package manifest (package_id, intent, objective, inputs).
- **Pattern** — eligibility gate decides the shape; pattern-author designs
  the package to standard, names evidence, builds per-package safeguards
  for risk-relevant intents, writes acceptance criteria. Output: DRAFT;
  manifest updated (artifacts, target_runtime).
- **Review** — standards checklist, spec-compliance check, anatomy check,
  coverage check, adversarial pass. Verdict with evidence; operator sign-off
  is the gate. Manifest updated (findings, verdict, isolation level);
  refuses review without a manifest.
- **Trial** — case set from acceptance criteria + scope surface (happy path,
  gray zone, escalation, boundary, trigger set), with/without baseline,
  actual vs expected recorded, token cost captured. Manifest updated (run
  link, verdict, content hashes).
- **Ship** — confirm gates (incl. manifest gates), define rollback, deploy
  via runtime-appropriate mechanisms, verify by read-back, record evidence.
  Manifest updated (deployment objects, state, rollback).

## Release integrity (v1.9.1)

- `process-engine.toml` is the canonical release manifest (version, lineage,
  artifact counts). `scripts/validate.py` + the GitHub Actions release gate
  fail on any mismatch: stale versions, wrong counts, broken evidence links,
  embedded↔root reference drift, frontmatter violations, generated-diff
  drift. `scripts/convert.py` regenerates from drafts with a stale-guard and
  atomic staging (no partial writes).

## Native mechanisms used

| Artifact | Native mechanism |
|---|---|
| Project | `POST /v1/api/projects` |
| Persona | `POST/PATCH /v1/api/admin/personas` |
| Skills + templates | skills API (`prompt_templates` store): `POST/PUT /v1/api/admin/skills` |
| References | skill resources: `POST /v1/api/admin/skills/{id}/resources` |
| Session start | prompt templates (orientation + starters) |

## Store format vs repository format

Turnstone's native store keeps skill metadata in API fields (name, description,
content), with frontmatter shown as a `yaml` code block inside content. The
Agent Skills open format standard uses real YAML frontmatter at the top of
`SKILL.md`. The repository keeps the spec-valid form; the native store keeps
its native form. Content is otherwise identical (verified by byte-for-byte
comparison at every deployment).
