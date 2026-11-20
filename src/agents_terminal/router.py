"""Select subprocess stand-in vs OpenShell driver."""

from __future__ import annotations

from .driver import RunResult, run_argv
from .openshell_driver import openshell_available, run_openshell
from .policy import Policy
from .proc import ProcError, bg_spawn, strip_bg_marker


def run_command(
    argv: list[str],
    *,
    policy: Policy | None = None,
    read: bool = False,
    write: bool = False,
    net: bool = False,
) -> RunResult:
    pol = policy or Policy.load()
    driver = pol.driver
    if driver == "auto":
        driver = "openshell" if openshell_available() else "subprocess"
    cmd = [str(x) for x in argv]
    marked = strip_bg_marker(cmd)
    if marked is not None:
        try:
            spawned = bg_spawn(marked, policy=pol)
        except ProcError as exc:
            return RunResult(argv=cmd, returncode=exc.code, stdout="", stderr=exc.message, denied=exc.message)
        return RunResult(
            argv=cmd,
            returncode=0,
            stdout=f"auto_backgrounded {spawned['id']} (manage with 'proc')",
            stderr="",
        )
    if driver == "openshell":
        if not openshell_available():
            msg = "openshell driver requested but openshell is not installed"
            return RunResult(argv=list(argv), returncode=127, stdout="", stderr=msg, denied=msg)
        return run_openshell(argv, policy=pol, read=read, write=write, net=net)
    return run_argv(argv, policy=pol, read=read, write=write, net=net)
