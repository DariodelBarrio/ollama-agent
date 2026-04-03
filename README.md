# Ollama Agent

Terminal-first coding agent for OpenAI-compatible backends.

Current release: `v0.1.0` ([`VERSION`](VERSION))

Split repositories:

- Windows legacy `.bat` repo: `https://github.com/DariodelBarrio/ollama-agent-windows-bat`
- TUI launcher repo: `https://github.com/DariodelBarrio/ollama-agent-tui`

Ollama Agent is a local-first CLI that can inspect a repository, read and edit
files, run shell commands inside the workspace, and answer with a concise
terminal workflow. The repository currently ships two variants built on the
same core:

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

It is not a hosted service, not a GUI product, and not a hardened sandbox.

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

Choose one of these paths:

- Base install for the Local agent: `python scripts/install.py`
- Extended install for Hybrid: `python scripts/install.py --hybrid`
- Rust TUI launcher: build [`tui/`](tui/) with `cargo build --release`

Prerequisites:

- Python 3.9+
- A local OpenAI-compatible backend such as Ollama for Local and Hybrid local mode
- `GROQ_API_KEY` only when Hybrid routes to Groq
- Rust toolchain only if you want the compiled TUI launcher

Dependency files:

- [`requirements.txt`](requirements.txt): canonical base dependencies
- [`requirements-hybrid.txt`](requirements-hybrid.txt): canonical Hybrid dependencies
- [`requirements-mega.txt`](requirements-mega.txt): legacy alias kept for compatibility

## Quick Start

Prerequisites:

- Python 3.9+
- [Ollama](https://ollama.com) running locally, or another OpenAI-compatible backend

### Local

```bash
git clone https://github.com/DariodelBarrio/ollama-agent.git
cd ollama-agent
python scripts/install.py
ollama pull qwen2.5-coder:14b
python src/agent.py --model qwen2.5-coder:14b --dir /path/to/project
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

Canonical launchers:

- `tui/` (`oat`) for interactive terminal-first launch and session management
- `src/agent.py`
- `src/hybrid/agent.py`
- `src/hybrid/windows/*.bat`
- `src/hybrid/unix/*.sh`

`IA/MEGA/` remains in the repository only as a compatibility layer for older
Windows launch flows. It is not the canonical location for active code.

### Launch Paths

The repository intentionally keeps two separate launch paths on Windows:

- `tui\target\release\oat.exe`: compiled terminal-first launcher and manager
- `IA\MEGA\*.bat` and `src\hybrid\windows\*.bat`: legacy script launchers kept for compatibility

Use `oat.exe` when you want profiles, model management, live session output,
and a managed terminal UI. Use the `.bat` launchers when you want the older
direct-script flow without the TUI.

The TUI-specific compatibility changes do not replace or remove the legacy
`.bat` entry points.

If you want those paths as standalone repositories instead of the combined
repo, use:

- `ollama-agent-windows-bat` for the Windows `.bat` workflow
- `ollama-agent-tui` for the compiled terminal-first launcher workflow

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
- Backward-compatibility shims still exist for legacy launch paths.
- `requirements-mega.txt` and `--mega` are legacy aliases; `requirements-hybrid.txt` and `--hybrid` are canonical.

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
- stabilize the canonical entry points and legacy compatibility story
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
`-- IA/MEGA/    # legacy compatibility only
```

## License

MIT
