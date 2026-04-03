# Demo Flow

## Flujo 1: refactoring asistido

Prompt:

```
Extrae la capa de herramientas a módulos compartidos y deja agent.py centrado en orquestación/UI.
```

Acciones esperadas del agente:

1. Leer `src/agent.py` y la variante híbrida.
2. Crear `common_tools.py` y `common_tool_schemas.py`.
3. Actualizar `TOOL_MAP` y `TOOLS` en ambas variantes.
4. Ejecutar tests.

Diff esperado:

```
+ common_tools.py
+ common_tool_schemas.py
~ src/agent.py
~ src/hybrid/agent.py
~ tests/test_agent_safety.py
```

Resultado esperado:

```
7 tests OK
tool runtime compartido
variantes local e hybrid unificadas
```

## Flujo 2: revisión de seguridad

Prompt:

```
Explica qué bloquea run_command y qué pasa si el modelo intenta salir del work_dir.
```

Resultado esperado:

- Referencia a `common_runtime.BLOCKED_COMMAND_PATTERNS` con los patrones concretos.
- Explicación de `resolve_in_root()` y cómo trata symlinks.
- Aclaración explícita de que no hay sandbox de SO.

## Captura actual

UI actual: [docs/screenshot.png](screenshot.png)

> El repositorio no incluye aún un GIF/video grabado desde una sesión reproducible.
> El flujo está documentado para poder capturarlo sin ambigüedad cuando haya un entorno estable.
