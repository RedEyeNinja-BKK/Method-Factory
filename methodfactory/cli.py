"""`mf` CLI — thin adapter over the engine (ADR-0001).

Bounded command surface during the persistence reset:

    mf --version
    mf migrate-store --source <legacy-root> [--dest <sqlite-path>]
    mf export --store <root> [--output <path>] --format <fmt>

Only migration/export commands are restored in this phase (ADR-0012
amendment). Lifecycle commands (create/apply/status/summary/validate
mutation/review/trial/ship/triage) remain unavailable.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .domain.errors import MethodFactoryError

AVAILABILITY = (
    "Method Factory storage is under architecture reset (ADR-0012); "
    "lifecycle commands return in a later phase."
)


def _fail(err: MethodFactoryError) -> int:
    print(err.as_dict(), file=sys.stderr)
    return 1


def _cmd_migrate_store(args) -> int:
    from .migrations.migrate import migrate_store

    try:
        receipt = migrate_store(args.source, dest=args.dest)
    except MethodFactoryError as exc:
        return _fail(exc)
    import json

    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


def _cmd_export(args) -> int:
    from .migrations.export import export_events

    try:
        count = export_events(args.store, args.output, fmt=args.format)
    except MethodFactoryError as exc:
        return _fail(exc)
    if args.output is None:
        # events already written to stdout; report count on stderr
        print(f"exported {count} events", file=sys.stderr)
    else:
        print(f"exported {count} events to {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mf", description="Method Factory CLI")
    parser.add_argument(
        "--version", action="version", version=f"methodfactory {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    p_migrate = sub.add_parser("migrate-store", help="migrate a v0.1.2 store to SQLite")
    p_migrate.add_argument("--source", required=True, help="legacy store root")
    p_migrate.add_argument("--dest", default=None, help="destination SQLite path")
    p_migrate.set_defaults(func=_cmd_migrate_store)

    p_export = sub.add_parser("export", help="deterministic event export")
    p_export.add_argument("--store", required=True, help="SQLite store root")
    p_export.add_argument("--output", default=None, help="output path (default stdout)")
    p_export.add_argument(
        "--format",
        default="method-factory-events-v1",
        choices=["method-factory-events-v1", "legacy-v012-jsonl"],
    )
    p_export.set_defaults(func=_cmd_export)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
