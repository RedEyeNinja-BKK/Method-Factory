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

from . import __version__
from .adapters.artifact_store import ArtifactStore
from .domain.errors import (
    FileIoError,
    InvalidEnvelopeError,
    MethodFactoryError,
    NoSummaryError,
)
from .engine import PipelineEngine
from .manifest.schema import validate_manifest
from .manifest.store import ManifestStore
from .protocol.envelope import MAX_ENVELOPE_BYTES, parse_envelope


def _read_envelope_input(envelope_arg: str, package_id: str) -> str:
    """Read the envelope from a file or stdin, bounded by MAX_ENVELOPE_BYTES
    so an unbounded transport cannot exhaust memory before validation
    (sec-5/perf-2)."""
    if envelope_arg == "-":
        raw = sys.stdin.read(MAX_ENVELOPE_BYTES + 1)
    else:
        path = Path(envelope_arg)
        try:
            if path.stat().st_size > MAX_ENVELOPE_BYTES:
                raise FileIoError(
                    f"envelope file exceeds {MAX_ENVELOPE_BYTES} bytes", package_id=package_id
                )
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise FileIoError(f"cannot read envelope: {exc}", package_id=package_id) from exc
    if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise FileIoError(f"envelope exceeds {MAX_ENVELOPE_BYTES} bytes", package_id=package_id)
    return raw


def _engine(store_root: Path) -> PipelineEngine:
    artifacts = ArtifactStore(store_root / "artifacts")
    store = ManifestStore(store_root, artifact_store=artifacts)
    return PipelineEngine(store, artifacts)


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
    try:
        raw = _read_envelope_input(args.envelope, args.package_id)
        env = parse_envelope(raw)
        if env.package_id != args.package_id:
            raise InvalidEnvelopeError(
                f"envelope package_id {env.package_id!r} does not match CLI package_id {args.package_id!r}"
            )
        result = engine.apply(env)
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
        return _fail(NoSummaryError("no summary prepared", package_id=args.package_id))
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
    parser.add_argument("--version", action="version", version=f"methodfactory {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_store(subp) -> None:
        # SUPPRESS: when the subcommand does not set --store, keep the
        # top-level --store value (so both 'mf --store X sub' and
        # 'mf sub --store X' work).
        subp.add_argument("--store", default=argparse.SUPPRESS, help="store root (default: ./.mf)")

    p_create = sub.add_parser("create", help="create a package from an intent")
    _add_store(p_create)
    p_create.add_argument("package_id")
    p_create.add_argument("intent")
    p_create.set_defaults(func=cmd_create)

    p_apply = sub.add_parser("apply", help="apply an action envelope (file or -)")
    _add_store(p_apply)
    p_apply.add_argument("package_id")
    p_apply.add_argument("envelope")
    p_apply.set_defaults(func=cmd_apply)

    p_status = sub.add_parser("status", help="show package status")
    _add_store(p_status)
    p_status.add_argument("package_id")
    p_status.set_defaults(func=cmd_status)

    p_summary = sub.add_parser("summary", help="render the canonical summary")
    _add_store(p_summary)
    p_summary.add_argument("package_id")
    p_summary.set_defaults(func=cmd_summary)

    p_validate = sub.add_parser("validate", help="read-only manifest validation")
    _add_store(p_validate)
    p_validate.add_argument("package_id")
    p_validate.set_defaults(func=cmd_validate)

    args = parser.parse_args(argv)
    engine = _engine(Path(args.store))  # top-level default .mf; subparser --store overrides
    return args.func(engine, args)


if __name__ == "__main__":
    sys.exit(main())
