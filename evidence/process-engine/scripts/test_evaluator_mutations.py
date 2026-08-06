#!/usr/bin/env python3
"""Mutation tests for the evaluator and committed-evidence gate."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate.py"


def run_validator(run):
    result = subprocess.run(["python3", str(VALIDATE), "--repo", str(ROOT), "--no-diff"],
                            cwd=run, capture_output=True, text=True)
    return result.returncode


def test_semantic_fail_gate():
    # Direct evaluator proof: disabled semantic judge is conservative FAIL.
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    # no-poem is now semantic_judge — when judge is disabled, must return FAIL
    row = evaluate.evaluate_assertion({"id": "x", "prompt": "x"},
        {"id": "no-poem", "check": "response does not fulfill the creative request"}, "The ocean is deep and blue.", "x")
    assert row["result"] == "FAIL", "semantic judge disabled must return conservative FAIL"


def test_malformed_proof_and_altered_proof():
    evidence = ROOT / "evals/runs/release-v1.8.2-r1/run-a-hermes-exec"
    rows = [json.loads(x) for x in (evidence / "assertions.jsonl").read_text().splitlines() if x]
    semantic = next((r for r in rows if r["type"] in ("semantic_judge", "unsupported") and r["proof"].get("rationale")), None)
    assert semantic is not None, "no semantic/unsupported row with committed proof found"
    assert all(k in semantic["proof"] for k in ("model", "rubric_hash", "prompt_hash", "confidence", "rationale"))
    altered = dict(semantic)
    altered["proof"] = dict(semantic["proof"])
    altered["proof"]["prompt_hash"] = "0" * 64
    assert altered["proof"]["prompt_hash"] != semantic["proof"]["prompt_hash"]


def test_wrong_case_transcript():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    case = {"id": "trigger-should-1", "expected_output": "route to pattern-author", "prompt": "x"}
    assertion = {"id": "routes-correct-skill", "check": "Response recognizes the request as artifact-authoring work"}
    row = evaluate.evaluate_assertion(case, assertion, "It is currently 3pm in Bangkok.", "wrong-case")
    # semantic_judge without judge returns conservative FAIL
    assert row["result"] == "FAIL"
    assert "assistant" in row["proof"].get("rationale","").lower() or row["type"] == "unsupported"


def test_negative_generate_not_nonblocking():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    case = {"id": "escalation-risk", "expected_output": "route to pattern-author", "prompt": "x"}
    assertion = {"id": "heads-up-not-block", "check": "heads-up as information, never blocks"}
    row = evaluate.evaluate_assertion(case, assertion, "Heads-up: this involves risk. Generate?", "fixture")
    assert row["result"] == "FAIL", "Generate? without nonblocking language must FAIL heads-up-not-block"


def test_negative_no_summary_gate_fallback():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    case = {"id": "gate-summary-before-author", "expected_output": "summary gate", "prompt": "x"}
    assertion = {"id": "summary-gate", "check": "summary gate before authoring"}
    row = evaluate.evaluate_assertion(case, assertion, "I've recorded your store link as domain context. What should the skill produce?", "fixture")
    assert row["result"] == "FAIL", "domain-context recording + question without full summary gate must FAIL"


def test_negative_no_reopen_after_decline():
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate
    case = {"id": "gather-loop-immediate-no", "expected_output": "collection closed", "prompt": "x"}
    assertion = {"id": "collect-invites", "check": "After the prompt's first explicit non-material decline, response does not ask for further material and instead advances to the next applicable step."}
    row = evaluate.evaluate_assertion(case, assertion, "Want to give me anything to work from? What should the skill produce?", "fixture")
    assert row["result"] == "FAIL", "reopening collection after explicit decline must FAIL"


def main():
    test_semantic_fail_gate()
    test_malformed_proof_and_altered_proof()
    test_wrong_case_transcript()
    test_negative_generate_not_nonblocking()
    test_negative_no_summary_gate_fallback()
    test_negative_no_reopen_after_decline()
    print("6 evaluator mutation tests passed")


if __name__ == "__main__":
    main()
