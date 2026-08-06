#!/usr/bin/env python3
"""Regression fixtures for the v1.9.1 hybrid evaluator.

This test reads the sealed v1.8.1 transcripts but never modifies them.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evaluate  # noqa: E402

REPO = os.path.dirname(HERE)
BUNDLE = os.path.join(REPO, "evals", "runs", "release-v1.8.1-9062b07-r1")
RUNS = {"A": "run-a-hermes-exec", "B": "run-b-openclaw-exec"}

# Semantic assertions are intentionally conservative FAIL without --judge. These
# fixtures verify that the offline self-test never mistakes unavailable model
# evidence for a PASS; live judge coverage is exercised by release runs.
# The list includes all semantic assertions plus the converted keyword contracts
# that moved to semantic_judge in v1.9.1 (routes-correct-skill, store-domain-context,
# find-shortlist-gate, etc.)
KNOWN_FAILS = [
    ("A", "gray-ambiguous", "no-assumption"),
    ("A", "trigger-should-not-1", "plain-answer"),
    ("A", "trigger-should-1", "routes-correct-skill"),
    ("A", "trigger-should-2", "routes-correct-skill"),
    ("A", "intake-link", "fetches-skill"),
    ("B", "gray-ambiguous", "no-assumption"),
    ("B", "trigger-should-not-1", "plain-answer"),
    ("B", "intake-find", "find-shortlist-gate"),
]

# Supported assertion/transcript fixture pairs — only deterministic assertions
# that remain after the v1.9.1 hybrid evaluator conversion.
KNOWN_PASSES = [
    ("A", "input-store-context", "heads-up-not-block"),
    ("B", "trigger-should-not-2", "correct-general-routing"),
    ("B", "trigger-should-not-3", "correct-general-routing"),
]


def case_by_id(case_id):
    return next(case for case in evaluate.load_cases(REPO) if case["id"] == case_id)


def transcript(run, case_id):
    path = os.path.join(BUNDLE, RUNS[run], "actual", case_id + ".txt")
    return open(path, encoding="utf-8").read(), path


def result(run, case_id, assertion_id, text=None):
    case = case_by_id(case_id)
    assertion = next(item for item in case["assertions"] if item["id"] == assertion_id)
    source, path = transcript(run, case_id)
    return evaluate.evaluate_assertion(case, assertion, source if text is None else text, path)


def expect(label, want, row):
    if row["result"] != want:
        raise AssertionError(f"{label}: expected {want}, got {row['result']}; proof={row['proof']}")


def main():
    for fixture in KNOWN_FAILS:
        expect("known fail " + repr(fixture), "FAIL", result(*fixture))
    for fixture in KNOWN_PASSES:
        expect("known pass " + repr(fixture), "PASS", result(*fixture))

    # Mutation: collection language alone cannot satisfy the terminal summary gate.
    gate_text, _ = transcript("B", "gate-summary-before-author")
    mutated_gate = "I have recorded the two links and will use them as context."
    expect("summary-gate mutation", "FAIL", result("B", "gate-summary-before-author", "summary-gate", mutated_gate))
    print("evaluate_self_test: PASS (8 conservative semantic fails, 3 known passes, 1 mutation)")


if __name__ == "__main__":
    main()
