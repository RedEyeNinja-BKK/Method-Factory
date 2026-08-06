#!/usr/bin/env python3
"""Regenerate repository content from the Process Engine authoring source.

Source of truth for CONTENT: the drafts directory (identical content is also
deployed to the turnstone native store). This script converts the
Turnstone-native skill format (YAML frontmatter inside a ```yaml code block)
into spec-valid Agent Skills SKILL.md files (real YAML frontmatter), then
copies references, templates, persona, and evals into place.

It ONLY touches generated content paths:
    skills/*/SKILL.md, references/*.md, templates/*.md, persona.md, evals/*
Repo-meta files (README, LICENSE, CONTRIBUTING, CHANGELOG, docs/, .gitignore,
scripts/) are never modified.

Stale-guard: refuses to overwrite repository content whose lineage is NEWER
than the drafts being written (Phase 5 regression prevention). Generation is
staged in a temporary directory and validated there before any repository
file is replaced, so a validation failure never modifies the repo. The final
swap applies staged files one-by-one (not a single filesystem transaction),
so it minimizes — but does not mathematically eliminate — partial-update
risk; on interruption, re-running the converter completes the swap.

Usage:
    python3 scripts/convert.py [--drafts DIR] [--repo DIR]

Defaults:
    --drafts  ../drafts   (repo-adjacent authoring directory)
    --repo    ..          (the repository root, parent of scripts/)

Exit code 0 = regenerated + validated. Non-zero = failure; nothing is
written to the repository on a validation failure (staging happens first).

Requires: python3 + PyYAML.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import yaml

# --- Load canonical release manifest ---
def load_version_config(repo):
    """Load release facts from process-engine.toml"""
    config_path = os.path.join(repo, "process-engine.toml")
    if not os.path.isfile(config_path):
        return None

    config = {}
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    return config

VERSION_CONFIG = None  # Will be loaded in main()

# --- Content lineage (loaded from process-engine.toml) ---
AUTHOR = None
CONTENT_VERSION = None
ENGINE_VERSION = None
COMPATIBILITY = None
LINEAGE = None
SKILL_COUNT = 0
REF_COUNT = 0
TMPL_COUNT = 0
EVAL_COUNT = 0

SKILL_MAP = {
    "02-skill-core.md": "process-engine-core",
    "03-skill-pattern-author.md": "process-engine-pattern-author",
    "04-skill-review.md": "process-engine-review",
    "05-skill-trial.md": "process-engine-trial",
    "06-skill-ship.md": "process-engine-ship",
    "07-skill-triage.md": "process-engine-triage",
}
REFERENCES = ["standards", "safety", "evidence-library", "skill-anatomy", "best-practices", "intake", "governance"]
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEADING_RE = re.compile(r"^# SKILL\.md — [^\n]+\n+")
FRONTMATTER_BLOCK_RE = re.compile(r"```yaml\n(.*?)\n```\n\n(.*)$", re.S)
TEMPLATE_BLOCK_RE = re.compile(
    r"^## (process-engine-[\w-]+)\n\*\*Category:\*\* [^\n]+ · \*\*Description:\*\* [^\n]+\n\n```\n(.*?)\n```",
    re.M | re.S,
)

FAILURES = []


def fail(msg):
    FAILURES.append(msg)
    print(f"  FAIL  {msg}")


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def extract_frontmatter(draft_text):
    m = FRONTMATTER_BLOCK_RE.search(draft_text)
    if not m:
        raise ValueError("no yaml frontmatter block found")
    desc = re.search(r"^description:\s*(.+)$", m.group(1), re.M)
    if not desc:
        raise ValueError("no description in frontmatter")
    return desc.group(1).strip(), re.sub(HEADING_RE, "", m.group(2))


def build_skill(skill_name, description, body):
    return (
        "---\n"
        f"name: {skill_name}\n"
        f"description: {description}\n"
        f"compatibility: {COMPATIBILITY}\n"
        "metadata:\n"
        f"  author: {AUTHOR}\n"
        f'  version: "{CONTENT_VERSION}"\n'
        f"  engine: {ENGINE_VERSION}\n"
        "---\n"
        f"{body}"
    )


def validate_skill(repo, skill_name):
    skill_dir = os.path.join(repo, "skills", skill_name)
    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(skill_md):
        fail(f"{skill_name}: SKILL.md missing")
        return False
    if os.path.basename(skill_dir) != skill_name:
        fail(f"{skill_name}: directory name mismatch")
        return False
    text = open(skill_md).read()
    if not text.startswith("---"):
        fail(f"{skill_name}: missing leading frontmatter")
        return False
    try:
        fm = yaml.safe_load(text.split("---", 2)[1])
    except Exception as e:
        fail(f"{skill_name}: frontmatter parse error: {e}")
        return False
    ok = True
    if fm.get("name") != skill_name:
        fail(f"{skill_name}: frontmatter name {fm.get('name')!r} != {skill_name!r}")
        ok = False
    desc = fm.get("description") or ""
    if not desc:
        fail(f"{skill_name}: missing description")
        ok = False
    elif len(desc) > 1024:
        fail(f"{skill_name}: description > 1024 chars")
        ok = False
    if not NAME_RE.match(skill_name):
        fail(f"{skill_name}: name fails lowercase-hyphen rule")
        ok = False
    return ok


def swap_file(staging, repo, rel):
    """Overwrite one generated file in the repo from staging (preserves siblings)."""
    staged = os.path.join(staging, rel)
    if not os.path.exists(staged):
        return
    target = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(staged, target)


def swap_dir(staging, repo, rel):
    """Replace one generated directory wholesale (skills/ is fully generated)."""
    staged = os.path.join(staging, rel)
    if not os.path.exists(staged):
        return
    target = os.path.join(repo, rel)
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
    elif os.path.exists(target):
        os.remove(target)
    shutil.move(staged, target)


def main():
    global AUTHOR, CONTENT_VERSION, ENGINE_VERSION, COMPATIBILITY, LINEAGE
    global SKILL_COUNT, REF_COUNT, TMPL_COUNT, EVAL_COUNT

    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts", default=None, help="authoring drafts directory")
    ap.add_argument("--repo", default=None, help="repository root")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    drafts = os.path.abspath(args.drafts) if args.drafts else os.path.join(os.path.dirname(repo), "drafts")

    # Load release manifest
    VERSION_CONFIG = load_version_config(repo)
    if not VERSION_CONFIG:
        print("ERROR: process-engine.toml not found")
        sys.exit(1)

    AUTHOR = VERSION_CONFIG.get("author")
    CONTENT_VERSION = VERSION_CONFIG.get("version")
    ENGINE_VERSION = VERSION_CONFIG.get("engine")
    COMPATIBILITY = VERSION_CONFIG.get("compatibility")
    LINEAGE = VERSION_CONFIG.get("lineage", "")
    SKILL_COUNT = int(VERSION_CONFIG.get("skill_count", 0) or 0)
    REF_COUNT = int(VERSION_CONFIG.get("reference_count", 0) or 0)
    TMPL_COUNT = int(VERSION_CONFIG.get("template_count", 0) or 0)
    EVAL_COUNT = int(VERSION_CONFIG.get("eval_case_count", 0) or 0)

    if not all([AUTHOR, CONTENT_VERSION, ENGINE_VERSION, COMPATIBILITY, LINEAGE]):
        print("ERROR: process-engine.toml missing required fields")
        sys.exit(1)

    # --- Stale-guard: refuse to overwrite newer repo content with older drafts ---
    # The canonical basis is process-engine.toml (CONTENT_VERSION). Drafts that
    # lag the canonical version indicate the Phase 5 regression class: stale
    # drafts regenerating over newer repo content. Guard on both surfaces:
    # (1) draft evals/README release-aligned version must equal CONTENT_VERSION
    # (2) draft evals.json package descriptor must contain CONTENT_VERSION
    import re as _re
    draft_readme_v = None
    draft_readme_path = os.path.join(drafts, "evals", "README.md")
    if os.path.isfile(draft_readme_path):
        m = _re.search(r"release-aligned \*\*v([0-9.]+)\*\*", open(draft_readme_path).read())
        if m:
            draft_readme_v = m.group(1)
    if draft_readme_v and draft_readme_v != CONTENT_VERSION:
        print(f"ERROR: stale-guard — drafts evals/README is v{draft_readme_v}, canonical is v{CONTENT_VERSION}")
        print("  Refusing to regenerate: drafts are behind the release manifest. Update drafts first.")
        sys.exit(1)

    draft_evals_json = os.path.join(drafts, "evals", "evals.json")
    if os.path.isfile(draft_evals_json):
        try:
            d = json.load(open(draft_evals_json))
            pkg = d.get("package", "") if isinstance(d, dict) else ""
        except Exception:
            pkg = ""
        if pkg and CONTENT_VERSION not in pkg:
            print(f"ERROR: stale-guard — drafts evals.json package descriptor lacks v{CONTENT_VERSION}: {pkg!r}")
            print("  Refusing to regenerate: drafts are behind the release manifest. Update drafts first.")
            sys.exit(1)

    print(f"drafts: {drafts}")
    print(f"repo:   {repo}")
    print(f"version: {CONTENT_VERSION} · lineage {LINEAGE} · {SKILL_COUNT} skills / {REF_COUNT} refs / {TMPL_COUNT} tmpl / {EVAL_COUNT} evals")

    if not os.path.isdir(drafts):
        fail(f"drafts directory not found: {drafts}")
        sys.exit(1)

    # --- Stage everything into a temp dir first; validate; then swap atomically ---
    staging = tempfile.mkdtemp(prefix="convert-staging-")
    try:
        # 1. Skills: convert Turnstone codeblock frontmatter -> real YAML frontmatter
        for fname, skill_name in SKILL_MAP.items():
            draft = os.path.join(drafts, fname)
            if not os.path.isfile(draft):
                fail(f"{skill_name}: draft {fname} missing")
                continue
            try:
                desc, body = extract_frontmatter(open(draft).read())
            except ValueError as e:
                fail(f"{skill_name}: {e}")
                continue
            write(os.path.join(staging, "skills", skill_name, "SKILL.md"),
                  build_skill(skill_name, desc, body))
            print(f"  skill: {skill_name}")

        # 2. References
        for name in REFERENCES:
            src = os.path.join(drafts, "references", f"{name}.md")
            if os.path.isfile(src):
                write(os.path.join(staging, "references", f"{name}.md"), open(src).read())
                print(f"  reference: {name}")
            else:
                fail(f"reference {name}: draft missing")

        # 2b. Self-contained package: copy references into process-engine-core
        core_refs_dir = os.path.join(staging, "skills", "process-engine-core", "references")
        os.makedirs(core_refs_dir, exist_ok=True)
        for name in REFERENCES:
            src = os.path.join(drafts, "references", f"{name}.md")
            if os.path.isfile(src):
                write(os.path.join(core_refs_dir, f"{name}.md"), open(src).read())
        print(f"  self-contained: {len(REFERENCES)} references copied to process-engine-core/references/")

        # 3. Templates from the session-templates draft
        tmpl_draft = os.path.join(drafts, "08-session-templates.md")
        if os.path.isfile(tmpl_draft):
            for m in TEMPLATE_BLOCK_RE.finditer(open(tmpl_draft).read()):
                tname = m.group(1).replace("process-engine-", "")
                write(os.path.join(staging, "templates", f"{tname}.md"), m.group(2))
                print(f"  template: {tname}")
        else:
            fail("templates draft 08-session-templates.md missing")

        # 4. Persona
        src = os.path.join(drafts, "01-persona-base-prompt.md")
        if os.path.isfile(src):
            write(os.path.join(staging, "persona.md"), open(src).read())
            print("  persona.md")
        else:
            fail("persona draft missing")

        # 5. Evals
        for f in ("evals.json", "README.md", "trial-evidence.md", "governance-evidence.md"):
            src = os.path.join(drafts, "evals", f)
            if os.path.isfile(src):
                write(os.path.join(staging, "evals", f), open(src).read())
                print(f"  evals/{f}")
            else:
                fail(f"evals/{f} draft missing")

        # 6. Validate everything generated in staging
        for skill_name in SKILL_MAP.values():
            validate_skill(staging, skill_name)

        # Validate template count
        expected_templates = {"orientation", "starter-author", "starter-review", "starter-trial", "starter-ship", "starter-triage"}
        actual_templates = set()
        templates_dir = os.path.join(staging, "templates")
        if os.path.isdir(templates_dir):
            for fname in os.listdir(templates_dir):
                if fname.endswith(".md"):
                    actual_templates.add(fname[:-3])  # strip .md

        missing_templates = expected_templates - actual_templates
        extra_templates = actual_templates - expected_templates
        if missing_templates:
            fail(f"missing templates: {', '.join(sorted(missing_templates))}")
        if extra_templates:
            fail(f"unexpected templates: {', '.join(sorted(extra_templates))}")
        if len(actual_templates) != TMPL_COUNT:
            fail(f"template count {len(actual_templates)} != manifest {TMPL_COUNT}")

        # Validate reference count
        expected_refs = set(REFERENCES)
        actual_refs = set()
        refs_dir = os.path.join(staging, "references")
        if os.path.isdir(refs_dir):
            for fname in os.listdir(refs_dir):
                if fname.endswith(".md"):
                    actual_refs.add(fname[:-3])  # strip .md

        missing_refs = expected_refs - actual_refs
        extra_refs = actual_refs - expected_refs
        if missing_refs:
            fail(f"missing references: {', '.join(sorted(missing_refs))}")
        if extra_refs:
            fail(f"unexpected references: {', '.join(sorted(extra_refs))}")
        if len(actual_refs) != REF_COUNT:
            fail(f"reference count {len(actual_refs)} != manifest {REF_COUNT}")
        if len(SKILL_MAP) != SKILL_COUNT:
            fail(f"skill count {len(SKILL_MAP)} != manifest {SKILL_COUNT}")

        # Validate version consistency across all skills
        for skill_name in SKILL_MAP.values():
            skill_md = os.path.join(staging, "skills", skill_name, "SKILL.md")
            if os.path.isfile(skill_md):
                with open(skill_md) as f:
                    content = f.read()
                # Extract version from frontmatter
                match = re.search(r'version:\s*"([^"]+)"', content)
                if match:
                    skill_version = match.group(1)
                    if skill_version != CONTENT_VERSION:
                        fail(f"{skill_name}: version {skill_version} != expected {CONTENT_VERSION}")
                else:
                    fail(f"{skill_name}: no version found in frontmatter")

        # Validate evals.json: parse + package descriptor + case count
        try:
            evals_data = json.load(open(os.path.join(staging, "evals", "evals.json")))
        except Exception as e:
            fail(f"evals.json invalid: {e}")
        else:
            cases = evals_data.get("evals", []) if isinstance(evals_data, dict) else []
            if len(cases) != EVAL_COUNT:
                fail(f"evals.json case count {len(cases)} != manifest {EVAL_COUNT}")
            pkg = evals_data.get("package", "")
            if CONTENT_VERSION not in pkg:
                fail(f"evals.json package descriptor missing version {CONTENT_VERSION}: {pkg!r}")

        if FAILURES:
            print(f"\nCONVERT FAILED: {len(FAILURES)} problem(s) — nothing written to repo")
            sys.exit(1)

        # All good — swap staged content into the repo
        # skills/ is fully generated -> wholesale replace
        swap_dir(staging, repo, "skills")
        # persona.md fully generated -> overwrite
        swap_file(staging, repo, "persona.md")
        # references/, templates/, evals/ -> per-file overwrite (preserve non-generated siblings like runs/, case-study)
        for name in REFERENCES:
            swap_file(staging, repo, os.path.join("references", f"{name}.md"))
        for tname in expected_templates:
            swap_file(staging, repo, os.path.join("templates", f"{tname}.md"))
        for f in ("evals.json", "README.md", "trial-evidence.md", "governance-evidence.md"):
            swap_file(staging, repo, os.path.join("evals", f))

        print("\nCONVERT OK — content regenerated, validated, and swapped into place.")
        print("Review `git status`/`git diff` before committing.")
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == "__main__":
    main()
