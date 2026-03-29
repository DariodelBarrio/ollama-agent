"""
Agente de programacion local con Ollama - UI estilo Claude Code
Uso: python src/agent.py [--model qwen2.5-coder:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import subprocess
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
C_PROMPT   = "#5B9BD5"      # azul para el >
C_BULLET   = "#4EC9B0"      # verde-azul para el •
C_TOOL     = "#C586C0"      # morado para tool calls
C_TOOLARG  = "#9CDCFE"      # azul claro para argumentos
C_OK       = "#6A9955"      # verde para resultados OK
C_ERR      = "#F44747"      # rojo para errores
C_DIM      = "#6E7681"      # gris para info secundaria
C_LOGO     = "#E8643B"      # naranja Claude
C_LOGO2    = "#C0391B"      # naranja oscuro
C_BORDER   = "#30363D"      # borde sutil
C_TEXT     = "#D4D4D4"      # texto principal

WORK_DIR     = "."
_NUM_CTX     = 16384   # 16K cabe en VRAM con modelos 14b en GPU de 12GB
_TEMPERATURE = 0.15

# ─── Herramientas ─────────────────────────────────────────────────────────────

def run_command(command: str, shell: str = "powershell", timeout: int = 60) -> dict:
    try:
        if shell == "powershell":
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True, text=True, timeout=timeout, cwd=WORK_DIR
            )
        else:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout, cwd=WORK_DIR
            )
        return {"stdout": result.stdout.strip(), "stderr": result.stderr.strip(), "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"error": f"Timeout: el comando tardó más de {timeout}s"}
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


def edit_file(path: str, old_text: str, new_text: str) -> dict:
    try:
        p = _resolve(path)
        if not p.exists():
            return {"error": f"Archivo no encontrado: {path}"}
        content = p.read_text(encoding="utf-8", errors="replace")
        if old_text not in content:
            return {"error": "Texto no encontrado. Debe ser exacto (incluyendo espacios e indentación)."}
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return {"success": True, "path": str(p)}
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
      "description": "Ejecuta comandos PowerShell o CMD.",
      "parameters": {"type": "object", "properties": {
          "command": {"type": "string"}, "shell": {"type": "string", "enum": ["powershell", "cmd"]},
          "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file",
      "description": "Lee un archivo con números de línea.",
      "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file",
      "description": "Crea un archivo nuevo.",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file",
      "description": "Edita texto exacto en un archivo existente.",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
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
      "description": "Busca en internet con DuckDuckGo. Usa esto para noticias, documentacion, precios, cualquier info actual.",
      "parameters": {"type": "object", "properties": {
          "query":       {"type": "string",  "description": "Terminos de busqueda"},
          "max_results": {"type": "integer", "description": "Numero de resultados (default 5)"}
      }, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fetch_url",
      "description": "Descarga y lee el contenido de una URL. Usa esto para leer documentacion, articulos o paginas web.",
      "parameters": {"type": "object", "properties": {
          "url":       {"type": "string",  "description": "URL a leer"},
          "max_chars": {"type": "integer", "description": "Maximo de caracteres a devolver (default 4000)"}
      }, "required": ["url"]}}},
] if WEB_AVAILABLE else []

TOOLS = _BASE_TOOLS + _WEB_TOOLS


# ─── UI ───────────────────────────────────────────────────────────────────────

LOGO_LINES = [
    f"[{C_LOGO}]▄████▄[/]",
    f"[{C_LOGO}]█[/][{C_LOGO2}]▄▄▄▄[/][{C_LOGO}]█[/]",
    f"[{C_LOGO}]█[/][bold white] IA [/][{C_LOGO}]█[/]",
    f"[{C_LOGO}]▀████▀[/]",
]


def print_header(model: str, work_dir: str, tag: str):
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
    info.append(f"  ctx:{_NUM_CTX}  temp:{_TEMPERATURE}  {work_dir}", style=C_DIM)
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
    parts = []
    for k, v in args.items():
        val = repr(v)[:100]
        parts.append(f"{k}={val}")
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
            t.append(out[:1000] + ("…" if len(out) > 1000 else ""), style=C_TEXT)
        if err:
            t.append(f"\n    stderr: {err[:300]}", style=C_ERR)
        if rc != 0:
            t.append(f"  [rc={rc}]", style=C_ERR)
    elif "content" in result and "url" in result:
        # fetch_url
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result.get('chars', 0)} chars  ·  {result['url'][:60]}", style=C_DIM)
    elif "content" in result:
        # read_file
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result['lines']} líneas  ·  {result['path']}", style=C_DIM)
    elif "query" in result and "results" in result:
        # search_web
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


def get_input(model_short: str) -> str:
    console.print()
    try:
        console.print(f"[{C_PROMPT}]>[/] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        return "salir"


def _build_options() -> dict:
    return {
        "num_ctx":        _NUM_CTX,
        "num_batch":      512,       # tokens procesados por batch en GPU — mejora ocupacion
        "num_gpu":        99,
        "main_gpu":       0,
        "f16_kv":         True,
        "num_predict":    -1,
        "temperature":    _TEMPERATURE,
        "mirostat":       2,
        "mirostat_tau":   5.0,
        "mirostat_eta":   0.1,
        "repeat_penalty": 1.05,
        "repeat_last_n":  256,
    }


def stream_response(client, model: str, messages: list, tools: list):
    collected  = []
    tool_calls = []
    options    = _build_options()

    console.print(f"\n[{C_BULLET}]●[/] ", end="")

    try:
        stream = client.chat(model=model, messages=messages, tools=tools, stream=True, options=options)
        for chunk in stream:
            msg = chunk.message
            if msg.tool_calls:
                tool_calls.extend(msg.tool_calls)
            if msg.content:
                console.print(f"[{C_TEXT}]{escape(msg.content)}[/]", end="")
                collected.append(msg.content)

    except Exception as e:
        if "does not support tools" in str(e):
            stream = client.chat(model=model, messages=messages, stream=True, options=options)
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


# ─── Prompts ──────────────────────────────────────────────────────────────────

def build_system_prompt(work_dir: str, project_context: str) -> str:
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

En su lugar: HAZLO TÚ MISMO con las herramientas. Si necesitas saber algo del proyecto,
usa list_directory o read_file. Si necesitas ejecutar algo, usa run_command. PUNTO.

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #2 — ENCADENA PASOS SIN PARAR NI PREGUNTAR
═══════════════════════════════════════════════════════
Cuando el usuario pide una tarea, la ejecutas completa de principio a fin:
  1. Llamas las herramientas necesarias en secuencia
  2. Usas el resultado de cada herramienta para decidir el siguiente paso
  3. No te detienes a mitad a explicar — terminas la tarea
  4. Solo al final reportas qué hiciste y el resultado

PROHIBIDO interrumpir con frases como:
  ✗ "¿Quieres que continúe?"
  ✗ "¿Procedo con el siguiente paso?"
  ✗ "¿Sigo?"
  ✗ "¿Te parece bien si...?"
  ✗ "Antes de continuar, ¿confirmas que...?"

Si ya tienes suficiente información para hacer el siguiente paso → HAZLO.
Solo pregunta al usuario si te falta información que NO puedes obtener con herramientas.

Ejemplo correcto para "arregla el bug en main.py":
  → list_directory() para ver la estructura
  → read_file("main.py") para leer el código
  → edit_file(...) para aplicar el fix
  → run_command("python main.py") para verificar
  → "Listo, corregí X en línea Y. Ahora funciona."

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #3 — LEE ANTES DE TOCAR
═══════════════════════════════════════════════════════
SIEMPRE usa read_file() antes de edit_file(). Sin excepciones.
Si no conoces la estructura del proyecto, usa list_directory() primero.
Si no sabes qué contiene un archivo, léelo con read_file().

═══════════════════════════════════════════════════════
REGLA ABSOLUTA #4 — CREAR ARCHIVOS = USAR write_file()
═══════════════════════════════════════════════════════
Cuando el usuario pide "hazme un script / crea un archivo / escribe un programa":
  → USA write_file(path, content) para crearlo en la ruta indicada
  → NUNCA muestres el código en el chat como respuesta
  → NUNCA digas "no puedo crear archivos" — TIENES write_file(), ÚSALO

Rutas especiales:
  "en el escritorio"   → {desktop}\\nombre_archivo.py
  "aquí" / "en este proyecto" → ruta relativa desde el directorio de trabajo

EJEMPLOS CORRECTOS:
  "hazme un script en el escritorio"
  → [write_file("{desktop}\\script.py", "...código completo...")]
  → "Listo, creé script.py en tu escritorio."

  "crea un archivo config.json"
  → [write_file("config.json", "...")]
  → "Listo, config.json creado."

PROHIBIDO:
  ✗ Mostrar código en el chat cuando el usuario pide crear un archivo
  ✗ Decir "no puedo colocar archivos en tu escritorio"
  ✗ Pedir más detalles cuando puedes inventarte algo útil y crearlo

═══════════════════════════════════════════════════════
HERRAMIENTAS DISPONIBLES
═══════════════════════════════════════════════════════
- run_command(command, shell?)         → ejecuta PowerShell/CMD
- read_file(path)                      → lee archivos con números de línea
- write_file(path, content)            → crea archivos nuevos
- edit_file(path, old_text, new_text)  → edita texto exacto en un archivo
- find_files(pattern, path?)           → glob: **/*.py, src/**/*.ts
- grep(pattern, path?, ext?)           → busca texto/regex en el código
- list_directory(path?)                → lista contenido de carpeta
- delete_file(path)                    → elimina archivos o carpetas (recursivo)
- create_directory(path)               → crea carpetas y subcarpetas
- move_file(src, dst)                  → mueve o renombra archivos/carpetas
- search_web(query)                    → DuckDuckGo para info actual
- fetch_url(url)                       → descarga y lee una URL completa

═══════════════════════════════════════════════════════
RAZONAMIENTO ANTES DE ACTUAR
═══════════════════════════════════════════════════════
Antes de llamar herramientas, piensa internamente:
  1. ¿Qué necesito saber? → qué herramientas debo llamar primero
  2. ¿Cuál es la secuencia lógica de pasos?
  3. ¿Qué puede salir mal y cómo lo manejo?

Razona así para cada tarea — no lo escribas, solo actúa.

═══════════════════════════════════════════════════════
AUTOCORRECCIÓN Y VERIFICACIÓN
═══════════════════════════════════════════════════════
- Después de run_command: si hay error → analiza, corrige, ejecuta de nuevo (hasta 3 intentos)
- Después de edit_file: si el texto no se encontró → re-lee el archivo y ajusta el old_text exacto
- Después de write_file: verifica que el archivo quedó correcto con read_file
- Si un enfoque no funciona → prueba uno diferente, no repitas lo mismo
- Si después de 3 intentos sigue fallando → explica al usuario qué encontraste y por qué

═══════════════════════════════════════════════════════
EJEMPLOS DE COMPORTAMIENTO CORRECTO
═══════════════════════════════════════════════════════

"hay un bug en mi código"
→ [run_command] para ejecutar y ver el error
→ [grep] para localizar la línea del error
→ [read_file] para leer el contexto completo
→ [edit_file] para corregir
→ [run_command] para verificar que ya no falla
→ "Listo, era X en línea Y."

"crea un servidor express"
→ [run_command("npm init -y")]
→ [run_command("npm install express")]
→ [write_file("index.js")] con código completo y funcional
→ [run_command("node index.js")] para verificar que arranca
→ "Servidor corriendo en puerto 3000."

"¿por qué falla mi script?"
→ [run_command] para ver el error real
→ [read_file] para leer el código
→ análisis interno de la causa raíz
→ [edit_file] con el fix correcto
→ [run_command] para confirmar que funciona
→ "Corregido. El problema era X porque Y."

═══════════════════════════════════════════════════════
PROYECTOS WEB
═══════════════════════════════════════════════════════
ANTES de cualquier tarea en un proyecto existente:
  → list_directory() para ver la estructura
  → read_file("package.json") o "requirements.txt" para ver el stack
  → grep() o find_files() para entender convenciones del proyecto

"crea un componente React de login"
  → find_files("**/*.tsx") para ver el estilo existente
  → read_file de un componente existente para seguir el mismo patrón
  → write_file("src/components/Login/Login.tsx") componente completo
  → write_file("src/components/Login/Login.css") si el proyecto usa CSS separado
  → write_file("src/components/Login/index.ts") para el export
  → verificar imports y que compile

"agrega endpoint POST /users"
  → read_file de las rutas existentes para ver el patrón
  → edit_file para añadir la ruta manteniendo el estilo del proyecto
  → run_command para verificar que el servidor arranca

"instala y configura Tailwind / cualquier librería"
  → run_command("npm install ...") o "pip install ..."
  → write_file o edit_file para la configuración
  → verificar con run_command

PATRONES MULTI-ARCHIVO — cuando creas algo nuevo, crea TODO lo necesario:
  Frontend: componente + estilos + tipos + barrel export
  Backend:  ruta + controlador + validación + middleware si aplica
  Full:     ambos lados + tipos compartidos

═══════════════════════════════════════════════════════
BASES DE DATOS Y MIGRACIONES
═══════════════════════════════════════════════════════
SIEMPRE lee el schema/modelos actuales antes de modificar.

Prisma:
  → read_file("prisma/schema.prisma")
  → edit_file para añadir/modificar modelos
  → run_command("npx prisma migrate dev --name descripcion")
  → run_command("npx prisma generate")

Drizzle:
  → read_file del schema actual
  → edit_file para modificar
  → run_command("npx drizzle-kit generate") → run_command("npx drizzle-kit migrate")

Django:
  → read_file("app/models.py")
  → edit_file para modificar modelos
  → run_command("python manage.py makemigrations")
  → run_command("python manage.py migrate")

SQLAlchemy / Alembic:
  → read_file de los modelos actuales
  → edit_file para modificar
  → run_command("alembic revision --autogenerate -m 'descripcion'")
  → run_command("alembic upgrade head")

SQL directo:
  → write_file("migrations/001_descripcion.sql") con los ALTER TABLE / CREATE TABLE
  → run_command para ejecutarla contra la BD

REGLA: nunca modifiques el schema sin leerlo primero. Nunca ejecutes migrate sin
haber editado el schema. Verifica siempre que la migración se aplicó con una query.

═══════════════════════════════════════════════════════
CALIDAD DE CÓDIGO
═══════════════════════════════════════════════════════
- Código idiomático: Pythonic, ES6+, JSX correcto, SQL limpio
- Maneja errores en boundaries (I/O, red, BD) — no en lógica interna
- Nombres descriptivos, sin abreviaciones oscuras
- Sin código muerto, sin comentarios obvios
- Funciones pequeñas con una sola responsabilidad
- Si hay tests existentes: córrelos después de cambiar código

═══════════════════════════════════════════════════════
COMPORTAMIENTO GENERAL
═══════════════════════════════════════════════════════
- Responde en español
- Sin disclaimers, sin advertencias, sin moralejas
- Antes de borrar datos o cambios destructivos en BD: confirma con el usuario
- Rutas relativas al directorio de trabajo cuando sea posible
- Si necesitas documentación de una librería: usa search_web o fetch_url
"""


