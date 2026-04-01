# Ollama Agent — Agente de Programación Local

Agente autónomo de programación 100% local con [Ollama](https://ollama.com) y backend compatible con OpenAI. Réplica las capacidades principales de asistentes como Claude Code sin costos de API.

![Python](https://img.shields.io/badge/Python-3.9+-blue) ![OpenAI API](https://img.shields.io/badge/OpenAI--compatible-API-green) ![CUDA](https://img.shields.io/badge/CUDA-12.x-76B900) ![License](https://img.shields.io/badge/license-MIT-blue)

---

## Proyectos

### `src/agent.py` — Agente local

Agente estándar que corre contra Ollama (o cualquier backend OpenAI-compatible).

**Características:**
- 13 herramientas — archivos, shell, web, grep, directorios, mover/renombrar, cambio de directorio
- Modos de trabajo: `/mode code` (temp 0.05) · `/mode architect` (0.7) · `/mode research` (0.3)
- Streaming con detección de bloques `<think>` y `<thought>`
- Autocorrección — reintenta hasta 3 veces con enfoque diferente ante errores
- Menú interactivo de selección de modelo al arrancar
- Seguridad básica — bloquea comandos destructivos comunes y restringe operaciones al `work_dir`
- Compatible con Ollama, vLLM, LMDeploy y LM Studio vía `--api-base`

### `IA/MEGA/agent.py` — Agente híbrido dual-brain

Agente avanzado con GPU local + Groq cloud. Router inteligente que decide el backend según la complejidad del prompt.

**Características adicionales:**
- SmartRouter — enruta automáticamente entre GPU local y Groq (128k ctx)
- Actor-Crítico — revisa el código generado con un segundo pase (flag `--critic`)
- Self-healing — inyecta contexto de error en el historial y reintenta hasta 3 veces
- Comandos `/slash` — `/help`, `/clear`, `/switch`, `/model`, `/ctx`, `/scan`, `/stats`
- Escáner AST — extrae esqueleto de clases, métodos y funciones del proyecto
- Seguridad — bloquea comandos destructivos (`rm`, `del`, `format`, `shutdown`, etc.)
- Rutas restringidas al work_dir — `change_directory` no puede salir del directorio raíz
- `prompt_toolkit` — historial persistente y autocompletado en el prompt

---

## Herramientas

| Herramienta | Descripción |
|-------------|-------------|
| `run_command` | PowerShell / bash (filtra comandos destructivos en MEGA) |
| `read_file` | Lee archivos con números de línea |
| `write_file` | Crea archivos nuevos |
| `edit_file` | Edita texto exacto (soporta regex y replace_all) |
| `find_files` | Busca por patrón glob |
| `grep` | Busca texto/regex en el proyecto |
| `list_directory` | Lista carpetas |
| `delete_file` | Elimina archivos o carpetas (recursivo) |
| `create_directory` | Crea carpetas y subcarpetas |
| `move_file` | Mueve o renombra archivos/carpetas |
| `change_directory` | Cambia el directorio de trabajo activo |
| `search_web` | DuckDuckGo para información actual |
| `fetch_url` | Descarga y lee URLs |

---

## Requisitos

- Python 3.9+
- [Ollama](https://ollama.com/download) instalado y corriendo
- NVIDIA GPU con CUDA (recomendado, funciona en CPU)
- Windows 10/11

---

## Instalación

```bash
git clone https://github.com/DariodelBarrio/ollama-agent.git
cd ollama-agent
python scripts/install.py

# Para MEGA (añade sglang/vllm y extras)
python scripts/install.py --mega
```

Instalación manual:

```bash
pip install -r requirements.txt               # agente estándar
pip install -r requirements-mega.txt         # MEGA
```

---

## Uso

### `src/agent.py`

```bash
# Menú interactivo de modelos
python src/agent.py

# Modelo y directorio específico
python src/agent.py --model qwen2.5-coder:14b --dir "C:\mi\proyecto"

# Backend alternativo (vLLM, LMDeploy, LM Studio)
python src/agent.py --model mistral --api-base http://localhost:8000/v1
```

**Argumentos:**

| Argumento | Default | Descripción |
|-----------|---------|-------------|
| `--model` | menú interactivo | Modelo a usar |
| `--dir` | `.` | Directorio de trabajo |
| `--tag` | `AGENTE` | Nombre en el header |
| `--ctx` | `16384` | Ventana de contexto en tokens |
| `--temp` | `0.15` | Temperatura |
| `--api-base` | `http://localhost:11434/v1` | URL base API (Ollama/vLLM/LMDeploy/LM Studio) |
| `--system-prompt` | `None` | Archivo opcional con prompt de sistema (acepta {work_dir}, {project_context}, {mode}, {mode_snippet}) |

**Comandos de sesión:**

| Comando | Acción |
|---------|--------|
| `salir` / `exit` / `quit` | Termina el agente |
| `limpiar` / `clear` / `reset` | Reinicia el historial |
| `/mode [code\|architect\|research]` | Cambia el modo de trabajo |

Prompt externo: pasa `--system-prompt ruta/al/archivo.md` para cargar tus propias reglas. Ejemplo en `prompts/system_prompt.example.md`.

### `IA/MEGA/agent.py`

```bash
# Local GPU (Ollama)
python agent.py --model qwen2.5-coder:14b --dir "C:\mi\proyecto"

# Forzar Groq cloud
python agent.py --model llama-3.3-70b-versatile --backend groq

# Router automático + Actor-Crítico
python agent.py --model qwen2.5-coder:14b --backend auto --critic
```

**Argumentos:**

| Argumento | Default | Descripción |
|-----------|---------|-------------|
| `--model` | menú interactivo | Modelo local o Groq |
| `--dir` | `.` | Directorio de trabajo |
| `--backend` | `auto` | `local`, `groq` o `auto` (router) |
| `--local-url` | `http://localhost:11434/v1` | URL del servidor local |
| `--groq-model` | `llama-3.3-70b-versatile` | Modelo de Groq |
| `--ctx` | `32768` | Ventana de contexto |
| `--temp` | `0.15` | Temperatura |
| `--critic` | off | Activa modo Actor-Crítico |
| `--system-prompt` | `None` | Archivo opcional con prompt de sistema (acepta {work_dir}, {project_context}, {memories}) |

**Comandos /slash de MEGA:**

| Comando | Acción |
|---------|--------|
| `/help` | Muestra todos los comandos |
| `/clear` | Reinicia el historial |
| `/switch [local\|groq\|auto]` | Fuerza o libera el backend |
| `/model [nombre]` | Muestra o cambia el modelo activo |
| `/ctx` | Muestra tokens de contexto usados |
| `/scan` | Escanea la estructura AST del proyecto |
| `/stats` | Estadísticas de llamadas al router |

Prompt externo: `--system-prompt ruta/al/archivo.md` (usa {work_dir}, {project_context}, {memories}).

**Launchers .bat incluidos:**

```
IA/MEGA/
├── SONNET [qwen2.5-coder - Coding RTX5070].bat
├── OPUS [deepseek-r1 - Razonamiento profundo].bat
├── CRITICO [qwen3 - Actor-Critico activado].bat
├── GEMINI [gemini-2.0-flash - Nube inteligente].bat   ← ahora usa Groq
└── INSTALAR DEPENDENCIAS.bat
```

Para usar Groq, define la API key (gratuita en [console.groq.com](https://console.groq.com)):

```powershell
setx GROQ_API_KEY tu_clave
```

---

## Modelos recomendados

### Local (RTX 5070 / 12 GB VRAM)

| Modelo | VRAM | Uso |
|--------|------|-----|
| `qwen2.5-coder:14b` | ~8.5 GB | Mejor coder, todo en GPU |
| `deepseek-r1:14b` | ~8.5 GB | Razonamiento profundo |
| `qwen2.5-coder:32b` | ~12+7 GB RAM | Máxima calidad (offload parcial) |
| `mistral-nemo:12b` | ~7.5 GB | General + multilingüe |
| `dolphin3:8b` | ~5 GB | Sin censura, rápido |

### Groq cloud (gratis)

| Modelo | Contexto | Uso |
|--------|----------|-----|
| `llama-3.3-70b-versatile` | 128k | Más capaz, general |
| `deepseek-r1-distill-llama-70b` | 128k | Thinking model |
| `qwen-qwq-32b` | 128k | Alternativa razonamiento |
| `llama-3.1-8b-instant` | 128k | Rápido, tareas simples |

---

## Configuración GPU

Variables de entorno (incluidas en los `.bat`):

```bash
set OLLAMA_NUM_GPU=999          # todas las capas en GPU
set OLLAMA_KEEP_ALIVE=-1        # modelo siempre cargado en VRAM
set CUDA_VISIBLE_DEVICES=0      # GPU primaria
set OLLAMA_KV_CACHE_TYPE=q8_0   # KV cache cuantizado (mitad de VRAM)
```

Para configurarlas permanentemente:

```powershell
setx OLLAMA_NUM_GPU 999
setx OLLAMA_KEEP_ALIVE -1
setx CUDA_VISIBLE_DEVICES 0
setx OLLAMA_KV_CACHE_TYPE q8_0
```

---

## Contexto por modelo y GPU

| Tamaño modelo | VRAM modelo | Contexto recomendado |
|---------------|-------------|----------------------|
| 7b / 8b | ~5 GB | 32768 (32K) |
| 14b | ~8.5 GB | 8192–16384 |
| 32b | ~12 GB + RAM | 8192 |

Con `OLLAMA_KV_CACHE_TYPE=q8_0` el KV cache ocupa la mitad — permite subir el contexto o liberar VRAM para el modelo.

---

## Estructura del proyecto

```
ollama-agent/
├── src/
│   └── agent.py                  # Agente local (OpenAI-compatible API)
├── IA/
│   ├── MEGA/                     # Agente híbrido dual-brain
│   │   ├── agent.py              # Local GPU + Groq, router, crítico, AST
│   │   ├── SONNET *.bat
│   │   ├── OPUS *.bat
│   │   ├── CRITICO *.bat
│   │   ├── GEMINI *.bat          # Groq cloud
│   │   └── INSTALAR DEPENDENCIAS.bat
│   └── sin censura/              # Bats modelos sin restricciones
├── config/
│   ├── Modelfile.sonnet
│   ├── Modelfile.opus
│   └── CONSTRUIR MODELOS.bat
├── docs/
│   └── screenshot.png
├── requirements.txt
└── README.md
```

---

## Dependencias

```
openai
rich
prompt_toolkit
duckduckgo-search
requests
beautifulsoup4
pydantic
```

---

## Tests

```bash
py -3 -m unittest discover -s tests -p "test_*.py"
```

---

## Licencia

MIT
