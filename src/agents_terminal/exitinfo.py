"""Human explanations for signal-style exit codes.

POSIX ``Popen.returncode`` reports ``-N`` for signal N; shells report
``128 + N``. Windows NTSTATUS failures arrive as large unsigned codes that
Python shows as negative int32. ``explain_exit`` maps both to one line of
human text; ordinary exit codes return ``None``.
"""

from __future__ import annotations

_SIGNALS = {
    1: ("SIGHUP", "terminal hangup"),
    2: ("SIGINT", "interrupted (Ctrl+C)"),
    3: ("SIGQUIT", "quit"),
    4: ("SIGILL", "illegal instruction"),
    5: ("SIGTRAP", "debug/breakpoint trap"),
    6: ("SIGABRT", "aborted"),
    7: ("SIGBUS", "bus error"),
    8: ("SIGFPE", "arithmetic fault (e.g. division by zero)"),
    9: ("SIGKILL", "killed; likely OOM kill or external kill"),
    10: ("SIGUSR1", "user signal 1"),
    11: ("SIGSEGV", "segmentation fault"),
    12: ("SIGUSR2", "user signal 2"),
    13: ("SIGPIPE", "wrote to a closed pipe"),
    14: ("SIGALRM", "alarm clock"),
    15: ("SIGTERM", "terminated"),
    16: ("SIGSTKFLT", "stack fault"),
    17: ("SIGCHLD", "child stopped or exited"),
    19: ("SIGSTOP", "stopped"),
    24: ("SIGXCPU", "CPU time limit exceeded"),
    25: ("SIGXFSZ", "file size limit exceeded"),
    26: ("SIGVTALRM", "virtual timer"),
    27: ("SIGPROF", "profiling timer"),
    29: ("SIGIO", "I/O possible"),
    30: ("SIGPWR", "power fail"),
    31: ("SIGSYS", "bad system call"),
}

_NTSTATUS = {
    0xC0000005: ("STATUS_ACCESS_VIOLATION", "memory access violation"),
    0xC00000FD: ("STATUS_STACK_OVERFLOW", "stack overflow"),
    0xC0000017: ("STATUS_NO_MEMORY", "out of memory"),
    0xC000013A: ("STATUS_CONTROL_C_EXIT", "Ctrl+C exit"),
    0xC0000142: ("STATUS_DLL_INIT_FAILED", "DLL initialization failed"),
    0xC0000409: ("STATUS_STACK_BUFFER_OVERRUN", "fail-fast / stack buffer overrun"),
    0xC000070A: ("STATUS_DLL_INIT_FAILED_LOGOFF", "DLL init failed during logoff"),
    0xC0000143: ("STATUS_MISSING_SYSTEMFILE", "missing system file"),
    0xE0434352: ("CLR_EXCEPTION", "unhandled .NET exception"),
}


def explain_exit(code: int | None) -> str | None:
    """Return ``"SIGKILL: killed; likely OOM kill"`` style text, or ``None``."""
    if code is None:
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if c < 0:
        sig = -c
        if sig > 64:
            unsigned = c & 0xFFFFFFFF
            hit = _NTSTATUS.get(unsigned)
            if hit:
                return f"{hit[0]}: {hit[1]}"
            return f"NTSTATUS 0x{unsigned:08X}"
    elif 129 <= c <= 192:
        sig = c - 128
    else:
        return None
    hit = _SIGNALS.get(sig)
    if not hit:
        return f"signal {sig}"
    return f"{hit[0]}: {hit[1]}"
