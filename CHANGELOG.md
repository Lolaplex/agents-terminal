# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- The workspace boundary is its own switch. `AGENTS_WORKSPACE_DIR` only names the working directory; `AGENTS_WORKSPACE_LOCK=1|true|yes|on` confines `run` and every path to it. A host that sets a working directory is no longer confined by accident.
- `AGENTS_WORKSPACE_ALLOW` adds allowed roots, separated by the OS path separator.

## [0.0.6] - 2026-11-08

### Added
- Read-only commands `list`, `read`, `grep` (`search`), and `stat`. They observe the workspace root and cannot create, modify, delete, or spawn a process. `read` accepts `--offset` (1-based line) and `--limit`.
- `write PATH [--stdin | --content TEXT] [--create-only] [--json]`. Writes UTF-8 text inside the workspace root, creates missing parent directories inside the root, and writes atomically with `os.replace`. An existing file keeps its line endings; a new file uses LF. A symlink, directory, or binary target is refused.
- `edit PATH --old TEXT --new TEXT [--replace-all] [--stdin-json] [--json]`. Exact string replacement with no regex. `--old` must match exactly once unless `--replace-all`; failures leave the file unchanged. An exact match on the file's own bytes wins, so a file with mixed line endings keeps every byte it had; only when that finds nothing does matching fall back to line-ending tolerance. `--stdin-json` reads `{"old", "new"}` from stdin for multi-line edits without shell quoting. Text output is a unified diff plus a summary line.
- `--help-json` declares per-command side effects. Canonical field `commands.<name>.side_effects` is `read-only` or `mutating`. `mutates` and MCP `annotations.readOnlyHint` mirror that fact. `run`, `write`, and `edit` are `mutating`. Missing `side_effects` metadata means mutating. See `abi/METADATA.md`.

### Security
- A set workspace refuses tool paths and working directories outside that root. Skills, modules, memory, traces, schedules, and the agent home stay reachable. An unset or blank workspace leaves commands unchanged.
- Without `O_NOFOLLOW` or `dir_fd`, read-only commands fail closed: the real path must stay inside the root, and symlinks, junctions, and reparse points are rejected before an open. `stat` uses that same confinement. `write` and `edit` reuse it.

## [0.0.5] - 2026-10-06

### Added
- CLI (and MCP, when present) check PyPI at most once per day for a newer release and print one stderr / tool-response line (`uv tool upgrade …`). Disabled with `AGENTS_NO_UPDATE_CHECK=1` or when `CI` is set; offline/timeout stays silent.

## [0.0.4] - 2026-09-26

### Added
- ABI contract in `abi/` for policy, drivers, and the `run` command.

### Changed
- README documents the single `run` command, driver selection, and env allowlist including `AGENTS_TERMINAL_EXTRA_ENV` and `AGENTS_TERMINAL_ENV_PASSTHROUGH`.

## [0.0.3] - 2026-09-26

### Changed
- CI runs only on pull requests to `main`.
- Refined README with full benchmark specification (architecture diagram, security rationale, environment configuration table, and testing instructions).

### Added
- Forward `GITHUB_TOKEN`, `GH_TOKEN`, and git author env vars by default in terminal policy.
- Support `AGENTS_TERMINAL_ENV_ALLOW`, `AGENTS_TERMINAL_EXTRA_ENV`, and `AGENTS_TERMINAL_ENV_PASSTHROUGH` for extra environment forwarding.
- Default execution CWD to resolved `workspace_dir()` (`AGENTS_WORKSPACE_DIR` or `~/.agents/workspace`) with automatic directory creation.

### Removed
- GitHub Release is no longer cut automatically on `v*.*.*` tags (manual `gh release create` from CHANGELOG instead).

## [0.0.2] - 2026-09-05

### Added
- Policy-bound sandbox CLI for coding agents.
- Dual drivers: `subprocess` fallback and `openshell` container isolation.
- Structured JSON API (`--help-json`) and Cordis `call_job mcp.terminal`.

[Unreleased]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.6...HEAD
[0.0.6]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/Lolaplex/agents-terminal/releases/tag/v0.0.2
