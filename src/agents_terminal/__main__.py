"""CLI entrypoint for agents-terminal."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import __version__
from .driver import format_result
from .manifest import help_json
from .mutate import edit_file, format_edit, format_write, write_file
from .policy import Policy, refuse_workspace
from .readonly import (
    DEFAULT_GREP_MAX,
    DEFAULT_READ_LIMIT,
    ReadonlyError,
    format_grep,
    format_list,
    format_read,
    format_stat,
    grep_files,
    list_directory,
    read_file,
    stat_path,
)
from .router import run_command

_READ_ONLY_COMMANDS = frozenset({"list", "read", "grep", "search", "stat"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agents-terminal")
    parser.add_argument("--help-json", action="store_true", help="Emit machine-readable CLI spec as JSON.")
    sub = parser.add_subparsers(dest="command")

    list_p = sub.add_parser("list", help="List a directory inside the workspace root (read-only)")
    list_p.add_argument("path", nargs="?", default=".")
    list_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    read_p = sub.add_parser("read", help="Read a text file inside the workspace root (read-only)")
    read_p.add_argument("path")
    read_p.add_argument("--offset", type=int, default=1, help="1-based starting line.")
    read_p.add_argument("--limit", type=int, default=DEFAULT_READ_LIMIT, help="Maximum lines.")
    read_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    grep_p = sub.add_parser(
        "grep",
        aliases=["search"],
        help="Search text files inside the workspace root (read-only)",
    )
    grep_p.add_argument("pattern")
    grep_p.add_argument("path", nargs="?", default=".")
    grep_p.add_argument("--glob", default=None, help="fnmatch filter against the workspace-relative path.")
    grep_p.add_argument("--literal", action="store_true", help="Treat PATTERN as a literal string.")
    grep_p.add_argument("--ignore-case", action="store_true", help="Case-insensitive search.")
    grep_p.add_argument("--max", type=int, default=DEFAULT_GREP_MAX, dest="max_matches", help="Maximum matches.")
    grep_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    stat_p = sub.add_parser("stat", help="Stat a path inside the workspace root (read-only)")
    stat_p.add_argument("path")
    stat_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    write_p = sub.add_parser("write", help="Write a UTF-8 file inside the workspace root (mutating)")
    write_p.add_argument("path")
    write_p.add_argument("--content", default=None, help="Text to write.")
    write_p.add_argument("--stdin", action="store_true", help="Read the text from stdin.")
    write_p.add_argument("--create-only", action="store_true", help="Fail when the file already exists.")
    write_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    edit_p = sub.add_parser("edit", help="Replace an exact string in a file inside the workspace root (mutating)")
    edit_p.add_argument("path")
    edit_p.add_argument("--old", default=None, help="Exact text to replace.")
    edit_p.add_argument("--new", default=None, help="Replacement text.")
    edit_p.add_argument("--replace-all", action="store_true", help="Replace every occurrence.")
    edit_p.add_argument("--stdin-json", action="store_true", help='Read {"old", "new"} from stdin.')
    edit_p.add_argument("--json", action="store_true", help="Emit JSON on stdout.")

    run_p = sub.add_parser("run", help="Run a command under policy")
    run_p.add_argument("argv", nargs=argparse.REMAINDER, help="Command after --")
    return parser


def _root() -> Path:
    try:
        root = Policy.load().work_root()
    except (OSError, RuntimeError) as exc:
        raise ReadonlyError("invalid path") from exc
    denial = refuse_workspace(root, ())
    if denial:
        raise ReadonlyError(denial)
    return root


def _emit(payload: dict[str, Any], text: str, *, as_json: bool, truncated: bool = False) -> int:
    if as_json:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(text)
        if truncated:
            print("truncated", file=sys.stderr)
    return 0


def _confined(
    fn: Callable[[], Any],
    *,
    as_json: bool,
    text_of: Callable[[Any], str],
) -> int:
    """Run a workspace-confined operation and emit its result or its error."""
    try:
        payload = fn()
    except ReadonlyError as exc:
        print(exc.message, file=sys.stderr)
        return exc.code
    truncated = bool(payload.get("truncated")) if isinstance(payload, dict) else False
    return _emit(payload, text_of(payload), as_json=as_json, truncated=truncated)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = getattr(args, "command", None)
    if command not in _READ_ONLY_COMMANDS and not getattr(args, "help_json", False):
        try:
            from .updates import check_for_updates

            check_for_updates("agents-terminal", __version__)
        except Exception:
            pass
    if getattr(args, "help_json", False):
        print(json.dumps(help_json(), indent=2))
        return 0
    if command == "list":
        return _confined(
            lambda: list_directory(_root(), args.path),
            as_json=args.json,
            text_of=format_list,
        )
    if command == "read":
        return _confined(
            lambda: read_file(_root(), args.path, offset=args.offset, limit=args.limit),
            as_json=args.json,
            text_of=format_read,
        )
    if command in ("grep", "search"):
        return _confined(
            lambda: grep_files(
                _root(),
                args.pattern,
                args.path,
                glob=args.glob,
                literal=args.literal,
                ignore_case=args.ignore_case,
                max_matches=args.max_matches,
            ),
            as_json=args.json,
            text_of=format_grep,
        )
    if command == "stat":
        return _confined(
            lambda: stat_path(_root(), args.path),
            as_json=args.json,
            text_of=format_stat,
        )
    if command == "write":
        if (args.content is not None) == bool(args.stdin):
            print("write requires exactly one of --content or --stdin", file=sys.stderr)
            return 2
        content = sys.stdin.read() if args.stdin else args.content
        return _confined(
            lambda: write_file(_root(), args.path, content, create_only=args.create_only),
            as_json=args.json,
            text_of=format_write,
        )
    if command == "edit":
        if args.stdin_json:
            if args.old is not None or args.new is not None:
                print("edit takes either --old/--new or --stdin-json, not both", file=sys.stderr)
                return 2
            try:
                payload = json.loads(sys.stdin.read())
            except (ValueError, TypeError):
                print("invalid stdin json", file=sys.stderr)
                return 2
            if not isinstance(payload, dict) or not isinstance(payload.get("old"), str) or not isinstance(payload.get("new"), str):
                print("invalid stdin json", file=sys.stderr)
                return 2
            old = payload["old"]
            new = payload["new"]
        else:
            if args.old is None or args.new is None:
                print("edit requires --old and --new, or --stdin-json", file=sys.stderr)
                return 2
            old = args.old
            new = args.new
        return _confined(
            lambda: edit_file(_root(), args.path, old=old, new=new, replace_all=args.replace_all),
            as_json=args.json,
            text_of=format_edit,
        )
    if command == "run":
        raw = list(args.argv or [])
        if raw and raw[0] == "--":
            raw = raw[1:]
        if not raw:
            print("run requires argv after --", file=sys.stderr)
            return 2
        result = run_command(raw)
        if result.denied:
            print(result.denied, file=sys.stderr)
            return int(result.returncode)
        out = format_result(result)
        if out:
            print(out)
        return int(result.returncode)
    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
