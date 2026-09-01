"""Subprocess driver under terminal policy."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Sequence

from .policy import Policy


@dataclass
class RunResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    denied: str | None = None


def format_result(result: RunResult) -> str:
    """Human-oriented stdout for CLI / tool output."""
    if result.denied:
        return result.denied
    parts: list[str] = []
    if result.stdout:
        parts.append(result.stdout.rstrip("\n"))
    if result.stderr:
        parts.append(result.stderr.rstrip("\n"))
    if result.timed_out:
        parts.append(f"(timed out after policy limit, exit {result.returncode})")
    elif result.returncode != 0 and not parts:
        parts.append(f"(exit {result.returncode})")
    return "\n".join(parts) if parts else ""


def _win_job_handle():
    if sys.platform != "win32":
        return None, None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, None

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel32.CloseHandle(job)
        return None, None
    return kernel32, job


def _assign_pid_to_job(kernel32, job, pid: int) -> None:
    if not kernel32 or not job:
        return
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if handle:
        kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)


def _terminate_job(kernel32, job) -> None:
    if kernel32 and job:
        kernel32.TerminateJobObject(job, 1)
        kernel32.CloseHandle(job)


def run_argv(
    argv: Sequence[str],
    *,
    policy: Policy | None = None,
    read: bool = False,
    write: bool = False,
    net: bool = False,
) -> RunResult:
    """Run argv without shell. Enforce policy cwd/env/timeout."""
    pol = policy or Policy.load()
    cmd = [str(x) for x in argv]
    if not cmd:
        return RunResult(argv=[], returncode=2, stdout="", stderr="empty argv", denied="empty argv")

    denied = pol.check_request(read=read, write=write, net=net)
    if denied:
        return RunResult(argv=cmd, returncode=1, stdout="", stderr=denied, denied=denied)

    env = pol.filtered_env()
    cwd = pol.cwd or os.getcwd()
    kernel32, job = _win_job_handle()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        return RunResult(argv=cmd, returncode=127, stdout="", stderr=str(exc))

    _assign_pid_to_job(kernel32, job, proc.pid)
    try:
        stdout_b, stderr_b = proc.communicate(timeout=pol.timeout_sec)
        return RunResult(
            argv=cmd,
            returncode=int(proc.returncode or 0),
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
        )
    except subprocess.TimeoutExpired:
        if sys.platform == "win32" and kernel32 and job:
            _terminate_job(kernel32, job)
        else:
            proc.kill()
        try:
            stdout_b, stderr_b = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout_b, stderr_b = b"", b""
        return RunResult(
            argv=cmd,
            returncode=124,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            timed_out=True,
        )
