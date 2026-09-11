# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Forward `GITHUB_TOKEN`, `GH_TOKEN`, and git author env vars by default in terminal policy.
- Support `AGENTS_TERMINAL_ENV_ALLOW`, `AGENTS_TERMINAL_EXTRA_ENV`, and `AGENTS_TERMINAL_ENV_PASSTHROUGH` for flexible environment forwarding.

## [0.0.2] - 2026-09-05

### Added
- Initial release of `agents-terminal` CLI and policy-bound sandbox execution for coding agents.
- Dual driver support: `subprocess` fallback and `openshell` container isolation.
- Structured JSON API (`--help-json`) and Cordis `call_job mcp.terminal` integration.
