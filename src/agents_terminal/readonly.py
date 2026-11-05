"""Workspace-bound filesystem reads. These functions never spawn a process and never write."""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, TypedDict

DEFAULT_READ_LIMIT = 2000
MAX_READ_LIMIT = 20000
MAX_READ_BYTES = 1_048_576
MAX_SCAN_BYTES = 8_388_608
DEFAULT_GREP_MAX = 200
MAX_GREP_MAX = 5000
MAX_GREP_FILE_BYTES = 1_048_576
MAX_MATCH_CHARS = 2000
MAX_PATTERN_CHARS = 1024
MAX_PATH_CHARS = 4096

_ESCAPE = "path escapes workspace root"
_NOT_FOUND = "not found"
_NOT_FILE = "not a file"
_NOT_DIR = "not a directory"
_BINARY = "binary file"
_INVALID_PATH = "invalid path"
_INVALID_PATTERN = "invalid pattern"
_EMPTY_PATTERN = "empty pattern"
_PERMISSION = "permission denied"
_UNAVAILABLE = "confinement unavailable"
# Windows FILE_ATTRIBUTE_REPARSE_POINT. Junctions and symlinks both set it.
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class ReadonlyError(Exception):
    """A read failed closed. ``code`` 2 is a usage error; 1 is everything else."""

    def __init__(self, message: str, *, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class DirEntry(TypedDict, total=False):
    name: str
    type: str
    size: int
    mtime: str | None
    target: str


class ListResult(TypedDict):
    path: str
    entries: list[DirEntry]


class ReadResult(TypedDict):
    path: str
    offset: int
    limit: int
    line_count: int
    truncated: bool
    content: str


class GrepMatch(TypedDict):
    path: str
    line: int
    text: str


class GrepResult(TypedDict):
    path: str
    matches: list[GrepMatch]
    truncated: bool


class StatResult(TypedDict):
    path: str
    type: str
    size: int
    mtime: str
    mode: str
    target: str | None


def list_directory(root: Path, path: str = ".") -> ListResult:
    """List one directory. Symlink entries are reported, not followed."""
    root_real = _prepare_root(root)
    target = resolve_path(root_real, path, follow_final=True)
    if not target.exists():
        raise ReadonlyError(_NOT_FOUND)
    entries = _list_entries(root_real, target)
    entries.sort(key=lambda item: item["name"])
    return {"path": _rel(root_real, target), "entries": entries}


def read_file(
    root: Path,
    path: str,
    *,
    offset: int = 1,
    limit: int = DEFAULT_READ_LIMIT,
) -> ReadResult:
    """Read a regular UTF-8 text file. ``offset`` is the 1-based starting line."""
    offset = _bounded_int(offset, name="offset", upper=10**9)
    limit = _bounded_int(limit, name="limit", upper=MAX_READ_LIMIT)
    root_real = _prepare_root(root)
    target = resolve_path(root_real, path, follow_final=True)
    if not target.exists():
        raise ReadonlyError(_NOT_FOUND)
    selected, truncated = _read_line_window(root_real, target, offset=offset, limit=limit)
    content = b"".join(selected).decode("utf-8", errors="replace")
    return {
        "path": _rel(root_real, target),
        "offset": offset,
        "limit": limit,
        "line_count": len(selected),
        "truncated": truncated,
        "content": content,
    }


def grep_files(
    root: Path,
    pattern: str,
    path: str = ".",
    *,
    glob: str | None = None,
    literal: bool = False,
    ignore_case: bool = False,
    max_matches: int = DEFAULT_GREP_MAX,
) -> GrepResult:
    """Search regular files. Directory symlinks are not descended."""
    compiled = _compile_pattern(pattern, literal=literal, ignore_case=ignore_case)
    max_matches = _bounded_int(max_matches, name="max", upper=MAX_GREP_MAX)
    glob_pattern = _clean_glob(glob)
    root_real = _prepare_root(root)
    start = resolve_path(root_real, path, follow_final=True)
    if not start.exists():
        raise ReadonlyError(_NOT_FOUND)
    matches: list[GrepMatch] = []
    truncated = False
    direct = start.is_file()
    filled = False
    for file_path in _iter_search_files(root_real, start):
        rel = _rel(root_real, file_path)
        if not _glob_ok(rel, file_path.name, glob_pattern):
            continue
        room = 1 if filled else max_matches - len(matches)
        try:
            file_matches, file_truncated = _search_file(root_real, file_path, compiled, room)
        except ReadonlyError:
            if direct:
                raise
            continue
        if filled:
            if file_matches or file_truncated:
                truncated = True
                break
            continue
        matches.extend(file_matches)
        if file_truncated:
            truncated = True
        if len(matches) >= max_matches:
            filled = True
            if truncated:
                break
    return {"path": _rel(root_real, start), "matches": matches, "truncated": truncated}


def stat_path(root: Path, path: str) -> StatResult:
    """lstat one path. A symlink is described, not opened.

    The parent directory goes through the same confinement as list/read/grep.
    """
    root_real = _prepare_root(root)
    target = resolve_path(root_real, path, follow_final=False)
    if _fd_confinement_supported():
        return _stat_fd(root_real, target)
    return _stat_fallback(root_real, target)


def format_list(result: ListResult) -> str:
    lines: list[str] = []
    for entry in result["entries"]:
        parts = [entry["type"], str(entry["size"]), entry["name"]]
        if entry["type"] == "symlink":
            parts.append(entry.get("target", ""))
        lines.append("\t".join(parts))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def format_read(result: ReadResult) -> str:
    return result["content"]


def format_grep(result: GrepResult) -> str:
    lines = [f"{hit['path']}:{hit['line']}:{hit['text']}" for hit in result["matches"]]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def format_stat(result: StatResult) -> str:
    lines = [
        f"path: {result['path']}",
        f"type: {result['type']}",
        f"size: {result['size']}",
        f"mtime: {result['mtime']}",
        f"mode: {result['mode']}",
    ]
    if result["target"] is not None:
        lines.append(f"target: {result['target']}")
    return "\n".join(lines) + "\n"


def resolve_path(root: Path, user_path: str, *, follow_final: bool) -> Path:
    """Return a path inside ``root``.

    ``follow_final`` resolves the last component. Stat passes False so a symlink
    that lives in the workspace is described even when its target is outside.
    """
    root_real = _root_real(root)
    user_path = _normalize_user_path(user_path)
    if follow_final:
        return _resolve_followed(root_real, user_path)

    raw = Path(user_path)
    name = raw.name
    if name not in ("", ".", ".."):
        if raw.is_absolute():
            parent_spec = str(raw.parent)
        else:
            parent_spec = "." if str(raw.parent) in (".", "") else str(raw.parent)
        try:
            parent_real = _resolve_followed(root_real, parent_spec)
        except ReadonlyError:
            followed = _resolve_followed(root_real, user_path)
            if followed == root_real:
                return root_real
            raise
        if not parent_real.exists():
            raise ReadonlyError(_NOT_FOUND)
        if not parent_real.is_dir():
            raise ReadonlyError(_NOT_DIR)
        return parent_real / name
    return _resolve_followed(root_real, user_path)


def _prepare_root(root: Path) -> Path:
    real = _root_real(root)
    if not real.exists():
        raise ReadonlyError(_NOT_FOUND)
    if not real.is_dir():
        raise ReadonlyError(_NOT_DIR)
    return real


def _root_real(root: Path) -> Path:
    try:
        return Path(root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ReadonlyError(_INVALID_PATH) from exc


def _normalize_user_path(user_path: str) -> str:
    if not isinstance(user_path, str):
        raise ReadonlyError(_INVALID_PATH, code=2)
    if user_path == "":
        return "."
    if len(user_path) > MAX_PATH_CHARS or any(ch in user_path for ch in ("\x00", "\n", "\r")):
        raise ReadonlyError(_INVALID_PATH, code=2)
    return user_path


def _resolve_followed(root_real: Path, user_path: str) -> Path:
    raw = Path(user_path)
    candidate = raw if raw.is_absolute() else root_real / raw
    try:
        real = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ReadonlyError(_INVALID_PATH) from exc
    try:
        real.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    return real


def _rel(root_real: Path, path: Path) -> str:
    try:
        rel = path.relative_to(root_real)
    except ValueError:
        rel = path.resolve(strict=False).relative_to(root_real)
    text = rel.as_posix()
    return "." if text in ("", ".") else text


def _bounded_int(value: int, *, name: str, upper: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReadonlyError(f"{name} must be an integer", code=2)
    if value < 1 or value > upper:
        raise ReadonlyError(f"{name} must be between 1 and {upper}", code=2)
    return value


def _compile_pattern(pattern: str, *, literal: bool, ignore_case: bool) -> re.Pattern[str]:
    if not isinstance(pattern, str) or not isinstance(literal, bool) or not isinstance(ignore_case, bool):
        raise ReadonlyError(_INVALID_PATTERN, code=2)
    if pattern == "":
        raise ReadonlyError(_EMPTY_PATTERN, code=2)
    if len(pattern) > MAX_PATTERN_CHARS:
        raise ReadonlyError(_INVALID_PATTERN, code=2)
    flags = re.IGNORECASE if ignore_case else 0
    source = re.escape(pattern) if literal else pattern
    try:
        return re.compile(source, flags)
    except re.error as exc:
        raise ReadonlyError(_INVALID_PATTERN, code=2) from exc


def _clean_glob(glob: str | None) -> str | None:
    if glob is None:
        return None
    if not isinstance(glob, str) or "\x00" in glob or len(glob) > MAX_PATTERN_CHARS:
        raise ReadonlyError(_INVALID_PATTERN, code=2)
    stripped = glob.strip()
    return stripped or None


def _glob_ok(rel: str, name: str, pattern: str | None) -> bool:
    if pattern is None:
        return True
    return fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(name, pattern)


def _kind(mode: int, is_link: bool) -> str:
    if is_link:
        return "symlink"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def _iso(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_from_stat(name: str, st: object, link_target: str | None) -> DirEntry:
    reparse = _is_reparse(st)
    mode = int(getattr(st, "st_mode"))
    item: DirEntry = {
        "name": name,
        "type": _kind(mode, reparse),
        "size": int(getattr(st, "st_size")),
        "mtime": _iso(float(getattr(st, "st_mtime"))),
    }
    if reparse:
        item["target"] = "" if link_target is None else link_target
    return item


def _dir_entry_at(dir_fd: int, name: str) -> DirEntry:
    try:
        st = _lstat_at(name, dir_fd)
    except ReadonlyError:
        raise
    except OSError:
        return {"name": name, "type": "other", "size": 0, "mtime": None}
    link_target: str | None = None
    if _is_reparse(st):
        try:
            link_target = _readlink_at(name, dir_fd)
        except ReadonlyError:
            raise
        except OSError:
            link_target = ""
    return _entry_from_stat(name, st, link_target)


def _dir_entry_scandir(ent: os.DirEntry[str]) -> DirEntry:
    try:
        st = ent.stat(follow_symlinks=False)
    except OSError:
        return {"name": ent.name, "type": "other", "size": 0, "mtime": None}
    link_target: str | None = None
    if _is_reparse(st):
        try:
            link_target = os.readlink(ent.path)
        except OSError:
            link_target = ""
    return _entry_from_stat(ent.name, st, link_target)


def _nofollow_flag() -> int | None:
    flag = getattr(os, "O_NOFOLLOW", None)
    if isinstance(flag, int) and flag != 0:
        return flag
    return None


def _fd_confinement_supported() -> bool:
    """True only when a root fd can be walked without following links.

    Missing ``O_NOFOLLOW`` or ``dir_fd`` support must not fall through to a
    following ``open``. Callers use the realpath and reparse-point fallback.
    """
    if _nofollow_flag() is None:
        return False
    dir_ok = getattr(os, "supports_dir_fd", frozenset())
    fd_ok = getattr(os, "supports_fd", frozenset())
    # os.lstat is often a wrapper and is absent from supports_dir_fd even when
    # os.stat(..., follow_symlinks=False, dir_fd=) works. Require the advertised API.
    if os.open not in dir_ok or os.readlink not in dir_ok:
        return False
    if os.lstat not in dir_ok and os.stat not in dir_ok:
        return False
    if os.listdir not in fd_ok and os.listdir not in dir_ok:
        return False
    return True


def _lstat_at(name: str, dir_fd: int):
    """lstat one directory entry. Uses only dir_fd operations the platform advertises."""
    dir_ok = getattr(os, "supports_dir_fd", frozenset())
    try:
        if os.lstat in dir_ok:
            return os.lstat(name, dir_fd=dir_fd)
        if os.stat in dir_ok:
            return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc
    raise ReadonlyError(_UNAVAILABLE)


def _readlink_at(name: str, dir_fd: int) -> str:
    try:
        return os.readlink(name, dir_fd=dir_fd)
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc


def _is_reparse(st: object) -> bool:
    """Symlink, junction, or any other reparse point. Never follow these on the fallback."""
    mode = int(getattr(st, "st_mode", 0) or 0)
    if stat.S_ISLNK(mode):
        return True
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    return bool(attrs & _REPARSE_ATTRIBUTE)


def _path_is_reparse(path: Path) -> bool:
    try:
        return _is_reparse(os.lstat(path))
    except OSError:
        return False


def _unsafe_to_descend(path: Path) -> bool:
    try:
        return _is_reparse(os.lstat(path))
    except OSError:
        return True


def _read_flags() -> int:
    flags = os.O_RDONLY
    nofollow = _nofollow_flag()
    if nofollow is not None:
        flags |= nofollow
    nonblock = getattr(os, "O_NONBLOCK", None)
    if isinstance(nonblock, int) and nonblock != 0:
        flags |= nonblock
    return flags


def _plain_read_flags() -> int:
    """Read-only flags with no ``dir_fd`` and no claim of ``O_NOFOLLOW``."""
    flags = os.O_RDONLY
    nonblock = getattr(os, "O_NONBLOCK", None)
    if isinstance(nonblock, int) and nonblock != 0:
        flags |= nonblock
    return flags


def _dir_flags() -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    nofollow = _nofollow_flag()
    if nofollow is not None:
        flags |= nofollow
    nonblock = getattr(os, "O_NONBLOCK", None)
    if isinstance(nonblock, int) and nonblock != 0:
        flags |= nonblock
    return flags


def _assert_realpath_inside(root_real: Path, target: Path) -> None:
    try:
        real = Path(target).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ReadonlyError(_INVALID_PATH) from exc
    try:
        real.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc


def _reject_reparse_components(root_real: Path, target: Path, *, allow_final_reparse: bool) -> None:
    """Reject symlinks, junctions, and other reparse points before an open."""
    try:
        rel = Path(target).relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    parts = [part for part in rel.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ReadonlyError(_ESCAPE)
    try:
        root_st = os.lstat(root_real)
    except OSError as exc:
        raise _map_open(exc) from exc
    if _is_reparse(root_st):
        raise ReadonlyError(_ESCAPE)
    current = root_real
    for index, part in enumerate(parts):
        current = current / part
        last = index == len(parts) - 1
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            if last:
                return
            raise ReadonlyError(_NOT_FOUND) from None
        except OSError as exc:
            raise _map_open(exc) from exc
        if _is_reparse(st) and not (last and allow_final_reparse):
            raise ReadonlyError(_ESCAPE)


def _same_inode(left: object, right: object) -> bool:
    return (getattr(left, "st_dev", None), getattr(left, "st_ino", None)) == (
        getattr(right, "st_dev", None),
        getattr(right, "st_ino", None),
    )


def _stat_result(root_real: Path, display: Path, st: object, link_target: str | None) -> StatResult:
    mode = int(getattr(st, "st_mode"))
    return {
        "path": _rel(root_real, display),
        "type": _kind(mode, _is_reparse(st)),
        "size": int(getattr(st, "st_size")),
        "mtime": _iso(float(getattr(st, "st_mtime"))),
        "mode": format(stat.S_IMODE(mode), "04o"),
        "target": link_target,
    }


def _link_text(st: object, reader: object) -> str | None:
    if not _is_reparse(st):
        return None
    try:
        text = reader()
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc
    except OSError:
        if stat.S_ISLNK(int(getattr(st, "st_mode", 0) or 0)):
            raise ReadonlyError(_INVALID_PATH)
        return ""
    return str(text)


def _stat_fd(root_real: Path, target: Path) -> StatResult:
    if target == root_real:
        fd = _open_under(root_real, root_real, directory=True)
        try:
            try:
                st = os.fstat(fd)
            except TypeError as exc:
                raise ReadonlyError(_UNAVAILABLE) from exc
        finally:
            os.close(fd)
        return _stat_result(root_real, root_real, st, None)
    name = target.name
    if name in ("", ".", ".."):
        raise ReadonlyError(_INVALID_PATH)
    fd = _open_under(root_real, target.parent, directory=True)
    try:
        try:
            st = _lstat_at(name, fd)
        except ReadonlyError:
            raise
        except OSError as exc:
            raise _map_open(exc) from exc
        link = _link_text(st, lambda: _readlink_at(name, fd))
        return _stat_result(root_real, target, st, link)
    finally:
        os.close(fd)


def _stat_fallback(root_real: Path, target: Path) -> StatResult:
    """Confined stat when ``dir_fd`` or ``O_NOFOLLOW`` is missing. Does not follow links."""
    try:
        target.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    if target == root_real:
        _assert_realpath_inside(root_real, target)
        _reject_reparse_components(root_real, target, allow_final_reparse=False)
        try:
            st = os.lstat(target)
        except OSError as exc:
            raise _map_open(exc) from exc
        if _is_reparse(st):
            raise ReadonlyError(_ESCAPE)
        return _stat_result(root_real, target, st, None)
    parent = target.parent
    _assert_realpath_inside(root_real, parent)
    _reject_reparse_components(root_real, parent, allow_final_reparse=False)
    try:
        st = os.lstat(target)
    except OSError as exc:
        raise _map_open(exc) from exc
    if _is_reparse(st):
        link = _link_text(st, lambda: os.readlink(target))
        return _stat_result(root_real, target, st, link)
    _assert_realpath_inside(root_real, target)
    return _stat_result(root_real, target, st, None)


def _list_entries(root_real: Path, target: Path) -> list[DirEntry]:
    if _fd_confinement_supported():
        if not target.is_dir():
            raise ReadonlyError(_NOT_DIR)
        fd = _open_under(root_real, target, directory=True)
        try:
            try:
                names = os.listdir(fd)
            except TypeError as exc:
                raise ReadonlyError(_UNAVAILABLE) from exc
            except PermissionError as exc:
                raise ReadonlyError(_PERMISSION) from exc
            except OSError as exc:
                raise ReadonlyError(_INVALID_PATH) from exc
            return [_dir_entry_at(fd, name) for name in names]
        finally:
            os.close(fd)
    _assert_realpath_inside(root_real, target)
    _reject_reparse_components(root_real, target, allow_final_reparse=False)
    try:
        st = os.lstat(target)
    except OSError as exc:
        raise _map_open(exc) from exc
    if _is_reparse(st):
        raise ReadonlyError(_ESCAPE)
    if not stat.S_ISDIR(st.st_mode):
        raise ReadonlyError(_NOT_DIR)
    entries: list[DirEntry] = []
    try:
        iterator = os.scandir(target)
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc
    except PermissionError as exc:
        raise ReadonlyError(_PERMISSION) from exc
    except OSError as exc:
        raise ReadonlyError(_INVALID_PATH) from exc
    with iterator:
        for ent in iterator:
            entries.append(_dir_entry_scandir(ent))
    return entries


def _open_fallback(root_real: Path, target: Path) -> int:
    """Open a regular file without ``dir_fd``. Reparse points are rejected first."""
    _assert_realpath_inside(root_real, target)
    _reject_reparse_components(root_real, target, allow_final_reparse=False)
    try:
        before = os.lstat(target)
    except OSError as exc:
        raise _map_open(exc) from exc
    if _is_reparse(before):
        raise ReadonlyError(_ESCAPE)
    if not stat.S_ISREG(int(getattr(before, "st_mode", 0) or 0)):
        raise ReadonlyError(_NOT_FILE)
    try:
        fd = os.open(os.fspath(target), _plain_read_flags())
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc
    except OSError as exc:
        raise _map_open(exc) from exc
    try:
        after = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise
    if not stat.S_ISREG(after.st_mode) or not _same_inode(before, after):
        os.close(fd)
        raise ReadonlyError(_ESCAPE)
    return fd


def _map_open(exc: OSError) -> ReadonlyError:
    if isinstance(exc, PermissionError) or exc.errno in (errno.EACCES, errno.EPERM):
        return ReadonlyError(_PERMISSION)
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return ReadonlyError(_NOT_FOUND)
    if exc.errno in (errno.ELOOP, errno.EMLINK):
        return ReadonlyError(_ESCAPE)
    if exc.errno == errno.ENOTDIR:
        return ReadonlyError(_NOT_DIR)
    return ReadonlyError(_INVALID_PATH)


def _open_under(root_real: Path, target: Path, *, directory: bool) -> int:
    """Open ``target`` from a root directory fd. Each component uses ``O_NOFOLLOW``."""
    if not _fd_confinement_supported():
        raise ReadonlyError(_UNAVAILABLE)
    try:
        rel = target.relative_to(root_real)
    except ValueError as exc:
        raise ReadonlyError(_ESCAPE) from exc
    parts = [part for part in rel.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ReadonlyError(_ESCAPE)
    try:
        current = os.open(root_real, _dir_flags())
    except TypeError as exc:
        raise ReadonlyError(_UNAVAILABLE) from exc
    except OSError as exc:
        raise _map_open(exc) from exc
    try:
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            try:
                st = _lstat_at(part, current)
            except ReadonlyError:
                raise
            except OSError as exc:
                raise _map_open(exc) from exc
            if _is_reparse(st):
                raise ReadonlyError(_ESCAPE)
            flags = _dir_flags() if directory or not last else _read_flags()
            try:
                nxt = os.open(part, flags, dir_fd=current)
            except TypeError as exc:
                raise ReadonlyError(_UNAVAILABLE) from exc
            except OSError as exc:
                raise _map_open(exc) from exc
            os.close(current)
            current = nxt
        st = os.fstat(current)
        if directory and not stat.S_ISDIR(st.st_mode):
            raise ReadonlyError(_NOT_DIR)
        if not directory and not stat.S_ISREG(st.st_mode):
            raise ReadonlyError(_NOT_FILE)
        owned = current
        current = -1
        return owned
    finally:
        if current >= 0:
            os.close(current)


@contextmanager
def _open_regular(path: Path, *, root_real: Path | None = None) -> Iterator[tuple[int, os.stat_result]]:
    """Open one regular file. Components are not followed and the file is not opened for write."""
    if root_real is None:
        if _nofollow_flag() is None:
            raise ReadonlyError(_UNAVAILABLE)
        try:
            fd = os.open(path, _read_flags())
        except TypeError as exc:
            raise ReadonlyError(_UNAVAILABLE) from exc
        except OSError as exc:
            raise _map_open(exc) from exc
    elif _fd_confinement_supported():
        fd = _open_under(root_real, path, directory=False)
    else:
        fd = _open_fallback(root_real, path)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ReadonlyError(_NOT_FILE)
        yield fd, st
    finally:
        os.close(fd)


def _iter_capped_lines(fd: int, max_bytes: int, state: dict[str, bool]) -> Iterator[bytes]:
    """Yield lines until ``max_bytes`` have been consumed. ``state['eof']`` is set."""
    state["eof"] = False
    consumed = 0
    pending = b""
    while consumed < max_bytes:
        chunk = os.read(fd, min(65536, max_bytes - consumed))
        if not chunk:
            state["eof"] = True
            if pending:
                yield pending
            return
        consumed += len(chunk)
        pending += chunk
        while True:
            nl = pending.find(b"\n")
            if nl < 0:
                break
            yield pending[: nl + 1]
            pending = pending[nl + 1 :]
    extra = os.read(fd, 1)
    if extra:
        state["eof"] = False
        return
    state["eof"] = True
    if pending:
        yield pending


def _read_line_window(root_real: Path, path: Path, *, offset: int, limit: int) -> tuple[list[bytes], bool]:
    with _open_regular(path, root_real=root_real) as (fd, _st):
        state: dict[str, bool] = {}
        selected: list[bytes] = []
        output_bytes = 0
        seen = 0
        truncated = False
        for line in _iter_capped_lines(fd, MAX_SCAN_BYTES, state):
            if b"\x00" in line:
                raise ReadonlyError(_BINARY)
            seen += 1
            if seen < offset:
                continue
            if len(selected) >= limit or output_bytes + len(line) > MAX_READ_BYTES:
                truncated = True
                break
            selected.append(line)
            output_bytes += len(line)
        else:
            if not state.get("eof", False):
                truncated = True
        return selected, truncated


def _iter_search_files(root_real: Path, start: Path) -> Iterator[Path]:
    if start.is_symlink() or _path_is_reparse(start):
        raise ReadonlyError(_ESCAPE)
    if start.is_file():
        yield start
        return
    if not start.is_dir():
        raise ReadonlyError(_NOT_FILE if start.exists() else _NOT_FOUND)
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        dirnames.sort()
        filenames.sort()
        kept: list[str] = []
        for dirname in dirnames:
            child = Path(dirpath) / dirname
            if child.is_symlink() or _unsafe_to_descend(child):
                continue
            try:
                _resolve_followed(root_real, str(child))
            except ReadonlyError:
                continue
            kept.append(dirname)
        dirnames[:] = kept
        for name in filenames:
            child = Path(dirpath) / name
            if child.is_symlink() or _path_is_reparse(child) or not child.is_file():
                continue
            try:
                _resolve_followed(root_real, str(child))
            except ReadonlyError:
                continue
            yield child


def _search_file(
    root_real: Path,
    path: Path,
    pattern: re.Pattern[str],
    room: int,
) -> tuple[list[GrepMatch], bool]:
    if room <= 0:
        return [], True
    rel = _rel(root_real, path)
    matches: list[GrepMatch] = []
    truncated = False
    with _open_regular(path, root_real=root_real) as (fd, _st):
        state: dict[str, bool] = {}
        line_no = 0
        for raw in _iter_capped_lines(fd, MAX_GREP_FILE_BYTES, state):
            if b"\x00" in raw:
                raise ReadonlyError(_BINARY)
            line_no += 1
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if pattern.search(text) is None:
                continue
            if len(matches) >= room:
                return matches, True
            if len(text) > MAX_MATCH_CHARS:
                text = text[:MAX_MATCH_CHARS]
                truncated = True
            matches.append({"path": rel, "line": line_no, "text": text})
        if not state.get("eof", False):
            truncated = True
    return matches, truncated
