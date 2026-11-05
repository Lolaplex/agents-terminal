# agents-terminal ABI

Version: see [`VERSION`](VERSION).

Policy-bound process execution for coding agents. No MCP server. The Python package in this repository is the reference implementation.

| Doc | Contract |
| --- | --- |
| [`WHY.md`](WHY.md) | argv, allowlisted env, no shell string |
| [`POLICY.md`](POLICY.md) | drivers, env, workspace, timeout |
| [`CLI.md`](CLI.md) | `list`, `read`, `grep`, `stat`, `run` |
| [`METADATA.md`](METADATA.md) | per-command `side_effects` (`read-only` or `mutating`) |

Machine-readable command list: `python -m agents_terminal --help-json`.
