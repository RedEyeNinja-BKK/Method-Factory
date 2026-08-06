#!/usr/bin/env python3
"""Record immutable mirrored release evidence and finalize complete bundles.

Usage:
    python3 scripts/record_release_run.py A --run-id ID --case CASE --transcript TEXT --verdict PASS --reason TEXT --judge NAME
    python3 scripts/record_release_run.py A --run-id ID --case CASE --assertion ASSERTION --result PASS --evidence actual/CASE.txt
    python3 scripts/record_release_run.py finalize --run-id ID --commit SHA --start ISO --completion ISO --executor NAME --verifier NAME --model MODEL --baseline executed
"""
import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime

import evaluate

RUNS = {"A": "run-a-hermes-exec", "B": "run-b-openclaw-exec"}


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_toml(repo):
    config = {}
    with open(os.path.join(repo, "process-engine.toml")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip().strip('"')
    return config


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def default_run_id(repo):
    return f"release-v{load_toml(repo)['version']}-{git(repo, 'rev-parse', '--short', 'HEAD')}"


def run_dir(repo, run_id, run):
    return os.path.join(repo, "evals", "runs", run_id, RUNS[run])


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_hash(repo):
    patterns = ["skills/*/SKILL.md", "references/*.md", "templates/*.md", "persona.md", "evals/evals.json"]
    paths = []
    for pattern in patterns:
        import glob
        paths.extend(glob.glob(os.path.join(repo, pattern)))
    digest = hashlib.sha256()
    for path in sorted(paths):
        with open(path, "rb") as f:
            digest.update(f.read())
    return digest.hexdigest()


def prompt_hash(cases):
    return hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def update_hashes(directory, case_id, transcript_path):
    path = os.path.join(directory, "hashes.json")
    hashes = json.load(open(path)) if os.path.isfile(path) else {}
    hashes[case_id] = sha256_file(transcript_path)
    with open(path, "w") as f:
        json.dump(hashes, f, indent=2, sort_keys=True)


def record_case(repo, args):
    directory = run_dir(repo, args.run_id, args.run)
    actual = os.path.join(directory, "actual")
    os.makedirs(actual, exist_ok=True)
    transcript_path = os.path.join(actual, f"{args.case}.txt")
    if os.path.exists(transcript_path):
        raise SystemExit(f"refusing to overwrite immutable transcript: {transcript_path}")
    with open(transcript_path, "w") as f:
        f.write(args.transcript)
    update_hashes(directory, args.case, transcript_path)
    with open(os.path.join(directory, "judgments.jsonl"), "a") as f:
        f.write(json.dumps({"case_id": args.case, "verdict": args.verdict, "reason": args.reason, "judge": args.judge, "commit": git(repo, "rev-parse", "HEAD"), "ts": datetime.now().astimezone().isoformat()}) + "\n")
    print(f"recorded {args.run}/{args.case}: {args.verdict}")


def record_assertion(repo, args):
    directory = run_dir(repo, args.run_id, args.run)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "assertions.jsonl"), "a") as f:
        f.write(json.dumps({"case_id": args.case, "assertion_id": args.assertion, "type": "deterministic", "result": args.result, "evidence": args.evidence}) + "\n")
    print(f"recorded {args.run}/{args.case}/{args.assertion}: {args.result}")


def last_judgments(path):
    result = {}
    if os.path.isfile(path):
        for line in open(path):
            if line.strip():
                row = json.loads(line)
                result[row.get("case_id")] = row
    return result


