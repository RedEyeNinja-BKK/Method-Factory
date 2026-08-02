#!/usr/bin/env bash
# Process Engine — portable end-to-end install test harness (PROVISIONED, not run).
#
# Operator decision (2026-08-01): no live testing on another agent client right
# now. Provisioning only — this script documents and prepares the first real
# proof of full-pipeline portability (deferred, like the scenario production line).
#
# Working assumption: built-to-Agent-Skills-standard => portable, even if not
# optimized for other clients.
#
# Usage (when un-deferred):
#   ./scripts/test-portable-install.sh <target-skills-dir>
#
# Steps it performs:
#   1. Fresh environment: mkdir -p <target>/skills; empty project dir
#   2. Install all six skills: cp -r Process-Engine/skills/process-engine-* <target>/skills/
#   3. Invoke core: start agent in empty project; "Use process-engine-core. I want to build..."
#   4. Generate one small package (e.g. a release-notes skill)
#   5. Review it (process-engine-review)
#   6. Trial it (process-engine-trial)
#   7. Filesystem ship (process-engine-ship -> copy to another dir)
#   8. Verify installed package (files present, frontmatter valid)
#   9. Roll it back (delete copied package)
#
# Records: commands, runtime version, outputs, discovered skills, failure
# points, final package tree -> docs/portable-install-test-<date>.md

set -euo pipefail

TARGET="${1:?usage: $0 <target-skills-dir>}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d)"
OUT="docs/portable-install-test-${STAMP}.md"

echo "# Portable install test — ${STAMP}" > "$OUT"
echo "" >> "$OUT"
echo "**Status:** provisioned, not executed (operator deferred external-client testing 2026-08-01)." >> "$OUT"
echo "" >> "$OUT"
echo "## Target" >> "$OUT"
echo "\`\`\`" >> "$OUT"
echo "skills dir: ${TARGET}" >> "$OUT"
echo "agent runtime: (record client name + version here)" >> "$OUT"
echo "repo commit: $(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)" >> "$OUT"
echo "\`\`\`" >> "$OUT"
echo "" >> "$OUT"
echo "## 1. Fresh environment" >> "$OUT"
mkdir -p "$TARGET"
echo "\`\`\`bash" >> "$OUT"
echo "mkdir -p ${TARGET}" >> "$OUT"
echo "\`\`\`" >> "$OUT"
echo "" >> "$OUT"

echo "## 2. Install all six skills" >> "$OUT"
echo "\`\`\`bash" >> "$OUT"
echo "cp -r ${REPO_DIR}/skills/process-engine-* ${TARGET}/" >> "$OUT"
echo "\`\`\`" >> "$OUT"
echo "" >> "$OUT"

echo "## 3-9. Pipeline (record outputs here when executed)" >> "$OUT"
echo "- Invoke core -> first response asks for material (PASS/FAIL/notes)" >> "$OUT"
echo "- Generate small package (release-notes) -> DRAFT produced" >> "$OUT"
echo "- Review -> verdict recorded" >> "$OUT"
echo "- Trial -> case set run, PASS/FAIL" >> "$OUT"
echo "- Filesystem ship -> files copied, hashes match" >> "$OUT"
echo "- Verify installed package -> frontmatter valid, agent discovers skills" >> "$OUT"
echo "- Rollback -> copied package deleted" >> "$OUT"
echo "" >> "$OUT"

echo "## Discovered skills" >> "$OUT"
echo "\`\`\`bash" >> "$OUT"
echo "ls ${TARGET}/ | grep process-engine" >> "$OUT"
echo "\`\`\`" >> "$OUT"
echo "" >> "$OUT"

echo "Harness prepared: $OUT"
echo "Not executed (deferred). When un-deferred: run ./scripts/test-portable-install.sh <dir> and fill in the pipeline results."
