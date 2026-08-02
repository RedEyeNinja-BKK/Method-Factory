"""Deterministic human-readable renders of manifest state.

The summary text rendered here is exactly what the operator reviews and
confirms; canonical_sha256 hashes its bytes (ADR-0006).
"""

from __future__ import annotations


def render_summary(manifest: dict) -> str:
    intent = (manifest.get("intent") or {}).get("raw") or ""
    objective = manifest.get("objective") or {}
    objective_stmt = objective.get("statement") or ""
    outcomes = objective.get("desired_outcomes") or []
    inputs = manifest.get("inputs") or []

    lines = [
        "=== PACKAGE SUMMARY ===",
        f"package_id : {manifest.get('package_id')}",
        f"intent     : {intent.strip()}",
        f"inputs     : {len(inputs)}",
    ]
    for item in inputs:
        lines.append(
            f"  - {item['input_id']} [{item['kind']}, {item['source']}, "
            f"{item['disposition']}] sha256:{item['content_sha256'][:12]}"
            + (f" — {item.get('exclusion_reason')}" if item.get("exclusion_reason") else "")
        )
    lines.append(f"objective  : {objective_stmt.strip()}")
    if outcomes:
        lines.append("outcomes   :")
        for o in outcomes:
            lines.append(f"  - {o.strip()}")
    return "\n".join(lines) + "\n"