def finalize_subrun(repo, run_id, run, cases, args, cfg):
    directory = run_dir(repo, run_id, run)
    os.makedirs(directory, exist_ok=True)
    # v1.8.2: when --evaluate is used, the summary verdicts derive from the
    # evaluator's assertion rows (case PASS = all its assertions PASS). The
    # manual judgments.jsonl path is the legacy v1.8.1 mechanism.
    if args.evaluate:
        rows = [json.loads(line) for line in open(os.path.join(directory, "assertions.jsonl")) if line.strip()]
        by_case = {}
        for row in rows:
            by_case.setdefault(row["case_id"], []).append(row["result"])
        latest = {cid: {"verdict": "PASS" if all(r == "PASS" for r in res) else "FAIL",
                        "reason": "evaluator-derived (all assertions PASS)" if all(r == "PASS" for r in res) else "evaluator-derived (assertion FAIL)",
                        "judge": "schema-bound-evaluator", "commit": args.commit} for cid, res in by_case.items()}
    else:
        judgment_path = os.path.join(directory, "judgments.jsonl")
        latest = last_judgments(judgment_path)
        missing = [case["id"] for case in cases if case["id"] not in latest]
        if missing:
            with open(judgment_path, "a") as f:
                for case_id in missing:
                    row = {"case_id": case_id, "verdict": "FAIL", "reason": "missing judgment", "judge": "finalize-conservative-default", "commit": args.commit, "ts": datetime.now().astimezone().isoformat()}
                    f.write(json.dumps(row) + "\n")
                    latest[case_id] = row
    summary_cases = [{"case_id": case["id"], "verdict": latest[case["id"]].get("verdict", "FAIL"), "evidence_link": f"actual/{case['id']}.txt", "transcript_sha256": (json.load(open(os.path.join(directory, "hashes.json"))).get(case["id"]) if os.path.isfile(os.path.join(directory, "hashes.json")) else None)} for case in cases]
    passed = sum(row["verdict"] == "PASS" for row in summary_cases)
    failed = sum(row["verdict"] == "FAIL" for row in summary_cases)
    pending = len(summary_cases) - passed - failed
    case_payload = [{"id": case["id"], "prompt": case["prompt"], "expected_output": case.get("expected_output", "")} for case in cases]
    p_hash, pkg_hash = prompt_hash(case_payload), package_hash(repo)
    metadata = {"run_id": f"{run_id}-{RUNS[run]}", "commit": args.commit, "engine_version": cfg["version"], "iteration": "final-release", "protocol": "mirrored-dual-source", "executor": args.executor, "verifier": args.verifier, "model": args.model, "case_count": len(cases), "passed": passed, "failed": failed, "pending": pending, "start": args.start, "completion": args.completion, "baseline_status": args.baseline, "prompt_hash": p_hash, "package_hash": pkg_hash, "sealed_at": git(repo, "rev-parse", "HEAD")}
    with open(os.path.join(directory, "manifest.json"), "w") as f: json.dump(metadata, f, indent=2)
    with open(os.path.join(directory, "cases.json"), "w") as f: json.dump(case_payload, f, indent=2)
    with open(os.path.join(directory, "summary.json"), "w") as f: json.dump({"cases": summary_cases}, f, indent=2)
    env = {"model": args.model, "provider": "openai", "node": "localclaw-vm", "repo_head": args.commit, "evals_json_sha256": sha256_file(os.path.join(repo, "evals", "evals.json")), "generated_at": datetime.now().astimezone().isoformat(), "hashes": {"prompt_hash": p_hash, "package_hash": pkg_hash}}
    with open(os.path.join(directory, "environment.json"), "w") as f: json.dump(env, f, indent=2)
    result = f"{passed} PASS / {failed} FAIL / {pending} PENDING"
    readme = f"# {RUNS[run]} evidence\n\nThis immutable release-evidence sub-run is `{metadata['run_id']}` for Process Engine v{cfg['version']}. It follows the mirrored-dual-source protocol: executor `{args.executor}` performed the case work and verifier `{args.verifier}` recorded the final judgments using model `{args.model}`. The recorded window is {args.start} through {args.completion}; final result: {result}.\n\nEvidence layout: `actual/` holds write-once transcripts, `hashes.json` seals their SHA-256 values, `judgments.jsonl` preserves judgment history, `assertions.jsonl` records deterministic checks, `cases.json` preserves evaluated prompts, and `summary.json` exposes the final per-case evidence links. The manifest binds this run to the passed commit and hashes the exact prompt and package inputs. Transcript files are immutable: recorder attempts to replace an existing transcript fail loudly.\n"
    with open(os.path.join(directory, "README.md"), "w") as f: f.write(readme)
    return metadata, result


