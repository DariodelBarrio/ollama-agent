"""
Agente de programacion local con Ollama - UI estilo Claude Code
Uso: python src/agent.py [--model qwen3:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import subprocess
import platform
import os
import sys
import re
import shutil
import argparse
from pathlib import Path

try:
    import ollama
except ImportError:
    print("Instala ollama: pip install ollama")
    sys.exit(1)

try:
    import requests
    from bs4 import BeautifulSoup
    from duckduckgo_search import DDGS
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

try:
    from rich.console import Console
    from rich.text import Text
    from rich.padding import Padding
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.markup import escape
except ImportError:
    print("Instala rich: pip install rich")
    sys.exit(1)

console = Console()

# ── Colores del tema ──────────────────────────────────────────────────────────
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

# Actualizado por Agent.__init__ — las funciones de herramientas lo leen vía _resolve()
WORK_DIR = "."

_OS = platform.system()  # "Windows", "Linux", "Darwin"

# ─── Herramientas ─────────────────────────────────────────────────────────────

def run_command(command: str, shell: str = "auto", timeout: int = 60) -> dict:
    """
    Ejecuta un comando en el shell apropiado para el SO actual.
    shell="auto" usa powershell en Windows y bash en Linux/macOS.
    Evita shell=True pasando el comando como lista de argumentos.
    """
    try:
        effective_shell = shell
        if shell == "auto":
            effective_shell = "powershell" if _OS == "Windows" else "bash"

        if effective_shell == "powershell":
            cmd = ["powershell", "-NoProfile", "-Command", command]
        elif effective_shell == "bash":
            cmd = ["bash", "-c", command]
        elif effective_shell == "sh":
            cmd = ["sh", "-c", command]
        else:  # cmd — fallback con shell=True solo para este caso
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=WORK_DIR
            )
            return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=WORK_DIR)
        return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout: el comando tardó más de {timeout}s"}
    except FileNotFoundError as e:
        return {"error": f"Shell no encontrado ({effective_shell}): {e}"}
    except Exception as e:
        return {"error": str(e)}


def read_file(path: str) -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"error": f"Archivo no encontrado: {path}"}
        if p.stat().st_size > 2_000_000:
            return {"error": "Archivo demasiado grande (>2MB)"}
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        numbered = "\n".join(f"{i+1:4}: {l}" for i, l in enumerate(lines))
        return {"content": numbered, "path": str(p), "lines": len(lines)}
    except Exception as e:
        return {"error": str(e)}


def write_file(path: str, content: str) -> dict:
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"success": True, "path": str(p), "lines": len(content.splitlines())}
    except Exception as e:
        return {"error": str(e)}


def edit_file(path: str, old_text: str, new_text: str,
              replace_all: bool = False, use_regex: bool = False) -> dict:
    """
    Edita un archivo.
    - replace_all=True  → reemplaza todas las ocurrencias (no solo la primera)
    - use_regex=True    → old_text se interpreta como expresión regular
    """
    try:
        p = _resolve(path)
        if not p.exists():
            return {"error": f"Archivo no encontrado: {path}"}
        content = p.read_text(encoding="utf-8", errors="replace")

        if use_regex:
            try:
                pattern = re.compile(old_text, re.MULTILINE)
            except re.error as e:
                return {"error": f"Regex inválida: {e}"}
            if not pattern.search(content):
                return {"error": "Patrón regex no encontrado en el archivo."}
            count = len(pattern.findall(content))
            new_content = pattern.sub(new_text, content) if replace_all \
                          else pattern.sub(new_text, content, count=1)
        else:
            if old_text not in content:
                return {"error": "Texto no encontrado. Debe ser exacto (incluyendo espacios e indentación)."}
            count = content.count(old_text)
            new_content = content.replace(old_text, new_text) if replace_all \
                          else content.replace(old_text, new_text, 1)

        p.write_text(new_content, encoding="utf-8")
        replaced = count if replace_all else 1
        return {"success": True, "path": str(p), "replaced": replaced}
    except Exception as e:
        return {"error": str(e)}


def find_files(pattern: str, path: str = ".") -> dict:
    try:
        p = _resolve(path)
        matches = sorted(p.glob(pattern))
        return {"pattern": pattern, "path": str(p),
                "files": [str(f.relative_to(p)) for f in matches if f.is_file()][:50]}
    except Exception as e:
        return {"error": str(e)}


def grep(pattern: str, path: str = ".", extension: str = "") -> dict:
    try:
        p = _resolve(path)
        results = []
        glob_pat = f"**/*{extension}" if extension else "**/*"
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return {"error": f"Regex inválida: {e}"}
        for file in sorted(p.glob(glob_pat)):
            if not file.is_file() or file.stat().st_size > 1_000_000:
                continue
            try:
                for i, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines()):
                    if regex.search(line):
                        results.append({"file": str(file.relative_to(p)), "line": i + 1, "content": line.strip()})
                        if len(results) >= 50:
                            break
            except Exception:
                pass
            if len(results) >= 50:
                break
        return {"pattern": pattern, "results": results}
    except Exception as e:
        return {"error": str(e)}


def list_directory(path: str = ".") -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"error": f"No encontrado: {path}"}
        entries = []
        for item in sorted(p.iterdir()):
            entries.append({"name": item.name, "type": "dir" if item.is_dir() else "file",
                             "size": item.stat().st_size if item.is_file() else None})
        return {"path": str(p), "entries": entries}
    except Exception as e:
        return {"error": str(e)}


def delete_file(path: str) -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"error": f"No existe: {path}"}
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"success": True, "deleted": str(p)}
    except Exception as e:
        return {"error": str(e)}


def create_directory(path: str) -> dict:
    try:
        p = _resolve(path)
        p.mkdir(parents=True, exist_ok=True)
        return {"success": True, "path": str(p)}
    except Exception as e:
        return {"error": str(e)}


def move_file(src: str, dst: str) -> dict:
    try:
        s = _resolve(src)
        d = _resolve(dst)
        if not s.exists():
            return {"error": f"No existe: {src}"}
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return {"success": True, "from": str(s), "to": str(d)}
    except Exception as e:
        return {"error": str(e)}


def search_web(query: str, max_results: int = 5) -> dict:
    if not WEB_AVAILABLE:
        return {"error": "Instala: pip install duckduckgo-search requests beautifulsoup4"}
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return {"results": [], "message": "Sin resultados"}
        return {"query": query, "results": [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]}
    except Exception as e:
        return {"error": str(e)}


def fetch_url(url: str, max_chars: int = 4000) -> dict:
    if not WEB_AVAILABLE:
        return {"error": "Instala: pip install requests beautifulsoup4"}
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return {"url": url, "content": text[:max_chars] + ("…" if len(text) > max_chars else ""), "chars": len(text)}
    except Exception as e:
        return {"error": str(e)}


def _resolve(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(WORK_DIR) / p
    return p.resolve()


TOOL_MAP = {
    "run_command":      run_command,
    "read_file":        read_file,
    "write_file":       write_file,
    "edit_file":        edit_file,
    "find_files":       find_files,
    "grep":             grep,
    "list_directory":   list_directory,
    "delete_file":      delete_file,
    "create_directory": create_directory,
    "move_file":        move_file,
    "search_web":       search_web,
    "fetch_url":        fetch_url,
}

_BASE_TOOLS = [
    {"type": "function", "function": {"name": "run_command",
      "description": "Ejecuta comandos en el shell del SO (auto-detecta powershell/bash).",
      "parameters": {"type": "object", "properties": {
          "command": {"type": "string"},
          "shell":   {"type": "string", "enum": ["auto", "powershell", "bash", "sh", "cmd"],
                      "description": "Shell a usar. 'auto' selecciona el correcto para el SO."},
          "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file",
      "description": "Lee un archivo con números de línea.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
      "description": "Crea un archivo nuevo.",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file",
      "description": "Edita texto en un archivo existente. Soporta reemplazo múltiple y regex.",
      "parameters": {"type": "object", "properties": {
          "path":        {"type": "string"},
          "old_text":    {"type": "string"},
          "new_text":    {"type": "string"},
          "replace_all": {"type": "boolean", "description": "Si true, reemplaza todas las ocurrencias"},
          "use_regex":   {"type": "boolean", "description": "Si true, old_text es una expresión regular"}},
          "required": ["path", "old_text", "new_text"]}}},
    {"type": "function", "function": {"name": "find_files",
      "description": "Busca archivos por patrón glob.",
      "parameters": {"type": "object", "properties": {
          "pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "grep",
      "description": "Busca texto/regex en el proyecto.",
      "parameters": {"type": "object", "properties": {
          "pattern": {"type": "string"}, "path": {"type": "string"}, "extension": {"type": "string"}},
          "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "list_directory",
      "description": "Lista carpetas.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "delete_file",
      "description": "Elimina un archivo o carpeta (recursivo para carpetas no vacías).",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "create_directory",
      "description": "Crea una carpeta y subcarpetas si es necesario.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "move_file",
      "description": "Mueve o renombra un archivo o carpeta.",
      "parameters": {"type": "object", "properties": {
          "src": {"type": "string", "description": "Ruta origen"},
          "dst": {"type": "string", "description": "Ruta destino"}},
          "required": ["src", "dst"]}}},
]

_WEB_TOOLS = [
    {"type": "function", "function": {"name": "search_web",
      "description": "Busca en internet con DuckDuckGo para info actual, documentación, noticias.",
      "parameters": {"type": "object", "properties": {
          "query":       {"type": "string"},
          "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fetch_url",
      "description": "Descarga y lee el contenido de una URL.",
      "parameters": {"type": "object", "properties": {
          "url":       {"type": "string"},
          "max_chars": {"type": "integer"}}, "required": ["url"]}}},
] if WEB_AVAILABLE else []

TOOLS = _BASE_TOOLS + _WEB_TOOLS


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


def print_tool_call(name: str, args: dict):
    t = Text()
    t.append("  ⚙ ", style=C_TOOL)
    t.append(name, style=f"bold {C_TOOL}")
    t.append("(", style=C_DIM)
    parts = [f"{k}={repr(v)[:100]}" for k, v in args.items()]
    t.append(", ".join(parts), style=C_TOOLARG)
    t.append(")", style=C_DIM)
    console.print(t)


def print_tool_result(result: dict):
    t = Text()
    if "error" in result:
        t.append("  ✗ ", style=C_ERR)
        t.append(result["error"], style=C_ERR)
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
    elif "success" in result:
        t.append("  ✓ ", style=C_OK)
        detail = result.get("to") or result.get("path") or result.get("deleted") or "ok"
        t.append(detail, style=C_DIM)
    else:
        t.append("  ✓ ", style=C_OK)
        t.append("ok", style=C_DIM)
    console.print(t)


def get_input(_: str) -> str:
    console.print()
    try:
        console.print(f"[{C_PROMPT}]>[/] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        return "salir"


# ─── Prompts ──────────────────────────────────────────────────────────────────

def build_system_prompt(work_dir: str, project_context: str) -> str:
    """
    Fuente principal de instrucciones del agente.
    Cualquier SYSTEM en el Modelfile de Ollama solo debe definir parámetros
    o instrucciones muy generales — este prompt tiene precedencia en toda
    lógica de comportamiento, herramientas y reglas de ejecución.
    """
    desktop = str(Path.home() / "Desktop")
    return f"""/no_think
