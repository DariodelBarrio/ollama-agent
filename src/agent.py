"""
Agente de programacion local con Ollama - UI estilo Claude Code
Uso: python src/agent.py [--model qwen3:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import logging
import os
import sys
import re
import argparse
import time
import threading
import inspect
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common_tool_schemas import PYDANTIC_AVAILABLE, TOOL_SCHEMA_MAP, ValidationError
from common_tools import WEB_AVAILABLE, ToolRuntime, build_tool_definitions

try:
    from openai import OpenAI
except ImportError:
    print("Instala openai: pip install openai")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.padding import Padding
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.markup import escape
except ImportError:
    print("Instala rich: pip install rich")
    sys.exit(1)

console = Console()


# Colores del tema
C_PROMPT   = "#5B9BD5"
C_BULLET   = "#4EC9B0"
C_TOOL     = "#C586C0"
C_TOOLARG  = "#9CDCFE"
C_OK       = "#6A9955"
C_ERR      = "#F44747"
C_DIM      = "#6E7681"
C_LOGO     = "#E8643B"
C_LOGO2    = "#C0391B"
C_BORDER   = "#30363D"
C_TEXT     = "#D4D4D4"


# Runtime y definiciones de herramientas compartidas
WORK_DIR = "."
ROOT_DIR = str(Path(".").resolve())
_TOOL_RUNTIME = ToolRuntime(WORK_DIR, ROOT_DIR)


def _sync_tool_runtime() -> None:
    _TOOL_RUNTIME.set_workspace(WORK_DIR, ROOT_DIR)


def _sync_tool_globals() -> None:
    global WORK_DIR, ROOT_DIR
    WORK_DIR = _TOOL_RUNTIME.work_dir
    ROOT_DIR = _TOOL_RUNTIME.root_dir


def _wrap_tool(method_name: str):
    method = getattr(_TOOL_RUNTIME, method_name)

    @wraps(method)
    def _wrapped(*args, **kwargs):
        _sync_tool_runtime()
        result = getattr(_TOOL_RUNTIME, method_name)(*args, **kwargs)
        _sync_tool_globals()
        return result

    return _wrapped


def _resolve(path: str) -> Path:
    _sync_tool_runtime()
    resolved = _TOOL_RUNTIME.resolve(path)
    _sync_tool_globals()
    return resolved


run_command = _wrap_tool("run_command")
read_file = _wrap_tool("read_file")
write_file = _wrap_tool("write_file")
edit_file = _wrap_tool("edit_file")
find_files = _wrap_tool("find_files")
grep = _wrap_tool("grep")
list_directory = _wrap_tool("list_directory")
delete_file = _wrap_tool("delete_file")
create_directory = _wrap_tool("create_directory")
move_file = _wrap_tool("move_file")
search_web = _wrap_tool("search_web")
fetch_url = _wrap_tool("fetch_url")
change_directory = _wrap_tool("change_directory")

TOOL_MAP = {
    "run_command": run_command,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "find_files": find_files,
    "grep": grep,
    "list_directory": list_directory,
    "delete_file": delete_file,
    "create_directory": create_directory,
    "move_file": move_file,
    "search_web": search_web,
    "fetch_url": fetch_url,
    "change_directory": change_directory,
}

TOOLS = build_tool_definitions(include_web=True)


# ─── UI ───────────────────────────────────────────────────────────────────────

LOGO_LINES = [
    f"[{C_LOGO}]▄████▄[/]",
    f"[{C_LOGO}]█[/][{C_LOGO2}]▄▄▄▄[/][{C_LOGO}]█[/]",
    f"[{C_LOGO}]█[/][bold white] IA [/][{C_LOGO}]█[/]",
    f"[{C_LOGO}]▀████▀[/]",
]


def print_header(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float):
    console.print()
    logo_text = Text.from_markup("\n".join(LOGO_LINES))
    info = Text()
    info.append(f"  {tag}", style="bold white")
    info.append("  ~  ", style=C_DIM)
    info.append(model, style=C_LOGO)
    info.append("\n")
    internet = "internet · " if WEB_AVAILABLE else ""
    info.append(f"  sin restricciones · {internet}herramientas · streaming", style=C_DIM)
    info.append("\n")
    info.append(f"  ctx:{num_ctx}  temp:{temperature}  {work_dir}", style=C_DIM)
    info.append("\n\n")
    info.append("  'salir' para terminar  ·  'limpiar' nueva sesión", style=C_DIM)
    console.print(Padding(Columns([logo_text, info], padding=(0, 2)), (1, 2)))
    console.print(Rule(style=C_BORDER))
    console.print()


def _render_inline(text: str) -> Text:
    """Aplica highlighting inline: `código` en cian, **negrita** en bold."""
    result = Text()
    i = 0
    while i < len(text):
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j != -1:
                result.append(text[i + 1:j], style=f"bold {C_TOOLARG}")
                i = j + 1
                continue
        if text[i:i + 2] == "**":
            j = text.find("**", i + 2)
            if j != -1:
                result.append(text[i + 2:j], style="bold white")
                i = j + 2
                continue
        result.append(text[i], style=C_TEXT)
        i += 1
    return result


_TOOL_LABELS = {
    "edit_file":        ("Update",  "path"),
    "write_file":       ("Write",   "path"),
    "read_file":        ("Read",    "path"),
    "run_command":      ("Bash",    "command"),
    "find_files":       ("Glob",    "pattern"),
    "grep":             ("Grep",    "pattern"),
    "list_directory":   ("LS",      "path"),
    "delete_file":      ("Delete",  "path"),
    "create_directory": ("Mkdir",   "path"),
    "move_file":        ("Move",    "src"),
    "search_web":       ("Web",     "query"),
    "fetch_url":        ("Fetch",   "url"),
    "change_directory": ("CD",      "path"),
}


def _rel(path_str: str) -> str:
    """Convierte ruta absoluta a relativa al WORK_DIR si es posible."""
    try:
        return str(Path(path_str).relative_to(Path(WORK_DIR)))
    except ValueError:
        return path_str


def print_tool_call(name: str, args: dict):
    if name in _TOOL_LABELS:
        label, key = _TOOL_LABELS[name]
        arg_val = _rel(str(args.get(key, "")))[:90]
        t = Text()
        t.append("● ", style=f"bold {C_BULLET}")
        t.append(label, style=f"bold {C_TOOL}")
        t.append("(", style=C_DIM)
        t.append(arg_val, style=C_TOOLARG)
        t.append(")", style=C_DIM)
        console.print(t)
    else:
        t = Text()
        t.append("● ", style=f"bold {C_BULLET}")
        t.append(name, style=f"bold {C_TOOL}")
        t.append("(", style=C_DIM)
        parts = [f"{k}={repr(v)[:80]}" for k, v in args.items()]
        t.append(", ".join(parts), style=C_TOOLARG)
        t.append(")", style=C_DIM)
        console.print(t)


def _print_diff(result: dict):
    added   = result.get("added",   0)
    removed = result.get("removed", 0)
    entries = result.get("diff",    [])

    summary = Text()
    summary.append("  └ ", style=C_DIM)
    parts = []
    if added:
        parts.append(Text(f"Added {added} {'line' if added == 1 else 'lines'}", style=C_OK))
    if removed:
        parts.append(Text(f"removed {removed} {'line' if removed == 1 else 'lines'}", style=C_ERR))
    if parts:
        summary.append_text(parts[0])
        for p in parts[1:]:
            summary.append(", ", style=C_DIM)
            summary.append_text(p)
    console.print(summary)

    for ln, kind, content in entries:
        row = Text(overflow="fold")
        num = f"{ln:4}"
        if kind == "removed":
            row.append(f"{num} ", style=C_DIM)
            row.append("- ", style=f"bold {C_ERR}")
            row.append(f"  {content}", style=f"{C_ERR} on #2d0000")
        elif kind == "added":
            row.append(f"{num} ", style=C_DIM)
            row.append("+ ", style=f"bold {C_OK}")
            row.append(f"  {content}", style=f"{C_OK} on #002d00")
        else:
            row.append(f"{num}   ", style=C_DIM)
            row.append(f"  {content}", style=C_DIM)
        console.print(row)


def print_tool_result(result: dict):
    t = Text()
    if "error" in result:
        t.append("  ✗ ", style=C_ERR)
        t.append(result["error"], style=C_ERR)
    elif "diff" in result:
        _print_diff(result)
        return
    elif "stdout" in result:
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        rc  = result.get("returncode", 0)
        t.append("  ✓ ", style=C_OK)
        if out:
            # Sin truncamiento cuando hay error — salida completa para diagnosticar
            if rc != 0:
                t.append(out, style=C_TEXT)
            else:
                t.append(out[:1000] + ("…" if len(out) > 1000 else ""), style=C_TEXT)
        if err:
            # stderr siempre completo — es información crítica
            t.append(f"\n    stderr: {err}", style=C_ERR)
        if rc != 0:
            t.append(f"  [rc={rc}]", style=C_ERR)
    elif "content" in result and "url" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result.get('chars', 0)} chars  ·  {result['url'][:60]}", style=C_DIM)
    elif "content" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result['lines']} líneas  ·  {result['path']}", style=C_DIM)
    elif "query" in result and "results" in result:
        t.append("  ✓ ", style=C_OK)
        items = result["results"]
        t.append(f"{len(items)} resultados para: {result['query']}\n", style=C_DIM)
        for r in items[:3]:
            t.append(f"    · {r.get('title', '')[:70]}\n", style=C_TEXT)
            snippet = r.get("snippet", "")[:100]
            if snippet:
                t.append(f"      {snippet}…\n", style=C_DIM)
    elif "files" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{len(result['files'])} archivos encontrados", style=C_DIM)
    elif "results" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{len(result['results'])} coincidencias", style=C_DIM)
    elif "cwd" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"directorio → {result['cwd']}", style=C_TOOLARG)
    elif "success" in result:
        t.append("  ✓ ", style=C_OK)
        detail = result.get("to") or result.get("path") or result.get("deleted") or "ok"
        t.append(detail, style=C_DIM)
    else:
        t.append("  ✓ ", style=C_OK)
        t.append("ok", style=C_DIM)
    console.print(t)


def get_input(color: str = C_PROMPT) -> str:
    console.print()
    try:
        console.print(f"[{color}]>[/] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        return "salir"


# ─── Prompts ──────────────────────────────────────────────────────────────────

def build_system_prompt(work_dir: str, project_context: str,
                        mode: str = "", mode_snippet: str = "") -> str:
    """
    Fuente principal de instrucciones del agente.
    Cualquier SYSTEM en el Modelfile de Ollama solo debe definir parámetros
    o instrucciones muy generales — este prompt tiene precedencia en toda
    lógica de comportamiento, herramientas y reglas de ejecución.
    """
    desktop = str(Path.home() / "Desktop")
    return f"""Eres un agente autónomo de programación. Directorio de trabajo: {work_dir}
