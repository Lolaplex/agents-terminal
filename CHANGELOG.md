# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Lolaplex/agents-terminal/compare/v0.0.2...HEAD
[0.0.2]: https://github.com/Lolaplex/agents-terminal/releases/tag/v0.0.2
