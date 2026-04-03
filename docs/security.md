# Security Model

This project does not implement a full operating-system sandbox. Its safety
story is based on application-level restrictions inside the agent runtime.

That distinction matters:

- these guards reduce accidental damage
- they do not make hostile code execution safe
- they do not replace containers, VMs, or OS security boundaries

## What The Agent Restricts

Current protections include:

- workspace-root validation for file access
- canonical path resolution before file operations
- a shared blocklist for clearly destructive shell commands
- limits on file read and write sizes
- protection against deleting or moving the workspace root itself

The relevant runtime lives primarily in [`common_runtime.py`](../common_runtime.py).

## Path Safety

`resolve_in_root(path, work_dir, root_dir)` allows absolute or relative paths
only if the resolved target remains inside `root_dir`.

Examples:

| Path | Result |
|---|---|
| `src/app.py` | Allowed |
| `/repo/src/app.py` | Allowed if `/repo` is the workspace root |
| `../../etc/passwd` | Blocked |
| `/etc/hosts` | Blocked |

Because the runtime resolves symlinks before checking the final path, a symlink
inside the repository that points outside the workspace is blocked as well.

`change_directory()` updates the working directory, but it does not allow the
agent to escape the original root workspace.

## Command Safety

The command filter is implemented as a blocklist in
`common_runtime.BLOCKED_COMMAND_PATTERNS`.

It is intended to catch obvious destructive operations such as:

- file and directory deletion
- disk formatting and partitioning
- raw writes to `/dev/*` with `dd`
- Windows registry modification
- shutdown and reboot commands
- inline download-and-execute shell patterns
- `git clean`
- `git reset --hard`
- `git checkout -- ...`

This is useful, but limited.

### Important Limits

- A blocklist does not prove a command is safe.
- Indirect destructive behavior may still bypass the filter.
- Safe-looking commands can still execute unsafe code from the repository.

For example, a command like `python -c "import shutil; shutil.rmtree(...)"` may
not match a deletion regex directly.

## File Operation Limits

Current limits in the runtime include:

| Operation | Limit |
|---|---|
| `read_file` | 2 MB per file |
| `write_file` | 10 MB per payload |
| `grep` | skips files larger than 1 MB |
| prompt context loading | limited project context files only |

The agent also rejects deletion of the workspace root directory itself.

## Network Exposure

If web tools are enabled, `fetch_url` can access any URL reachable from the
machine running the agent, including local services such as `localhost`.

That means:

- the agent can read internal development endpoints
- it can access local HTTP services if the model chooses to do so
- this should be treated as controlled local SSRF risk

If your environment exposes sensitive internal services, do not treat this
agent as safely isolated.

## Optional Docker Sandbox

[`src/sandbox.py`](../src/sandbox.py) provides an optional Docker-based sandbox
for `run_command`.

The Docker mode uses:

- ephemeral containers
- read-only root filesystem
- dropped Linux capabilities
- `no-new-privileges`
- no network by default
- CPU and memory limits

The Docker path still uses the same application-level command blocklist as the
local runtime. The container adds isolation around command execution; it does
not replace the runtime guardrails.

Important limitations:

- this only affects `run_command`
- file operations such as `write_file`, `edit_file`, `move_file` and `delete_file`
  still execute on the host workspace
- the repository is mounted read-write inside the container, so sandboxed
  commands can still modify workspace files

Example:

```bash
python src/hybrid/agent.py --sandbox docker --sandbox-image python:3.12-slim
```

## Practical Guidance

For untrusted code or sensitive repositories:

1. work on a disposable clone
2. use a low-privilege user account
3. enable the Docker sandbox if command isolation helps
4. use a container or VM when stronger isolation is required

## Bottom Line

Ollama Agent is safer than an unrestricted shell wrapper, but it is not a
hardened execution environment. Treat it as a developer tool with guardrails,
not as a security boundary.