Escritorio del usuario: {desktop}

{project_context}

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #1 — NUNCA LE DIGAS AL USUARIO QUÉ HACER
═══════════════════════════════════════════════════════
PROHIBIDO escribir frases como:
  ✗ "Puedes ejecutar: git status"
  ✗ "Deberías correr: npm install"
  ✗ "Para ver el archivo usa: cat main.py"
  ✗ "Te recomiendo que hagas..."
  ✗ "Primero debes..., luego..."

En su lugar: HAZLO TÚ MISMO con las herramientas. PUNTO.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #2 — ENCADENA PASOS SIN PARAR NI PREGUNTAR
═══════════════════════════════════════════════════════
Ejecuta la tarea completa de principio a fin:
  1. Llamas las herramientas necesarias en secuencia
  2. Usas el resultado de cada herramienta para decidir el siguiente paso
  3. No te detienes a mitad a explicar — terminas la tarea
  4. Solo al final reportas qué hiciste y el resultado

PROHIBIDO:
  ✗ "¿Quieres que continúe?"
  ✗ "¿Procedo con el siguiente paso?"
  ✗ "¿Te parece bien si...?"

Si tienes suficiente información → HAZLO.
Solo pregunta si te falta algo que NO puedes obtener con herramientas.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #3 — DIRECTORIO CORRECTO ANTES DE ACTUAR
═══════════════════════════════════════════════════════
Si el usuario menciona un directorio específico (ej. "en C:\\proyecto", "en la carpeta X",
"en D:\\trabajo\\app"), llama PRIMERO a change_directory(path) para establecerlo como
directorio activo. A partir de ese momento todas las rutas relativas apuntan ahí.
NUNCA ignores el directorio que el usuario indica — cámbialo antes de operar.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #4 — LEE ANTES DE TOCAR
═══════════════════════════════════════════════════════
SIEMPRE usa read_file() antes de edit_file(). Sin excepciones.
Si no conoces la estructura, usa list_directory() primero.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #5 — CREAR ARCHIVOS = USAR write_file()
═══════════════════════════════════════════════════════
Cuando el usuario pide "hazme un script / crea un archivo / escribe un programa":
  → USA write_file(path, content) — NUNCA muestres el código en el chat
  → NUNCA digas "no puedo crear archivos"

