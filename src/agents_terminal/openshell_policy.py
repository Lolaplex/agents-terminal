"""Map agents-terminal Policy to OpenShell sandbox policy YAML."""

from __future__ import annotations

from pathlib import Path

from .policy import Policy


def _yaml_list(items: list[str], indent: int = 2) -> str:
    pad = " " * indent
    if not items:
        return "[]"
    return "\n".join(f"{pad}- {item}" for item in items)


def policy_to_openshell_yaml(policy: Policy, *, workspace: str | Path) -> str:
    """Build minimal OpenShell policy v1 from our policy flags (stdlib, no PyYAML)."""
    work = str(Path(workspace).resolve()).replace("\\", "/")
    read_only = ["/usr", "/lib", "/lib64", "/bin", "/sbin", "/etc"]
    read_write = ["/tmp", "/sandbox"]
    if policy.read and work not in read_only:
        read_only.append(work)
    if policy.write and work not in read_write:
        read_write.append(work)
    lines = [
        "version: 1",
        "filesystem_policy:",
        "  include_workdir: true",
        "  read_only:",
        *_yaml_list(read_only, 4).splitlines(),
        "  read_write:",
        *_yaml_list(read_write, 4).splitlines(),
    ]
    if not policy.net:
        lines.append("network_policies: {}")
    return "\n".join(lines) + "\n"


def write_policy_file(policy: Policy, *, workspace: str | Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(policy_to_openshell_yaml(policy, workspace=workspace), encoding="utf-8")
    return dest
