# Ollama Agent

Terminal-first coding agent for OpenAI-compatible backends.

Current release: `v0.1.0` ([`VERSION`](VERSION))

This repository is the combined source tree.

Standalone split repositories:

- Windows legacy `.bat` repo: `https://github.com/DariodelBarrio/ollama-agent-windows-bat`
- TUI launcher repo: `https://github.com/DariodelBarrio/ollama-agent-tui`

Ollama Agent is a local-first CLI that can inspect a repository, read and edit
files, run shell commands inside the workspace, and answer in a concise
terminal workflow. The product currently has two Python execution variants
behind one shared runtime:

- **Local**: [`src/agent.py`](src/agent.py)
- **Hybrid**: [`src/hybrid/agent.py`](src/hybrid/agent.py)

![Tests](https://github.com/DariodelBarrio/ollama-agent/actions/workflows/tests.yml/badge.svg) ![Python](https://img.shields.io/badge/Python-3.9+-blue) ![OpenAI API](https://img.shields.io/badge/OpenAI--compatible-API-green) ![License](https://img.shields.io/badge/license-MIT-blue)

## What It Does

The agent is designed for terminal-based coding tasks in a local repository:

- inspect code and documentation
- edit files inside the workspace
- run shell commands with application-level safety guards
- use web search and URL fetch when enabled
- keep an interactive coding loop with tool calls and streamed output

It is not a hosted service, not a web GUI, and not a hardened sandbox.

## Variants

| Variant | Entry point | Intended use | Notes |
|---|---|---|---|
| Local | [`src/agent.py`](src/agent.py) | Pure local workflow against an OpenAI-compatible backend such as Ollama | Smallest setup, no Groq dependency |
| Hybrid | [`src/hybrid/agent.py`](src/hybrid/agent.py) | Local workflow plus optional Groq routing, critic mode, AST scan, and persistent memory | More capable, but also more experimental |

### Local vs Hybrid

| Capability | Local | Hybrid |
|---|---|---|
| Local OpenAI-compatible backend | Yes | Yes |
| Optional Groq backend | No | Yes |
| Modes | `code`, `architect`, `research` | Same plus routing, critic workflow, and memory commands |
| Persistent memory | No | Yes |
| AST scan | No | Yes |
| Extra dependencies | `requirements.txt` | `requirements-hybrid.txt` |

## Installation

Choose one of these install paths:

- Local core: `python scripts/install.py`
- Hybrid core: `python scripts/install.py --hybrid`
- TUI launcher: build [`tui/`](tui/) with `cargo build --release`

Prerequisites:

- Python 3.9+
- A local OpenAI-compatible backend such as Ollama for Local and Hybrid local mode
- `GROQ_API_KEY` only when Hybrid routes to Groq
- Rust toolchain only if you want the compiled TUI launcher

Dependency files:

- [`requirements.txt`](requirements.txt): canonical base dependencies
- [`requirements-hybrid.txt`](requirements-hybrid.txt): canonical Hybrid dependencies

Compatibility aliases still exist for older setups, but they are not part of
the canonical product story in this repo.

## Quick Start

Prerequisites:

- Python 3.9+
- [Ollama](https://ollama.com) running locally, or another OpenAI-compatible backend

### Local

```bash
git clone https://github.com/DariodelBarrio/ollama-agent.git
cd ollama-agent
python scripts/install.py
ollama pull qwen2.5-coder:7b
python src/agent.py --model qwen2.5-coder:7b --dir /path/to/project
```

### Hybrid

```bash
python scripts/install.py --hybrid

# Linux/macOS
export GROQ_API_KEY=gsk_...
chmod +x src/hybrid/unix/*.sh

# Windows
set GROQ_API_KEY=gsk_...

python src/hybrid/agent.py --model qwen2.5-coder:14b --dir /path/to/project --backend auto
```

`GROQ_API_KEY` is only needed when Hybrid routes to Groq.

Parameter semantics:

- `--ctx` controls the backend token budget or context window hint, not a guaranteed output length.
- `--api-base` and `--local-url` both mean an OpenAI-compatible local backend endpoint.
- `--backend` in Hybrid chooses `auto`, `local`, or `groq`.

## Usage

### Local

```bash
python src/agent.py \
  --model qwen2.5-coder:14b \
  --dir /path/to/project \
  [--ctx 8192] \
  [--temp 0.05] \
  [--api-base http://localhost:11434/v1]
```

### Hybrid

```bash
python src/hybrid/agent.py \
  --model qwen2.5-coder:14b \
  --dir /path/to/project \
  --backend auto \
  [--critic]
```

In Hybrid:

- `--model` is the main model selection. If it matches a known Groq model name, the CLI routes accordingly.
- `--groq-model` is the explicit Groq fallback/override model.
- `--local-url` is the local OpenAI-compatible endpoint.

Canonical launch paths in this repo:

- `tui/` (`oat`) for interactive terminal-first launch and session management
- `src/agent.py`
- `src/hybrid/agent.py`
- `src/hybrid/unix/*.sh` for Unix shell launchers

### Launch Paths

The project keeps one canonical Windows launch path here:

- `tui\target\release\oat.exe`: compiled terminal-first launcher and manager

If you want the legacy Windows `.bat` workflow, use the standalone split
repository instead:

- `ollama-agent-windows-bat`

If you want the launcher split as a standalone repository, use:

- `ollama-agent-tui`

## Architecture

At a high level:

1. The CLI entry point loads a system prompt and repository context.
2. The model receives tool definitions for file, shell, and optional web tasks.
3. Shared runtime modules execute tool calls inside the workspace.
4. The agent loops until the task is complete or the user exits.

Core modules:

- [`src/agent.py`](src/agent.py): Local agent entry point
- [`src/hybrid/agent.py`](src/hybrid/agent.py): Hybrid agent entry point
- [`src/base_agent.py`](src/base_agent.py): shared UI, logging, and tool wrappers
- [`common_tools.py`](common_tools.py): tool runtime
- [`common_runtime.py`](common_runtime.py): path and command safety guards
- [`agent_prompting.py`](agent_prompting.py): prompt loading and rendering

Launch boundary:

- Python remains the execution engine
- Rust TUI is a launcher and session manager around the Python core
- legacy `.bat` launchers live in the separate Windows compatibility repo

## Security Model

Ollama Agent uses application-level guards. It does **not** provide OS-level
isolation.

What it does:

- constrains file operations to the workspace root
- resolves paths canonically before acting on them
- blocks a set of clearly destructive shell patterns
- prevents directory changes outside the root workspace

What it does not do:

- sandbox CPU, memory, network, or system calls
- fully validate shell semantics
- guarantee safe execution against hostile prompts or hostile code

If you need stronger isolation, run it inside a disposable environment or use
the optional Docker command sandbox described in [docs/security.md](docs/security.md).

## Project Status

- Version: `0.1.0`
- Release type: initial public release
- Current state: usable but still experimental
- Public API stability: not guaranteed
- Platform focus: local CLI usage on developer machines

Experimental areas:

- Hybrid routing heuristics
- smaller local models using tool calls reliably
- persistent memory behavior in Hybrid
- benchmark methodology and reporting workflow
- optional Docker sandbox integration

What `v0.1.0` means:

- the repository has a coherent local and hybrid CLI story
- the TUI launcher exists and is part of the supported workflow
- the project is still early and should not be treated as a stable platform
- backward compatibility may change between minor releases

## Limitations

- Safety is guardrail-based, not a real sandbox.
- Benchmark documentation exists, but there are no published benchmark results yet.
- The project is optimized for terminal workflows, not editor integration.
- Hybrid memory is local to the machine and not synchronized across environments.
- some legacy aliases still exist for older setups, but `Hybrid` is the canonical naming.

## Documentation

- [Security model](docs/security.md)
- [Benchmark methodology](docs/benchmark.md)
- [Demo flow](docs/demo-flow.md)
- [TUI launcher](tui/README.md)
- [Changelog](CHANGELOG.md)
- [Roadmap](ROADMAP.md)
- [Release notes](RELEASE_NOTES.md)
- [Version file](VERSION)

## Roadmap

Short-term priorities:

- tighten documentation and repository consistency
- stabilize the canonical entry points and split-repo boundaries
- improve test coverage around shared runtime behavior
- publish reproducible benchmark runs when the methodology is stable

## Testing

```bash
python -m unittest discover -s tests -p "test_*.py"
```

CI currently runs on Windows with Python 3.11 and 3.12 via
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

For the TUI launcher:

```bash
cd tui
cargo build --release
```

The Rust TUI is part of `v0.1.0`, but it should still be treated as an early
launcher layer around the Python core.

What CI currently proves:

- Python unit tests on Windows
- CLI help/smoke paths for Local, Hybrid, and benchmark helper
- Rust TUI build and unit tests on Linux

What CI does not fully prove:

- end-to-end Hybrid execution against real Groq or Ollama services
- model quality or tool reliability for any specific local model

## Repository Layout

```text
ollama-agent/
|-- src/
|   |-- agent.py
|   |-- base_agent.py
|   |-- sandbox.py
|   `-- hybrid/
|       |-- agent.py
|       |-- windows/
|       `-- unix/
|-- common_runtime.py
|-- common_tools.py
|-- common_tool_schemas.py
|-- agent_prompting.py
|-- prompts/
|-- docs/
|-- tests/
`-- tui/
```

## License

MIT
