"""Terminal policy loaded from env or default overlay path."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

    def workspace_dir(self) -> Path:
        if self.openshell_workspace:
            return Path(self.openshell_workspace).expanduser().resolve()
        agents_home = os.environ.get("AGENTS_HOME", "").strip()
        if agents_home:
            return (Path(agents_home) / "terminal-workspace").resolve()
        return Path.cwd().resolve()
