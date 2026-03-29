# 🧠 Ollama Agent — Agente de Programación Local

Agente autónomo de programación que corre **100% local** con [Ollama](https://ollama.com). Replica las capacidades principales de asistentes como Claude Code sin conexión a internet ni costos de API.

![Python](https://img.shields.io/badge/Python-3.9+-blue) ![Ollama](https://img.shields.io/badge/Ollama-latest-green) ![CUDA](https://img.shields.io/badge/CUDA-12.x-76B900) ![License](https://img.shields.io/badge/license-MIT-blue)

![screenshot](docs/screenshot.png)



## Características

- **100% offline** — tu código nunca sale de tu equipo
- **Cero costos** — sin facturación por tokens
- **12 herramientas** — archivos, shell, web, grep, directorios, mover/renombrar
- **Modo agente** — encadena pasos sin interrumpir, nunca pide confirmación entre herramientas
- **Autocorrección** — si falla, analiza el error y reintenta hasta 3 veces con enfoque diferente
- **Streaming** — respuestas en tiempo real con Rich UI
- **Multi-modelo** — 9 modelos con bats preconfigurados
- **GPU optimizada** — num_batch:512, contexto ajustado por tamaño de modelo para no derramar a RAM
- **Modelos personalizados** — Modelfiles con reglas de comportamiento integradas permanentemente
- **Proyectos reales** — web (React, Express, Vue), bases de datos (Prisma, Django, Alembic, SQL)

## Modelos Disponibles

### Con censura

| Tag | Modelo base | Modelo personalizado | Uso |
|-----|-------------|----------------------|-----|
| **SONNET** | `qwen3:14b` | `sonnet-agente` | Coding general, mejor all-rounder |
| **OPUS** | `deepseek-r1:14b` | `opus-agente` | Razonamiento profundo, arquitectura |
| **HAIKU** | `phi4:latest` | — | Matemáticas, lógica, razonamiento |

### Sin censura

| Tag | Modelo | Uso |
|-----|--------|-----|
| **DOLPHIN** | `dolphin3:8b` | General, sin restricciones, rápido |
| **HERMES** | `hermes3:8b` | General, sin restricciones, preciso |
| **GROQ** | `llama3-groq-tool-use:8b` | Tool calling optimizado |
| **DOLPHIN-HACKER** | `dolphin-hacker` | Pentesting, HTB, exploits |
| **HERMES-HACKER** | `hermes-hacker` | Pentesting, HTB, exploits |

> Los modelos `sonnet-agente` y `opus-agente` tienen las reglas de comportamiento y `/no_think` integrados permanentemente vía Modelfile. Construirlos con `config/CONSTRUIR MODELOS.bat`.

## Herramientas

| Herramienta | Descripción |
|-------------|-------------|
| `run_command` | Ejecuta PowerShell/CMD |
| `read_file` | Lee archivos con números de línea |
| `write_file` | Crea archivos nuevos |
| `edit_file` | Edita texto exacto en archivos |
| `find_files` | Busca por patrón glob |
| `grep` | Busca texto/regex en el proyecto |
| `list_directory` | Lista carpetas |
| `delete_file` | Elimina archivos o carpetas (recursivo) |
| `create_directory` | Crea carpetas y subcarpetas |
| `move_file` | Mueve o renombra archivos/carpetas |
| `search_web` | DuckDuckGo para info actual |
| `fetch_url` | Descarga y lee URLs |

## Requisitos

- Python 3.9+
- [Ollama](https://ollama.com/download) instalado y corriendo
- NVIDIA GPU con CUDA (recomendado, funciona en CPU)
- Windows 10/11

## Instalación

```bash
# 1. Clonar repositorio
git clone https://github.com/DariodelBarrio/ollama-agent.git
cd ollama-agent

# 2. Instalar dependencias Python
pip install -r requirements.txt

# 3. Descargar modelos base
cd "IA\sin censura"
"DESCARGAR MODELOS.bat"

# 4. (Opcional) Construir modelos personalizados con reglas integradas
config\CONSTRUIR MODELOS.bat
```

## Uso

### Desde los accesos directos .bat

```
IA/
├── con censura/
│   ├── SONNET [qwen3 - Coding e inteligente].bat
│   ├── OPUS [deepseek-r1 - Razonamiento profundo].bat
│   └── HAIKU [phi4 - Razonamiento y matematicas].bat
└── sin censura/
    ├── DOLPHIN [dolphin3 - Sin censura rapido].bat
    ├── HERMES [hermes3 - Sin censura preciso].bat
    ├── GROQ [llama3-groq-tool-use - Herramientas optimizado].bat
    ├── DOLPHIN-HACKER [HTB - Pentesting - Exploits].bat
    └── HERMES-HACKER [HTB - Pentesting - Exploits].bat
```

### Desde línea de comandos

```bash
# Modelo por defecto
python src/agent.py

# Modelo y directorio específico
python src/agent.py --model qwen3:14b --dir "C:\mi\proyecto"

# Con contexto y temperatura personalizados
python src/agent.py --model qwen3:14b --ctx 8192 --temp 0.1

# Con nombre personalizado
python src/agent.py --model hermes3:8b --tag "MI-AGENTE"
```

### Argumentos CLI

| Argumento | Default | Descripción |
|-----------|---------|-------------|
| `--model` | `qwen2.5-coder:7b` | Modelo Ollama a usar |
| `--dir` | `.` | Directorio de trabajo del agente |
| `--tag` | `AGENTE` | Nombre que aparece en el header |
| `--ctx` | `16384` | Ventana de contexto en tokens |
| `--temp` | `0.15` | Temperatura (0.0 = determinista, 1.0 = creativo) |

### Comandos de sesión

| Comando | Acción |
|---------|--------|
| `salir` / `exit` / `quit` | Termina el agente |
| `limpiar` / `clear` / `reset` | Reinicia el historial |

## Contexto por modelo y GPU

El contexto por defecto está ajustado para no exceder la VRAM disponible:

| Tamaño modelo | VRAM modelo | Contexto recomendado | KV cache aprox |
|---------------|-------------|----------------------|----------------|
| 7b / 8b | ~5 GB | 32768 (32K) | ~2 GB |
| 14b | ~8.5 GB | 16384 (16K) | ~3 GB |

Con GPU de 12 GB (RTX 5070/4070 Ti): los modelos 14b caben justo con 16K contexto.
Usar 32K en 14b derrama el KV cache a RAM del sistema (lento).

## Modelos Personalizados (Modelfiles)

Los archivos en `config/` definen versiones personalizadas de los modelos con reglas y parámetros integrados:

```
config/
├── Modelfile.sonnet       # qwen3:14b + /no_think + reglas de agente
├── Modelfile.opus         # deepseek-r1:14b + /no_think + reglas de agente
└── CONSTRUIR MODELOS.bat  # crea sonnet-agente y opus-agente con ollama create
```

Beneficio: aunque se llamen desde otra app o directamente con `ollama run sonnet-agente`, se comportan como agentes sin necesitar que el código Python les pase las instrucciones.

## Configuración GPU

Variables de entorno (ya configuradas en los `.bat`):

```bash
set OLLAMA_NUM_GPU=999       # todas las capas en GPU
set OLLAMA_KEEP_ALIVE=-1     # modelo siempre cargado en VRAM
set CUDA_VISIBLE_DEVICES=0   # GPU primaria
```

Para configurarlas permanentemente:

```powershell
setx OLLAMA_NUM_GPU 999
setx OLLAMA_KEEP_ALIVE -1
setx CUDA_VISIBLE_DEVICES 0
```

Verificar:

```bash
ollama ps   # columna PROCESSOR debe mostrar 100% GPU
```

## Parámetros de Modelo

| Parámetro | Valor | Efecto |
|-----------|-------|--------|
| `mirostat` | 2 | Muestreo adaptativo — coherencia superior a top_p fijo |
| `mirostat_tau` | 5.0 | Entropía objetivo equilibrada para código |
| `temperature` | 0.15 | Preciso sin ser robótico |
| `num_ctx` | 16384 | 16K tokens — todo en VRAM para modelos 14b |
| `num_batch` | 512 | Tokens por batch en GPU — mejora utilización |
| `num_predict` | -1 | Sin límite de generación |
| `repeat_penalty` | 1.05 | Evita repeticiones sin cortar creatividad |

## Contexto de Proyecto

El agente carga automáticamente el primer archivo que encuentre en el directorio de trabajo:

1. `CLAUDE.md` — instrucciones para Claude Code
2. `README.md` — documentación del proyecto
3. `.cursorrules` — reglas del editor Cursor

## Estructura del Proyecto

```
ollama-agent/
├── src/
│   └── agent.py                        # Agente principal (12 tools, streaming, Rich UI)
├── IA/
│   ├── con censura/                    # Bats modelos estándar
│   └── sin censura/                    # Bats modelos sin restricciones + hacker
├── config/
│   ├── Modelfile.sonnet                # Modelo personalizado qwen3
│   ├── Modelfile.opus                  # Modelo personalizado deepseek-r1
│   └── CONSTRUIR MODELOS.bat           # Construye sonnet-agente y opus-agente
├── scripts/
│   └── generar_pdf.py
├── docs/
│   └── screenshot.png
├── requirements.txt
└── README.md
```

## Dependencias

```
ollama
rich
duckduckgo-search
requests
beautifulsoup4
fpdf2
```

## Licencia

MIT
