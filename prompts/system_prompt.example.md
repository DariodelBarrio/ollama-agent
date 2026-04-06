# Ejemplo de prompt de sistema externo

Personaliza las reglas del agente guardando tu propio prompt aquí y pasándolo con
`--system-prompt prompts/system_prompt.example.md`.

## Variables disponibles

Los templates usan Jinja2. Variables disponibles según variante:

| Variable | Descripción | Local | Hybrid |
|---|---|---|---|
| `{{ work_dir }}` | Directorio de trabajo actual (mutable durante la sesión) | Sí | Sí |
| `{{ workspace }}` | Raíz segura del proyecto/workspace (estable durante la sesión) | Sí | Sí |
| `{{ project_context }}` | Contenido de CLAUDE.md / README.md / .cursorrules | Sí | Sí |
| `{{ mode_section }}` | Sección del modo activo (`code`, `architect`, `research`) | Sí | No |
| `{{ desktop }}` | Ruta segura `workspace/desktop` | Sí | Sí |
| `{{ documents }}` | Ruta segura `workspace/documents` | Sí | Sí |
| `{{ memories }}` | Memorias persistentes de sesiones anteriores (SQLite) | No | Sí |

## Ejemplo mínimo

```
Eres un agente de programación. Directorio: {{ work_dir }}

{% if project_context %}
{{ project_context }}
{% endif %}

Responde siempre en inglés.
```

## Compatibilidad con sintaxis legada

Los override files también soportan `$variable` de `string.Template` (detección automática).
Útil para reutilizar prompts escritos antes de la migración a Jinja2.

```
# Sintaxis antigua — sigue funcionando
Directorio: $work_dir
Contexto: $project_context
```

## Notas

- Mantén las instrucciones críticas (seguridad, uso de herramientas) al inicio del template.
- No dependas de formatos como `<thought>` o `<think>`; el agente no debería necesitarlos para funcionar.
- Este archivo no se carga automáticamente: úsalo como plantilla y referencia.
- Las variables no definidas se renderizan como cadena vacía, no provocan error.
