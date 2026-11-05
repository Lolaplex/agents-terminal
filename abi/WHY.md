# Why agents-terminal exists

Version: see [`VERSION`](VERSION).

An agent that receives a shell string can expand variables, chain commands, and read the parent environment. This package does not start a shell. The caller passes an argv vector. The child sees an allowlist, not the host secret set.

Isolation is a driver choice. `subprocess` is the portable jail (env strip, workspace directory, process-tree kill on timeout). `openshell` is the container jail when that binary is available. `auto` picks `openshell` when it is on `PATH`, or reachable through WSL on Windows, otherwise `subprocess`.

There is no MCP server. A long-running server would hold the policy next to every other tool. Call `agents-terminal run` as a subprocess.

Reads do not need that subprocess. `list`, `read`, `grep`, and `stat` only observe the workspace root, and `--help-json` marks each command `read-only` or `mutating` so a harness can tell them apart without guessing from the command name.