Rutas:
  "en el escritorio" → {desktop}\\nombre.py
  "aquí"             → ruta relativa al directorio de trabajo

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #6 — EXPLORA ANTES DE CONSTRUIR
═══════════════════════════════════════════════════════
Si no estás 100% seguro de cómo proceder (uso de una API, estructura de un
archivo, librería desconocida, comportamiento de un comando):
  → USA search_web() y fetch_url() para investigar la documentación real.
  → USA list_directory() y read_file() para entender el contexto del proyecto.
Es MEJOR gastar tokens en investigación que en intentos fallidos.
No adivines. No inventes. Investiga.

═══════════════════════════════════════════════════════
HERRAMIENTAS DISPONIBLES
═══════════════════════════════════════════════════════
- run_command(command, shell?)         → PowerShell en Windows, bash en Linux/macOS
- read_file(path)                      → lee archivos con números de línea
- write_file(path, content)            → crea archivos nuevos
- edit_file(path, old, new, replace_all?, use_regex?) → edita archivos
- find_files(pattern, path?)           → glob: **/*.py, src/**/*.ts
- grep(pattern, path?, ext?)           → busca texto/regex en el código
- list_directory(path?)                → lista contenido de carpeta
- delete_file(path)                    → elimina archivos o carpetas
- create_directory(path)               → crea carpetas y subcarpetas
- move_file(src, dst)                  → mueve o renombra
- change_directory(path)               → cambia el directorio de trabajo activo
- search_web(query)                    → DuckDuckGo para info actual
- fetch_url(url)                       → descarga y lee una URL

═══════════════════════════════════════════════════════
PROYECTOS WEB
═══════════════════════════════════════════════════════
ANTES de cualquier tarea: list_directory() + read_file("package.json" o "requirements.txt")

