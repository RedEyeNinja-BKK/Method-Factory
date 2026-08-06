---
name: process-engine-ship
description: Deploy an approved, trialed project/persona/skills/governance package via native mechanisms, verify it, and record evidence.
compatibility: Turnstone 1.8.x or any Agent Skills-compatible client
metadata:
  author: RedEyeNinja-BKK
  version: "1.9.1"
  engine: process-engine 1.9.1
---
## Overview
Ships only what has PASSED review AND trial — the generated package (project /
persona / skills / templates / governance) as a whole. Deployment is via
runtime-appropriate mechanisms, and verification matches the runtime:
read-back of created objects (Turnstone), file presence + hash checks
(filesystem), or remote branch/tag + content match (Git). Rollback is
defined before ship.

## When to Use
- Artifact passed review and trial, operator approved ship.
- Repo content release (public repo lifecycle).

## Core Process
1. **Confirm gates** according to the package's assurance tier (from manifest):

   - **Lightweight:** operator review PASS + basic trial PASS (2-3 deterministic
     cases). No baseline required. Ship deploys the skill/persona + records the
     manifest. Rollback is delete-and-restore.
   - **Standard:** review PASS (incl. spec compliance) + trial PASS (case suite +
     trigger set). Baseline recommended but optional. Rollback plan required.
   - **High-Assurance:** review PASS + trial all-PASS (incl. trigger set +
     baseline) + operator ship approval. Manifest must carry assurance_tier
     with basis. Rollback plan verified before deployment. Judge rules and
     prompt policies deployed as advisory, reversible governance helpers.

   All tiers require operator approval. Manifest must be present. No manifest,
   no ship.
2. **Define rollback**: how to undo this deployment (delete the created object /
   revert content) before touching anything.
3. **Deploy the package via runtime-appropriate mechanisms**:
   - **Turnstone deployment** (when target_runtime includes `turnstone`):
     - project → POST /v1/api/projects
     - persona → POST /v1/api/admin/personas
     - skills/templates → skills API (prompt_templates store)
     - prompt policy → POST /v1/api/admin/prompt-policies (content-only,
       priority 1, no tool_gate — the package's operating stance)
     - judge rules → POST /v1/api/admin/judge/heuristic-rules (advisory,
       risk=low, recommendation=review — the package's risk posture)
     - project context → project resources / workstream
     Governance artifacts are deployed as HELPER objects: advisory, never
     silent blockers, operator-visible, reversible (disable/delete).
   - **Filesystem deployment** (when target_runtime is `portable`):
     - Copy skill folders to the agent's skills directory (e.g. ~/.claude/skills/)
     - Copy persona.md to the agent's persona location (if supported)
     - Copy templates to the agent's template location (if supported)
     - No governance objects (portable runtime has no native governance)
   - **Git repository release** (when target_runtime is `portable` and the
     operator wants version-controlled distribution):
     - Stage files in the repo
     - Operator reviews final diff
     - Push via deploy key or operator credentials
     - Verify on the remote (GitHub, GitLab, etc.)
4. **Verify**: GET the created object back (Turnstone) or confirm file presence
   and content (filesystem/git); confirm identity + content.
5. **Manifest update**: record deployment objects (type, id, preexisting,
   rollback) + deployment state (PLANNED → APPLYING → VERIFYING → COMPLETE /
   PARTIAL) + rollback_plan in the manifest.
6. **Record evidence**: what shipped, mechanism, verification result, rollback path.

## Examples
- Ship generated package to Turnstone: POST project → POST persona → POST
  skills/templates → POST prompt policy → POST judge rule → GET each back →
  record → done.
- Ship generated package to Claude Code: copy skills/ to ~/.claude/skills/ →
  verify files present → record → done.
- Release repo content: stage files, operator reviews final diff, push via
  the project's deploy key (automated git tooling handles the mutation),
  verify on GitHub.

## Common Rationalizations
- "It passed review, just create it." → Trial is required too. No trial, no ship.
- "Rollback is easy, skip defining it." → Define it BEFORE the deploy, not after.

## Red Flags
- Shipping without all required gates. Tier determines which gates apply.
- No verification read-back.
- No rollback path.

## Verification
- [ ] Review PASS + trial PASS (depth per assurance tier) + operator approval all recorded
- [ ] Manifest present with all artifact records and evidence links
- [ ] Rollback path defined before deploy
- [ ] Manifest gates passed (manifest present; artifacts, review verdict,
  trial run linked)

Branch by runtime:

**Turnstone**
- [ ] Native objects deployed and read back
- [ ] Governance objects verified (prompt policy + judge rules, advisory,
  no tool_gate)

**Filesystem**
- [ ] Files copied to target skills directory
- [ ] Hashes match source package
- [ ] Agent discovers installed skills
- [ ] Smoke invocation passes

**Git**
- [ ] Commit SHA recorded
- [ ] Remote branch/tag verified
- [ ] Release contents match manifest

- [ ] Evidence recorded (deployment objects, state, rollback path)
