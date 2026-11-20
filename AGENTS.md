# agents-terminal

Jailed terminal CLI catalogued as `mcp.terminal` in agents-harness.

## Drivers

| Driver | When | Backend |
| --- | --- | --- |
| `subprocess` | Windows stand-in, no OpenShell | env strip, cwd, timeout, Job Object kill-tree |
| `openshell` | Linux + Docker/Podman | `openshell sandbox create --no-keep` (supervisor in container) |
| `ssh` | remote host via ssh | `ssh -o BatchMode=yes`, quoted argv line, optional remote workdir |
| `auto` (default) | picks `openshell` if `openshell` on PATH | otherwise subprocess |

Set `AGENTS_TERMINAL_DRIVER=openshell|subprocess|ssh|auto` or policy JSON `"driver": "openshell"`.

`ssh` config: `AGENTS_TERMINAL_SSH_HOST` (required), `AGENTS_TERMINAL_SSH_USER`, `AGENTS_TERMINAL_SSH_KEY`, `AGENTS_TERMINAL_SSH_PORT`, `AGENTS_TERMINAL_SSH_DIR` (remote workdir). `auto` never picks ssh. `bg` refuses on ssh (detached remote procs unsupported).

## OpenShell install (sandbox / Docker)

Cache-local install (no system `dpkg`, no `~/.agents`):

```bash
export AGENTS_OPENSHELL_DIR=/path/to/.cache/sandbox/openshell
bash scripts/install-openshell.sh
bash scripts/start-openshell-gateway.sh
```

Windows dev: run via WSL (`agents-sandbox/install-openshell.ps1`). Full supervisor sandboxes are validated on native Linux; WSL+Docker Desktop may fail supervisor relay provisioning.

Future NAS/Docker image:

```dockerfile
RUN curl -fsSL .../install-openshell.sh | AGENTS_OPENSHELL_DIR=/opt/openshell bash
ENV AGENTS_TERMINAL_DRIVER=openshell
ENV AGENTS_OPENSHELL_DIR=/opt/openshell
```

`source.yml` keeps Python install only; OpenShell is an optional post-step via the scripts above (vand `sync-hooks` can add machine overlay commands later).

## Read-only commands

`list`, `read`, `grep` (`search`), and `stat` only observe the workspace root. They do not spawn a shell. `write` and `edit` change files inside the root and are mutating; `run` executes argv and is mutating.

`python -m agents_terminal --help-json` sets `side_effects` to `read-only` or `mutating` on every command. Contract: `abi/METADATA.md`.