"crea un componente React"
  → find_files("**/*.tsx") para ver el estilo del proyecto
  → write_file componente + estilos + index.ts export

"agrega endpoint"
  → read_file de rutas existentes → edit_file manteniendo el patrón

Patrones multi-archivo: crea TODOS los archivos necesarios (componente + estilos + tipos + export)

═══════════════════════════════════════════════════════
BASES DE DATOS Y MIGRACIONES
═══════════════════════════════════════════════════════
SIEMPRE lee el schema actual antes de modificar.

Prisma:   edit schema → npx prisma migrate dev → npx prisma generate
Django:   edit models.py → python manage.py makemigrations → migrate
Alembic:  edit models → alembic revision --autogenerate → alembic upgrade head
Drizzle:  edit schema → drizzle-kit generate → drizzle-kit migrate
SQL:      write_file migration.sql → run_command para ejecutarla

Nunca ejecutes migrate sin haber editado el schema primero.
Confirma con el usuario antes de cambios destructivos en BD.

═══════════════════════════════════════════════════════
AUTOCORRECCIÓN Y VERIFICACIÓN
═══════════════════════════════════════════════════════
Si una herramienta devuelve error (run_command rc!=0, edit_file texto no encontrado, etc.):
  1. Lee el mensaje de error COMPLETO, especialmente stderr — es información crítica.
  2. Revisa tu <thought> anterior y el contexto del proyecto (re-lee archivos si hace falta).
  3. Formula una nueva hipótesis sobre la causa raíz del fallo.
  4. Ejecuta la corrección inmediatamente — sin explicar al usuario.
  5. Repite hasta 3 intentos por problema.
  → Solo si después de 3 intentos fallidos no puedes resolverlo, reporta al usuario
    con: qué intentaste, qué devolvió cada intento, y tu hipótesis sobre la causa.

Reglas adicionales:
  - Si un enfoque no funciona → prueba uno DIFERENTE, no repitas lo mismo ciegamente.
  - Después de edit_file fallido → re-lee el archivo para obtener el old_text exacto.
  - Después de write_file → verifica con read_file que el contenido es correcto.

═══════════════════════════════════════════════════════
CALIDAD DE CÓDIGO
═══════════════════════════════════════════════════════
- Código idiomático: Pythonic, ES6+, SQL limpio
- Maneja errores en boundaries (I/O, red, BD)
- Nombres descriptivos, funciones pequeñas con una sola responsabilidad
- Si hay tests existentes: córrelos después de cambiar código

═══════════════════════════════════════════════════════
RAZONAMIENTO INTERNO (Chain of Thought — First Principles)
═══════════════════════════════════════════════════════
SIEMPRE, antes de responder o llamar a una herramienta, razona internamente.
Usa el siguiente formato ESTRUCTURADO y RIGUROSO:

<thought>
**1. Entendimiento:** El usuario solicita [resumen exacto de la tarea en mis propias palabras].
**2. Desglose y Primeros Principios:** Para lograr esto necesito [componentes clave, dependencias, conceptos fundamentales].
**3. Plan de Acción:**
   a. [Herramienta 1] con [argumentos] para [propósito concreto].
   b. [Herramienta 2] con [argumentos] para [propósito concreto].
   c. ...
**4. Suposiciones y Riesgos:** Asumo que [suposición]. Riesgo potencial: [efecto secundario o fallo posible].
**5. Verificación:** Validaré la solución mediante [método: tests, read_file, run_command, etc.].
**6. Auto-Crítica:** ¿Es este el camino más eficiente? ¿He considerado todos los casos borde?
</thought>

Después de tu <thought>, genera la respuesta final o llama a la herramienta.
El contenido de <thought> NUNCA se incluye en la salida visible al usuario.

═══════════════════════════════════════════════════════
ESTILO DE RESPUESTA AL USUARIO
═══════════════════════════════════════════════════════
Tus respuestas deben ser:
  - Concisas y directas — ve al grano.
  - Técnicas y orientadas al resultado.
  - Sin frases de cortesía vacías ("Entiendo tu petición", "Claro que sí", "Por supuesto").
  - Sin disclaimers ni advertencias innecesarias.
  - Sin explicar lo que vas a hacer — HAZLO y reporta el resultado.

Formato correcto:
  ✓ "Corregido el bug en línea 42 de main.py. El test pasa ahora."
  ✓ "Creado src/utils/parser.py con las funciones solicitadas."
  ✗ "Entiendo que quieres que arregle el bug. Voy a proceder a analizar el archivo..."