Eres un agente autónomo de programación. Directorio de trabajo: {work_dir}
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
REGLA ABSOLUTA #3 — LEE ANTES DE TOCAR
═══════════════════════════════════════════════════════
SIEMPRE usa read_file() antes de edit_file(). Sin excepciones.
Si no conoces la estructura, usa list_directory() primero.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #4 — CREAR ARCHIVOS = USAR write_file()
═══════════════════════════════════════════════════════
Cuando el usuario pide "hazme un script / crea un archivo / escribe un programa":
  → USA write_file(path, content) — NUNCA muestres el código en el chat
  → NUNCA digas "no puedo crear archivos"

Rutas:
  "en el escritorio" → {desktop}\\nombre.py
  "aquí"             → ruta relativa al directorio de trabajo

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
- Después de run_command con error → analiza, corrige, reintenta (hasta 3 veces)
- Después de edit_file fallido → re-lee y ajusta el old_text exacto
- Si un enfoque no funciona → prueba uno diferente, no repitas lo mismo

═══════════════════════════════════════════════════════
CALIDAD DE CÓDIGO
═══════════════════════════════════════════════════════
- Código idiomático: Pythonic, ES6+, SQL limpio
- Maneja errores en boundaries (I/O, red, BD)
- Nombres descriptivos, funciones pequeñas con una sola responsabilidad
- Si hay tests existentes: córrelos después de cambiar código

