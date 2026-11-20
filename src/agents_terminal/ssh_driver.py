"""SSH driver: run the jailed argv on a remote host.

The agent stays local; commands execute on a VPS via ``ssh``. Config from env
(or policy JSON under the same names): ``AGENTS_TERMINAL_SSH_HOST`` (required),
``AGENTS_TERMINAL_SSH_USER``, ``AGENTS_TERMINAL_SSH_KEY`` (identity file),
``AGENTS_TERMINAL_SSH_PORT``, ``AGENTS_TERMINAL_SSH_DIR`` (remote workdir).

Each argv element is ``shlex.quote``d once — the remote shell parses that one
line; metacharacters stay inside their argument. BatchMode disables password
prompts so a missing key fails fast instead of hanging.
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .driver import RunResult
from .policy import Policy


def ssh_target() -> str:
    """``user@host`` from env config, or empty when unconfigured."""
    host = os.environ.get("AGENTS_TERMINAL_SSH_HOST", "").strip()
    if not host:
        return ""
    user = os.environ.get("AGENTS_TERMINAL_SSH_USER", "").strip()
    return f"{user}@{host}" if user else host


def ssh_available() -> bool:
    return bool(ssh_target())


def _ssh_argv() -> list[str] | None:
    target = ssh_target()
    if not target:
        return None
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15"]
    key = os.environ.get("AGENTS_TERMINAL_SSH_KEY", "").strip()
    if key:
        argv += ["-i", key]
    port = os.environ.get("AGENTS_TERMINAL_SSH_PORT", "").strip()
    if port:
        argv += ["-p", port]
    return argv + [target]


def _remote_line(argv: list[str]) -> str:
    line = " ".join(shlex.quote(a) for a in argv)
    workdir = os.environ.get("AGENTS_TERMINAL_SSH_DIR", "").strip()
    if workdir:
        line = f"cd {shlex.quote(workdir)} && {line}"
    return line


def run_ssh(
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

    base = _ssh_argv()
    if base is None:
        msg = "ssh driver requested but AGENTS_TERMINAL_SSH_HOST is not set"
        return RunResult(argv=cmd, returncode=127, stdout="", stderr=msg, denied=msg)
    try:
        proc = subprocess.run(
            [*base, "--", _remote_line(cmd)],
            capture_output=True,
            timeout=pol.timeout_sec + 30,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode()
        err = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode()
        return RunResult(
            argv=cmd,
            returncode=124,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
            timed_out=True,
        )
    except OSError as exc:
        return RunResult(argv=cmd, returncode=127, stdout="", stderr=str(exc))
    return RunResult(
        argv=cmd,
        returncode=int(proc.returncode),
        stdout=(proc.stdout or b"").decode("utf-8", errors="replace"),
        stderr=(proc.stderr or b"").decode("utf-8", errors="replace"),
    )
