"""Terminal policy loaded from env or default overlay path."""

from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

_DEFAULT_ENV_ALLOW = (
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "WINDIR",
    "HOME",
    "USER",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
)


@dataclass
class Policy:
    cwd: str | None = None
    timeout_sec: int = 60
    home: bool = False
    read: bool = False
    write: bool = False
    net: bool = False
    driver: str = "auto"
    openshell_workspace: str | None = None
    env_allow: tuple[str, ...] = field(default_factory=lambda: _DEFAULT_ENV_ALLOW)

    @classmethod
    def load(cls, path: str | None = None) -> "Policy":
        raw_path = path or os.environ.get("AGENTS_TERMINAL_POLICY", "").strip()
        data: dict[str, Any] = {}
        if raw_path:
            p = Path(raw_path).expanduser()
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
        allow = data.get("env_allow")
        if allow is None:
            extra_env = os.environ.get("AGENTS_TERMINAL_ENV_ALLOW") or os.environ.get("AGENTS_TERMINAL_EXTRA_ENV", "")
            base = list(_DEFAULT_ENV_ALLOW)
            if extra_env.strip():
                base.extend([x.strip() for x in extra_env.split(",") if x.strip()])
            allow = base
        driver = str(data.get("driver") or os.environ.get("AGENTS_TERMINAL_DRIVER", "auto")).strip().lower()
        return cls(
            cwd=str(data["cwd"]) if data.get("cwd") else None,
            timeout_sec=int(data.get("timeout_sec") or 60),
            home=bool(data.get("home", False)),
            read=bool(data.get("read", False)),
            write=bool(data.get("write", False)),
            net=bool(data.get("net", False)),
            driver=driver or "auto",
            openshell_workspace=str(data["openshell_workspace"]) if data.get("openshell_workspace") else None,
            env_allow=tuple(str(x) for x in allow),
        )

    def check_request(self, *, read: bool, write: bool, net: bool) -> str | None:
        if read and not self.read:
            return "read denied (no driver)"
        if write and not self.write:
            return "write denied (no driver)"
        if net and not self.net:
            return "net denied (no driver)"
        return None

    def filtered_env(self) -> dict[str, str]:
        passthrough = os.environ.get("AGENTS_TERMINAL_ENV_PASSTHROUGH", "").strip().lower() in ("1", "true", "yes")
        if passthrough:
            return dict(os.environ)
        out: dict[str, str] = {}
        for key in self.env_allow:
            val = os.environ.get(key)
            if val is not None:
                out[key] = val
        return out

    def work_root(self) -> Path:
        """Directory ``run`` uses as its working directory. This does not create it."""
        if self.cwd:
            return Path(self.cwd).expanduser().resolve()
        return self.workspace_dir()

    def workspace_dir(self) -> Path:
        if self.openshell_workspace:
            return Path(self.openshell_workspace).expanduser().resolve()
        workspace_env = os.environ.get("AGENTS_WORKSPACE_DIR", "").strip()
        if workspace_env:
            return Path(workspace_env).expanduser().resolve()
        agents_home = os.environ.get("AGENTS_HOME", "").strip()
        if agents_home:
            return (Path(agents_home) / "workspace").resolve()
        return (Path.home() / ".agents" / "workspace").resolve()


_ESCAPE = "path escapes workspace root"
_WIN_ABS = re.compile(r"[A-Za-z]:[\\/][^\"'\s),;]+")
_UNC = re.compile(r"\\\\[^\"'\s),;]+")
_EMBED_REL = re.compile(r"(?:^|[\s\"'=])(\.\.[\\/][^\"'\s),;]*)")
_POSIX_ABS = re.compile(r"(?:^|[\s\"'=])(/[^\"'\s),;]+)")


