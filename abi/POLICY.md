# Policy

Loaded from `AGENTS_TERMINAL_POLICY` (JSON file) when that path is a file. Otherwise from the environment, then defaults.

## Driver

`AGENTS_TERMINAL_DRIVER` is `auto` (default), `subprocess`, or `openshell`.

`auto`: `openshell` when `openshell_available()` is true, else `subprocess`. On Windows, availability includes `openshell` inside WSL.

Requesting `openshell` when the binary is missing is an error. It does not silently fall back.

## Environment

Default allowlist: `PATH`, `SYSTEMROOT`, `TEMP`, `TMP`, `WINDIR`, `HOME`, `USER`, `SHELL`, `LANG`, `LC_ALL`, `TERM`, `GITHUB_TOKEN`, `GH_TOKEN`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`.

`AGENTS_TERMINAL_ENV_ALLOW` (alias `AGENTS_TERMINAL_EXTRA_ENV`) appends comma-separated names.

A JSON policy `env_allow` array replaces the default list instead of appending.

`AGENTS_TERMINAL_ENV_PASSTHROUGH=1|true|yes` copies the full parent environment and skips the allowlist.

## Workspace and timeout

Working directory: policy `cwd` or `openshell_workspace`, else `AGENTS_WORKSPACE_DIR`, else `AGENTS_HOME/workspace`, else `~/.agents/workspace`. The directory is created if missing.

`timeout_sec` defaults to 60. On timeout the process tree is killed.
