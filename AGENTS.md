# agents-terminal

Jailed terminal CLI catalogued as `mcp.terminal` in agents-harness.

## Drivers

| Driver | When | Backend |
| --- | --- | --- |
| `subprocess` | Windows stand-in, no OpenShell | env strip, cwd, timeout, Job Object kill-tree |
| `openshell` | Linux + Docker/Podman | `openshell sandbox create --no-keep` (supervisor in container) |
| `auto` (default) | picks `openshell` if `openshell` on PATH | otherwise subprocess |

Set `AGENTS_TERMINAL_DRIVER=openshell|subprocess|auto` or policy JSON `"driver": "openshell"`.

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
