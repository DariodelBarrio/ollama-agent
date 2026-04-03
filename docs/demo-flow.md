# Demo Flow

This document describes a reproducible demo workflow for the repository. It is
meant to show the intended interaction pattern, not to market the project.

## Flow 1: Shared tool runtime refactor

Prompt:

```text
Extrae la capa de herramientas a modulos compartidos y deja agent.py centrado en orquestacion/UI.
```

Expected behavior:

1. Read `src/agent.py` and `src/hybrid/agent.py`.
2. Create shared tool modules.
3. Update both agent variants to use the shared runtime.
4. Run the test suite.

Expected diff shape:

```text
+ common_tools.py
+ common_tool_schemas.py
~ src/agent.py
~ src/hybrid/agent.py
~ tests/test_agent_safety.py
```

Expected outcome:

```text
shared tool runtime
local and hybrid variants aligned
tests still passing
```

## Flow 2: Security explanation

Prompt:

```text
Explica que bloquea run_command y que pasa si el modelo intenta salir del work_dir.
```

Expected answer characteristics:

- references `common_runtime.BLOCKED_COMMAND_PATTERNS`
- explains `resolve_in_root()`
- states clearly that there is no OS-level sandbox

## Screenshot

Current UI screenshot: [screenshot.png](screenshot.png)

The repository does not yet include a recorded video or GIF for a stable,
reproducible session. This document is intentionally limited to the workflow
that can be reproduced from the current codebase.
