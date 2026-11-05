"""Machine-readable command catalog. Side effects are declared here, not inferred."""

from __future__ import annotations

from typing import Any

from . import __version__
from .readonly import DEFAULT_GREP_MAX, DEFAULT_READ_LIMIT, MAX_GREP_MAX, MAX_READ_LIMIT

SIDE_EFFECT_READ_ONLY = "read-only"
SIDE_EFFECT_MUTATING = "mutating"

CLASSIFICATION: dict[str, Any] = {
    "field": "side_effects",
    "enum": [SIDE_EFFECT_READ_ONLY, SIDE_EFFECT_MUTATING],
    "boolean_field": "mutates",
    "annotation": "annotations.readOnlyHint",
    "missing": SIDE_EFFECT_MUTATING,
    "description": (
        "Read commands[name].side_effects. "
        "read-only: the command only observes paths inside the workspace root, "
        "does not create, modify, or delete anything, and does not spawn a process. "
        "mutating: the command may change state or execute arbitrary argv. "
        "mutates is true if and only if side_effects is mutating. "
        "annotations.readOnlyHint is true if and only if side_effects is read-only. "
        "annotations.destructiveHint is true if and only if side_effects is mutating. "
        "Missing side_effects metadata means mutating. "
        "Do not infer the class from the command name."
    ),
}


def effective_side_effects(spec: Any) -> str:
    """Classify one command. Missing or unknown ``side_effects`` is mutating."""
    if isinstance(spec, dict) and spec.get("side_effects") == SIDE_EFFECT_READ_ONLY:
        return SIDE_EFFECT_READ_ONLY
    return SIDE_EFFECT_MUTATING


def is_mutating(spec: Any) -> bool:
    """Fail closed. Hints and ``mutates: false`` do not override a missing field."""
    return effective_side_effects(spec) != SIDE_EFFECT_READ_ONLY


def _validate_catalog(commands: dict[str, Any]) -> None:
    for name, spec in commands.items():
        side = spec.get("side_effects") if isinstance(spec, dict) else None
        if side not in (SIDE_EFFECT_READ_ONLY, SIDE_EFFECT_MUTATING):
            raise RuntimeError(f"{name}: missing side_effects metadata means mutating; refusing to publish")
        if is_mutating(spec) != (side == SIDE_EFFECT_MUTATING):
            raise RuntimeError(f"{name}: side_effects disagree with fail-closed classification")


def _annotations(*, read_only: bool, open_world: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": not read_only,
        "idempotentHint": read_only,
        "openWorldHint": open_world,
    }


def _command(
    *,
    usage: str,
    description: str,
    side_effects: str,
    parameters: dict[str, Any],
    open_world: bool,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    read_only = side_effects == SIDE_EFFECT_READ_ONLY
    spec: dict[str, Any] = {
        "usage": usage,
        "description": description,
        "side_effects": side_effects,
        "mutates": not read_only,
        "annotations": _annotations(read_only=read_only, open_world=open_world),
        "parameters": parameters,
    }
    if aliases:
        spec["aliases"] = list(aliases)
    return spec


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def help_json() -> dict[str, Any]:
    read_only = SIDE_EFFECT_READ_ONLY
    mutating = SIDE_EFFECT_MUTATING
    data = {
        "name": "agents-terminal",
        "version": __version__,
        "description": (
            "Policy-bound jailed terminal. "
            "Read-only commands observe the workspace root and do not spawn a process."
        ),
        "classification": CLASSIFICATION,
        "commands": {
            "list": _command(
                usage="agents-terminal list [PATH] [--json]",
                description="List entries in a directory inside the workspace root.",
                side_effects=read_only,
                open_world=False,
                parameters=_object(
                    {
                        "path": {
                            "type": "string",
                            "description": "Directory relative to the workspace root, or an absolute path inside it. Default '.'.",
                        },
                        "json": {
                            "type": "boolean",
                            "default": False,
                            "description": "Emit a JSON object on stdout.",
                        },
                    },
                    [],
                ),
            ),
            "read": _command(
                usage="agents-terminal read PATH [--offset N] [--limit N] [--json]",
                description=(
                    "Read a UTF-8 text file inside the workspace root. "
                    "offset is the 1-based starting line. limit is the maximum number of lines."
                ),
                side_effects=read_only,
                open_world=False,
                parameters=_object(
                    {
                        "path": {
                            "type": "string",
                            "description": "File relative to the workspace root, or an absolute path inside it.",
                        },
                        "offset": {
                            "type": "integer",
                            "minimum": 1,
                            "default": 1,
                            "description": "1-based starting line.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_READ_LIMIT,
                            "default": DEFAULT_READ_LIMIT,
                            "description": "Maximum number of lines to return.",
                        },
                        "json": {
                            "type": "boolean",
                            "default": False,
                            "description": "Emit a JSON object on stdout.",
                        },
                    },
                    ["path"],
                ),
            ),
            "grep": _command(
                usage="agents-terminal grep PATTERN [PATH] [--glob GLOB] [--literal] [--ignore-case] [--max N] [--json]",
                description="Search UTF-8 text files inside the workspace root. Python regular expressions. Alias: search.",
                side_effects=read_only,
                open_world=False,
                aliases=["search"],
                parameters=_object(
                    {
                        "pattern": {
                            "type": "string",
                            "description": "Python regular expression, or a literal string when literal is true.",
                        },
                        "path": {
                            "type": "string",
                            "description": "File or directory inside the workspace root. Default '.'.",
                        },
                        "glob": {
                            "type": "string",
                            "description": "fnmatch filter against the path relative to the workspace root.",
                        },
                        "literal": {
                            "type": "boolean",
                            "default": False,
                            "description": "Treat pattern as a literal string.",
                        },
                        "ignore_case": {
                            "type": "boolean",
                            "default": False,
                            "description": "Case-insensitive search.",
                        },
                        "max": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_GREP_MAX,
                            "default": DEFAULT_GREP_MAX,
                            "description": "Maximum matches.",
                        },
                        "json": {
                            "type": "boolean",
                            "default": False,
                            "description": "Emit a JSON object on stdout.",
                        },
                    },
                    ["pattern"],
                ),
            ),
            "stat": _command(
                usage="agents-terminal stat PATH [--json]",
                description="Report type, size, mode, and mtime for a path inside the workspace root. Symlinks are not opened.",
                side_effects=read_only,
                open_world=False,
                parameters=_object(
                    {
                        "path": {
                            "type": "string",
                            "description": "Path relative to the workspace root, or an absolute path inside it.",
                        },
                        "json": {
                            "type": "boolean",
                            "default": False,
                            "description": "Emit a JSON object on stdout.",
                        },
                    },
                    ["path"],
                ),
            ),
            "run": _command(
                usage="agents-terminal run -- <argv...>",
                description="Run argv under terminal policy with no shell. May modify state.",
                side_effects=mutating,
                open_world=True,
                parameters=_object(
                    {
                        "argv": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Argv executed with no shell.",
                        }
                    },
                    ["argv"],
                ),
            ),
        },
        "flags": ["--help-json"],
    }
    _validate_catalog(data["commands"])
    return data
