"""Select subprocess stand-in vs OpenShell driver."""

from __future__ import annotations

from .driver import RunResult, run_argv
from .openshell_driver import openshell_available, run_openshell
from .policy import Policy


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
    if driver == "openshell":
        if not openshell_available():
            msg = "openshell driver requested but openshell is not installed"
            return RunResult(argv=list(argv), returncode=127, stdout="", stderr=msg, denied=msg)
        return run_openshell(argv, policy=pol, read=read, write=write, net=net)
    return run_argv(argv, policy=pol, read=read, write=write, net=net)
