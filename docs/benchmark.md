# Benchmark

Benchmark mínimo y reproducible para Ollama Agent. Tres tareas pequeñas con
criterios de éxito verificables. Sin números fabricados: este documento define
la metodología; los resultados se publican cuando hay una ejecución completa
y reproducible.

## Diseño

### Por qué estas tareas

Se eligieron tareas que:

- Cubren el flujo principal del agente: leer, editar, crear.
- Tienen criterio de éxito binario y verificable (no dependen de juicio estético).
- Se pueden reproducir en cualquier máquina con el repo clonado.
- No requieren conocimiento externo al propio codebase.

### Qué se mide

| Métrica | T1 | T2 | T3 |
|---|---|---|---|
| Precisión del output | Manual | Automático | Automático |
| Tiempo de respuesta | Cronómetro | Cronómetro | Cronómetro |
| Número de tool calls | Manual (log) | Manual (log) | Manual (log) |
| Regresión (tests pasan) | Post-run | Post-run | Post-run |

### Qué no se mide (aún)

- Comparativa con Aider u OpenCode: requiere entorno homogéneo con las tres herramientas instaladas.
- Calidad de código generado más allá de corrección sintáctica.
- Uso de tokens (la variante local no expone contadores por defecto).

---

## Preparación

```bash
# Desde la raíz del repo
python scripts/run_benchmark.py setup
```

El script crea los fixtures necesarios en `benchmark_run/` e imprime los prompts
exactos para cada tarea. Anota la hora de inicio antes de pegar cada prompt.

Lanza el agente con `--dir` apuntando a la raíz del repo:

```bash
python src/agent.py --model <MODEL> --dir .
```

---

## Tareas

### T1 — Lectura y análisis `[verificación manual]`

**Prompt exacto:**

```
Lee common_runtime.py. ¿Cuántos patrones regex tiene BLOCKED_COMMAND_PATTERNS?
Lista todos con una descripción de qué bloquea cada uno.
```

**Criterio de éxito:**

- El agente usa la tool `read_file` o `grep` para leer el archivo (no adivina).
- Lista los 15 patrones presentes en la variable.
- La descripción de cada patrón es correcta (no inventa comportamientos).

**Cómo registrar:**

| Campo | Valor |
|---|---|
| Patrones listados | / 15 |
| Patrones correctos | / 15 |
| Tool calls usados | |
| Tiempo (s) | |
| Resultado | PASS / FAIL |

Criterio de PASS: todos los patrones presentes y descripciones correctas.

---

### T2 — Edición puntual `[verificación automática]`

**Prompt exacto** (generado por `setup`, incluye la ruta relativa real):

```
En benchmark_run/T2/config.py, cambia el valor de MAX_RETRIES
de 3 a 5. No toques ninguna otra línea.
```

**Fixture inicial** (`benchmark_run/T2/config.py`):

```python
# Fixture T2 — benchmark Ollama Agent (no eliminar este comentario)
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
```

**Estado esperado tras la tarea:**

```python
# Fixture T2 — benchmark Ollama Agent (no eliminar este comentario)
MAX_RETRIES = 5
TIMEOUT_SECONDS = 30
```

**Verificación:**

```bash
python scripts/run_benchmark.py check
```

Criterio de PASS: `MAX_RETRIES = 5`, comentario intacto, `TIMEOUT_SECONDS` sin cambios.

---

### T3 — Creación de archivo `[verificación automática]`

**Prompt exacto** (generado por `setup`, incluye la ruta relativa real):

```
Crea benchmark_run/T3/utils.py con dos funciones:
  add(a, b)      -> devuelve a + b
  multiply(a, b) -> devuelve a * b
Sin imports, sin docstrings, sin nada más.
```

**Estado esperado:**

```python
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b
```

**Verificación:**

```bash
python scripts/run_benchmark.py check
```

Criterio de PASS: archivo existe, define `add` y `multiply`, sintaxis Python válida.

---

## Verificación y reporte

```bash
# Verificar T2 y T3 automáticamente
python scripts/run_benchmark.py check

# Generar informe JSON archivable (--t1-pass yes/no tras revisión manual de T1)
python scripts/run_benchmark.py report --model qwen2.5-coder:14b --t1-pass yes
```

El informe se guarda en `benchmark_run/result_YYYYMMDD_HHMM_MODEL.json`.

---

## Suite de tests unitarios

Los tests del repo son parte del benchmark base. Deben pasar antes y después
de cada ejecución de las tareas:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Si alguna tarea rompe los tests, la ejecución no es válida.

---

## Entorno mínimo a registrar

Para que un resultado sea comparable, el informe JSON debe incluir:

| Campo | Ejemplo |
|---|---|
| `git_commit` | `5aa6438...` |
| `git_dirty` | `false` |
| `model` | `qwen2.5-coder:14b` |
| `date_utc` | `2026-04-03T14:00:00Z` |
| `python` | `3.12.2` |
| `platform` | `Windows-11-...` |
| `processor` | `Intel Core i7-...` / GPU si es relevante |

El script `report` captura estos campos automáticamente del entorno de ejecución.

---

## Plantilla de resultados

```json
{
  "env": {
    "date_utc": "",
    "model": "",
    "python": "",
    "platform": "",
    "processor": "",
    "git_commit": "",
    "git_dirty": false
  },
  "tasks": {
    "T1": { "pass": null,  "auto": false, "reason": "" },
    "T2": { "pass": false, "auto": true,  "reason": "" },
    "T3": { "pass": false, "auto": true,  "reason": "" }
  },
  "notes": {
    "T1_tool_calls": 0,
    "T2_tool_calls": 0,
    "T3_tool_calls": 0,
    "T1_time_s": 0,
    "T2_time_s": 0,
    "T3_time_s": 0,
    "unit_tests_before": "OK / FAIL",
    "unit_tests_after": "OK / FAIL"
  }
}
```

El campo `notes` se rellena manualmente; los demás los genera `report`.

---

## Resultados publicados

*Ninguno todavía.* Los resultados se publicarán cuando haya una ejecución
completa con las tres tareas y los tests unitarios verificados.
