"""
Agente de programacion local con Ollama - UI estilo Claude Code
Uso: python src/agent.py [--model qwen3:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import logging
import subprocess
import platform
import os
import sys
import re
import shutil
import argparse
import time
import threading
import difflib
from datetime import datetime, timezone
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

try:
    from pydantic import BaseModel, Field, ValidationError
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

console = Console()


# ── Logging estructurado JSON ─────────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Formatea cada registro como una línea JSON (JSONL)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":     record.levelname,
            "message":   record.getMessage(),
        }
        # Campos extra opcionales pasados como kwargs al llamar al logger
        for key in ("user_input", "assistant_response", "tool_name",
                    "tool_args", "tool_result", "error_details"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _make_logger(name: str, log_path: Path) -> logging.Logger:
    """Crea un logger que escribe en *log_path* sin tocar la consola."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False          # nunca llega a root → no aparece en consola

    if not logger.handlers:           # evita duplicar handlers al reiniciar sesión
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_JsonFormatter())
        logger.addHandler(fh)

    return logger


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

# ── Modelos Pydantic para validación de argumentos de herramientas ────────────

if PYDANTIC_AVAILABLE:
    class RunCommandArgs(BaseModel):
        command: str = Field(..., description="Comando a ejecutar.")
        shell: str = Field("auto", description="Shell: 'auto', 'powershell', 'bash', 'sh', 'cmd'.")
        timeout: int = Field(60, description="Tiempo máximo de ejecución en segundos.")

    class ReadFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")

    class WriteFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")
        content: str = Field(..., description="Contenido a escribir.")

    class EditFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo.")
        old_text: str = Field(..., description="Texto a buscar.")
        new_text: str = Field(..., description="Texto de reemplazo.")
        replace_all: bool = Field(False, description="Reemplazar todas las ocurrencias.")
        use_regex: bool = Field(False, description="Interpretar old_text como regex.")

    class FindFilesArgs(BaseModel):
        pattern: str = Field(..., description="Patrón glob.")
        path: str = Field(".", description="Directorio de búsqueda.")

    class GrepArgs(BaseModel):
        pattern: str = Field(..., description="Patrón regex a buscar.")
        path: str = Field(".", description="Directorio de búsqueda.")
        extension: str = Field("", description="Filtrar por extensión (ej. '.py').")

    class ListDirectoryArgs(BaseModel):
        path: str = Field(".", description="Ruta del directorio.")

    class DeleteFileArgs(BaseModel):
        path: str = Field(..., description="Ruta del archivo o carpeta.")

    class CreateDirectoryArgs(BaseModel):
        path: str = Field(..., description="Ruta de la carpeta a crear.")

    class MoveFileArgs(BaseModel):
        src: str = Field(..., description="Ruta origen.")
        dst: str = Field(..., description="Ruta destino.")

    class SearchWebArgs(BaseModel):
        query: str = Field(..., description="Consulta de búsqueda.")
        max_results: int = Field(5, description="Número máximo de resultados.")

    class FetchUrlArgs(BaseModel):
        url: str = Field(..., description="URL a descargar.")
        max_chars: int = Field(4000, description="Máximo de caracteres a retornar.")

    class ChangeDirectoryArgs(BaseModel):
        path: str = Field(..., description="Ruta del nuevo directorio de trabajo.")

    TOOL_SCHEMA_MAP: dict = {
        "run_command":      RunCommandArgs,
        "read_file":        ReadFileArgs,
        "write_file":       WriteFileArgs,
        "edit_file":        EditFileArgs,
        "find_files":       FindFilesArgs,
        "grep":             GrepArgs,
        "list_directory":   ListDirectoryArgs,
        "delete_file":      DeleteFileArgs,
        "create_directory": CreateDirectoryArgs,
        "move_file":        MoveFileArgs,
        "search_web":       SearchWebArgs,
        "fetch_url":        FetchUrlArgs,
        "change_directory": ChangeDirectoryArgs,
    }