═══════════════════════════════════════════════════════
COMPORTAMIENTO GENERAL
═══════════════════════════════════════════════════════
- Responde en español
- Sin disclaimers, sin advertencias, sin moralejas
- Antes de borrar datos o cambios destructivos en BD: confirma con el usuario
- Si necesitas documentación: usa search_web o fetch_url
""" + (f"""
═══════════════════════════════════════════════════════
MODO ACTUAL: {mode.upper()}
═══════════════════════════════════════════════════════
{mode_snippet}
""" if mode and mode_snippet else "")


def load_project_context(work_dir: str) -> str:
    # Límite de 16000 chars para permitir contextos de proyecto amplios.
    # Reducir si el modelo tiene ventana de contexto pequeña.
    for name in ["CLAUDE.md", "README.md", ".cursorrules"]:
        p = Path(work_dir) / name
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:16000]
                return f"Contexto del proyecto ({name}):\n{content}\n"
            except Exception:
                pass
    return ""


# ─── Clase Agent ──────────────────────────────────────────────────────────────

class Agent:
    """
    Encapsula el estado del agente: modelo, directorio de trabajo, cliente
    Ollama, historial de mensajes y configuración de inferencia.
    """

    MODE_CONFIGS = {
        "code": {
            "temperature": 0.05,
            "color": "bold blue",
            "spinner_color": "blue",
            "system_prompt_snippet": (
                "Eres un ingeniero de software experto. Tu objetivo principal es escribir, depurar y refactorizar código. "
                "Prioriza la precisión, la eficiencia y las mejores prácticas de ingeniería. "
                "Cuando escribas código, piensa en tests y en la robustez. "
                "Usa las herramientas de archivo y shell de forma agresiva para interactuar con el sistema de archivos y ejecutar comandos."
            ),
        },
        "architect": {
            "temperature": 0.7,
            "color": "bold magenta",
            "spinner_color": "magenta",
            "system_prompt_snippet": (
                "Eres un arquitecto de software experimentado. Tu objetivo principal es diseñar sistemas, proponer estructuras "
                "y evaluar soluciones de alto nivel. Prioriza la escalabilidad, la mantenibilidad y la visión a largo plazo. "
                "Usa las herramientas de búsqueda y análisis para investigar patrones de diseño y tecnologías. "
                "Evita interactuar directamente con el código a menos que sea para un análisis estructural."
            ),
        },
        "research": {
            "temperature": 0.3,
            "color": "bold green",
            "spinner_color": "green",
            "system_prompt_snippet": (
                "Eres un investigador experto. Tu objetivo principal es recopilar información, analizar datos y sintetizar conocimientos. "
                "Prioriza la exhaustividad y la verificación de fuentes. "
                "Usa las herramientas de búsqueda web y lectura de archivos para explorar y comprender nuevos temas. "
                "Resume la información de manera concisa y objetiva."
            ),
        },
    }

    def __init__(self, model: str, work_dir: str, tag: str,
                 num_ctx: int, temperature: float,
                 api_base: str = "http://localhost:11434/v1",
                 system_prompt_path: Optional[str] = None):
        global WORK_DIR, ROOT_DIR
        self.model        = model
        self.work_dir     = str(Path(work_dir).resolve())
        self.tag          = tag
        self.num_ctx      = num_ctx
        self.temperature  = temperature
        self.api_base     = api_base
        self.current_mode = "code"
        self.client       = OpenAI(base_url=api_base, api_key="sk-no-key-required")
        self.messages: list = []
        self.system_prompt_path = Path(system_prompt_path).resolve() if system_prompt_path else None
        # Actualiza la variable global para que las funciones de herramientas
        # (module-level) resuelvan rutas relativas al directorio correcto.
        WORK_DIR = self.work_dir
        ROOT_DIR = self.work_dir

        # Logger de auditoría — escribe en work_dir/agent_session.jsonl
        log_path = Path(self.work_dir) / "agent_session.jsonl"
        self.logger = _make_logger(f"agent.{id(self)}", log_path)

    def _read_system_prompt_override(self) -> Optional[str]:
        """Lee un prompt de sistema externo si se proporcionó la ruta."""
        if not self.system_prompt_path:
            return None
        try:
            return self.system_prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            self.logger.error(
                "No se pudo leer el prompt externo",
                extra={"error_details": str(e)}
            )
            return None

    def _build_options(self) -> dict:
        return {
            "temperature": self.MODE_CONFIGS[self.current_mode]["temperature"],
            "top_p":       0.85,
            "top_k":       20,
        }

    def _trim_history(self, max_pairs: int = 20) -> list:
        system = [m for m in self.messages if m["role"] == "system"]
        rest   = [m for m in self.messages if m["role"] != "system"]
        return system + rest[-(max_pairs * 4):]

    def _stream_response(self, messages: list, tools: list):
        """Hace streaming y devuelve (content, tool_calls).
        Detecta bloques <think>...</think> y los muestra en gris dim."""
        collected: list[str] = []
        tc_accum:  dict      = {}   # index → {id, name, args}
        opts = self._build_options()
        first_output = [True]
        t_start = time.monotonic()

        def _drain(stream_iter):
            state = None
            thought_buf: list[str] = []
            buf = ""
            for chunk in stream_iter:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                # Acumular tool_calls por índice
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "args": []}
                        if tc_delta.id:
                            tc_accum[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc_accum[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tc_accum[idx]["args"].append(tc_delta.function.arguments)
                content = delta.content or ""
                if not content:
                    continue
                if first_output[0]:
                    live.stop()
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    first_output[0] = False
                buf += content
                while True:
                    if state is None:
                        ti  = buf.find("<think>")
                        thi = buf.find("<thought>")
                        first_tag = None
                        first_pos = len(buf)
                        if ti  != -1 and ti  < first_pos: first_pos, first_tag = ti,  "think"
                        if thi != -1 and thi < first_pos: first_pos, first_tag = thi, "thought"
                        if first_tag is None:
                            cut = max(0, len(buf) - 9)
                            if cut:
                                console.print(_render_inline(buf[:cut]), end="")
                                collected.append(buf[:cut])
                                buf = buf[cut:]
                            break
                        if first_pos:
                            console.print(_render_inline(buf[:first_pos]), end="")
                            collected.append(buf[:first_pos])
                        if first_tag == "think":
                            buf = buf[first_pos + 7:]
                            state = "think"
                            console.print(f"\n[{C_DIM}]  💭 ", end="")
                        else:
                            buf = buf[first_pos + 9:]
                            state = "thought"
                            thought_buf = []
                    elif state == "thought":
                        i = buf.find("</thought>")
                        if i == -1:
                            cut = max(0, len(buf) - 10)
                            if cut:
                                thought_buf.append(buf[:cut])
                                buf = buf[cut:]
                            break
                        thought_buf.append(buf[:i])
                        buf = buf[i + 10:]
                        state = None
                        thought_content = "".join(thought_buf)
                        if thought_content.strip():
                            self.logger.debug(
                                "Razonamiento interno",
                                extra={"tool_args": {"thought": thought_content[:2000]}}
                            )
                        console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    else:  # state == "think"
                        i = buf.find("</think>")
                        if i == -1:
                            cut = max(0, len(buf) - 8)
                            if cut:
                                console.print(f"[{C_DIM}]{escape(buf[:cut])}[/]", end="")
                                buf = buf[cut:]
                            break
                        if i:
                            console.print(f"[{C_DIM}]{escape(buf[:i])}[/]", end="")
                        buf = buf[i + 8:]
                        state = None
                        console.print(f"\n[{C_BULLET}]●[/] ", end="")
            if buf.strip():
                if state == "thought":
                    thought_buf.append(buf)
                elif state == "think":
                    console.print(f"[{C_DIM}]{escape(buf)}[/]", end="")
                else:
                    console.print(_render_inline(buf), end="")
                    collected.append(buf)

        spinner_color = self.MODE_CONFIGS[self.current_mode]["spinner_color"]
        with Live(Spinner("dots", text="Pensando... 0s", style=spinner_color), console=console, transient=True, refresh_per_second=4) as live:
            def _tick():
                while first_output[0]:
                    elapsed = time.monotonic() - t_start
                    live.update(Spinner("dots", text=f"Pensando... {elapsed:.0f}s", style=spinner_color))
                    time.sleep(0.25)
            threading.Thread(target=_tick, daemon=True).start()

            _ollama_extra = {"options": {
                "num_ctx":        self.num_ctx,
                "num_gpu":        99,
                "top_k":          opts["top_k"],
                "repeat_penalty": 1.05,
                "num_predict":    -1,
            }}
            try:
                _drain(self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                    temperature=opts["temperature"],
                    top_p=opts["top_p"],
                    stream=True,
                    extra_body=_ollama_extra,
                ))
            except Exception as e:
                if first_output[0]:
                    live.stop()
                    first_output[0] = False
                if "tool" in str(e).lower():
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    _drain(self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=opts["temperature"],
                        top_p=opts["top_p"],
                        stream=True,
                        extra_body=_ollama_extra,
                    ))
                else:
                    console.print(f"\n[{C_ERR}]Error: {e}[/]")
                    self.logger.error(
                        "Error en streaming LLM",
                        extra={"error_details": str(e)},
                        exc_info=True
                    )

        elapsed_total = time.monotonic() - t_start

        # Construir lista de tool_calls desde el acumulador
        tool_calls = []
        for idx in sorted(tc_accum):
            entry = tc_accum[idx]
            args_str = "".join(entry["args"])
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({
                "id":        entry["id"] or entry["name"],
                "name":      entry["name"],
                "arguments": args,
            })

        if not tool_calls:
            console.print()
        console.print(f"[{C_DIM}]✳ Brewed for {elapsed_total:.0f}s[/]")

        return "".join(collected), tool_calls

    def _validate_tool_args(self, fn_name: str, args: dict) -> dict:
        """Valida argumentos contra el modelo Pydantic correspondiente.
        Devuelve los argumentos validados (con defaults aplicados) o un dict con 'error'."""
        if not PYDANTIC_AVAILABLE:
            return args
        model_cls = TOOL_SCHEMA_MAP.get(fn_name)
        if not model_cls:
            return args
        try:
            validated = model_cls(**args)
            return validated.model_dump()
        except ValidationError as e:
            msgs = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
            return {"error": f"ValidationError en '{fn_name}': {msgs}"}

    def _invoke_tool(self, fn_name: str, fn_args: dict) -> dict:
        fn = TOOL_MAP[fn_name]
        try:
            inspect.signature(fn).bind(**fn_args)
        except TypeError as e:
            return {"error": f"Argumentos inválidos para '{fn_name}': {e}"}
        try:
            return fn(**fn_args)
        except Exception as e:
            self.logger.error(
                "Excepción en herramienta",
                extra={"tool_name": fn_name, "error_details": str(e)},
                exc_info=True
            )
            return {"error": f"Excepción ejecutando '{fn_name}': {e}"}

    def _validate_model(self) -> bool:
        try:
            available = [m.id for m in self.client.models.list().data]
            if self.model not in available:
                console.print(f"\n[{C_ERR}]Modelo '{self.model}' no encontrado. Disponibles:[/]")
                for m in available:
                    console.print(f"  [{C_DIM}]·[/] {m}")
                if available:
                    self.model = available[0]
                    console.print(f"[{C_OK}]→ Usando '{self.model}'[/]\n")
                else:
                    return False
            return True
        except Exception:
            return True

    def run(self):
        if not self._validate_model():
            sys.exit(1)

        project_context = load_project_context(self.work_dir)

        def _make_system_prompt() -> str:
            cfg = self.MODE_CONFIGS[self.current_mode]
            override = self._read_system_prompt_override()
            if override:
                try:
                    return override.format(
                        work_dir=self.work_dir,
                        project_context=project_context,
                        mode=self.current_mode,
                        mode_snippet=cfg["system_prompt_snippet"],
                    )
                except Exception as e:
                    self.logger.error(
                        "Falló el formateo del prompt externo",
                        extra={"error_details": str(e)}
                    )
                    return override
            return build_system_prompt(
                self.work_dir, project_context,
                self.current_mode, cfg["system_prompt_snippet"]
            )

        system_prompt = _make_system_prompt()
        self.messages = [{"role": "system", "content": system_prompt}]

        self.logger.info("Sesión iniciada", extra={
            "tool_args": {
                "model": self.model, "work_dir": self.work_dir,
                "tag": self.tag, "num_ctx": self.num_ctx,
                "temperature": self.temperature,
            }
        })

        print_header(self.model, self.work_dir, self.tag, self.num_ctx, self.temperature)

        while True:
            prompt_color = self.MODE_CONFIGS[self.current_mode]["color"]
            user_input = get_input(prompt_color)

            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                console.print(f"\n[{C_DIM}]  Hasta luego.[/]\n")
                self.logger.info("Sesión finalizada por el usuario")
                break
            if user_input.lower() in ("limpiar", "clear", "reset"):
                system_prompt = _make_system_prompt()
                self.messages = [{"role": "system", "content": system_prompt}]
                console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
                self.logger.info("Historial limpiado")
                continue
            if user_input.lower().startswith("/mode"):
                parts = user_input.split(maxsplit=1)
                if len(parts) == 2 and parts[1].lower() in self.MODE_CONFIGS:
                    self.current_mode = parts[1].lower()
                    system_prompt = _make_system_prompt()
                    self.messages[0] = {"role": "system", "content": system_prompt}
                    color = self.MODE_CONFIGS[self.current_mode]["color"]
                    console.print(f"[{color}]  ✓ Modo: {self.current_mode.upper()}[/]")
                    self.logger.info("Modo cambiado", extra={"tool_args": {"mode": self.current_mode}})
                else:
                    modes = " | ".join(self.MODE_CONFIGS.keys())
                    console.print(f"[{C_ERR}]  Uso: /mode [{modes}][/]")
                continue

            self.logger.info("Mensaje del usuario", extra={"user_input": user_input})
            self.messages.append({"role": "user", "content": user_input})

            while True:
                trimmed = self._trim_history()
                full_content, tool_calls = self._stream_response(trimmed, TOOLS)

                if full_content:
                    self.logger.info(
                        "Respuesta del asistente",
                        extra={"assistant_response": full_content[:2000]}
                    )

                if tool_calls:
                    console.print()
                    self.messages.append({
                        "role": "assistant",
                        "content": full_content or None,
                        "tool_calls": [
                            {"id": tc["id"], "type": "function",
                             "function": {"name": tc["name"],
                                          "arguments": json.dumps(tc["arguments"])}}
                            for tc in tool_calls
                        ]
                    })
                    for tc in tool_calls:
                        fn_name = tc["name"]
                        fn_args = tc["arguments"]
                        if fn_name in TOOL_MAP:
                            fn_args = self._validate_tool_args(fn_name, fn_args)
                            if "error" in fn_args:
                                result = fn_args
                                self.logger.warning(
                                    "Validación de argumentos fallida",
                                    extra={"tool_name": fn_name, "error_details": fn_args["error"]}
                                )
                            else:
                                self.logger.debug(
                                    "Llamada a herramienta",
                                    extra={"tool_name": fn_name, "tool_args": fn_args}
                                )
                                print_tool_call(fn_name, fn_args)
                                result = self._invoke_tool(fn_name, fn_args)
                                self.logger.debug(
                                    "Resultado de herramienta",
                                    extra={
                                        "tool_name": fn_name,
                                        "tool_result": {
                                            k: (str(v)[:500] if isinstance(v, str) else v)
                                            for k, v in result.items()
                                        }
                                    }
                                )
                                if "error" in result:
                                    self.logger.error(
                                        "Herramienta devolvió error",
                                        extra={"tool_name": fn_name, "error_details": result["error"]}
                                    )
                        else:
                            result = {"error": f"Tool desconocida: {fn_name}"}
                            self.logger.error(
                                "Tool desconocida",
                                extra={"tool_name": fn_name, "error_details": result["error"]}
                            )
                        print_tool_result(result)
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                else:
                    self.messages.append({"role": "assistant", "content": full_content})
                    break


# ─── Entry point ──────────────────────────────────────────────────────────────

RECOMMENDED_MODELS = [
    # ── Todo en VRAM 12GB · RTX 5070 · rápido ─────────────────────────────────
    ("qwen2.5-coder:14b",     "Coding · ~8.5GB VRAM · Mejor coder todo-GPU",   "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:14b",       "Razonamiento · ~8.5GB VRAM · Thinking model",   "⭐⭐⭐⭐⭐"),
    ("deepseek-coder-v2:16b", "Coding MoE · ~10GB VRAM · Muy eficiente",       "⭐⭐⭐⭐⭐"),
    ("mistral-nemo:12b",      "General+Coding · ~7.5GB VRAM · Multilingüe",    "⭐⭐⭐⭐ "),
    ("dolphin3:8b",           "Sin censura · ~5GB VRAM · Llama3-based",        "⭐⭐⭐⭐ "),
    ("qwen2.5-coder:7b",      "Coding · ~4.5GB VRAM · Más rápido",             "⭐⭐⭐⭐ "),
    # ── VRAM + RAM offload · más potente · algo más lento ─────────────────────
    ("qwen2.5-coder:32b",     "Coding · ~12+7GB RAM · Máxima calidad",         "⭐⭐⭐⭐⭐"),
    ("codestral:22b",         "Coding · ~13GB VRAM+RAM · Mistral coding",      "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:32b",       "Razonamiento · ~12+7GB RAM · Thinking máximo",  "⭐⭐⭐⭐⭐"),
    ("dolphin-mistral:7b",    "Sin censura · ~4.5GB VRAM · Mistral-based",     "⭐⭐⭐⭐ "),
]


def select_model_menu(api_base: str = "http://localhost:11434/v1") -> str:
    """Menú interactivo de selección de modelo al arrancar."""
    try:
        _client = OpenAI(base_url=api_base, api_key="sk-no-key-required")
        installed = {m.id for m in _client.models.list().data}
    except Exception:
        installed = set()

    console.print(f"\n[{C_LOGO}]  Selecciona un modelo para esta sesión:[/]\n")

    rec_names = [r[0] for r in RECOMMENDED_MODELS]
    for i, (model, desc, stars) in enumerate(RECOMMENDED_MODELS, 1):
        tick = f"[{C_OK}]✓[/]" if model in installed else f"[{C_DIM}] [/]"
        console.print(f"  [{C_LOGO}]{i:2}[/]  {tick}  {stars}  [bold]{model}[/]")
        console.print(f"           [{C_DIM}]{desc}[/]")

    others = sorted(m for m in installed if m not in rec_names)
    if others:
        console.print(f"\n  [{C_DIM}]── Otros instalados ──[/]")
        for i, m in enumerate(others, len(RECOMMENDED_MODELS) + 1):
            console.print(f"  [{C_DIM}]{i:2}  ✓  {m}[/]")

    all_models = rec_names + others
    default = "qwen2.5-coder:14b"
    console.print(f"\n  [{C_DIM}]Número, nombre exacto, o Enter [{default}]:[/] ", end="")

    try:
        choice = input("").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return default

    if not choice:
        return default
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(all_models):
            return all_models[idx]
    return choice


def run_agent(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float,
              api_base: str = "http://localhost:11434/v1",
              system_prompt_path: Optional[str] = None):
    Agent(model, work_dir, tag, num_ctx, temperature, api_base, system_prompt_path).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente local con Ollama/vLLM/LMDeploy/LM Studio")
    parser.add_argument("--model",    default=None,  help="Modelo (omitir para menú interactivo)")
    parser.add_argument("--dir",      default=".")
    parser.add_argument("--tag",      default="AGENTE")
    parser.add_argument("--ctx",      type=int,   default=16384, help="Ventana de contexto en tokens")
    parser.add_argument("--temp",     type=float, default=0.15,  help="Temperatura 0.0-1.0")
    parser.add_argument("--api-base", default="http://localhost:11434/v1",
                        help="URL base API compatible OpenAI (Ollama, vLLM, LMDeploy, LM Studio)")
    parser.add_argument("--system-prompt", default=None,
                        help="Ruta de archivo para usar como prompt de sistema")
    args = parser.parse_args()
    model = args.model if args.model else select_model_menu(args.api_base)
    run_agent(model, args.dir, args.tag, args.ctx, args.temp, args.api_base, args.system_prompt)