def load_project_context(work_dir: str) -> str:
    for name in ["CLAUDE.md", "README.md", ".cursorrules"]:
        p = Path(work_dir) / name
        if p.exists():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:6000]
                return f"Contexto del proyecto ({name}):\n{content}\n"
            except Exception:
                pass
    return ""


def _trim_history(messages: list, max_pairs: int = 20) -> list:
    system = [m for m in messages if m["role"] == "system"]
    rest   = [m for m in messages if m["role"] != "system"]
    # max_pairs * 4 cubre ~20 turnos de usuario con tool calls
    return system + rest[-(max_pairs * 4):]


# ─── Bucle principal ──────────────────────────────────────────────────────────

def run_agent(model: str, work_dir: str, tag: str):
    global WORK_DIR
    WORK_DIR = str(Path(work_dir).resolve())

    client = ollama.Client()

    try:
        available = [m.model for m in client.list().models]
        if model not in available:
            console.print(f"\n[{C_ERR}]Modelo '{model}' no encontrado. Disponibles:[/]")
            for m in available:
                console.print(f"  [{C_DIM}]·[/] {m}")
            if available:
                model = available[0]
                console.print(f"[{C_OK}]→ Usando '{model}'[/]\n")
            else:
                sys.exit(1)
    except Exception as e:
        console.print(f"[{C_ERR}]Error conectando a Ollama: {e}[/]")
        sys.exit(1)

    project_context = load_project_context(WORK_DIR)
    system_prompt   = build_system_prompt(WORK_DIR, project_context)

    print_header(model, WORK_DIR, tag)

    messages = [{"role": "system", "content": system_prompt}]

    while True:
        user_input = get_input(model.split(":")[0])

        if not user_input:
            continue
        if user_input.lower() in ("salir", "exit", "quit"):
            console.print(f"\n[{C_DIM}]  Hasta luego.[/]\n")
            break
        if user_input.lower() in ("limpiar", "clear", "reset"):
            messages = [{"role": "system", "content": system_prompt}]
            console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
            continue

        messages.append({"role": "user", "content": user_input})

        while True:
            full_content, tool_calls = stream_response(client, model, _trim_history(messages), TOOLS)

            if tool_calls:
                console.print()
                messages.append({
                    "role": "assistant",
                    "content": full_content,
                    "tool_calls": [
                        {"id": tc.function.name, "type": "function",
                         "function": {"name": tc.function.name,
                                      "arguments": tc.function.arguments if isinstance(tc.function.arguments, dict)
                                                   else json.loads(tc.function.arguments)}}
                        for tc in tool_calls
                    ]
                })
                for tc in tool_calls:
                    fn_name = tc.function.name
                    fn_args = tc.function.arguments if isinstance(tc.function.arguments, dict) \
                              else json.loads(tc.function.arguments)
                    print_tool_call(fn_name, fn_args)
                    result = TOOL_MAP[fn_name](**fn_args) if fn_name in TOOL_MAP \
                             else {"error": f"Tool desconocida: {fn_name}"}
                    print_tool_result(result)
                    messages.append({
                        "role": "tool",
                        "content": json.dumps(result, ensure_ascii=False),
                        "name": fn_name
                    })
            else:
                messages.append({"role": "assistant", "content": full_content})
                break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente local con Ollama")
    parser.add_argument("--model", default="qwen2.5-coder:7b")
    parser.add_argument("--dir",   default=".")
    parser.add_argument("--tag",   default="AGENTE")
    parser.add_argument("--ctx",   type=int,   default=16384, help="Ventana de contexto en tokens (default: 16384)")
    parser.add_argument("--temp",  type=float, default=0.15,  help="Temperatura 0.0-1.0 (default: 0.15)")
    args = parser.parse_args()

    _NUM_CTX     = args.ctx
    _TEMPERATURE = args.temp

    run_agent(args.model, args.dir, args.tag)
