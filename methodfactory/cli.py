"""`mf` CLI — thin adapter over the engine (ADR-0001).

Phase 2: version + availability notice only. The full command surface
(create/apply/status/summary/validate, migrate-store, export) returns after the
SQLite store and lifecycle are implemented (ADR-0012 Phase 2 stop gate).
"""

from __future__ import annotations

import argparse
import sys

from . import __version__

AVAILABILITY = (
    "Method Factory storage is under architecture reset (ADR-0012); "
    "commands return in a later phase."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mf", description="Method Factory CLI")
    parser.add_argument(
        "--version", action="version", version=f"methodfactory {__version__}"
    )
    parser.add_argument(
        "args", nargs="*",
        help="command + arguments (unavailable in this phase: persistence reset in progress)",
    )
    args = parser.parse_args(argv)
    if args.args:
        print(AVAILABILITY, file=sys.stderr)
        return 2
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
