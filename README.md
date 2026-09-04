# agents-terminal

<p align="left">
  <a href="https://github.com/Lolaplex/agents-terminal/releases"><img src="https://img.shields.io/badge/version-0.0.2-blue.svg?style=flat-square" alt="Version 0.0.2"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-terminal/"><img src="https://img.shields.io/pypi/v/agents-terminal.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

**Policy-bound terminal for agent computer-use (`call_job mcp.terminal`).**  
Harness never shells directly; this package owns the execution jail and driver routing.

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
> The agent installs the package and routes terminal commands through `python -m agents_terminal`.

*Source checkouts can also be installed and managed using [vand](https://github.com/Lolaplex/vand).*

---

## Usage & Drivers

```bash
# JSON capability and policy discovery
python -m agents_terminal --help-json

# Jailed execution with default policy
python -m agents_terminal run -- echo hello
```

### Drivers

| Driver | When | Backend |
| :--- | :--- | :--- |
| `subprocess` | Windows stand-in, fallback | Env stripping, directory confinement, process tree timeout |
| `openshell` | Linux / Docker / OpenShell container | `openshell sandbox create` containerized supervisor |
| `auto` (default) | Picks `openshell` if available on PATH, otherwise falls back to `subprocess` |

Set `AGENTS_TERMINAL_DRIVER=openshell|subprocess|auto` to configure the driver.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
