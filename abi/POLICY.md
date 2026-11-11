# Policy

Loaded from `AGENTS_TERMINAL_POLICY` (JSON file) when that path is a file. Otherwise from the environment, then defaults.

Configuration rule: one variable carries one decision. A value never implies enforcement; enforcement has its own switch, and restrictive switches default to off. Booleans accept `1`/`true`/`yes`/`on`; lists use the OS path separator.

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

`list`, `read`, `grep` / `search`, and `stat` use `work_root()` and do not create it. That path is policy `cwd` when set, otherwise the workspace directory below. They do not go through the subprocess or OpenShell driver. Path rules are in [`CLI.md`](CLI.md). `write` and `edit` use the same root and confinement and are mutating. `run` is unchanged and remains mutating.

## Workspace and timeout

Working directory for `run`: policy `cwd` or `openshell_workspace`, else `AGENTS_WORKDIR`, else the workspace workdir (`<ws>/work`). `run` creates that directory if it is missing. Read-only commands use the same path and do not create it.

## Workspace lock

`AGENTS_WORKDIR` only names the working directory. The boundary is a separate decision: `AGENTS_WORKDIR_LOCK=1|true|yes|on` confines `run` and every path to that root. Unset, blank, or any other value leaves the lock off, so a host that sets a working directory is never confined by accident.

When the lock is on and `AGENTS_WORKDIR` is unset, the root is the default workdir above. `AGENTS_WORKDIR_ALLOW` adds roots, separated by the OS path separator. The host dir (`AGENTS_HOST_DIR`), skills, modules, memory, traces, schedules, and routine runs stay reachable. (`AGENTS_WORKSPACE_DIR`/`AGENTS_WORKSPACE_LOCK`/`AGENTS_WORKSPACE_ALLOW`/`AGENTS_HOME` are deprecated aliases for one release.)

`timeout_sec` defaults to 60. On timeout the process tree is killed.
