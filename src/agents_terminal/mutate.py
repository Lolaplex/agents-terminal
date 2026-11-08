"""Workspace-bound writes and surgical edits.

These functions reuse the confinement helpers from :mod:`agents_terminal.readonly`
and never spawn a process. Every write is atomic: a temp file in the target
directory is replaced into place with ``os.replace``.
"""

from __future__ import annotations

import difflib
import os
import stat
import tempfile
from pathlib import Path
from typing import TypedDict

from .readonly import (
    _BINARY,
    _ESCAPE,
    _INVALID_PATH,
    _NOT_FILE,
    _NOT_FOUND,
    ReadonlyError,
    _is_reparse,
    _map_open,
    _normalize_user_path,
    _open_regular,
    _prepare_root,
    _rel,
    resolve_path,
)

_WRITE_TMP_PREFIX = ".agents-terminal-"
_WRITE_TMP_SUFFIX = ".tmp"


class WriteResult(TypedDict):
    path: str
    created: bool
    lines: int
    bytes: int


class EditResult(TypedDict):
    path: str
    replacements: int
    first_line: int
    last_line: int
    diff: str


def write_file(
    root: Path,
    path: str,
    content: str,
    *,
    create_only: bool = False,
) -> WriteResult:
    """Write UTF-8 text to ``path`` inside ``root``.

    Missing parent directories are created inside the root. An existing file
    keeps its line endings. A symlink, directory, or binary target is refused.
    """
    if not isinstance(content, str):
        raise ReadonlyError("content must be text", code=2)
    root_real, target = _write_target(root, path)
    existing = _existing_bytes(root_real, target, create_only=create_only)
    created = existing is None
    if created:
        data = content.replace("\r\n", "\n").encode("utf-8")
    else:
        eol = "\r\n" if b"\r\n" in existing else "\n"
        data = content.replace("\r\n", "\n").replace("\n", eol).encode("utf-8")
    _ensure_parent(root_real, target.parent)
    _atomic_write(target.parent, target, data)
    return {
        "path": _rel(root_real, target),
        "created": created,
        "lines": _line_count(data),
        "bytes": len(data),
    }


def edit_file(
    root: Path,
    path: str,
    *,
    old: str,
    new: str,
    replace_all: bool = False,
) -> EditResult:
    """Replace an exact string in a UTF-8 file inside ``root``.

    An exact match on the file's own bytes wins, so a file with mixed line
    endings keeps every byte it had and the diff stays local. Only when that
    finds nothing does the match fall back to line-ending-tolerant comparison,
    which rewrites the file with its dominant line ending.
    """
    if not isinstance(old, str) or not isinstance(new, str):
        raise ReadonlyError("old and new must be text", code=2)
    if old == "":
        raise ReadonlyError("old text must not be empty", code=2)
    root_real = _prepare_root(root)
    target = resolve_path(root_real, path, follow_final=True)
    if not target.exists():
        raise ReadonlyError(_NOT_FOUND)
    raw = _read_all(root_real, target)
    if b"\x00" in raw:
        raise ReadonlyError(_BINARY)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadonlyError(_BINARY) from exc

    count = text.count(old)
    if count:
        _require_single(count, replace_all)
        first_line, last_line = _line_span(text, old, replace_all=replace_all)
        updated = text.replace(old, new, -1 if replace_all else 1)
    else:
        eol = "\r\n" if "\r\n" in text else "\n"
        normalized = text.replace("\r\n", "\n")
        old_norm = old.replace("\r\n", "\n")
        new_norm = new.replace("\r\n", "\n")
        count = normalized.count(old_norm)
        if count == 0:
            raise ReadonlyError("old text not found")
        _require_single(count, replace_all)
        first_line, last_line = _line_span(normalized, old_norm, replace_all=replace_all)
        updated = normalized.replace(old_norm, new_norm, -1 if replace_all else 1).replace("\n", eol)

    diff = "".join(
        difflib.unified_diff(
            text.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=_rel(root_real, target),
            tofile=_rel(root_real, target),
            n=3,
        )
    )
    _atomic_write(target.parent, target, updated.encode("utf-8"))
    return {
        "path": _rel(root_real, target),
        "replacements": count if replace_all else 1,
        "first_line": first_line,
        "last_line": last_line,
        "diff": diff,
    }


