# CLI

Installed command: `agents-terminal`. One subcommand.

- `agents-terminal run -- <argv…>` — execute that argv under the policy. The `--` is stripped. Missing argv exits 2. The process exit code is the child's exit code. Stdout is the driver's formatted result.

No subcommand prints help. It does not start a server.

`python -m agents_terminal --help-json` prints the machine catalog.
