# Demo Flow

## Flujo 1: prompt -> accion -> diff -> resultado

Prompt:

```text
Extrae la capa de herramientas a modulos compartidos y deja agent.py centrado en orquestacion/UI.
```

Acciones esperadas:

1. Leer `src/agent.py` y la variante hibrida.
2. Crear `common_tools.py` y `common_tool_schemas.py`.
3. Rewire de `TOOL_MAP` y `TOOLS`.
4. Ejecutar tests.

Diff esperado:

```text
+ common_tools.py
+ common_tool_schemas.py
~ src/agent.py
~ src/hybrid/agent.py
~ tests/test_agent_safety.py
```

Resultado esperado:

```text
7 tests OK
tool runtime compartido
variantes local e hybrid unificadas
```

## Flujo 2: review de seguridad

Prompt:

```text
Explica que bloquea run_command y que pasa si el modelo intenta salir del work_dir.
```

Resultado esperado:

- referencia a `common_runtime.BLOCKED_COMMAND_PATTERNS`
- explicacion de `resolve_in_root()`
- aclaracion de que no hay sandbox de SO

## Captura actual

UI actual: [docs/screenshot.png](/C:/Users/dapio/Documents/ollama/docs/screenshot.png)

Nota:

- Este repo todavia no incluye un GIF/video nuevo grabado desde una sesion reproducible.
- Se ha dejado el flujo demo documentado para poder capturarlo sin ambiguedad.
