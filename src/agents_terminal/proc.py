"""Background processes under terminal policy.

``bg`` spawns argv detached; ``proc`` manages it. State lives in per-proc dirs
under ``AGENTS_TERMINAL_PROCS_DIR`` (default: ``<workspace>/procs``):

    procs/<id>/meta.json   id, argv, wrapper pid, cwd, created
    procs/<id>/out.log     stdout
    procs/<id>/err.log     stderr
    procs/<id>/in.txt      stdin feed (posix fifo mode only)
    procs/<id>/exit.json   {"code": N, "finished": ts} written by the wrapper

POSIX spawns a ``tail -f in.txt | argv`` feeder so ``proc write`` can append
stdin later. Windows spawns argv directly; ``write`` is refused there.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .policy import Policy


def _procs_root() -> Path:
    raw = os.environ.get("AGENTS_TERMINAL_PROCS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    from agents_workspace import Workspace

    return Workspace.from_env().dir / "procs"


def _proc_dir(proc_id: str) -> Path:
    safe = "".join(ch for ch in proc_id if ch.isalnum() or ch in ("-", "_"))
    if not safe or safe != proc_id:
        raise ProcError("invalid process id", code=2)
    return _procs_root() / safe


class ProcError(Exception):
    def __init__(self, message: str, *, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _proc_state(pdir: Path) -> dict[str, Any]:
    meta = _read_json(pdir / "meta.json")
    code = _read_exit_code(pdir)
    finished = _read_json(pdir / "exit.json").get("finished") or ""
    pid = int(meta.get("pid") or 0)
    running = code is None and _pid_alive(pid)
    return {
        "id": pdir.name,
        "argv": meta.get("argv") or [],
        "pid": pid,
        "cwd": meta.get("cwd") or "",
        "created": meta.get("created") or "",
        "state": "running" if running else "exited",
        "exit_code": code,
        "finished": finished,
    }


def _tail(path: Path, max_lines: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    if max_lines > 0:
        lines = lines[-max_lines:]
    return "\n".join(lines)


def bg_spawn(argv: list[str], *, policy: Policy | None = None) -> dict[str, Any]:
    pol = policy or Policy.load()
    if pol.driver not in ("auto", "subprocess"):
        raise ProcError("bg unsupported on openshell driver; run the foreground command instead", code=2)
    denied = pol.check_request(read=False, write=False, net=False)
    if denied:
        raise ProcError(denied)
    cmd = [str(a) for a in argv if str(a)]
    if not cmd:
        raise ProcError("bg requires argv after --", code=2)

    from pathlib import Path as _P

    cwd_path = _P(pol.cwd).expanduser().resolve() if pol.cwd else pol.workdir_root()
    from .policy import refuse_workspace

    locked = refuse_workspace(cwd_path, cmd)
    if locked:
        raise ProcError(locked)
    try:
        cwd_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    proc_id = "proc_" + uuid.uuid4().hex[:12]
    pdir = _procs_root() / proc_id
    pdir.mkdir(parents=True, exist_ok=True)
    out_f = pdir / "out.log"
    err_f = pdir / "err.log"
    in_f = pdir / "in.txt"
    exit_f = pdir / "exit.json"
    in_f.touch()

    env = pol.filtered_env()
    if sys.platform == "win32":
        inner = subprocess.list2cmdline(cmd)
        # Batch file, not cmd /c text: nested quoting in the command line is unsafe.
        # A bat expands %errorlevel% per line at run time, so the child's real code lands in exit.json.
        bat = pdir / "run.bat"
        bat.write_text(
            "@echo off\r\n"
            f'{inner} >"{out_f}" 2>"{err_f}" <"{in_f}"\r\n'
            f"echo %errorlevel% >\"{exit_f}\"\r\n",
            encoding="utf-8",
        )
        try:
            proc = subprocess.Popen(
                ["cmd.exe", "/c", str(bat)],
                cwd=str(cwd_path),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # CREATE_NO_WINDOW detaches without a console. DETACHED_PROCESS
                # would hand the child invalid std handles and bat redirects
                # would create empty log files.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )
        except OSError as exc:
            raise ProcError(str(exc))
        # exit.json holds the raw number on Windows; _read_exit_code normalizes.
    else:
        import shlex

        fifo = pdir / "stdin.fifo"
        try:
            os.mkfifo(fifo)
        except OSError as exc:
            raise ProcError(f"mkfifo failed: {exc}")
        cmd_q = " ".join(shlex.quote(a) for a in cmd)
        script = (
            f"tail -n +1 -f {shlex.quote(str(in_f))} >{shlex.quote(str(fifo))} & "
            f"feeder=$!; "
            f"{cmd_q} <{shlex.quote(str(fifo))} >{shlex.quote(str(out_f))} 2>{shlex.quote(str(err_f))}; "
            f"code=$?; "
            f"kill $feeder 2>/dev/null; "
            f"printf '%s' \"$code\" >{shlex.quote(str(exit_f))}"
        )
        try:
            proc = subprocess.Popen(
                ["sh", "-c", script],
                cwd=str(cwd_path),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            raise ProcError(str(exc))

    meta = {
        "id": proc_id,
        "argv": cmd,
        "pid": proc.pid,
        "cwd": str(cwd_path),
        "created": datetime.now(timezone.utc).isoformat(),
        "stdin": "file" if sys.platform == "win32" else "fifo",
    }
    _write_json(pdir / "meta.json", meta)
    return {"id": proc_id, "pid": proc.pid, "state": "running", "dir": str(pdir)}


def proc_list() -> dict[str, Any]:
    root = _procs_root()
    rows = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "meta.json").is_file():
                rows.append(_proc_state(child))
    return {"processes": rows}


def _load(proc_id: str) -> Path:
    pdir = _proc_dir(proc_id)
    if not (pdir / "meta.json").is_file():
        raise ProcError("unknown process id", code=2)
    return pdir


def proc_poll(proc_id: str) -> dict[str, Any]:
    return _proc_state(_load(proc_id))


def proc_log(proc_id: str, *, stream: str = "both", tail: int = 200) -> dict[str, Any]:
    pdir = _load(proc_id)
    out = {}
    if stream in ("out", "both"):
        out["stdout"] = _tail(pdir / "out.log", tail)
    if stream in ("err", "both"):
        out["stderr"] = _tail(pdir / "err.log", tail)
    out["state"] = _proc_state(pdir)["state"]
    return out


def _read_exit_code(pdir: Path) -> int | None:
    raw = (pdir / "exit.json")
    if not raw.is_file():
        return None
    try:
        text = raw.read_text(encoding="utf-8").strip()
        if text.startswith("{"):
            data = json.loads(text)
            code = data.get("code") if isinstance(data, dict) else data
            return int(code) if code is not None else None
        return int(text)
    except (OSError, ValueError, TypeError):
        return None


def proc_wait(proc_id: str, *, timeout_sec: float = 600) -> dict[str, Any]:
    pdir = _load(proc_id)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        state = _proc_state(pdir)
        if state["state"] == "exited" or (pdir / "exit.json").is_file():
            state["exit_code"] = _read_exit_code(pdir)
            state["stdout"] = _tail(pdir / "out.log", 200)
            state["stderr"] = _tail(pdir / "err.log", 200)
            return state
        time.sleep(0.5)
    state = _proc_state(pdir)
    state["timed_out"] = True
    return state


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def proc_kill(proc_id: str) -> dict[str, Any]:
    pdir = _load(proc_id)
    state = _proc_state(pdir)
    if state["state"] == "exited":
        return {"id": proc_id, "state": "exited", "exit_code": state.get("exit_code")}
    _kill_tree(int(state.get("pid") or 0))
    if not (pdir / "exit.json").is_file():
        _write_json(
            pdir / "exit.json",
            {"code": -9, "finished": datetime.now(timezone.utc).isoformat(), "killed": True},
        )
    return {"id": proc_id, "state": "exited", "exit_code": -9}


def proc_write(proc_id: str, data: str) -> dict[str, Any]:
    pdir = _load(proc_id)
    meta = _read_json(pdir / "meta.json")
    if meta.get("stdin") != "fifo":
        raise ProcError("proc write unsupported on this platform (spawned without stdin feeder)", code=2)
    if _proc_state(pdir)["state"] != "running":
        raise ProcError("process exited")
    with open(pdir / "in.txt", "a", encoding="utf-8") as fh:
        fh.write(data if data.endswith("\n") else data + "\n")
    return {"id": proc_id, "written": len(data)}


def format_proc(payload: dict[str, Any]) -> str:
    if "processes" in payload:
        rows = payload["processes"]
        if not rows:
            return "(no background processes)"
        lines = []
        for r in rows:
            code = "" if r["exit_code"] is None else f" exit={r['exit_code']}"
            lines.append(f"{r['id']}\t{r['state']}{code}\t{' '.join(r['argv'])}")
        return "\n".join(lines)
    parts = [f"{payload.get('id', '')} {payload.get('state', '')}"]
    if payload.get("exit_code") is not None:
        parts.append(f"exit={payload['exit_code']}")
    if payload.get("timed_out"):
        parts.append("(wait timed out, still running)")
    for key in ("stdout", "stderr"):
        if payload.get(key):
            parts.append(payload[key])
    if payload.get("written") is not None:
        parts.append(f"wrote {payload['written']} bytes")
    return "\n".join(p for p in parts if p)
