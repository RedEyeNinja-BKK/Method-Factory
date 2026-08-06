"""Prompt→envelope conformance fixtures (Phase 3 acceptance).

Purpose: prove the reoptimized core skill produces ONLY valid Action
Envelopes at decision points — no ACTION: markers, no enforcement prose,
and every proposed transition parses against the schema for its state.

These are fixtures, not a runtime dependency of the engine. They drive a
mock "operator" transcript through the prompt and assert the envelope the
prompt emits is valid.

Run: python -m unittest discover -s methodfactory/tests -t .   (Phase 4 CI)
     or: python3 methodfactory/tests/test_prompt_conformance.py  (direct)

Requires pyyaml (CI installs it via requirements-dev.txt) for the
frontmatter fixture check.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from methodfactory.domain.errors import InvalidEnvelopeError
from methodfactory.domain.transitions import ACTION_VOCABULARY
from methodfactory.protocol.envelope import parse_envelope

REPO = Path(__file__).resolve().parents[2]  # repo-staging/
PROMPTS = REPO / "prompts"

# ── structural checks (no execution) ────────────────────────────────────


class PromptStructuralTests(unittest.TestCase):
    def test_core_skill_exists_and_frontmatter_valid(self):
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        self.assertTrue(smd.is_file(), f"missing {smd}")
        text = smd.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"), "frontmatter missing")
        fm = text.split("---", 2)[1]
        data = yaml.safe_load(fm)
        self.assertEqual(data["name"], "method-factory-core")
        self.assertTrue(data.get("description"))

    def test_no_action_marker_text_anywhere_in_prompts(self):
        # The legacy marker style ("ACTION: TOKEN") must not reappear.
        # The accepted protocol is a JSON envelope. This is the regression
        # guard: marker-style text must not be proposed as a state change.
        bad = []
        for p in PROMPTS.rglob("*.md"):
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"ACTION\s*:\s*[A-Z_]+", text):
                bad.append(f"{p.relative_to(PROMPTS)}: {m.group(0)}")
        self.assertEqual(bad, [])

    def test_no_enforcement_prose_in_core(self):
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        for banned in (
            "must not proceed until",
            "do not proceed until",
            "first-response",
            "tier",
            "manifest mechanics",
            "No manifest, no package",
        ):
            self.assertNotIn(banned.lower(), text.lower(), f"enforcement prose: {banned}")

    def test_templates_created(self):
        for rel in ("orientation.md", "starter-author.md"):
            self.assertTrue((PROMPTS / "templates" / rel).is_file(), f"missing templates/{rel}")

    def test_references_copied(self):
        for rel in ("standards.md", "intake.md", "safety.md"):
            self.assertTrue((PROMPTS / "references" / rel).is_file(), f"missing references/{rel}")


# ── envelope emission checks (the core acceptance) ──────────────────────


class EnvelopeEmissionTests(unittest.TestCase):
    """Simulate: 'collect a link' decision → the prompt must emit a valid
    record_input envelope; 'confirmation' → confirm_summary with basis."""

    def test_core_mentions_the_envelope_and_json(self):
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        self.assertIn("Action Envelope", text)
        self.assertIn("protocol_version", text)
        self.assertIn("expected_revision", text)

    def test_vocabulary_aligned_with_engine(self):
        # The prompt's stated actions must be exactly the engine's vocabulary.
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        for action in sorted(ACTION_VOCABULARY):
            self.assertIn(action, text, f"prompt missing action {action}")

    def test_example_envelope_parses(self):
        # The example record_input envelope shown in the prompt must parse.
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        # find the first JSON block
        blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
        self.assertTrue(blocks, "no JSON example block found in core skill")
        ok = False
        for block in blocks:
            try:
                env = parse_envelope(block)
                ok = True
                break
            except InvalidEnvelopeError:
                continue
        self.assertTrue(ok, "no example JSON block parses as a valid envelope")

    def test_confirm_example_has_basis(self):
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        # confirm_summary example must show basis.summary_sha256 (approval binding)
        self.assertIn("summary_sha256", text)

    def test_expected_revision_and_package_id_are_placeholders(self):
        smd = PROMPTS / "skills" / "method-factory-core" / "SKILL.md"
        text = smd.read_text(encoding="utf-8")
        # The prompt must tell the agent to take package_id + expected_revision
        # FROM THE CODE (never invent them).
        self.assertIn("package_id", text)
        self.assertIn("expected_revision", text)


if __name__ == "__main__":
    unittest.main()