else:
    TOOL_SCHEMA_MAP = {}

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

        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        raw_diff  = list(difflib.unified_diff(old_lines, new_lines, n=2))

        diff_entries: list = []
        lines_added = lines_removed = 0
        old_ln = new_ln = 0
        for dl in raw_diff:
            if dl.startswith("@@"):
                m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", dl)
                if m:
                    old_ln, new_ln = int(m.group(1)), int(m.group(2))
            elif dl.startswith("---") or dl.startswith("+++"):
                continue
            elif dl.startswith("-"):
                diff_entries.append((old_ln, "removed", dl[1:].rstrip("\n")))
                old_ln += 1; lines_removed += 1
            elif dl.startswith("+"):
                diff_entries.append((new_ln, "added", dl[1:].rstrip("\n")))
                new_ln += 1; lines_added += 1
            elif dl.startswith(" "):
                diff_entries.append((old_ln, "context", dl[1:].rstrip("\n")))
                old_ln += 1; new_ln += 1

        p.write_text(new_content, encoding="utf-8")
        replaced = count if replace_all else 1
        return {
            "success": True, "path": str(p), "replaced": replaced,
            "added": lines_added, "removed": lines_removed,
            "diff": diff_entries[:30],
        }
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


def change_directory(path: str) -> dict:
    """Cambia el directorio de trabajo activo del agente."""
    global WORK_DIR
    try:
        p = Path(path)
        if not p.is_absolute():
            p = Path(WORK_DIR) / p
        p = p.resolve()
        if not p.exists():
            return {"error": f"Directorio no encontrado: {path}"}
        if not p.is_dir():
            return {"error": f"No es un directorio: {path}"}
        WORK_DIR = str(p)
        return {"success": True, "cwd": str(p)}
    except Exception as e:
        return {"error": str(e)}


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
    "change_directory": change_directory,
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
    {"type": "function", "function": {"name": "change_directory",
      "description": "Cambia el directorio de trabajo activo. Úsalo cuando el usuario mencione un directorio específico distinto al actual.",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string", "description": "Ruta absoluta o relativa del nuevo directorio de trabajo"}},
          "required": ["path"]}}},
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

        # Logger de auditoría — escribe en work_dir/agent_session.jsonl
        log_path = Path(self.work_dir) / "agent_session.jsonl"
        self.logger = _make_logger(f"agent.{id(self)}", log_path)

    def _build_options(self) -> dict:
        return {
            "num_ctx":        self.num_ctx,
            "num_batch":      4096,
            "num_gpu":        99,
            "main_gpu":       0,
            "f16_kv":         True,
            "num_predict":    -1,
            "temperature":    self.temperature,
            "mirostat":       2,
            "mirostat_tau":   3.5,
            "mirostat_eta":   0.1,
            "repeat_penalty": 1.05,
            "repeat_last_n":  512,
            "top_k":          20,
            "top_p":          0.85,
        }

    def _trim_history(self, max_pairs: int = 20) -> list:
        system = [m for m in self.messages if m["role"] == "system"]
        rest   = [m for m in self.messages if m["role"] != "system"]
        return system + rest[-(max_pairs * 4):]

    def _stream_response(self, messages: list, tools: list):
        """Hace streaming y devuelve (content, tool_calls).
        Detecta bloques <think>...</think> y los muestra en gris dim."""
        collected:  list[str] = []
        tool_calls: list      = []
        options = self._build_options()
        first_output = [True]
        t_start = time.monotonic()

        def _drain(stream_iter):
            # state: None = normal, "think" = inside <think>, "thought" = inside <thought>
            state = None
            thought_buf: list[str] = []
            buf = ""
            for chunk in stream_iter:
                if first_output[0]:
                    live.stop()
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    first_output[0] = False
                msg = chunk.message
                if msg.tool_calls:
                    tool_calls.extend(msg.tool_calls)
                # Campo thinking separado (Ollama >= 0.6)
                if getattr(msg, "thinking", None):
                    if state != "think":
                        console.print(f"\n[{C_DIM}]  💭 ", end="")
                        state = "think"
                    console.print(f"[{C_DIM}]{escape(msg.thinking)}[/]", end="")
                if not msg.content:
                    continue
                buf += msg.content
                while True:
                    if state is None:
                        ti  = buf.find("<think>")
                        thi = buf.find("<thought>")
                        first_tag = None
                        first_pos = len(buf)
                        if ti  != -1 and ti  < first_pos: first_pos, first_tag = ti,  "think"
                        if thi != -1 and thi < first_pos: first_pos, first_tag = thi, "thought"
                        if first_tag is None:
                            cut = max(0, len(buf) - 9)  # 9 = len("<thought>")
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
                            cut = max(0, len(buf) - 10)  # 10 = len("</thought>")
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

        with Live(Spinner("dots", text="Pensando... 0s"), console=console, transient=True, refresh_per_second=4) as live:
            def _tick():
                while first_output[0]:
                    elapsed = time.monotonic() - t_start
                    live.update(Spinner("dots", text=f"Pensando... {elapsed:.0f}s"))
                    time.sleep(0.25)
            threading.Thread(target=_tick, daemon=True).start()

            try:
                _drain(self.client.chat(
                    model=self.model, messages=messages, tools=tools,
                    stream=True, options=options
                ))
            except Exception as e:
                if first_output[0]:
                    live.stop()
                    first_output[0] = False
                if "does not support tools" in str(e):
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    _drain(self.client.chat(
                        model=self.model, messages=messages,
                        stream=True, options=options
                    ))
                else:
                    console.print(f"\n[{C_ERR}]Error: {e}[/]")
                    self.logger.error(
                        "Error en streaming LLM",
                        extra={"error_details": str(e)},
                        exc_info=True
                    )

        elapsed_total = time.monotonic() - t_start
        if not tool_calls:
            console.print()
        console.print(f"[{C_DIM}]✳ Brewed for {elapsed_total:.0f}s[/]")

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
        system_prompt = build_system_prompt(self.work_dir, project_context)
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
            user_input = get_input(self.model.split(":")[0])

            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                console.print(f"\n[{C_DIM}]  Hasta luego.[/]\n")
                self.logger.info("Sesión finalizada por el usuario")
                break
            if user_input.lower() in ("limpiar", "clear", "reset"):
                self.messages = [{"role": "system", "content": system_prompt}]
                console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
                self.logger.info("Historial limpiado")
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
                            self.logger.error(
                                "Error al parsear argumentos de herramienta",
                                extra={"tool_name": fn_name, "error_details": result["error"]}
                            )
                        elif fn_name in TOOL_MAP:
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
                                result = TOOL_MAP[fn_name](**fn_args)
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
                            "content": json.dumps(result, ensure_ascii=False),
                            "name": fn_name
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


def select_model_menu() -> str:
    """Menú interactivo de selección de modelo al arrancar."""
    try:
        import ollama as _ollama
        installed = {m.model for m in _ollama.Client().list().models}
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


def run_agent(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float):
    Agent(model, work_dir, tag, num_ctx, temperature).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente local con Ollama")
    parser.add_argument("--model", default=None, help="Modelo Ollama (omitir para menú interactivo)")
    parser.add_argument("--dir",   default=".")
    parser.add_argument("--tag",   default="AGENTE")
    parser.add_argument("--ctx",   type=int,   default=16384, help="Ventana de contexto en tokens")
    parser.add_argument("--temp",  type=float, default=0.15,  help="Temperatura 0.0-1.0")
    args = parser.parse_args()
    model = args.model if args.model else select_model_menu()
    run_agent(model, args.dir, args.tag, args.ctx, args.temp)
