"""`mf` CLI — thin adapter over the engine (ADR-0001).

Commands:
    mf create <package_id> "<intent>"
    mf apply <package_id> <envelope.json|->        # '-' reads stdin
    mf status <package_id>
    mf validate <package_id>                       # read-only, collects errors
    mf summary <package_id>                        # render the canonical summary

Store root defaults to ./.mf; override with --store.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters.artifact_store import ArtifactStore
from .domain.errors import MethodFactoryError
from .engine import PipelineEngine
from .manifest.render import render_summary
from .manifest.schema import validate_manifest
from .manifest.store import ManifestStore


def _engine(store_root: Path) -> PipelineEngine:
    return PipelineEngine(ManifestStore(store_root), ArtifactStore(store_root / "artifacts"))


def _fail(err: MethodFactoryError) -> int:
    print(json.dumps(err.as_dict(), indent=2), file=sys.stderr)
    return 1


def cmd_create(engine: PipelineEngine, args) -> int:
    try:
        manifest = engine.create_package(args.package_id, args.intent)
    except MethodFactoryError as exc:
        return _fail(exc)
    print(json.dumps(engine.status(args.package_id), indent=2))
    return 0


def cmd_apply(engine: PipelineEngine, args) -> int:
    raw = sys.stdin.read() if args.envelope == "-" else Path(args.envelope).read_text(encoding="utf-8")
    try:
        result = engine.apply_json(raw)
    except MethodFactoryError as exc:
        return _fail(exc)
    print(
        json.dumps(
            {
                "replayed": result.replayed,
                "state": result.manifest["state"],
                "revision": result.manifest["revision"],
                "event_id": result.event["event_id"],
            },
            indent=2,
        )
    )
    return 0


def cmd_status(engine: PipelineEngine, args) -> int:
    try:
        status = engine.status(args.package_id)
    except MethodFactoryError as exc:
        return _fail(exc)
    print(json.dumps(status, indent=2))
    return 0


def cmd_summary(engine: PipelineEngine, args) -> int:
    try:
        manifest = engine.store.load(args.package_id)
    except MethodFactoryError as exc:
        return _fail(exc)
    if manifest.get("summary") is None:
        print("no summary prepared", file=sys.stderr)
        return 1
    print(manifest["summary"]["content"], end="")
    return 0


def cmd_validate(engine: PipelineEngine, args) -> int:
    try:
        manifest = engine.store.load(args.package_id)
    except MethodFactoryError as exc:
        return _fail(exc)
    errors = validate_manifest(manifest)
    if errors:
        for e in errors:
            print(f"  FAIL  {e}", file=sys.stderr)
        return 1
    print(f"manifest valid: {args.package_id} @ rev {manifest['revision']} state {manifest['state']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mf", description="Method Factory CLI")
    parser.add_argument("--store", default=".mf", help="store root (default: ./.mf)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create a package from an intent")
    p_create.add_argument("package_id")
    p_create.add_argument("intent")
    p_create.set_defaults(func=cmd_create)

    p_apply = sub.add_parser("apply", help="apply an action envelope (file or -)")
    p_apply.add_argument("package_id")
    p_apply.add_argument("envelope")
    p_apply.set_defaults(func=cmd_apply)

    p_status = sub.add_parser("status", help="show package status")
    p_status.add_argument("package_id")
    p_status.set_defaults(func=cmd_status)

    p_summary = sub.add_parser("summary", help="render the canonical summary")
    p_summary.add_argument("package_id")
    p_summary.set_defaults(func=cmd_summary)

    p_validate = sub.add_parser("validate", help="read-only manifest validation")
    p_validate.add_argument("package_id")
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    engine = _engine(Path(args.store))
    return args.func(engine, args)


if __name__ == "__main__":
    sys.exit(main())
