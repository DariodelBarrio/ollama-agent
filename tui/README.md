# TUI Launcher (`oat`)

`oat` is the terminal-first launcher and session manager for Ollama Agent.
It does not replace the Python agents. It wraps the existing entry points and
keeps the runtime logic in Python.

Canonical agent entry points:

- [`../src/agent.py`](../src/agent.py)
- [`../src/hybrid/agent.py`](../src/hybrid/agent.py)

## Current Scope

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

This keeps the project terminal-first without turning the TUI into a rewrite
of the agent. The legacy Windows `.bat` launchers live in the separate
compatibility repository.

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

- GPU profile (`custom`, `5060`, `5070`, `5080`, `5090`)
- GPU recommendation level (`safe`, `balanced`, `max`)
- model
- work directory
- tag
- context window (`ctx`)
- temperature
- optional system prompt path

Hybrid also exposes:

- backend (`auto`, `local`, `groq`, `remote`)
- local endpoint
- Groq model
- optional cloud provider preset (`groq`, `openai`, `openrouter`, `custom`)
- optional cloud endpoint, cloud model, and cloud API key
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

Legacy Windows launchers are not part of this repository. Use the separate
Windows compatibility repository if you want the `.bat` workflow.

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
- `g`: pull the recommended model for the selected GPU profile
- `Enter`: set selected installed model as the active profile model
- `p`: type a model name to pull, then `Enter` to start download
- `d`: delete the selected installed model
- `Esc`: return to configuration

Download progress is shown when the local backend streams status updates in the
same format as Ollama. Repeated progress updates are coalesced into a live
status line instead of flooding the log pane.

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

- `F4`: apply the selected GPU recommendation to `model` and `ctx`
- `F5`: launch
- `F2`: save current profile
- type directly in the input box
- `Enter`: send the current line
- `F6`: stop the child process
- `Up/Down`, `PageUp/PageDown`, `Home/End`: browse retained output
- `Esc`: return from session view to configuration

The session view follows live output by default. Scrolling up pauses follow
mode; `End` jumps back to the bottom and resumes it.

## Hybrid Cloud Providers

The TUI can configure `Hybrid` against an extra cloud provider without
rewriting the Python core. The current path is honest and simple:

- choose `Backend = remote` when you want a generic OpenAI-compatible cloud
- choose `Proveedor cloud` to prefill a known base URL when possible
- set or edit `Modelo cloud`
- either leave `API key cloud` empty to rely on environment variables, or paste
  a key directly into the profile

Current provider presets:

- `groq`: uses `GROQ_API_KEY`
- `openai`: uses `OPENAI_API_KEY` or `REMOTE_API_KEY`
- `openrouter`: uses `OPENROUTER_API_KEY` or `REMOTE_API_KEY`
- `custom`: expects `REMOTE_API_KEY` unless you paste one inline

There is no OAuth-style "login with ChatGPT" flow in the launcher today. The
real integration path is API-key based.

## Practical Limits

This is an early launcher, not a full terminal multiplexer.

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

GPU recommendation limits:

- GPU selection is a manual profile choice, not automatic hardware detection
- recommendations depend on both the selected GPU and the selected level: `safe`, `balanced`, or `max`
- recommendations only apply suggested defaults for `model` and `ctx`
- model installation can use that same recommendation as a pull target
- lower-VRAM presets now bias toward smaller models first, especially on `5060`
- larger recommendations for `5080` and `5090` are intended for users with more VRAM headroom, but they are not guarantees

## Environment Variables

| Variable | Purpose |
|---|---|
| `OLLAMA_AGENT_ROOT` | Repository path when `oat` starts outside the repo |
| `GROQ_API_KEY` | Required for Hybrid runs that route to Groq |
| `PYTHONUNBUFFERED` | Set automatically by `oat` for live output |
| `OLLAMA_AGENT_SIMPLE_INPUT` | Set automatically by `oat` for managed Local and Hybrid sessions |