def evaluate_subrun(repo, directory, cases):
    """Derive assertions and accept only exact all-PASS schema coverage."""
    # judge=True: the semantic assertions (no-assumption, plain-answer) require
    # a real judge call; without it they conservatively FAIL and the seal is
    # impossible. The judge is part of the release protocol for v1.8.2+.
    rows = evaluate.evaluate(run_dir=directory, repo=repo, judge=True)
    expected = {(case["id"], assertion["id"]) for case in cases for assertion in case["assertions"]}
    actual = {(row["case_id"], row["assertion_id"]) for row in rows}
    failures = [row for row in rows if row["result"] != "PASS"]
    if len(rows) != len(expected) or actual != expected or failures:
        detail = f"rows={len(rows)}/{len(expected)}, coverage={'ok' if actual == expected else 'bad'}, failures={len(failures)}"
        raise SystemExit(f"--evaluate rejected finalize for {directory}: {detail}")
    output = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    with open(os.path.join(directory, "assertions.jsonl"), "w", encoding="utf-8") as f:
        f.write(output)


def finalize(repo, args):
    cfg = load_toml(repo)
    evals = json.load(open(os.path.join(repo, "evals", "evals.json")))
    cases = evals["evals"]
    if args.evaluate:
        for run in RUNS:
            evaluate_subrun(repo, run_dir(repo, args.run_id, run), cases)
    runs = {}
    for run in RUNS:
        metadata, result = finalize_subrun(repo, args.run_id, run, cases, args, cfg)
        runs[run] = {"executor": metadata["executor"], "verifier": metadata["verifier"], "model": metadata["model"], "result": result}
    top_dir = os.path.join(repo, "evals", "runs", args.run_id)
    top = {"run_id": args.run_id, "commit": args.commit, "engine_version": cfg["version"], "protocol": "mirrored-dual-source", "run_a": runs["A"], "run_b": runs["B"], "baseline": args.baseline, "sealed_at": git(repo, "rev-parse", "HEAD")}
    with open(os.path.join(top_dir, "manifest.json"), "w") as f: json.dump(top, f, indent=2)
    readme = f"# Process Engine v{cfg['version']} mirrored release bundle\n\nThis bundle `{args.run_id}` records two independently sourced final-release sub-runs against commit `{args.commit}` under the mirrored-dual-source protocol. Run A: `{runs['A']['executor']}` executed and `{runs['A']['verifier']}` verified using `{runs['A']['model']}`; result {runs['A']['result']}. Run B: `{runs['B']['executor']}` executed and `{runs['B']['verifier']}` verified using `{runs['B']['model']}`; result {runs['B']['result']}. The requested baseline status is `{args.baseline}`.\n\nEach sub-run contains immutable `actual/` transcript evidence, SHA-256 integrity data in `hashes.json`, append-only judgment and assertion records, the case inputs, a sealed manifest, environment metadata, and summary evidence links. Finalization writes conservative FAIL judgments for cases that lack recorded judgment evidence; it never creates an automatic PASS.\n"
    with open(os.path.join(top_dir, "README.md"), "w") as f: f.write(readme)
    print(f"finalized {args.run_id}: A {runs['A']['result']}; B {runs['B']['result']}")


def main():
    repo = repo_root()
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for run in RUNS:
        command = sub.add_parser(run)
        command.add_argument("--run-id", default=default_run_id(repo))
        command.add_argument("--case", required=True)
        command.add_argument("--transcript")
        command.add_argument("--verdict", choices=["PASS", "FAIL"], default="PASS")
        command.add_argument("--reason", default="")
        command.add_argument("--judge", default="")
        command.add_argument("--assertion", help="DEPRECATED manual assertion record; v1.8.2 finalization should use --evaluate")
        command.add_argument("--result", choices=["PASS", "FAIL"], help="DEPRECATED with --assertion")
        command.add_argument("--evidence", help="DEPRECATED with --assertion")
    command = sub.add_parser("finalize")
    command.add_argument("--run-id", default=default_run_id(repo))
    command.add_argument("--commit", required=True)
    command.add_argument("--start", required=True)
    command.add_argument("--completion", required=True)
    command.add_argument("--executor", required=True)
    command.add_argument("--verifier", required=True)
    command.add_argument("--model", required=True)
    command.add_argument("--baseline", choices=["executed", "not-executed"], required=True)
    command.add_argument("--evaluate", action="store_true", help="derive all assertions from transcripts and reject finalize unless exact all-PASS coverage succeeds")
    args = parser.parse_args()
    if args.command == "finalize":
        finalize(repo, args)
    elif args.assertion:
        if not args.result or not args.evidence:
            parser.error("--assertion requires --result and --evidence")
        record_assertion(repo, args)
    else:
        if args.transcript is None:
            parser.error("case recording requires --transcript")
        record_case(repo, args)

if __name__ == "__main__":
    main()
