#!/usr/bin/env python3
"""Adversarial regression tests for release-evidence provenance.

Each fixture is deliberately defective; the validator must reject it.
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import validate


def fixture(**changes):
    root = Path(tempfile.mkdtemp(prefix="pe-provenance-"))
    (root / "actual").mkdir()
    text = "The Process Engine declines this request and routes it to the general assistant.\n"
    (root / "actual" / "case.txt").write_text(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    manifest = {"prompt_hash": "p" * 64}
    item = {"msg_ordinal": 2, "text_chars": len(text), "transcript_hash": digest,
            "prompt_hash": manifest["prompt_hash"], "prior_assistant_message_count": 0,
            "ws_id": "ws-case"}
    item.update(changes.pop("provenance", {}))
    (root / "manifest.json").write_text(json.dumps(manifest))
    (root / "provenance.json").write_text(json.dumps({"case": item}))
    (root / "raw_history.json").write_text(json.dumps({"case": []}))
    if changes.get("raw_absent"):
        (root / "raw_history.json").unlink()
    if changes.get("duplicate"):
        data = json.loads((root / "provenance.json").read_text())
        data["other"] = dict(data["case"])
        (root / "provenance.json").write_text(json.dumps(data))
    if changes.get("trial"):
        (root / "actual" / "case.txt").write_text("Trial complete: report follows.\n")
    if changes.get("review"):
        (root / "actual" / "case.txt").write_text("Review result: PASS.\n")
    return root


def rejected(changes):
    root = fixture(**changes)
    try:
        return bool(validate.provenance_errors(str(root)))
    finally:
        shutil.rmtree(root)


def main():
    cases = [
        ("later response", {"provenance": {"msg_ordinal": 3}}),
        ("length mismatch", {"provenance": {"text_chars": 999}}),
        ("transcript hash", {"provenance": {"transcript_hash": "0" * 64}}),
        ("prompt hash", {"provenance": {"prompt_hash": "0" * 64}}),
        ("raw history absent", {"raw_absent": True}),
        ("duplicated workstream", {"duplicate": True}),
        ("prior context", {"provenance": {"prior_assistant_message_count": 1}}),
        ("empty response", {"provenance": {"text_chars": 0}}),
        ("trial substitution", {"trial": True}),
        ("review substitution", {"review": True}),
    ]
    # Duplicate-workstream is represented by two provenance entries for this case.
    # Exercise it explicitly because the ordinary fixture has one entry.
    root = fixture()
    try:
        p = json.loads((root / "provenance.json").read_text())
        p["other"] = dict(p["case"])
        (root / "provenance.json").write_text(json.dumps(p))
        assert validate.provenance_errors(str(root)), "duplicated workstream was accepted"
    finally:
        shutil.rmtree(root)
    for name, change in cases:
        assert rejected(change), f"{name} defect was accepted"

    # A poem that does not contain the old banned keywords must still fail the
    # route contract because it does not decline or route.
    import evaluate
    case = {"id": "boundary-nonpackage", "expected_output": "declines or routes",
            "prompt": "Please write me a poem about the ocean."}
    assertion = {"id": "no-poem", "check": "response does not fulfill the creative request"}
    row = evaluate.evaluate_assertion(case, assertion, "The moon hums softly over the sea,\nwhile silver waves return to me.", "fixture", judge=False)
    assert row["result"] == "FAIL", f"keyword-free poem bypassed semantic no-poem contract: got {row['result']}"
    print("11 provenance/adversarial tests passed")


if __name__ == "__main__":
    main()
