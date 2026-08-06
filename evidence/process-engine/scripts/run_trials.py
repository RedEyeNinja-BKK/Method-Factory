#!/usr/bin/env python3
"""INTERNAL-ONLY Process Engine live trial runner.

Runs eval cases in fresh Turnstone workstreams, captures transcripts, and applies
heuristic triage grading (NOT an independent judge). By default, workstreams use
the configured persona and skill. --baseline instead creates generic-assistant
workstreams with no persona or skill. Refuses non-loopback endpoints unless
--allow-remote is explicitly supplied.

Usage:
    python3 scripts/run_trials.py [--run-id ID] [--limit N] [--model ALIAS]
        [--baseline] [--base URL] [--token-file PATH] [--project-id ID]
        [--persona NAME] [--skill NAME] [--node ID] [--allow-remote]
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE = "http://127.0.0.1:8090"
TOKEN_FILE = "/opt/turnstone/.schedule-api-token"
PROJECT_ID = "554fcd8fba5f4ecc8b36fb8f3502640a"
PERSONA = "process-engine"
SKILL = "process-engine-core"
NODE_PORTS = [8082, 8083, 8084, 8085, 8086]

STOPWORDS = {"a", "an", "and", "any", "are", "as", "at", "be", "before", "by", "contains", "does", "for", "from", "has", "have", "in", "is", "it", "no", "not", "of", "on", "or", "response", "states", "that", "the", "to", "with"}


def load_manifest(repo):
    cfg = {}
    with open(os.path.join(repo, "process-engine.toml")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip().strip('"')
    return cfg


def now_iso():
    return datetime.now().astimezone().isoformat()


def token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def api(path, method="GET", payload=None, base=BASE):
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", "Bearer " + token())
    data = None
    if payload is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(payload).encode()
    with urllib.request.urlopen(req, data=data, timeout=60) as response:
        return json.loads(response.read().decode())


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_ws(name, prompt, model, baseline=False):
    payload = {
        "name": name,
        "project_id": PROJECT_ID,
        "initial_message": prompt,
        "node_id": NODE_PORTS,
        "model": model,
        "model_alias": model,
    }
    # The API expects an identifier, not a port list. --node preserves the
    # previous pinned-node default while NODE_PORTS remains configurable metadata.
    payload["node_id"] = NODE_PORTS[0] if isinstance(NODE_PORTS, list) else NODE_PORTS
    if not baseline:
        payload["persona"] = PERSONA
        payload["skill"] = SKILL
    return api("/v1/api/cluster/workstreams/new", "POST", payload)


def wait_idle(ws_id, timeout=300):
    started = time.time()
    while time.time() - started < timeout:
        try:
            detail = api(f"/v1/api/cluster/ws/{ws_id}/detail")
            if detail.get("live", {}).get("state") in ("idle", "error", "attention"):
                return detail
        except Exception:
            pass
        time.sleep(8)
    return None


def node_url(ws_id):
    try:
        detail = api(f"/v1/api/cluster/ws/{ws_id}/detail")
        node_id = detail.get("persisted", {}).get("node_id")
        if node_id:
            for node in api("/v1/api/cluster/nodes").get("nodes", []):
                if node.get("node_id") == node_id:
                    return node.get("server_url")
    except Exception:
        pass
    return None


def history(ws_id):
    url = node_url(ws_id)
    if not url:
        return []
    try:
        return api(f"/v1/api/workstreams/{ws_id}/history", base=url).get("messages", [])
    except Exception:
        return []


def assistant_text(messages):
    return "\n".join(m["content"] for m in messages if m.get("role") == "assistant" and m.get("content"))


def grade_case(case, text):
    expected = case.get("expected_output", "").lower()
    low = text.lower()
    verdict = "FAIL"  # Conservative default: only explicit behavior recognition can pass.
    if len(text.strip()) >= 40:
        groups = {
            "collect": ["anything to work from", "want to give me", "any material", "give me anything", "share", "anything helps", "do you have any", "work from"],
            "clarify": ["what are you thinking", "what do you want", "one question", "a bit more", "clarif", "rough description", "first", "before i"],
            "gate": ["gate", "review", "trial", "draft", "generate?", "working from", "confirm"],
            "scope": ["out of scope", "decline", "not an artifact", "route", "not a fit", "can't generate", "can't build", "i can't", "outside", "not something i"],
            "objective": ["what does good look", "good look", "objective", "outcome", "vision"],
        }
        recognized = {name: any(phrase in low for phrase in phrases) for name, phrases in groups.items()}
        if "collect" in expected or "material" in expected or "before proceeding" in expected:
            verdict = "PASS" if recognized["collect"] or recognized["clarify"] else "FAIL"
        elif "clarif" in expected or "question" in expected or "ambiguous" in expected:
            verdict = "PASS" if recognized["clarify"] or recognized["collect"] else "FAIL"
        elif "decline" in expected or "route" in expected or "out of scope" in expected:
            verdict = "PASS" if recognized["scope"] else "FAIL"
        elif "gate" in expected or "summary gate" in expected or "before author" in expected:
            verdict = "PASS" if recognized["gate"] or recognized["collect"] else "FAIL"
        elif "objective" in expected or "good" in expected:
            verdict = "PASS" if recognized["objective"] else "FAIL"
        elif "trigger" in expected or "activation" in expected:
            verdict = "PASS" if recognized["collect"] or recognized["clarify"] or recognized["gate"] else "FAIL"
    return verdict


def assertion_passes(check, text):
    """Require every significant check token as a word-boundary match in substantive evidence."""
    if len(text.strip()) < 40:
        return False
    tokens = [token for token in re.findall(r"[a-z]+", check.lower()) if token not in STOPWORDS]
    return bool(tokens) and all(re.search(r"\b" + re.escape(token) + r"\b", text, re.IGNORECASE) for token in tokens)


def run_cases(cases, run_dir, model, baseline=False):
    destination = os.path.join(run_dir, "baseline" if baseline else "actual")
    os.makedirs(destination, exist_ok=True)
    results, assertions, judgments = [], [], []
    for index, case in enumerate(cases, 1):
        case_id = case["id"]
        print(f"[{index}/{len(cases)}] {'baseline ' if baseline else ''}{case_id} ...", flush=True)
        name = f"pe-{'baseline-' if baseline else 'trial-'}{case_id[:24]}-{int(time.time()) % 100000}"
        try:
            created = create_ws(name, case["prompt"], model, baseline=baseline)
            workstream_id = created.get("correlation_id")
            wait_idle(workstream_id, timeout=300)
            messages = history(workstream_id) if workstream_id else []
            text = assistant_text(messages)
            for _ in range(4):
                if len(text) > 30:
                    break
                time.sleep(10)
                messages = history(workstream_id) if workstream_id else []
                text = assistant_text(messages)
        except Exception as exc:
            print(f"  CREATE/RUN FAIL: {exc}")
            text, messages = "(no assistant text)", []
        target = os.path.join(destination, f"{case_id}.txt")
        with open(target, "w") as f:
            f.write(text or "(no assistant text)")
        verdict = grade_case(case, text)
        results.append({"case_id": case_id, "verdict": verdict, "evidence_link": f"{'baseline' if baseline else 'actual'}/{case_id}.txt"})
        if not baseline:
            for assertion in case.get("assertions", []):
                assertions.append({"case_id": case_id, "assertion_id": assertion.get("id", ""), "type": "deterministic", "result": "PASS" if assertion_passes(assertion.get("check", ""), text) else "FAIL", "evidence": f"actual/{case_id}.txt"})
            judgments.append({"case_id": case_id, "judge": "heuristic-keyword-grader (NOT an independent judge)", "verdict": verdict, "evidence": f"actual/{case_id}.txt", "note": "Heuristic behavior-recognition grading for triage only; it is not an independent judge."})
        print(f"  -> {verdict} ({len(messages)} msgs, {len(text)} chars)", flush=True)
    return results, assertions, judgments


def main():
    global BASE, TOKEN_FILE, PROJECT_ID, PERSONA, SKILL, NODE_PORTS
    parser = argparse.ArgumentParser(description="INTERNAL-ONLY: run local Turnstone Process Engine trial workstreams; remote bases require --allow-remote.")
    parser.add_argument("--run-id", default="run-20260731-001")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--repo", default=None)
    parser.add_argument("--baseline", action="store_true", help="also run generic-assistant baselines with no persona or skill")
    parser.add_argument("--base", default=BASE, help="INTERNAL-ONLY base URL (loopback unless --allow-remote)")
    parser.add_argument("--token-file", default=TOKEN_FILE)
    parser.add_argument("--project-id", default=PROJECT_ID)
    parser.add_argument("--persona", default=PERSONA)
    parser.add_argument("--skill", default=SKILL)
    parser.add_argument("--node", default="localclaw-vm_e8bb", help="Turnstone node identifier")
    parser.add_argument("--allow-remote", action="store_true", help="explicitly permit a non-loopback --base URL")
    args = parser.parse_args()
    hostname = urllib.parse.urlparse(args.base).hostname
    if not args.allow_remote and hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("INTERNAL-ONLY guard: --base must be loopback/localhost unless --allow-remote is passed")
    BASE, TOKEN_FILE, PROJECT_ID, PERSONA, SKILL, NODE_PORTS = args.base.rstrip("/"), args.token_file, args.project_id, args.persona, args.skill, args.node
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(here)
    cfg = load_manifest(repo)
    cases = json.load(open(os.path.join(repo, "evals", "evals.json")))["evals"]
    if args.limit:
        cases = cases[:args.limit]
    run_dir = os.path.join(repo, "evals", "runs", args.run_id)
    os.makedirs(run_dir, exist_ok=True)
    started = now_iso()
    results, assertions, judgments = run_cases(cases, run_dir, args.model)
    baseline_results = []
    if args.baseline:
        baseline_results, _, _ = run_cases(cases, run_dir, args.model, baseline=True)
        with open(os.path.join(run_dir, "baseline", "summary.json"), "w") as f:
            json.dump(baseline_results, f, indent=2)
    completed = now_iso()
    try:
        head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        head = "unknown"
    manifest = {"run_id": args.run_id, "commit": head, "engine_version": cfg.get("version"), "persona": PERSONA, "skill": SKILL, "runner": "turnstone-workstream-trial", "model": args.model, "provider": "openai", "case_count": len(results), "passed": sum(r["verdict"] == "PASS" for r in results), "failed": sum(r["verdict"] == "FAIL" for r in results), "start": started, "completion": completed, "baseline_status": "executed" if args.baseline else "not-executed", "notes": "Live workstream triage; heuristic grading is NOT an independent judge."}
    with open(os.path.join(run_dir, "manifest.json"), "w") as f: json.dump(manifest, f, indent=2)
    with open(os.path.join(run_dir, "cases.json"), "w") as f: json.dump([{"id": c["id"], "prompt": c["prompt"], "expected_output": c.get("expected_output", "")} for c in cases], f, indent=2)
    with open(os.path.join(run_dir, "assertions.jsonl"), "w") as f: f.write("".join(json.dumps(row) + "\n" for row in assertions))
    with open(os.path.join(run_dir, "judgments.jsonl"), "w") as f: f.write("".join(json.dumps(row) + "\n" for row in judgments))
    with open(os.path.join(run_dir, "summary.json"), "w") as f: json.dump({"cases": results}, f, indent=2)
    env = {"model": args.model, "provider": "openai", "runner": "turnstone-workstream-trial", "node": args.node, "repo_head": head, "evals_json_sha256": sha256(os.path.join(repo, "evals", "evals.json")), "generated_at": completed}
    with open(os.path.join(run_dir, "environment.json"), "w") as f: json.dump(env, f, indent=2)
    with open(os.path.join(run_dir, "README.md"), "w") as f: f.write("# Run Bundle\n\nLive workstream triage evidence. Heuristic results are not independent-judge verdicts.\n")
    print(f"\nDONE: {manifest['passed']}/{manifest['case_count']} PASS")

if __name__ == "__main__":
    main()
