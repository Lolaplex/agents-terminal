"""OpenShell-backed driver: ephemeral sandbox per command."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .driver import RunResult
from .openshell_policy import write_policy_file
from .policy import Policy


def openshell_available() -> bool:
    if shutil.which("openshell"):
        return True
    if sys.platform == "win32" and shutil.which("wsl"):
        try:
            proc = subprocess.run(
                ["wsl", "-e", "bash", "-lc", "command -v openshell"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return proc.returncode == 0 and bool((proc.stdout or "").strip())
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def _openshell_prefix() -> Path | None:
    raw = os.environ.get("OPENSHELL_PREFIX", "").strip()
    if raw:
        p = Path(raw)
        if (p / "usr" / "bin" / "openshell").is_file():
            return p
    cache = os.environ.get("AGENTS_OPENSHELL_DIR", "").strip()
    if cache:
        p = Path(cache) / "prefix"
        if (p / "usr" / "bin" / "openshell").is_file():
            return p
    return None


def _openshell_cmd(argv: list[str]) -> list[str]:
    prefix = _openshell_prefix()
    if sys.platform == "win32" and shutil.which("wsl"):
        cache = os.environ.get("AGENTS_OPENSHELL_DIR", "").strip()
        state = os.environ.get("OPENSHELL_STATE_DIR", "").strip()
        if cache:
            prefix_path = str(prefix) if prefix else f"{cache}/prefix"
            state_path = state or f"{cache}/state"
            inner = " ".join(
                [
                    f"export AGENTS_OPENSHELL_DIR='{cache}'",
                    f"export OPENSHELL_PREFIX='{prefix_path}'",
                    f"export OPENSHELL_STATE_DIR='{state_path}'",
                    f"export XDG_CONFIG_HOME='{state_path}/config'",
                    f"export XDG_DATA_HOME='{state_path}/data'",
                    f"export PATH='{prefix_path}/usr/bin:$PATH'",
                    "openshell",
                    *argv,
                ]
            )
            return ["wsl", "-e", "bash", "-lc", inner]
    if prefix:
        bin_path = prefix / "usr" / "bin" / "openshell"
        return [str(bin_path), *argv]
    exe = shutil.which("openshell")
    if exe:
        return [exe, *argv]
    raise RuntimeError("openshell binary not found")


def run_openshell(
    argv: list[str],
    *,
    policy: Policy | None = None,
    read: bool = False,
    write: bool = False,
    net: bool = False,
) -> RunResult:
    pol = policy or Policy.load()
    cmd = [str(x) for x in argv]
    if not cmd:
        return RunResult(argv=[], returncode=2, stdout="", stderr="empty argv", denied="empty argv")

    denied = pol.check_request(read=read, write=write, net=net)
    if denied:
        return RunResult(argv=cmd, returncode=1, stdout="", stderr=denied, denied=denied)

    workspace = pol.workspace_dir()
    workspace.mkdir(parents=True, exist_ok=True)
    name = f"agents-term-{uuid.uuid4().hex[:12]}"

    with tempfile.TemporaryDirectory(prefix="agents-terminal-policy-") as tmp:
        policy_path = write_policy_file(pol, workspace=workspace, dest=Path(tmp) / "policy.yaml")
        wsl_policy = str(policy_path)
        if sys.platform == "win32" and shutil.which("wsl"):
            wsl_policy = subprocess.run(
                ["wsl", "-e", "wslpath", "-a", str(policy_path)],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip() or wsl_policy

        os_argv = [
            "sandbox",
            "create",
            "--no-keep",
            "--name",
            name,
            "--policy",
            wsl_policy,
            "--upload",
            f"{workspace}:/sandbox",
            "--",
            *cmd,
        ]
        full = _openshell_cmd(os_argv)
        try:
            proc = subprocess.run(
                full,
                capture_output=True,
                text=True,
                timeout=pol.timeout_sec + 30,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(
                argv=cmd,
                returncode=124,
                stdout=(exc.stdout or b"").decode("utf-8", errors="replace") if exc.stdout else "",
                stderr=(exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else "",
                timed_out=True,
            )
        except OSError as exc:
            return RunResult(argv=cmd, returncode=127, stdout="", stderr=str(exc))

    return RunResult(
        argv=cmd,
        returncode=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
