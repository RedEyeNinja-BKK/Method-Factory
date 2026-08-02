#!/usr/bin/env python3
"""Cluster-API workstream capture: create, poll, extract first text response.

Usage:
  python3 scripts/capture_workstream.py --case trigger-should-4 --prompt "trial the skill..."
  python3 scripts/capture_workstream.py --case-file evals/evals.json --out-dir /tmp/captures/
  python3 scripts/capture_workstream.py --case-file evals/evals.json --run-all \
    --project-id d135622... --persona process-engine --skill process-engine-core

Creates an isolated workstream via the Turnstone Console cluster API, polls
until a text-bearing assistant response appears, then exports:
  - actual/<case-id>.txt       (first assistant text)
  - raw-history/<case-id>.json  (full message array)
  - provenance/<case-id>.json   (canonical provenance record)

Environment:
  TURNSTONE_API_BASE   console base URL (default http://127.0.0.1:8090)
  TURNSTONE_API_TOKEN  bearer token (falls back to /opt/turnstone/.schedule-api-token)
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _env_or_default(key, default):
    val = os.environ.get(key, "").strip()
    return val if val else default


API_BASE = _env_or_default("TURNSTONE_API_BASE", "http://127.0.0.1:8090").rstrip("/")
TOKEN = _env_or_default("TURNSTONE_API_TOKEN", "")
if not TOKEN:
    try:
        TOKEN = open("/opt/turnstone/.schedule-api-token", encoding="utf-8").read().strip()
    except OSError:
        pass


def _req(method, path, body=None):
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_workstream(name, project_id, persona, skill, initial_message):
    """POST /v1/api/cluster/workstreams/new — returns correlation_id as workstream id."""
    payload = {
        "name": name,
        "project_id": project_id,
        "persona": persona,
        "skill": skill,
        "initial_message": initial_message,
    }
    result = _req("POST", "/v1/api/cluster/workstreams/new", payload)
    return result.get("correlation_id") or result.get("workstream_id")


def poll_workstream(ws_id, timeout_seconds=120, poll_interval=2.0):
    """Poll GET /v1/api/cluster/ws/{id}/detail until text-bearing assistant response.

    Returns (messages, first_text_msg_idx, first_text_content).
    Returns (None, None, None) on timeout or error.
    """
    deadline = time.time() + timeout_seconds
    tool_only_responses_seen = 0

    while time.time() < deadline:
        try:
            detail = _req("GET", f"/v1/api/cluster/ws/{ws_id}/detail")
            messages = detail.get("messages", [])
            if not messages:
                time.sleep(poll_interval)
                continue

            for idx, msg in enumerate(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    tool_calls = msg.get("tool_calls", [])
                    # Skip pure tool-call messages (empty content, has tool calls)
                    if not content and tool_calls:
                        tool_only_responses_seen += 1
                        continue
                    if content:
                        return messages, idx, content

            # No text response yet — wait
            if tool_only_responses_seen > 6:
                # Stuck in tool loop — unlikely to resolve
                return messages, None, None

        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            print(f"  poll error: {exc}", file=sys.stderr)

        time.sleep(poll_interval)

    return None, None, None


def capture_case(case_id, prompt, project_id, persona, skill, out_dir, timeout=120):
    """Capture a single case and write transcript + provenance + raw history."""
    os.makedirs(os.path.join(out_dir, "actual"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "raw-history"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "provenance"), exist_ok=True)

    ws_name = f"pe-capture-{case_id}"
    submitted_at = datetime.now(timezone.utc).isoformat()

    try:
        ws_id = create_workstream(ws_name, project_id, persona, skill, prompt)
    except Exception as exc:
        print(f"  {case_id}: create failed — {exc}", file=sys.stderr)
        return {"case_id": case_id, "capture_status": "FAIL", "error": str(exc)}

    if not ws_id:
        return {"case_id": case_id, "capture_status": "FAIL", "error": "no workstream_id returned"}

    messages, assistant_idx, text = poll_workstream(ws_id, timeout_seconds=timeout)
    received_at = datetime.now(timezone.utc).isoformat()

    if not text and not messages:
        return {"case_id": case_id, "capture_status": "TIMEOUT", "ws_id": ws_id}

    # Save transcript
    transcript_path = os.path.join(out_dir, "actual", f"{case_id}.txt")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(text)

    # Save raw history
    raw_path = os.path.join(out_dir, "raw-history", f"{case_id}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, default=str)

    # Build provenance record
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()
    text_sha = hashlib.sha256(text.encode()).hexdigest()
    raw_sha = hashlib.sha256(json.dumps(messages, default=str).encode()).hexdigest()

    # Count prior messages
    prior_user = sum(1 for m in messages[:assistant_idx] if m.get("role") == "user")
    prior_assistant = sum(1 for m in messages[:assistant_idx] if m.get("role") == "assistant")
    tool_calls_before = sum(len(m.get("tool_calls", [])) for m in messages[:assistant_idx] if m.get("role") == "assistant")

    # Extract the assistant message ID if present
    assistant_msg = messages[assistant_idx] if assistant_idx is not None and assistant_idx < len(messages) else {}
    assistant_msg_id = assistant_msg.get("id") or assistant_msg.get("message_id", "")

    provenance = {
        "case_id": case_id,
        "run_id": f"capture-{case_id}-{int(time.time())}",
        "workstream_id": ws_id,
        "prompt_path": f"cases/{case_id}.json",
        "prompt_sha256": prompt_sha,
        "prompt_submitted_at": submitted_at,
        "assistant_message_id": assistant_msg_id,
        "assistant_message_ordinal": assistant_idx + 1 if assistant_idx is not None else None,
        "assistant_text_path": f"actual/{case_id}.txt",
        "assistant_text_sha256": text_sha,
        "assistant_text_chars": len(text) if text else 0,
        "assistant_received_at": received_at,
        "prior_user_message_count": prior_user,
        "prior_assistant_message_count": prior_assistant,
        "tool_calls_before_response": tool_calls_before,
        "raw_history_path": f"raw-history/{case_id}.json",
        "raw_history_sha256": raw_sha,
        "capture_status": "PASS",
    }

    prov_path = os.path.join(out_dir, "provenance", f"{case_id}.json")
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)

    return provenance


def load_case_file(path):
    """Load eval cases from evals.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)["evals"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Single case ID")
    parser.add_argument("--prompt", help="Prompt text (required with --case)")
    parser.add_argument("--case-file", help="Path to evals.json")
    parser.add_argument("--run-all", action="store_true", help="Capture all cases from evals.json")
    parser.add_argument("--cases", help="Comma-separated case IDs to capture")
    parser.add_argument("--project-id", default="d135622ef17349828edb9fc3cbb62feb")
    parser.add_argument("--persona", default="process-engine")
    parser.add_argument("--skill", default="process-engine-core")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--timeout", type=int, default=120, help="Per-case timeout seconds")
    args = parser.parse_args()

    if not TOKEN:
        print("ERROR: TURNSTONE_API_TOKEN not set and /opt/turnstone/.schedule-api-token not found", file=sys.stderr)
        sys.exit(1)

    results = []

    if args.case and args.prompt:
        result = capture_case(args.case, args.prompt, args.project_id, args.persona,
                             args.skill, args.out_dir, args.timeout)
        results.append(result)

    elif args.run_all and args.case_file:
        cases = load_case_file(args.case_file)
        for case in cases:
            print(f"{case['id']} ...", end=" ", flush=True)
            result = capture_case(case["id"], case["prompt"], args.project_id, args.persona,
                                  args.skill, args.out_dir, args.timeout)
            status = result.get("capture_status", "?")
            chars = result.get("assistant_text_chars", 0)
            ordinal = result.get("assistant_message_ordinal", "?")
            print(f"{status}  {chars} chars  ordinal={ordinal}")
            results.append(result)

    elif args.cases and args.case_file:
        target_ids = set(args.cases.split(","))
        cases = [c for c in load_case_file(args.case_file) if c["id"] in target_ids]
        for case in cases:
            print(f"{case['id']} ...", end=" ", flush=True)
            result = capture_case(case["id"], case["prompt"], args.project_id, args.persona,
                                  args.skill, args.out_dir, args.timeout)
            status = result.get("capture_status", "?")
            chars = result.get("assistant_text_chars", 0)
            ordinal = result.get("assistant_message_ordinal", "?")
            print(f"{status}  {chars} chars  ordinal={ordinal}")
            results.append(result)

    else:
        parser.error("Use --case + --prompt for single capture, or --case-file + (--run-all | --cases) for batch")

    # Summary
    passed = sum(1 for r in results if r.get("capture_status") == "PASS")
    failed = sum(1 for r in results if r.get("capture_status") != "PASS")
    print(f"\n{passed} PASS / {failed} FAIL of {len(results)}")

    if args.run_all or args.cases:
        # Write aggregate provenance.json
        prov_all = {r["case_id"]: r for r in results if r.get("case_id")}
        prov_path = os.path.join(args.out_dir, "provenance.json")
        with open(prov_path, "w", encoding="utf-8") as f:
            json.dump(prov_all, f, indent=2)
        print(f"Aggregate provenance written to {prov_path}")


if __name__ == "__main__":
    main()
