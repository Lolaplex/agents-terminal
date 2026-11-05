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

## Read-only root

`list`, `read`, `grep` / `search`, and `stat` use `work_root()` and do not create it. That path is policy `cwd` when set, otherwise the workspace directory below. They do not go through the subprocess or OpenShell driver. Path rules are in [`CLI.md`](CLI.md). `run` is unchanged and remains the mutating command.

## Workspace and timeout

Working directory for `run`: policy `cwd` or `openshell_workspace`, else `AGENTS_WORKSPACE_DIR`, else `AGENTS_HOME/workspace`, else `~/.agents/workspace`. `run` creates that directory if it is missing. Read-only commands use the same path and do not create it.

`timeout_sec` defaults to 60. On timeout the process tree is killed.
