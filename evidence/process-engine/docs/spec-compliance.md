# Spec compliance

Every skill this engine generates complies with the
[Agent Skills open format standard](https://github.com/agentskills/agentskills)
(originally developed by Anthropic; code Apache-2.0, docs CC-BY-4.0).

## What compliance means

### Frontmatter

| Field | Rule enforced |
|---|---|
| `name` | lowercase letters/digits/hyphens only; ≤64 chars; must match the parent directory name |
| `description` | ≤1024 chars; says what the skill does and when to use it; imperative phrasing |
| `compatibility` | optional; ≤500 chars; environment requirements |
| `metadata` | optional; arbitrary key-value map |
| `license` | optional; license name or bundled license file |
| `allowed-tools` | optional; experimental |

### Folder layout

```
skill-name/
├── SKILL.md          # required: metadata + instructions
├── scripts/          # optional: executable code
├── references/       # optional: documentation
├── assets/           # optional: templates, resources
└── evals/            # optional: evals.json case set
```

### Progressive disclosure

- **Discovery** — agents load only `name` + `description` (the activation
  surface; descriptions are written trigger-first for this reason).
- **Activation** — full SKILL.md loads when a task matches.
- **Execution** — references/scripts load on demand.

## How compliance is checked

- **At authoring** (pattern-author): spec-valid frontmatter is part of the
  generation standard — valid by construction.
- **At review** (review): a spec-compliance step validates the generated
  skill; on turnstone this uses the native parse endpoint
  (`POST /v1/api/admin/skills/parse`), externally the
  [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref)
  reference implementation (`skills-ref validate path/to/skill`).
- **At trial** (trial): trigger sets exercise the description surface —
  activation must be correct, not just valid.

## Notes

- The engine's own skills in this repository are spec-valid (real frontmatter,
  per-skill folders, references/ directory).
- When deployed into turnstone's native store, the same content is stored in
  turnstone-native form (frontmatter in a `yaml` code block); the two forms
  are equivalent in content and both pass their respective validators.
