# Changelog

All notable changes to this project will be documented in this file.

The format is intentionally simple for now.

## [Unreleased]

### Added

- direct-input session flow in the TUI, without a separate "press `i`" mode
- TUI-side UTF-8 process environment handling for managed Python sessions on Windows
- TUI render caching and output-windowing to reduce redraw and string rebuild cost

### Changed

- Local and Hybrid agents now recover tool calls when smaller models print them as JSON-like text inside Markdown fences
- Main README now links to the standalone Windows `.bat` and TUI split repositories
- Main repository no longer ships the legacy Windows `.bat` compatibility layer

## [0.1.0] - 2026-04-03

Initial public release.

### Added

- Local agent entry point in [`src/agent.py`](src/agent.py)
- Hybrid agent entry point in [`src/hybrid/agent.py`](src/hybrid/agent.py)
- Shared tool runtime and workspace safety guards
- Prompt templating and shared prompting helpers
- Compiled Rust TUI launcher in [`tui/`](tui/)
- Local model management in the TUI for Ollama-compatible local backends
- Benchmark helper workflow in [`scripts/run_benchmark.py`](scripts/run_benchmark.py)
- Unit tests and CI workflow for Python paths

### Changed

- Documentation now treats `src/agent.py`, `src/hybrid/agent.py`, and `tui/` as canonical entry points
- `--mega` naming remains only as a compatibility alias; `Hybrid` is the canonical name
- Security guardrails now block additional clearly destructive command patterns

### Known Limits

- Safety is application-level only, not OS isolation
- Hybrid remains more experimental than Local
- The TUI is a launcher and session manager, not a full terminal multiplexer
- Benchmark documentation is present, but no official benchmark results are published in this release