def workspace_root() -> Path | None:
    """Resolved ``AGENTS_WORKSPACE_DIR``, or None when the lock is off."""
    raw = os.environ.get("AGENTS_WORKSPACE_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError):
        return path


def _path_key(path: Path) -> str:
    try:
        text = os.path.normcase(os.path.normpath(str(path.expanduser().resolve(strict=False))))
    except (OSError, RuntimeError):
        return ""
    for prefix in ("\\\\?\\unc\\", "\\\\?\\"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text


def _under(root: Path, path: Path) -> bool:
    root_s = _path_key(root)
    child_s = _path_key(path)
    if not root_s or not child_s:
        return False
    if child_s == root_s:
        return True
    prefix = root_s if root_s.endswith(os.sep) else root_s + os.sep
    return child_s.startswith(prefix)


def _agents_home() -> Path:
    raw = os.environ.get("AGENTS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".agents"


def _internal_roots() -> list[Path]:
    """Dirs the workspace lock must not treat as escapes.

    ``AGENTS_HOME`` is the instance root when a host sets it, otherwise
    ``~/.agents``. Skills, modules, memory, traces, and schedules stay
    reachable even when that home is a narrower instance directory.
    """
    home = _agents_home()
    dot = Path.home() / ".agents"
    roots = [
        home,
        dot / "skills",
        dot / "modules",
        dot / "memory",
        dot / "traces",
        dot / "schedules",
        home / "skills",
        home / "modules",
        home / "memory",
        home / "traces",
        home / "schedules",
        home / "routine-runs",
    ]
    for key in (
        "AGENTS_SKILLS_DIR",
        "AGENTS_MODULES_DIR",
        "AGENTS_MEMORY_PATH",
        "AGENTS_TRACES_DIR",
        "AGENTS_SCHEDULES_DIR",
        "AGENTS_ROUTINE_RUNS_DIR",
    ):
        raw = os.environ.get(key, "").strip()
        if raw:
            roots.append(Path(raw).expanduser())
    extra = os.environ.get("AGENTS_SKILLS_EXTRA", "")
    for part in extra.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).expanduser())
    return roots


def _permitted(path: Path, root: Path) -> bool:
    if _under(root, path):
        return True
    for base in _internal_roots():
        if _under(base, path):
            return True
    return False


def _pieces(text: str) -> list[str]:
    if text.startswith("-"):
        eq = text.find("=")
        return [] if eq < 0 else _pieces(text[eq + 1 :])
    raw = Path(text).expanduser()
    if raw.is_absolute() or ".." in raw.parts:
        return [text]
    if not any(ch.isspace() for ch in text):
        return [text]
    if (
        _WIN_ABS.search(text)
        or _UNC.search(text)
        or _EMBED_REL.search(text)
        or (os.name != "nt" and _POSIX_ABS.search(text))
    ):
        try:
            return [part for part in shlex.split(text, posix=(os.name != "nt")) if part]
        except ValueError:
            return text.split()
    return [text]


def _is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return True


def _piece_paths(piece: str, base: Path) -> list[Path]:
    if not piece or piece == "." or "://" in piece:
        return []
    if os.name == "nt" and re.fullmatch(r"/[A-Za-z?][\w.-]*", piece):
        return []
    raw = Path(piece).expanduser()
    if raw.is_absolute() or ".." in raw.parts:
        return [raw if raw.is_absolute() else base / raw]
    if "/" in piece or "\\" in piece:
        return [base / raw]
    candidate = base / raw
    try:
        linked = candidate.is_symlink()
        exists = candidate.exists()
    except OSError:
        return [candidate]
    if linked or exists:
        return [candidate]
    return []


def _argv_paths(argv: Sequence[str], base: Path) -> list[Path]:
    found: list[Path] = []
    for index, arg in enumerate(argv):
        text = str(arg).strip()
        if not text:
            continue
        if index == 0:
            raw = Path(text).expanduser()
            if not raw.is_absolute() and (
                ".." in raw.parts or "/" in text or "\\" in text or _is_symlink(base / raw)
            ):
                found.append(base / raw)
            continue
        for piece in _pieces(text):
            found.extend(_piece_paths(piece, base))
        for match in _WIN_ABS.findall(text):
            found.append(Path(match))
        for match in _UNC.findall(text):
            found.append(Path(match))
        for match in _EMBED_REL.findall(text):
            found.append(base / match)
        if os.name != "nt":
            for match in _POSIX_ABS.findall(text):
                found.append(Path(match))
    return found


def refuse_workspace(cwd: str | Path | None, argv: Sequence[str] = ()) -> str | None:
    """Refuse a user cwd or tool path that resolves outside ``AGENTS_WORKSPACE_DIR``.

    Unset or blank env keeps the current behavior. Skills, modules, memory,
    traces, schedules, and ``AGENTS_HOME`` stay reachable. Symlink targets count.
    """
    root = workspace_root()
    if root is None:
        return None
    explicit: Path | None = None
    if cwd is not None and str(cwd).strip():
        explicit = Path(str(cwd)).expanduser()
        if not _permitted(explicit, root):
            return _ESCAPE
    base = explicit if explicit is not None else Path.cwd()
    try:
        base = base.resolve(strict=False)
    except (OSError, RuntimeError):
        return _ESCAPE
    for path in _argv_paths(argv, base):
        if not _permitted(path, root):
            return _ESCAPE
    return None

