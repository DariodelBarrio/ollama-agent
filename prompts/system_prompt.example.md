# Ejemplo de prompt de sistema externo

Personaliza las reglas del agente guardando tu propio prompt aqui y pasalo con
`--system-prompt prompts/system_prompt.example.md`.

## Sintaxis de variables

Los templates usan Jinja2. Variables disponibles:

| Variable           | Descripción                                        |
|--------------------|-----------------------------------------------------|
| `{{ work_dir }}`       | Directorio de trabajo actual                       |
| `{{ desktop }}`        | Ruta del escritorio del usuario                    |
| `{{ project_context }}` | Contenido de CLAUDE.md / README.md / .cursorrules |
| `{{ memories }}`       | Memorias persistentes de sesiones anteriores       |
| `{{ mode_section }}`   | Sección de modo activo (local agent)               |

## Ejemplo mínimo

```
Eres un agente de programación. Directorio: {{ work_dir }}

{% if project_context %}
{{ project_context }}
{% endif %}

Responde siempre en inglés.
```

## Compatibilidad hacia atrás

Los override files también soportan la sintaxis antigua `$variable` de
`string.Template` (detección automática). Esto permite reutilizar prompts
escritos antes de la migración a Jinja2.

```
# Sintaxis antigua — sigue funcionando
Directorio: $work_dir
Contexto: $project_context
```

## Notas

- Manten las instrucciones criticas (seguridad, uso de herramientas) al inicio.
- Este archivo no se carga automaticamente: usalo como plantilla y referencia.
- Las variables no definidas se renderizan como cadena vacía (no provocan error).