═══════════════════════════════════════════════════════
COMPORTAMIENTO GENERAL
═══════════════════════════════════════════════════════
- Responde en español
- Sin disclaimers, sin advertencias, sin moralejas
- Antes de borrar datos o cambios destructivos en BD: confirma con el usuario
- Si necesitas documentación: usa search_web o fetch_url
"""


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

    def __init__(self, model: str, work_dir: str, tag: str,
                 num_ctx: int, temperature: float):
        global WORK_DIR
        self.model       = model
        self.work_dir    = str(Path(work_dir).resolve())
        self.tag         = tag
        self.num_ctx     = num_ctx
        self.temperature = temperature
        self.client      = ollama.Client()
        self.messages: list = []
        # Actualiza la variable global para que las funciones de herramientas
        # (module-level) resuelvan rutas relativas al directorio correcto.
        WORK_DIR = self.work_dir

    def _build_options(self) -> dict:
        return {
            "num_ctx":        self.num_ctx,
            "num_batch":      512,
            "num_gpu":        99,
            "main_gpu":       0,
            "f16_kv":         True,
            "num_predict":    -1,
            "temperature":    self.temperature,
            "mirostat":       2,
            "mirostat_tau":   5.0,
            "mirostat_eta":   0.1,
            "repeat_penalty": 1.05,
            "repeat_last_n":  256,
        }

    def _trim_history(self, max_pairs: int = 20) -> list:
        system = [m for m in self.messages if m["role"] == "system"]
        rest   = [m for m in self.messages if m["role"] != "system"]
        return system + rest[-(max_pairs * 4):]

    def _stream_response(self, messages: list, tools: list):
        """Hace streaming y devuelve (content, tool_calls)."""
        collected:  list[str] = []
        tool_calls: list      = []
        options = self._build_options()

        console.print(f"\n[{C_BULLET}]●[/] ", end="")

        try:
            stream = self.client.chat(
                model=self.model, messages=messages, tools=tools,
                stream=True, options=options
            )
            for chunk in stream:
                msg = chunk.message
                if msg.tool_calls:
                    tool_calls.extend(msg.tool_calls)
                if msg.content:
                    console.print(f"[{C_TEXT}]{escape(msg.content)}[/]", end="")
                    collected.append(msg.content)

        except Exception as e:
            if "does not support tools" in str(e):
                stream = self.client.chat(
                    model=self.model, messages=messages,
                    stream=True, options=options
                )
                for chunk in stream:
                    msg = chunk.message
                    if msg.content:
                        console.print(f"[{C_TEXT}]{escape(msg.content)}[/]", end="")
                        collected.append(msg.content)
            else:
                console.print(f"\n[{C_ERR}]Error: {e}[/]")

        if not tool_calls:
            console.print()

        return "".join(collected), tool_calls

    def _parse_tool_args(self, tc) -> dict | None:
        """Parsea los argumentos de un tool call con manejo robusto de errores."""
        if isinstance(tc.function.arguments, dict):
            return tc.function.arguments
        try:
            return json.loads(tc.function.arguments)
        except (json.JSONDecodeError, TypeError) as e:
            console.print(f"\n[{C_ERR}]  ✗ Argumentos inválidos para {tc.function.name}: {e}[/]")
            return None

    def _validate_model(self) -> bool:
        try:
            available = [m.model for m in self.client.list().models]
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
        except Exception as e:
            console.print(f"[{C_ERR}]Error conectando a Ollama: {e}[/]")
            return False

    def run(self):
        if not self._validate_model():
            sys.exit(1)

        project_context = load_project_context(self.work_dir)
        # build_system_prompt es la fuente autoritativa de instrucciones.
        # Tiene precedencia sobre cualquier SYSTEM definido en el Modelfile.
        system_prompt = build_system_prompt(self.work_dir, project_context)
        self.messages = [{"role": "system", "content": system_prompt}]

        print_header(self.model, self.work_dir, self.tag, self.num_ctx, self.temperature)

        while True:
            user_input = get_input(self.model.split(":")[0])

            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                console.print(f"\n[{C_DIM}]  Hasta luego.[/]\n")
                break
            if user_input.lower() in ("limpiar", "clear", "reset"):
                self.messages = [{"role": "system", "content": system_prompt}]
                console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
                continue

            self.messages.append({"role": "user", "content": user_input})

            while True:
                trimmed = self._trim_history()
                full_content, tool_calls = self._stream_response(trimmed, TOOLS)

                if tool_calls:
                    console.print()
                    self.messages.append({
                        "role": "assistant",
                        "content": full_content,
                        "tool_calls": [
                            {"id": tc.function.name, "type": "function",
                             "function": {"name": tc.function.name,
                                          "arguments": self._parse_tool_args(tc) or {}}}
                            for tc in tool_calls
                        ]
                    })
                    for tc in tool_calls:
                        fn_name = tc.function.name
                        fn_args = self._parse_tool_args(tc)
                        if fn_args is None:
                            result = {"error": f"No se pudieron parsear los argumentos de {fn_name}"}
                        elif fn_name in TOOL_MAP:
                            print_tool_call(fn_name, fn_args)
                            result = TOOL_MAP[fn_name](**fn_args)
                        else:
                            result = {"error": f"Tool desconocida: {fn_name}"}
                        print_tool_result(result)
                        self.messages.append({
                            "role": "tool",
                            "content": json.dumps(result, ensure_ascii=False),
                            "name": fn_name
                        })
                else:
                    self.messages.append({"role": "assistant", "content": full_content})
                    break


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_agent(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float):
    Agent(model, work_dir, tag, num_ctx, temperature).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente local con Ollama")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--dir",   default=".")
    parser.add_argument("--tag",   default="AGENTE")
    parser.add_argument("--ctx",   type=int,   default=16384, help="Ventana de contexto en tokens")
    parser.add_argument("--temp",  type=float, default=0.15,  help="Temperatura 0.0-1.0")
    args = parser.parse_args()
    run_agent(args.model, args.dir, args.tag, args.ctx, args.temp)
