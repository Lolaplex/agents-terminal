"""CLI entrypoint for agents-terminal."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .driver import format_result
from .router import run_command
def _help_json() -> dict:
    return {
        "name": "agents-terminal",
        "version": __version__,
        "commands": {
            "run": {
                "usage": "agents-terminal run -- <argv...>",
                "description": "Run argv under terminal policy (no shell).",
            }
        },
        "flags": ["--help-json"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents-terminal")
    parser.add_argument("--help-json", action="store_true", help="Emit machine-readable CLI spec as JSON.")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="Run a command under policy")
    run_p.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "help_json", False):
        try:
            from .updates import check_for_updates
            check_for_updates("agents-terminal", __version__)
        except Exception:
            pass
    if getattr(args, "help_json", False):
        print(json.dumps(_help_json(), indent=2))
        return 0
    if args.command == "run":
        raw = list(args.argv or [])
        if raw and raw[0] == "--":
            raw = raw[1:]
        if not raw:
            print("run requires argv after --", file=sys.stderr)
            return 2
        result = run_command(raw)
        out = format_result(result)
        if out:
            print(out)
        return int(result.returncode)
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
