# Release Notes

## v0.1.0

`v0.1.0` is the first serious public cut of Ollama Agent as a terminal-first
coding tool.

What is included:

- Local and Hybrid Python agent entry points
- Shared file, shell, and prompt runtime
- Rust TUI launcher for terminal-based session management
- Local model management from the TUI when the backend supports Ollama's native API
- Basic test coverage and CI for the Python codebase
- Documentation for security model, benchmark workflow, and launch paths

What is not claimed in this release:

- stable API guarantees
- hardened sandboxing
- published benchmark wins
- complete feature parity between every local backend
- mature cross-platform polish in every interactive path

Recommended release posture:

- use Local for the smallest and clearest setup
- treat Hybrid as useful but more experimental
- treat the TUI as supported for launch and session management, while keeping the Python core as the source of truth
- treat legacy `.bat` launchers as compatibility and quick-launch paths, not as the canonical product surface
