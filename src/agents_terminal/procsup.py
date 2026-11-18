"""Background-process supervisor: runs one proc, feeds stdin, records exit.

Spawned detached by ``proc.bg_spawn`` as ``python -m agents_terminal.procsup
<id>``. Reads ``meta.json`` (argv, cwd) from the proc dir, execs argv with
``shell=False`` (no batch file, no shell metachars), forwards bytes appended to
``in.txt`` into the child stdin, and writes ``exit.json`` when the child ends.

The supervisor records ``child_pid`` in ``meta.json`` so ``proc kill`` and
``proc poll`` can still reach the real process when the supervisor itself was
reaped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def _procs_root() -> Path:
    raw = os.environ.get("AGENTS_TERMINAL_PROCS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    from agents_workspace import Workspace

    return Workspace.from_env().dir / "procs"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _feed_stdin(in_path: Path, stream, stop: threading.Event) -> None:
    """Append in.txt bytes to the child stdin until it closes or we stop."""
    offset = 0
    while not stop.is_set():
        try:
            size = in_path.stat().st_size
        except OSError:
            size = 0
        if size < offset:
            offset = 0  # file was replaced/truncated
        if size > offset:
            try:
                with open(in_path, "rb") as fh:
                    fh.seek(offset)
                    chunk = fh.read(size - offset)
                offset = size
                if chunk:
                    stream.write(chunk)
                    stream.flush()
            except (OSError, ValueError, BrokenPipeError):
                return
        stop.wait(0.2)


def supervise(proc_id: str) -> int:
    pdir = _procs_root() / proc_id
    meta = _read_json(pdir / "meta.json")
    argv = [str(a) for a in meta.get("argv") or [] if str(a)]
    cwd = str(meta.get("cwd") or "") or None
    if not argv:
        _write_json(pdir / "exit.json", {"code": 2, "finished": _now(), "error": "empty argv"})
        return 2

    out_f = pdir / "out.log"
    err_f = pdir / "err.log"
    in_f = pdir / "in.txt"
    in_f.touch(exist_ok=True)
    # KILL_ON_JOB_CLOSE: when the supervisor dies — taskkill, crash, whatever —
    # the job's last handle closes and the kernel kills the child. No orphan
    # window between Popen and the child_pid write below.
    from .driver import _assign_pid_to_job, _win_job_handle

    kernel32, job = _win_job_handle()
    try:
        with open(out_f, "ab") as out, open(err_f, "ab") as err:
            try:
                child = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdin=subprocess.PIPE,
                    stdout=out,
                    stderr=err,
                    shell=False,
                )
            except OSError as exc:
                _write_json(
                    pdir / "exit.json",
                    {"code": 127, "finished": _now(), "error": str(exc)},
                )
                return 127
            _assign_pid_to_job(kernel32, job, child.pid)
            meta["child_pid"] = child.pid
            _write_json(pdir / "meta.json", meta)

            stop = threading.Event()
            feeder = threading.Thread(
                target=_feed_stdin, args=(in_f, child.stdin, stop), daemon=True
            )
            feeder.start()
            code = int(child.wait())
            stop.set()
        _write_json(
            pdir / "exit.json",
            {"code": code, "finished": _now()},
        )
        return code
    finally:
        if kernel32 and job:
            kernel32.CloseHandle(job)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("procsup requires a proc id", file=sys.stderr)
        return 2
    return supervise(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
