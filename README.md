# agents-terminal

<p align="left">
  <a href="https://github.com/Lolaplex/agents-terminal/releases"><img src="https://img.shields.io/badge/version-0.0.3-blue.svg?style=flat-square" alt="Version 0.0.3"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-terminal/"><img src="https://img.shields.io/pypi/v/agents-terminal.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

**Policy-bound jailed terminal CLI for agent execution (`call_job mcp.terminal`).**  
Harness never shells directly; this package owns the execution jail, driver routing, and environment sanitization.

---

## Quickstart

### 1-Step Setup

```bash
pip install agents-terminal
```

### 2. Agent-Driven Setup (Zero Friction)

> [!TIP]
> **🤖 Agent-Driven Setup (Zero Friction):**  
> Simply tell your coding agent: **"Install and use agents-terminal for jailed shell execution."**  
> The agent installs the package and routes terminal execution through `python -m agents_terminal`.

*Source checkouts can also be installed and managed using [vand](https://github.com/Lolaplex/vand).*

---

## Why `agents-terminal`?

Letting autonomous coding agents execute arbitrary shell commands directly on host machines creates severe risks: leaked environment secrets (API keys, SSH credentials), orphan background processes, and uncontained filesystem modifications.

**`agents-terminal` applies the Lolaplex philosophy:**
- **Zero Shell Injection**: Commands are passed as strict argument vectors (`argv`), completely bypassing shell interpreter parsing vulnerabilities (`bash -c`, `sh -c`, `powershell.exe -Command`).
- **Strict Environment Stripping**: Only an explicit, minimal allowlist of standard environment variables (`PATH`, `TEMP`, `HOME`, safe Git/GitHub author tokens) is inherited. Sensitive host secrets are stripped before execution.
- **Process Tree Cleanup**: Subprocess execution uses OS job objects / process group killing to ensure descendant processes are terminated on timeout.
- **Pluggable Drivers**: Seamlessly switches between a portable local `subprocess` jail and an isolated `openshell` container sandbox.

---

## Architecture & Flow

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                     CODING AGENT / IDE                      │
 │       agents-harness · Claude Code · Custom Agents          │
 └──────────────────────────────┬──────────────────────────────┘
                                │  argv vector (no raw shell string)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │                      AGENTS-TERMINAL                        │
 │    Policy Enforcement · Env Stripper · Timeout Supervisor   │
 └──────────────┬───────────────────────────────┬──────────────┘
                │                               │
                ▼ (auto / configured)           ▼
 ┌─────────────────────────────┐ ┌─────────────────────────────┐
 │      SUBPROCESS DRIVER      │ │      OPENSHELL DRIVER       │
 │   OS Job Object / Timeout   │ │   Containerized Supervisor  │
 │   Stripped Host Environment │ │   Jailed Linux / Docker     │
 └─────────────────────────────┘ └─────────────────────────────┘
```

---

## Usage & Drivers

Machine catalog: `python -m agents_terminal --help-json`

```bash
# Jailed execution with default policy
agents-terminal run -- echo hello
```

### Drivers

| Driver | When | Backend |
| :--- | :--- | :--- |
| `subprocess` | Windows / macOS stand-in, fallback | Environment stripping, directory confinement, process tree timeout |
| `openshell` | Linux / Docker / OpenShell container | `openshell sandbox create` containerized supervisor |
| `auto` (default) | Picks `openshell` if available on PATH, otherwise falls back to `subprocess` |

Set `AGENTS_TERMINAL_DRIVER=openshell|subprocess|auto` to configure the active driver.

---

## Environment & Policy Configuration

| Variable | Description |
| :--- | :--- |
| `AGENTS_TERMINAL_DRIVER` | `auto` (default), `subprocess`, or `openshell` |
| `AGENTS_WORKSPACE_DIR` | Working directory for commands (default: `~/.agents/workspace`) |
| `AGENTS_TERMINAL_POLICY` | Path to a custom JSON policy configuration file |
| `AGENTS_TERMINAL_ENV_ALLOW` | Comma-separated list of additional environment variables to pass through |

---

## Testing & Verification

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
