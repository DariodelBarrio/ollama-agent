# TUI Launcher (`oat`)

`oat` is the terminal-first launcher and session manager for Ollama Agent.
It does not replace the Python agents. It wraps the existing entry points and
keeps the runtime logic in Python.

Canonical agent entry points:

- [`../src/agent.py`](../src/agent.py)
- [`../src/hybrid/agent.py`](../src/hybrid/agent.py)

## What Phase 1 Includes

The current TUI is intentionally small but useful:

- choose `Local` or `Hybrid`
- edit the main launch parameters
- list local models
- download local models
- delete local models
- save and load reusable profiles
- launch the Python agent as a managed child process
- watch live stdout/stderr in the TUI
- send line-based input to the running agent
- stop the child process from the launcher

This keeps the project terminal-first without making `.bat` files the primary
interface anymore.

## Architecture

The TUI has three layers:

1. profile state and persistence in `src/config.rs`
2. command derivation and child-process control in `src/agent.rs`
3. local model management in `src/models.rs`
4. terminal UI and navigation in `src/app.rs` + `src/ui.rs`

The Python agents remain the execution core. `oat` only builds the command,
spawns the process, forwards input, and renders output.

## Supported Parameters

Both variants expose:

- model
- work directory
- tag
- context window (`ctx`)
- temperature
- optional system prompt path

Hybrid also exposes:

- backend (`auto`, `local`, `groq`)
- local endpoint
- Groq model
- critic mode
- optional Docker sandbox settings

Local model management uses the active local endpoint from the current profile:

- `api_base` for `Local`
- `local_url` for `Hybrid`

The launcher strips a trailing `/v1` and then talks to Ollama's native
management endpoints (`/api/tags`, `/api/pull`, `/api/delete`).

## Build

```bash
cd tui
cargo build --release
```

Binary output:

- Linux/macOS: `tui/target/release/oat`
- Windows: `tui\target\release\oat.exe`

## Usage

From the repository root:

```bash
./tui/target/release/oat
oat.exe
```

From outside the repository:

```bash
OLLAMA_AGENT_ROOT=/path/to/repo oat
set OLLAMA_AGENT_ROOT=C:\path\to\repo && oat.exe
```

## Model Management

Open the model screen from:

- main menu: `Local models`
- configure screen: `F3`

Current controls:

- `r`: refresh installed models
- `Enter`: set selected installed model as the active profile model
- `p`: type a model name to pull, then `Enter` to start download
- `d`: delete the selected installed model
- `Esc`: return to configuration

Download progress is shown when the local backend streams status updates in the
same format as Ollama.

## Profiles

Profiles are stored at:

- Linux/macOS: `~/.config/ollama-agent/profiles.toml`
- Windows: `%APPDATA%\ollama-agent\profiles.toml`

The TUI keeps old profiles readable by using defaults for fields that were
added later.

## Session Model

`oat` launches the selected Python agent as a child process and keeps the user
inside one terminal UI.

Current session controls:

- `F5`: launch
- `F2`: save current profile
- `i`: start editing a line of input for the running agent
- `Enter`: send that line
- `F6`: stop the child process
- `Esc`: return from session view to configuration

## Practical Limits

This is a first-phase TUI, not a full terminal multiplexer.

- input forwarding is line-based
- the integrated session does not try to preserve `prompt_toolkit` features
- `Hybrid` runs in a simplified input mode when launched from `oat`
- stopping a session kills the child process; it is not a graceful in-agent shutdown

Those limits are deliberate for now: the TUI manages the current Python core
without forking a second frontend stack.

Model-management limits:

- it is only available when the configured local backend exposes Ollama's
  native model-management API
- generic OpenAI-compatible backends may work for inference but not for model
  listing, pull, or delete
- the launcher reports that limitation directly instead of faking support

## Environment Variables

| Variable | Purpose |
|---|---|
| `OLLAMA_AGENT_ROOT` | Repository path when `oat` starts outside the repo |
| `GROQ_API_KEY` | Required for Hybrid runs that route to Groq |
| `PYTHONUNBUFFERED` | Set automatically by `oat` for live output |
| `OLLAMA_AGENT_SIMPLE_INPUT` | Set automatically by `oat` for managed Hybrid sessions |
