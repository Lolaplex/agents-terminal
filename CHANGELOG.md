# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.5...HEAD
[0.0.5]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/Lolaplex/agents-terminal/releases/tag/v0.0.2
