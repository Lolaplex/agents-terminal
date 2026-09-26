<p align="center">
  <a href="https://github.com/Lolaplex/agents-terminal/releases"><img src="https://img.shields.io/badge/version-0.0.3-blue.svg?style=flat-square" alt="Version 0.0.3"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/agents-terminal/"><img src="https://img.shields.io/pypi/v/agents-terminal.svg?style=flat-square" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License"></a>
</p>

<p align="center">
  <strong>Policy-bound jailed terminal for agent execution.</strong><br>
  argv in, stripped env out. No MCP server.
</p>

## Quickstart

```bash
pip install agents-terminal
```

There is no `init`. The harness calls `agents-terminal run`. Nothing is written into IDE configs.

> [!TIP]
> **🤖 Agent-Driven Setup:**
> Give your coding agent **this repo** (clone or URL), then tell it to **"install agents-terminal and run commands through it."**

Source checkouts can also be installed and managed with [vand](https://github.com/Lolaplex/vand).

---

## What it does

Agents do not get a shell string. `run` takes an argv vector after `--`, so the host shell never parses the command.

The child inherits an allowlist, not the parent environment. Default names: `PATH`, `HOME`, `USER`, `SHELL`, `TEMP` / `TMP`, locale (`LANG`, `LC_ALL`, `TERM`), Windows roots (`SYSTEMROOT`, `WINDIR`), git author/committer, `GITHUB_TOKEN`, `GH_TOKEN`. Anything else is dropped unless you extend the list.

On timeout the process tree is killed (job object / process group). Working directory defaults to `AGENTS_WORKSPACE_DIR` or `~/.agents/workspace`, created if missing.

---

## Drivers

| Driver | When | Backend |
| :--- | :--- | :--- |
| `subprocess` | Windows / macOS stand-in, and the fallback | Allowlisted env, directory confinement, process-tree timeout |
| `openshell` | Linux / Docker / OpenShell on `PATH` | `openshell sandbox create` |
| `auto` (default) | Starting point | `openshell` when that binary is on `PATH` (or inside WSL on Windows), else `subprocess` |

Set `AGENTS_TERMINAL_DRIVER=openshell|subprocess|auto`.

---

## Environment

| Variable | Description |
| :--- | :--- |
| `AGENTS_TERMINAL_DRIVER` | `auto` (default), `subprocess`, or `openshell` |
| `AGENTS_WORKSPACE_DIR` | Working directory (default `~/.agents/workspace`) |
| `AGENTS_TERMINAL_POLICY` | Path to a JSON policy file (`driver`, `env_allow`, `timeout_sec`, `cwd`, …) |
| `AGENTS_TERMINAL_ENV_ALLOW` | Extra names, comma-separated, appended to the default allowlist. Alias: `AGENTS_TERMINAL_EXTRA_ENV` |
| `AGENTS_TERMINAL_ENV_PASSTHROUGH` | `1` / `true` / `yes` copies the full parent environment and skips the allowlist |

---

## CLI

One command. No MCP. Machine-readable catalog: `python -m agents_terminal --help-json`.

| Command | Purpose |
| --- | --- |
| `agents-terminal run -- <argv…>` | Run that argv under the policy. No shell |

No subcommand prints help. Exit code is the child's exit code.

```bash
agents-terminal run -- echo hello
```

---

## Tests

```bash
python -m unittest discover -s tests -v
```

---

## License

MIT. See [LICENSE](LICENSE).