def _require_single(count: int, replace_all: bool) -> None:
    if count > 1 and not replace_all:
        raise ReadonlyError(f"old text matches {count} times; add context or pass --replace-all")


def format_write(result: WriteResult) -> str:
    return f"wrote {result['path']} ({result['lines']} lines, {result['bytes']} bytes)\n"


def format_edit(result: EditResult) -> str:
    diff = result["diff"]
    if diff and not diff.endswith("\n"):
        diff += "\n"
    return (
        diff
        + f"edited {result['path']}: {result['replacements']} replacement(s), "
        + f"lines {result['first_line']}-{result['last_line']}\n"
    )


def _write_target(root: Path, user_path: str) -> tuple[Path, Path]:
    """Resolve a write target without following the final component.

    The parent is resolved with the same realpath confinement as the read-only
    commands, so ``..``, an absolute path outside, and a symlinked or junctioned
    parent that leaves the root all fail before anything is created.
    """
    root_real = _prepare_root(root)
    user_path = _normalize_user_path(user_path)
    raw = Path(user_path)
    name = raw.name
    if name in ("", ".", ".."):
        raise ReadonlyError(_INVALID_PATH, code=2)
    parent_spec = raw.parent
    if str(parent_spec) in ("", "."):
        parent_candidate = root_real
    elif raw.is_absolute():
        parent_candidate = parent_spec
    else:
        parent_candidate = root_real / parent_spec
    try:
        parent_real = parent_candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ReadonlyError(_INVALID_PATH) from exc
    try:
        parent_real.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    return root_real, parent_real / name


def _existing_bytes(root_real: Path, target: Path, *, create_only: bool) -> bytes | None:
    """Return the current bytes, or ``None`` when the target does not exist."""
    try:
        st = os.lstat(target)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _map_open(exc) from exc
    if create_only:
        raise ReadonlyError("exists")
    if _is_reparse(st):
        raise ReadonlyError(_ESCAPE)
    if not stat.S_ISREG(int(getattr(st, "st_mode", 0) or 0)):
        raise ReadonlyError(_NOT_FILE)
    data = _read_all(root_real, target)
    if b"\x00" in data:
        raise ReadonlyError(_BINARY)
    return data


def _read_all(root_real: Path, target: Path) -> bytes:
    # ``os.fdopen(..., "rb")`` switches the Windows fd to binary mode so CRLF
    # bytes survive; ``_open_regular`` still owns the close.
    with _open_regular(target, root_real=root_real) as (fd, _st), os.fdopen(fd, "rb", closefd=False) as handle:
        return handle.read()


def _ensure_parent(root_real: Path, parent: Path) -> None:
    try:
        parent.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise _map_open(exc) from exc


def _atomic_write(parent: Path, target: Path, data: bytes) -> None:
    try:
        fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=_WRITE_TMP_PREFIX, suffix=_WRITE_TMP_SUFFIX)
    except OSError as exc:
        raise _map_open(exc) from exc
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise _map_open(exc) from exc
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _line_count(data: bytes) -> int:
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def _line_span(normalized: str, old: str, *, replace_all: bool) -> tuple[int, int]:
    first_index = normalized.find(old)
    if first_index < 0:
        return 1, 1
    first_line = normalized.count("\n", 0, first_index) + 1
    last_index = first_index
    if replace_all:
        cursor = first_index
        while True:
            nxt = normalized.find(old, cursor + len(old))
            if nxt < 0:
                break
            last_index = nxt
            cursor = nxt
    end = last_index + len(old)
    last_line = normalized.count("\n", 0, max(end - 1, first_index)) + 1
    return first_line, last_line
