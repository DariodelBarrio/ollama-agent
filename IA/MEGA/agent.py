"""
Agente Híbrido Dual-Brain — MEGA Edition
Motor: SGLang · vLLM · Ollama (RTX 5070 local) + Groq (nube)
Router inteligente · Self-healing · Actor-Crítico · TUI profesional · Comandos /slash

Uso: python agent.py [--model MODEL] [--dir DIR] [--backend local|groq|auto]
     [--local-url URL] [--groq-model MODEL] [--ctx N] [--temp F] [--critic] [--tag TAG]
"""
import json, os, re, sys, time, argparse, threading, logging, sqlite3, inspect
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common_tools import WEB_AVAILABLE, ToolRuntime, build_tool_definitions

try:
    from openai import OpenAI
except ImportError:
    print("pip install openai"); sys.exit(1)

try:
    from rich.console import Console
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.padding import Padding
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.markup import escape
    from rich.panel import Panel
except ImportError:
    print("pip install rich"); sys.exit(1)

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.styles import Style as PTStyle
    PTOOLKIT = True
except ImportError:
    PTOOLKIT = False

try:
    import ast as _ast
    PYAST = True
except ImportError:
    PYAST = False

console = Console()
_SCRIPT_DIR = Path(__file__).parent

# Colores
C_PROMPT = "#5B9BD5"
C_BULLET = "#4EC9B0"
C_TOOL = "#C586C0"
C_TOOLARG = "#9CDCFE"
C_OK = "#6A9955"
C_ERR = "#F44747"
C_DIM = "#6E7681"
C_LOGO = "#E8643B"
C_BORDER = "#30363D"
C_TEXT = "#D4D4D4"
C_ROUTER = "#FFD700"
C_CRITIC = "#FF8C00"


class _JsonFmt(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key in ("user_input", "assistant_response", "tool_name", "tool_args", "tool_result", "error_details"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _make_logger(name, path):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(_JsonFmt())
        logger.addHandler(handler)
    return logger


@contextmanager
def _db_conn(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


_CLOUD_PATTERNS = [
    r"\b(architecture|design a system|review all|audit entire|comprehensive analysis)\b",
    r"\b(toda la base|entire codebase|todo el proyecto|full project)\b",
    r"\b(security audit|threat model|compare frameworks|explain everything)\b",
]


class SmartRouter:
    def __init__(self, ctx_threshold: int = 6000, force: Optional[str] = None):
        self.ctx_threshold = ctx_threshold
        self.force = force
        self.calls = {"local": 0, "groq": 0}

    def route(self, prompt: str, history_chars: int) -> tuple[str, str]:
        if self.force:
            return self.force, "forzado (/switch)"
        est_tokens = history_chars // 4
        if est_tokens > self.ctx_threshold:
            return "groq", f"contexto ~{est_tokens}t > umbral {self.ctx_threshold}t"
        for pattern in _CLOUD_PATTERNS:
            if re.search(pattern, prompt, re.I):
                return "groq", "tarea compleja/arquitectural detectada"
        return "local", "tarea coding/local"

    def icon(self, backend: str) -> str:
        return {"local": "⚡ LOCAL", "groq": "☁  GROQ"}.get(backend, backend)

    def record(self, backend: str):
        if backend in self.calls:
            self.calls[backend] += 1

    def stats(self) -> str:
        return f"local:{self.calls['local']}  groq:{self.calls['groq']}"

# Herramientas compartidas
WORK_DIR = "."
ROOT_DIR = str(Path(".").resolve())
_TOOL_RUNTIME = ToolRuntime(WORK_DIR, ROOT_DIR)


def _sync_tool_runtime() -> None:
    _TOOL_RUNTIME.set_workspace(WORK_DIR, ROOT_DIR)


def _sync_tool_globals() -> None:
    global WORK_DIR, ROOT_DIR
    WORK_DIR = _TOOL_RUNTIME.work_dir
    ROOT_DIR = _TOOL_RUNTIME.root_dir


def _is_within_root(path: Path) -> bool:
    _sync_tool_runtime()
    try:
        path.resolve().relative_to(Path(ROOT_DIR).resolve())
        return True
    except ValueError:
        return False


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


# Memoria Persistente SQLite + FTS5 ────────────────────────────────────────
COMPACT_THRESHOLD = 50

class MemoryDB:
    """
    Memoria persistente entre sesiones usando SQLite + FTS5.
    Soporta búsqueda full-text, importancia, timestamps y conteo de accesos.
    """
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init()
        self._migrate_json()

    def _init(self):
        with _db_conn(self.db_path) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    key          TEXT    NOT NULL,
                    value        TEXT    NOT NULL,
                    category     TEXT    NOT NULL DEFAULT 'fact',
                    tags         TEXT    NOT NULL DEFAULT '',
                    importance   INTEGER NOT NULL DEFAULT 5,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    created_at   REAL    NOT NULL DEFAULT 0,
                    updated_at   REAL    NOT NULL DEFAULT 0,
                    UNIQUE(key, category)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(key, value, content=memories, content_rowid=id);
                CREATE TRIGGER IF NOT EXISTS mem_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid,key,value) VALUES(new.id,new.key,new.value);
                END;
                CREATE TRIGGER IF NOT EXISTS mem_au AFTER UPDATE ON memories BEGIN
                    UPDATE memories_fts SET key=new.key,value=new.value WHERE rowid=new.id;
                END;
                CREATE TRIGGER IF NOT EXISTS mem_ad AFTER DELETE ON memories BEGIN
                    DELETE FROM memories_fts WHERE rowid=old.id;
                END;
            """)

    def _migrate_json(self):
        """Migra memorias del formato JSON anterior si existe."""
        old = _SCRIPT_DIR / "agent_memory.json"
        if not old.exists(): return
        try:
            data = json.loads(old.read_text(encoding="utf-8"))
            for cat, items in data.items():
                if isinstance(items, dict):
                    for key, value in items.items():
                        self.save(key, str(value), category=cat)
            old.rename(old.with_suffix(".json.bak"))
        except Exception:
            pass

    def save(self, key: str, value: str, category: str = "fact",
             importance: int = 5, tags: str = "") -> dict:
        try:
            with _db_conn(self.db_path) as c:
                c.execute("""
                    INSERT INTO memories(key,value,category,tags,importance,created_at,updated_at)
                    VALUES(?,?,?,?,?,unixepoch('now'),unixepoch('now'))
                    ON CONFLICT(key,category) DO UPDATE SET
                        value=excluded.value, tags=excluded.tags,
                        importance=excluded.importance, updated_at=unixepoch('now')
                """, (key, value, category, tags, importance))
            return {"success": True, "key": key, "category": category}
        except Exception as e:
            return {"error": str(e)}

    def search(self, query: str, limit: int = 5) -> list:
        try:
            with _db_conn(self.db_path) as c:
                rows = c.execute("""
                    SELECT m.key, m.value, m.category, m.importance
                    FROM memories_fts f
                    JOIN memories m ON m.id = f.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY rank, m.importance DESC, m.updated_at DESC
                    LIMIT ?
                """, (query, limit)).fetchall()
                if rows:
                    c.executemany(
                        "UPDATE memories SET access_count=access_count+1 WHERE key=?",
                        [(r[0],) for r in rows]
                    )
            return [{"key": r[0], "value": r[1], "category": r[2], "importance": r[3]}
                    for r in rows]
        except Exception:
            return []

    def delete(self, key: str, category: str = "fact") -> dict:
        try:
            with _db_conn(self.db_path) as c:
                n = c.execute(
                    "DELETE FROM memories WHERE key=? AND category=?", (key, category)
                ).rowcount
            return {"success": True, "deleted": n} if n else {"error": f"'{key}' no encontrado en '{category}'"}
        except Exception as e:
            return {"error": str(e)}

    def top(self, limit: int = 12) -> list:
        """Memorias más importantes para inyectar en el system prompt."""
        try:
            with _db_conn(self.db_path) as c:
                rows = c.execute("""
                    SELECT key, value, category, importance
                    FROM memories
                    ORDER BY importance DESC, access_count DESC, updated_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            return [{"key": r[0], "value": r[1], "category": r[2], "importance": r[3]}
                    for r in rows]
        except Exception:
            return []

    def list_all(self, category: str = "") -> list:
        try:
            with _db_conn(self.db_path) as c:
                if category:
                    rows = c.execute(
                        "SELECT key,value,category,importance FROM memories WHERE category=? ORDER BY importance DESC,updated_at DESC",
                        (category,)
                    ).fetchall()
                else:
                    rows = c.execute(
                        "SELECT key,value,category,importance FROM memories ORDER BY category,importance DESC"
                    ).fetchall()
            return [{"key": r[0], "value": r[1], "category": r[2], "importance": r[3]}
                    for r in rows]
        except Exception:
            return []

    def format_for_prompt(self) -> str:
        mems = self.top(12)
        if not mems: return ""
        by_cat: dict = {}
        for m in mems:
            by_cat.setdefault(m["category"], []).append(f"  • {m['key']}: {m['value']}")
        lines = ["═══════════════════════════════════════════════════════",
                 "MEMORIAS DE SESIONES ANTERIORES",
                 "═══════════════════════════════════════════════════════"]
        for cat, items in by_cat.items():
            lines.append(f"[{cat.upper()}]"); lines.extend(items)
        return "\n".join(lines) + "\n"


# Global — inicializado en Agent.__init__
_mem: Optional[MemoryDB] = None

def save_memory(key: str, value: str, category: str = "fact", importance: int = 5) -> dict:
    if _mem is None: return {"error": "Memoria no inicializada"}
    return _mem.save(key, value, category, importance)

def memory_search(query: str, limit: int = 5) -> dict:
    if _mem is None: return {"error": "Memoria no inicializada"}
    results = _mem.search(query, limit)
    return {"query": query, "results": results, "count": len(results)}

def delete_memory(key: str, category: str = "fact") -> dict:
    if _mem is None: return {"error": "Memoria no inicializada"}
    return _mem.delete(key, category)

_KW_MODES = [
    (r'\b(planifica|plan\s+detallado|plan\s+paso\s+a\s+paso)\b',
     'plan', "Primero genera un plan detallado paso a paso sin usar herramientas. Tarea: "),
    (r'\b(revisa|review)\b.{0,50}\b(código|code|codebase|archivo|función)\b',
     'review', "Revisa el código en profundidad: bugs, seguridad, performance, code smells. "),
    (r'\b(busca\s+(el\s+)?bugs?|bughunter|encuentra\s+(el\s+)?(bug|error))\b',
     'debug', "Modo bughunter: hipótesis → reproduce → localiza → corrige. "),
    (r'\bauditor[íi]a\s+de\s+seguridad\b|security\s+audit\b',
     'security', "Auditoría de seguridad: inyección, auth, autorización, datos sensibles, dependencias vulnerables. "),
]

def detect_keyword_mode(text: str) -> tuple[str, str]:
    """Detecta triggers de modo en el prompt. Retorna (mode, texto_modificado)."""
    if text.startswith("/"):
        return "", text
    for pattern, mode, prefix in _KW_MODES:
        if re.search(pattern, text, re.I):
            return mode, prefix + text
    return "", text


TOOL_MAP = {
    "run_command": run_command, "read_file": read_file, "write_file": write_file,
    "edit_file": edit_file, "find_files": find_files, "grep": grep,
    "list_directory": list_directory, "delete_file": delete_file,
    "create_directory": create_directory, "move_file": move_file,
    "search_web": search_web, "fetch_url": fetch_url, "change_directory": change_directory,
    "save_memory": save_memory, "memory_search": memory_search, "delete_memory": delete_memory,
}

TOOLS = build_tool_definitions(
    include_web=True,
    extra_tools=[
        {"type":"function","function":{"name":"save_memory","description":"Guarda un hecho duradero en memoria persistente SQLite entre sesiones. Usa para preferencias, patrones de código, decisiones de arquitectura, bugs conocidos.","parameters":{"type":"object","properties":{"key":{"type":"string","description":"Identificador corto en snake_case"},"value":{"type":"string","description":"Descripción concisa del hecho a recordar"},"category":{"type":"string","enum":["fact","pattern","preference","bug","project"],"description":"Categoría de la memoria"},"importance":{"type":"integer","description":"Importancia 1-10 (10=crítico). Default 5."}},"required":["key","value"]}}},
        {"type":"function","function":{"name":"memory_search","description":"Busca en la memoria persistente por texto. Usa full-text search para encontrar memorias relevantes al contexto actual.","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Términos a buscar"},"limit":{"type":"integer","description":"Máximo de resultados (default 5)"}},"required":["query"]}}},
        {"type":"function","function":{"name":"delete_memory","description":"Elimina una memoria guardada.","parameters":{"type":"object","properties":{"key":{"type":"string"},"category":{"type":"string","enum":["fact","pattern","preference","bug","project"]}},"required":["key"]}}},
    ],
)


# ── AST Scanner (Fase 5) ──────────────────────────────────────────────────────
def scan_project_ast(work_dir: str, max_files: int = 30) -> str:
    """
    Extrae esqueleto AST del proyecto: clases, funciones, métodos.
    Usa ast de Python para .py y regex para .js/.ts/.tsx.
    Ahorra tokens enviando estructura en lugar de texto completo.
    """
    wd = Path(work_dir)
    lines = [f"# Esqueleto AST de {wd.name}"]
    count = 0

    # Python via ast module
    for f in sorted(wd.rglob("*.py")):
        if any(p in f.parts for p in [".git","__pycache__","node_modules",".venv","venv"]): continue
        if count >= max_files: break
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = _ast.parse(src, filename=str(f))
            rel = f.relative_to(wd)
            file_items = []
            for node in tree.body:
                if isinstance(node, _ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
                    file_items.append(f"  class {node.name}({', '.join(methods[:8])})")
                elif isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    file_items.append(f"  def {node.name}()")
            if file_items:
                lines.append(f"\n## {rel}"); lines.extend(file_items[:20])
                count += 1
        except: pass

    # JS/TS via regex
    for ext in ("*.js", "*.ts", "*.tsx", "*.jsx"):
        for f in sorted(wd.rglob(ext)):
            if any(p in f.parts for p in [".git","node_modules","dist","build",".next"]): continue
            if count >= max_files: break
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
                rel = f.relative_to(wd)
                items = []
                for m in re.finditer(r'(?:export\s+)?(?:default\s+)?(?:class|function|const|interface|type)\s+(\w+)', src):
                    items.append(f"  {m.group(0)[:60]}")
                if items:
                    lines.append(f"\n## {rel}"); lines.extend(items[:20])
                    count += 1
            except: pass

    return "\n".join(lines) if count > 0 else "No se encontraron archivos de código."


# ── UI ────────────────────────────────────────────────────────────────────────
_TOOL_LABELS = {
    "edit_file":("Update","path"), "write_file":("Write","path"), "read_file":("Read","path"),
    "run_command":("Bash","command"), "find_files":("Glob","pattern"), "grep":("Grep","pattern"),
    "list_directory":("LS","path"), "delete_file":("Delete","path"), "create_directory":("Mkdir","path"),
    "move_file":("Move","src"), "search_web":("Web","query"), "fetch_url":("Fetch","url"),
    "change_directory":("CD","path"), "save_memory":("Memory+","key"),
    "memory_search":("MemSearch","query"), "delete_memory":("Memory-","key"),
}

def _rel(s: str) -> str:
    try: return str(Path(s).relative_to(Path(WORK_DIR)))
    except ValueError: return s

def _render_inline(text: str) -> Text:
    result = Text(); i = 0
    while i < len(text):
        if text[i] == "`":
            j = text.find("`", i+1)
            if j != -1: result.append(text[i+1:j], style=f"bold {C_TOOLARG}"); i = j+1; continue
        if text[i:i+2] == "**":
            j = text.find("**", i+2)
            if j != -1: result.append(text[i+2:j], style="bold white"); i = j+2; continue
        result.append(text[i], style=C_TEXT); i += 1
    return result

def print_tool_call(name: str, args: dict):
    t = Text()
    if name in _TOOL_LABELS:
        label, key = _TOOL_LABELS[name]; val = _rel(str(args.get(key, "")))[:90]
        t.append("● ", style=f"bold {C_BULLET}"); t.append(label, style=f"bold {C_TOOL}")
        t.append("(", style=C_DIM); t.append(val, style=C_TOOLARG); t.append(")", style=C_DIM)
    else:
        t.append("● ", style=f"bold {C_BULLET}"); t.append(name, style=f"bold {C_TOOL}")
        t.append("(" + ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items()) + ")", style=C_TOOLARG)
    console.print(t)

def _print_diff(result: dict):
    la = result.get("added", 0); lr = result.get("removed", 0)
    s = Text(); s.append("  └ ", style=C_DIM)
    parts = []
    if la: parts.append(Text(f"+{la}", style=C_OK))
    if lr: parts.append(Text(f"-{lr}", style=C_ERR))
    for i, p in enumerate(parts):
        if i: s.append("  ", style=C_DIM)
        s.append_text(p)
    console.print(s)
    for ln, kind, content in result.get("diff", []):
        row = Text(overflow="fold")
        if kind == "removed":
            row.append(f"{ln:4} ", style=C_DIM); row.append("- ", style=f"bold {C_ERR}")
            row.append(f"  {content}", style=f"{C_ERR} on #2d0000")
        elif kind == "added":
            row.append(f"{ln:4} ", style=C_DIM); row.append("+ ", style=f"bold {C_OK}")
            row.append(f"  {content}", style=f"{C_OK} on #002d00")
        else:
            row.append(f"{ln:4}   ", style=C_DIM); row.append(f"  {content}", style=C_DIM)
        console.print(row)

def print_tool_result(result: dict):
    t = Text()
    if "error" in result: t.append("  ✗ " + result["error"], style=C_ERR)
    elif "diff" in result: _print_diff(result); return
    elif "stdout" in result:
        out = result.get("stdout",""); err = result.get("stderr",""); rc = result.get("returncode",0)
        t.append("  ✓ ", style=C_OK)
        if out: t.append(out[:1200] + ("…" if len(out)>1200 else ""), style=C_TEXT)
        if err: t.append(f"\n    stderr: {err}", style=C_ERR)
        if rc != 0: t.append(f"  [rc={rc}]", style=C_ERR)
    elif "content" in result and "url" in result:
        t.append(f"  ✓ {result.get('chars',0)} chars · {result['url'][:60]}", style=C_DIM)
    elif "content" in result:
        t.append(f"  ✓ {result['lines']} líneas · {result['path']}", style=C_DIM)
    elif "query" in result and "results" in result:
        t.append(f"  ✓ {len(result['results'])} resultados: {result['query']}\n", style=C_DIM)
        for r in result["results"][:3]:
            t.append(f"    · {r.get('title','')[:70]}\n", style=C_TEXT)
    elif "files" in result: t.append(f"  ✓ {len(result['files'])} archivos", style=C_DIM)
    elif "results" in result: t.append(f"  ✓ {len(result['results'])} coincidencias", style=C_DIM)
    elif "cwd" in result: t.append(f"  ✓ dir → {result['cwd']}", style=C_TOOLARG)
    elif "success" in result:
        t.append("  ✓ " + (result.get("to") or result.get("path") or "ok"), style=C_DIM)
    else: t.append("  ✓ ok", style=C_DIM)
    console.print(t)

def print_header(model: str, backend: str, work_dir: str, tag: str, ctx: int, temp: float, router: SmartRouter):
    console.print()
    logo = Text.from_markup(f"[{C_LOGO}]╔════╗\n║MEGA║\n║ IA ║\n╚════╝[/]")
    info = Text()
    info.append(f"  {tag}", style="bold white"); info.append("  ·  ", style=C_DIM)
    info.append(model, style=C_LOGO); info.append("  ", style=C_DIM)
    info.append(router.icon(backend), style=C_ROUTER); info.append("\n")
    info.append(f"  ctx:{ctx}  temp:{temp}  {work_dir}\n", style=C_DIM)
    internet = "internet · " if WEB_AVAILABLE else ""
    critic_txt = "actor-crítico · " if tag.endswith("★") else ""
    info.append(f"  {internet}{critic_txt}tools · streaming · router · self-healing\n", style=C_DIM)
    info.append("  /help para comandos  ·  'salir' para terminar", style=C_DIM)
    console.print(Padding(Columns([logo, info], padding=(0, 2)), (1, 2)))
    console.print(Rule(style=C_BORDER)); console.print()

SLASH_HELP = """[bold]Comandos disponibles:[/]
  [bold cyan]/help[/]                    — muestra esta ayuda
  [bold cyan]/clear[/]                   — nueva sesión (borra historial)
  [bold cyan]/switch [local|groq|auto][/]   — fuerza backend
  [bold cyan]/model [nombre][/]          — cambia modelo local o cloud
  [bold cyan]/ctx[/]                     — muestra uso estimado de contexto
  [bold cyan]/cost[/]                    — estadísticas de uso local/groq
  [bold cyan]/critic [on|off][/]         — activa/desactiva modo Actor-Crítico
  [bold cyan]/ast[/]                     — muestra esqueleto AST del proyecto
  [bold cyan]/plan [tarea][/]            — genera un plan antes de ejecutar
  [bold cyan]/dream[/]                   — extrae memorias valiosas de esta sesión
  [bold cyan]/memory [list|forget KEY|clear][/] — gestiona memorias persistentes
  [bold cyan]/compact[/]                 — compacta el contexto con resumen LLM"""


# ── System Prompt ─────────────────────────────────────────────────────────────
def build_system_prompt(work_dir: str, project_context: str, memories: str = "") -> str:
    desktop = str(Path.home() / "Desktop")
    return f"""Eres un agente autónomo de programación de nivel profesional. Directorio de trabajo: {work_dir}
Escritorio del usuario: {desktop}

{project_context}
{memories}
═══════════════════════════════════════════════════════
REGLA #0 — CUÁNDO NO USAR HERRAMIENTAS
═══════════════════════════════════════════════════════
Para saludos, preguntas generales y conversación casual → responde
directamente con texto. NO uses ninguna herramienta.
Ejemplos que NO requieren herramientas:
  "hola", "¿cómo estás?", "¿qué puedes hacer?", "gracias", "explícame X"
Las herramientas son para TAREAS concretas sobre archivos, código o terminal.

═══════════════════════════════════════════════════════
REGLA #1 — NUNCA DIGAS AL USUARIO QUÉ HACER — HAZLO TÚ
═══════════════════════════════════════════════════════
Cuando la tarea requiera acción: PROHIBIDO escribir "Puedes ejecutar:",
"Deberías correr:", "Te recomiendo que...". Usa la herramienta directamente.

═══════════════════════════════════════════════════════
REGLA #2 — ENCADENA PASOS SIN PAUSAR NI PREGUNTAR
═══════════════════════════════════════════════════════
1. Llama herramientas en secuencia hasta completar la tarea.
2. Solo reporta al final qué hiciste y el resultado.
PROHIBIDO: "¿Quieres que continúe?", "¿Procedo?"

═══════════════════════════════════════════════════════
REGLA #3 — EDICIÓN POR DIFFS (NUNCA REESCRIBIR ENTERO)
═══════════════════════════════════════════════════════
SIEMPRE usa edit_file(old_text, new_text) para modificar archivos.
PROHIBIDO reescribir un archivo completo con write_file si ya existe.
Ventaja: preserva VRAM, evita conflictos, es reversible.

═══════════════════════════════════════════════════════
REGLA #4 — CREAR ARCHIVOS = write_file() SIEMPRE
═══════════════════════════════════════════════════════
Cuando el usuario pide "crea un script", "hazme un archivo", "escribe un programa":
  → USA write_file(path, content) — NUNCA muestres el código en el chat
  → NUNCA digas "aquí está el código" y lo pegues como texto

Rutas según lo que diga el usuario:
  "en el escritorio" → {desktop}\\nombre.py
  "aquí" o sin indicar → ruta relativa al directorio de trabajo
  ruta absoluta explícita → úsala tal cual

═══════════════════════════════════════════════════════
REGLA #5 — LEE ANTES DE TOCAR
═══════════════════════════════════════════════════════
SIEMPRE usa read_file() antes de edit_file(). Sin excepciones.

═══════════════════════════════════════════════════════
REGLA #6 — AUTO-CORRECCIÓN (SELF-HEALING)
═══════════════════════════════════════════════════════
Si un comando falla (rc!=0 o error en herramienta):
  1. Lee el error COMPLETO incluyendo stderr.
  2. Reformula tu hipótesis sobre la causa.
  3. Ejecuta la corrección inmediatamente, sin explicar.
  4. Hasta 3 intentos diferentes por problema.
Solo reporta si 3 intentos distintos fallan.

═══════════════════════════════════════════════════════
RAZONAMIENTO INTERNO (Chain of Thought)
═══════════════════════════════════════════════════════
Antes de actuar, razona en:
<thought>
1. Entendimiento: [qué pide el usuario exactamente]
2. Plan: [pasos a-b-c con herramientas y argumentos]
3. Riesgos: [efectos secundarios posibles]
4. Verificación: [cómo confirmaré que funcionó]
</thought>
El contenido de <thought> NUNCA se muestra al usuario.

═══════════════════════════════════════════════════════
ESTILO DE RESPUESTA
═══════════════════════════════════════════════════════
- Conciso y directo. Sin cortesías vacías.
- ✓ "Corregido bug en main.py:42. Tests pasan."
- ✗ "Entiendo que quieres... voy a proceder a..."
- Responde en español.
"""

def load_project_context(work_dir: str) -> str:
    for name in ["CLAUDE.md", "README.md", ".cursorrules"]:
        p = Path(work_dir) / name
        if p.exists():
            try:
                return f"Contexto del proyecto ({name}):\n{p.read_text(encoding='utf-8', errors='replace')[:16000]}\n"
            except: pass
    return ""


# ── Clase Agent ───────────────────────────────────────────────────────────────
class Agent:
    def __init__(self, model: str, work_dir: str, tag: str, ctx: int, temp: float,
                 local_url: str, groq_model: str, backend: str, critic: bool,
                 system_prompt_path: Optional[str] = None):
        global WORK_DIR, ROOT_DIR, _mem
        self.model      = model
        self.work_dir   = str(Path(work_dir).resolve())
        self.tag        = tag + (" ★" if critic else "")
        self.ctx        = ctx
        self.temp       = temp
        self.local_url  = local_url
        self.groq_model = groq_model
        self.critic     = critic
        self.messages: list = []
        self.system_prompt_path = Path(system_prompt_path).resolve() if system_prompt_path else None
        WORK_DIR = self.work_dir
        ROOT_DIR = self.work_dir
        self.selected_backend = backend if backend != "auto" else None

        # Clientes OpenAI-compatible
        self.local_client = OpenAI(
            base_url=local_url,
            api_key=os.getenv("LOCAL_API_KEY", "ollama"),
        )
        groq_key = os.getenv("GROQ_API_KEY", "")
        self.groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key or "NO_KEY",
        ) if groq_key else None

        self.router = SmartRouter(force=None if backend == "auto" else backend)
        self.logger = _make_logger(f"mega.{id(self)}", Path(self.work_dir) / "agent_session.jsonl")

        # Memoria persistente SQLite + FTS5
        _mem = MemoryDB(_SCRIPT_DIR / "memory.db")
        self.memdb = _mem

        # prompt_toolkit session con historial en el directorio del script
        history_path = str(_SCRIPT_DIR / ".history")
        if PTOOLKIT:
            pt_style = PTStyle.from_dict({"prompt": "#5B9BD5 bold"})
            self.pt_session = PromptSession(
                history=FileHistory(history_path),
                auto_suggest=AutoSuggestFromHistory(),
                style=pt_style,
            )
        else:
            self.pt_session = None

    def _read_system_prompt_override(self) -> Optional[str]:
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

    def _client_for(self, backend: str):
        if backend == "groq" and self.groq_client:
            return self.groq_client, self.groq_model
        return self.local_client, self.model

    def _model_for(self, backend: str) -> str:
        if backend == "groq":
            return self.groq_model
        return self.model

    def _set_model(self, model_name: str) -> str:
        if model_name in {name for name, *_ in GROQ_MODELS}:
            self.groq_model = model_name
            self.selected_backend = "groq"
            return f"Modelo cloud cambiado a: {model_name}"
        self.model = model_name
        self.selected_backend = "local"
        return f"Modelo local cambiado a: {model_name}"

    def _get_input(self) -> str:
        console.print()
        if self.pt_session:
            try:
                return self.pt_session.prompt("> ").strip()
            except (KeyboardInterrupt, EOFError):
                return "salir"
        try:
            console.print(f"[{C_PROMPT}]>[/] ", end="")
            return input().strip()
        except (KeyboardInterrupt, EOFError):
            return "salir"

    def _handle_slash(self, cmd: str, system_prompt: str) -> Optional[str]:
        """Procesa comandos /slash. Retorna None para continuar, 'break' para salir."""
        parts = cmd.split(maxsplit=1)
        c = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if c == "/help":
            console.print(Panel(SLASH_HELP, border_style=C_BORDER))
        elif c == "/clear":
            self.messages = [{"role": "system", "content": system_prompt}]
            console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
        elif c == "/switch":
            if arg in ("local", "groq"):
                self.router.force = arg
                self.selected_backend = arg
                console.print(f"[{C_ROUTER}]  ✓ Backend forzado: {self.router.icon(arg)}[/]")
            elif arg == "auto":
                self.router.force = None
                self.selected_backend = None
                console.print(f"[{C_ROUTER}]  ✓ Router automático activado[/]")
            else:
                console.print(f"[{C_ERR}]  Uso: /switch [local|groq|auto][/]")
        elif c == "/model":
            if arg:
                msg = self._set_model(arg)
                console.print(f"[{C_OK}]  ✓ {msg}[/]")
            else:
                actual = self.groq_model if self.selected_backend == "groq" else self.model
                origen = "cloud" if self.selected_backend == "groq" else "local"
                console.print(f"[{C_DIM}]  Modelo actual ({origen}): {actual}[/]")
        elif c == "/ctx":
            chars = sum(len(str(m.get("content",""))) for m in self.messages)
            est = chars // 4
            console.print(f"[{C_DIM}]  Contexto estimado: ~{est} tokens ({chars} chars) · ventana: {self.ctx}[/]")
        elif c == "/cost":
            console.print(f"[{C_DIM}]  Uso de backends → {self.router.stats()}[/]")
        elif c == "/critic":
            if arg == "on":
                self.critic = True
                console.print(f"[{C_CRITIC}]  ✓ Actor-Crítico activado[/]")
            elif arg == "off":
                self.critic = False
                console.print(f"[{C_DIM}]  Actor-Crítico desactivado[/]")
            else:
                console.print(f"[{C_DIM}]  Crítico: {'ON' if self.critic else 'OFF'}[/]")
        elif c == "/ast":
            console.print(f"[{C_DIM}]  Escaneando proyecto...[/]")
            ast_out = scan_project_ast(self.work_dir)
            console.print(Panel(ast_out[:3000], title="AST Skeleton", border_style=C_BORDER))
        elif c == "/plan":
            if arg:
                return f"Antes de ejecutar nada, genera un plan detallado paso a paso para: {arg}. No ejecutes herramientas aún, solo el plan."
            else:
                console.print(f"[{C_ERR}]  Uso: /plan [descripción de la tarea][/]")
        elif c == "/dream":
            self._dream()
        elif c == "/memory":
            sub = arg.split(maxsplit=1)
            if sub and sub[0] == "forget":
                key = sub[1].strip() if len(sub) > 1 else ""
                if not key:
                    console.print(f"[{C_ERR}]  Uso: /memory forget [clave][/]")
                else:
                    r = self.memdb.delete(key)
                    if r.get("deleted", 0):
                        console.print(f"[{C_OK}]  ✓ Eliminado: {key}[/]")
                    else:
                        console.print(f"[{C_ERR}]  '{key}' no encontrado[/]")
            elif sub and sub[0] == "search":
                q = sub[1].strip() if len(sub) > 1 else ""
                if not q:
                    console.print(f"[{C_ERR}]  Uso: /memory search [consulta][/]")
                else:
                    results = self.memdb.search(q, limit=8)
                    if results:
                        for m in results:
                            console.print(f"  [{C_CRITIC}]{m['category']}[/]  [bold]{m['key']}[/]  [{C_DIM}]★{m['importance']}[/]: {m['value']}")
                    else:
                        console.print(f"[{C_DIM}]  Sin resultados para: {q}[/]")
            elif arg == "clear":
                with _db_conn(self.memdb.db_path) as c_:
                    c_.execute("DELETE FROM memories")
                console.print(f"[{C_OK}]  ✓ Todas las memorias eliminadas[/]")
            else:
                all_mems = self.memdb.list_all()
                if not all_mems:
                    console.print(f"[{C_DIM}]  Sin memorias guardadas. Usa /dream para extraer.[/]")
                else:
                    for m in all_mems:
                        console.print(f"  [{C_CRITIC}]{m['category']}[/]  [{C_DIM}]★{m['importance']}[/]  [bold]{m['key']}[/]: {m['value']}")
        elif c == "/compact":
            self._compact_if_needed(force=True)
        else:
            console.print(f"[{C_ERR}]  Comando desconocido: {c}  (usa /help)[/]")
        return None

    def _stream_response(self, messages: list, backend: str) -> tuple[str, list]:
        """Hace streaming y retorna (content, tool_calls). Parsea <think>/<thought>."""
        client, model = self._client_for(backend)
        collected: list[str] = []
        tool_calls_raw: list = []
        first_output = [True]
        t_start = time.monotonic()

        def _drain(stream):
            state = None
            thought_buf: list[str] = []
            tc_accum: dict = {}
            buf = ""
            json_mode   = [False]  # bufferear en silencio si el modelo emite JSON como texto
            hdr_printed = [False]  # header diferido hasta tener contenido real

            def _hdr():
                if not hdr_printed[0]:
                    console.print(f"\n[{C_BULLET}]●[/] [{C_ROUTER}]{self.router.icon(backend)}[/]  ", end="")
                    hdr_printed[0] = True

            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if not delta: continue

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id: tc_accum[idx]["id"] = tc.id
                        if tc.function.name: tc_accum[idx]["name"] += tc.function.name
                        if tc.function.arguments: tc_accum[idx]["arguments"] += tc.function.arguments

                content = delta.content or ""
                if not content: continue

                if first_output[0]:
                    live.stop()
                    first_output[0] = False

                # Detectar JSON en el primer carácter no-blanco (puede estar en chunks tardíos)
                if not json_mode[0] and not hdr_printed[0]:
                    visible = (buf + content).lstrip()
                    if visible and visible[0] in ("{", "["):
                        json_mode[0] = True

                # Modo JSON: bufferear en silencio, sin imprimir
                if json_mode[0]:
                    collected.append(content)
                    continue

                buf += content
                while True:
                    if state is None:
                        ti = buf.find("<think>"); thi = buf.find("<thought>")
                        first_pos = len(buf); first_tag = None
                        if ti != -1 and ti < first_pos: first_pos, first_tag = ti, "think"
                        if thi != -1 and thi < first_pos: first_pos, first_tag = thi, "thought"
                        if first_tag is None:
                            cut = max(0, len(buf) - 9)
                            if cut:
                                _hdr()
                                console.print(_render_inline(buf[:cut]), end="")
                                collected.append(buf[:cut]); buf = buf[cut:]
                            break
                        if first_pos:
                            _hdr()
                            console.print(_render_inline(buf[:first_pos]), end="")
                            collected.append(buf[:first_pos])
                        if first_tag == "think":
                            buf = buf[first_pos+7:]; state = "think"
                            console.print(f"\n[{C_DIM}]  💭 ", end="")
                        else:
                            buf = buf[first_pos+9:]; state = "thought"; thought_buf = []
                    elif state == "thought":
                        i = buf.find("</thought>")
                        if i == -1:
                            cut = max(0, len(buf) - 10)
                            if cut: thought_buf.append(buf[:cut]); buf = buf[cut:]
                            break
                        thought_buf.append(buf[:i]); buf = buf[i+10:]; state = None
                        tc_content = "".join(thought_buf)
                        if tc_content.strip():
                            self.logger.debug("Razonamiento interno", extra={"tool_args": {"thought": tc_content[:2000]}})
                        console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    else:  # think
                        i = buf.find("</think>")
                        if i == -1:
                            cut = max(0, len(buf) - 8)
                            if cut: console.print(f"[{C_DIM}]{escape(buf[:cut])}[/]", end=""); buf = buf[cut:]
                            break
                        if i: console.print(f"[{C_DIM}]{escape(buf[:i])}[/]", end="")
                        buf = buf[i+8:]; state = None
                        console.print(f"\n[{C_BULLET}]●[/] ", end="")

            if buf.strip():
                if state == "thought": thought_buf.append(buf)
                elif state == "think": console.print(f"[{C_DIM}]{escape(buf)}[/]", end="")
                else:
                    _hdr()
                    console.print(_render_inline(buf), end=""); collected.append(buf)

            # Finalizar tool calls acumulados vía delta.tool_calls
            for tc in tc_accum.values():
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    tool_calls_raw.append({"id": tc["id"] or tc["name"], "name": tc["name"], "arguments": args})
                except json.JSONDecodeError:
                    tool_calls_raw.append({"id": tc["id"] or tc["name"], "name": tc["name"], "arguments": {}})

            # Fallback: el modelo emitió el tool call como texto JSON
            if not tool_calls_raw and collected:
                raw_text = "".join(collected).strip()
                candidates = []
                if raw_text.startswith("["):
                    try: candidates = json.loads(raw_text)
                    except json.JSONDecodeError: pass
                elif raw_text.startswith("{"):
                    try: candidates = [json.loads(raw_text)]
                    except json.JSONDecodeError: pass
                for obj in candidates:
                    if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
                        args = obj["arguments"]
                        if not isinstance(args, dict):
                            try: args = json.loads(args)
                            except (json.JSONDecodeError, TypeError): args = {}
                        tool_calls_raw.append({
                            "id":        obj.get("id", obj["name"]),
                            "name":      obj["name"],
                            "arguments": args,
                        })
                if tool_calls_raw:
                    collected.clear()
                elif json_mode[0]:
                    # era JSON pero no válido como tool call — imprimir como texto
                    _hdr()
                    console.print(_render_inline("".join(collected)), end="")

        with Live(Spinner("dots", text=f"[{C_ROUTER}]{self.router.icon(backend)}[/] Pensando... 0s"),
                  console=console, transient=True, refresh_per_second=4) as live:
            def _tick():
                while first_output[0]:
                    elapsed = time.monotonic() - t_start
                    live.update(Spinner("dots", text=f"[{C_ROUTER}]{self.router.icon(backend)}[/] Pensando... {elapsed:.0f}s"))
                    time.sleep(0.25)
            threading.Thread(target=_tick, daemon=True).start()
            # extra_body solo se aplica al backend local (Ollama) — fuerza todo a GPU
            _ollama_opts = {"num_gpu": 99, "num_ctx": self.ctx, "num_predict": -1,
                            "num_batch": 512, "main_gpu": 0} if backend == "local" else {}
            try:
                kwargs = dict(model=model, messages=messages, tools=TOOLS, stream=True,
                              temperature=self.temp, max_tokens=self.ctx,
                              **({"extra_body": {"options": _ollama_opts}} if _ollama_opts else {}))
                _drain(client.chat.completions.create(**kwargs))
            except Exception as e:
                if first_output[0]: live.stop(); first_output[0] = False
                no_tools_err = any(x in str(e).lower() for x in ["tool", "function_call", "not supported"])
                if no_tools_err:
                    console.print(f"\n[{C_BULLET}]●[/] [{C_ROUTER}]{self.router.icon(backend)}[/]  ", end="")
                    try:
                        kw2 = dict(model=model, messages=messages, stream=True, temperature=self.temp, max_tokens=self.ctx,
                                   **({"extra_body": {"options": _ollama_opts}} if _ollama_opts else {}))
                        _drain(client.chat.completions.create(**kw2))
                    except Exception as e2:
                        console.print(f"\n[{C_ERR}]Error: {e2}[/]")
                else:
                    console.print(f"\n[{C_ERR}]Error ({backend}): {e}[/]")
                    self.logger.error("Error LLM", extra={"error_details": str(e)}, exc_info=True)

        elapsed = time.monotonic() - t_start
        if not tool_calls_raw: console.print()
        console.print(f"[{C_DIM}]✳ {elapsed:.1f}s · {self.router.icon(backend)}[/]")
        return "".join(collected), tool_calls_raw

    def _critic_review(self, task_summary: str, changes: list[str]) -> None:
        """Actor-Crítico: segunda llamada local para revisar cambios de código."""
        if not changes: return
        console.print(f"\n[{C_CRITIC}]  ⚡ Actor-Crítico revisando...[/]")
        review_prompt = f"""Eres un revisor de código senior. Revisa estos cambios brevemente:

Tarea realizada: {task_summary}
Archivos modificados: {', '.join(changes)}

Busca: bugs obvios, problemas de seguridad, errores de lógica.
Responde en máximo 3 puntos concisos. Si todo está bien, di solo "✓ Sin problemas."
No repitas lo que se hizo, solo señala problemas si los hay."""
        try:
            resp = self.local_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": review_prompt}],
                stream=False, temperature=0.1, max_tokens=300,
            )
            review = resp.choices[0].message.content or ""
            if review.strip():
                console.print(f"[{C_CRITIC}]  ★ Crítico:[/] ", end="")
                console.print(_render_inline(review.strip()))
        except Exception as e:
            console.print(f"[{C_DIM}]  (Crítico no disponible: {e})[/]")

    def _validate_tool_args(self, fn_name: str, args: dict) -> dict:
        fn = TOOL_MAP[fn_name]
        try:
            bound = inspect.signature(fn).bind(**args)
            bound.apply_defaults()
            return dict(bound.arguments)
        except TypeError as e:
            return {"error": f"Argumentos inválidos para '{fn_name}': {e}"}

    def _invoke_tool(self, fn_name: str, fn_args: dict) -> dict:
        try:
            return TOOL_MAP[fn_name](**fn_args)
        except Exception as e:
            self.logger.error(
                "Excepción en herramienta",
                extra={"tool_name": fn_name, "error_details": str(e)},
                exc_info=True
            )
            return {"error": f"Excepción ejecutando '{fn_name}': {e}"}

    def _dream(self) -> None:
        """Extrae memorias valiosas de la sesión actual con un call LLM separado."""
        if len(self.messages) < 5:
            console.print(f"[{C_DIM}]  Sesión muy corta para extraer memorias.[/]")
            return
        console.print(f"[{C_CRITIC}]  💭 Extrayendo memorias de la sesión...[/]")
        session_text = "\n".join(
            f"[{m['role'].upper()}]: {str(m.get('content',''))[:400]}"
            for m in self.messages[1:] if m.get("content")
        )[-7000:]
        dream_tools = [t for t in TOOLS if t["function"]["name"] == "save_memory"]
        prompt = (f"Analiza esta sesión y extrae hasta 6 hechos valiosos para futuras sesiones.\n"
                  f"Llama save_memory(key, value, category) por cada uno.\n"
                  f"Categorías: facts (info del proyecto), patterns (cómo trabaja el usuario), "
                  f"preferences (estilo preferido), bugs (bugs encontrados/resueltos).\n"
                  f"Solo lo realmente útil para retomar el trabajo. Si no hay nada, no guardes.\n\n"
                  f"Sesión:\n{session_text}")
        try:
            resp = self.local_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                tools=dream_tools, temperature=0.1, max_tokens=1500, stream=False,
            )
            saved = 0
            msg = resp.choices[0].message
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.function.name == "save_memory":
                        try:
                            args = json.loads(tc.function.arguments)
                            r = save_memory(**args)
                            if "success" in r:
                                saved += 1
                                console.print(f"[{C_DIM}]    · [{r['category']}] {r['key']}: {str(args.get('value',''))[:60]}[/]")
                        except Exception:
                            pass
            console.print(f"[{C_OK}]  ✓ {saved} memorias guardadas[/]" if saved
                          else f"[{C_DIM}]  Sin memorias valiosas en esta sesión.[/]")
        except Exception as e:
            console.print(f"[{C_ERR}]  ✗ Dream error: {e}[/]")

    def _compact_if_needed(self, force: bool = False) -> None:
        """Compacta el historial con resumen LLM si supera el umbral."""
        if not force and len(self.messages) < COMPACT_THRESHOLD:
            return
        keep_recent = 8
        to_summarize = self.messages[1:-keep_recent]
        if not to_summarize:
            return
        console.print(f"[{C_DIM}]  ↻ Compactando {len(to_summarize)} msgs...[/]")
        session_text = "\n".join(
            f"[{m['role'].upper()}]: {str(m.get('content',''))[:300]}"
            for m in to_summarize if m.get("content")
        )[-6000:]
        try:
            resp = self.local_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content":
                    f"Resume en 350 tokens preservando: tareas completadas, archivos modificados, "
                    f"decisiones tomadas, errores y soluciones encontradas. Solo hechos.\n\n{session_text}"}],
                temperature=0.1, max_tokens=400, stream=False,
            )
            summary = resp.choices[0].message.content or ""
            if summary:
                self.messages = [
                    self.messages[0],
                    {"role": "system", "content": f"[SESIÓN COMPACTADA]\n{summary}"},
                    *self.messages[-keep_recent:]
                ]
                console.print(f"[{C_OK}]  ✓ Contexto: {len(to_summarize)+keep_recent} → {len(self.messages)} msgs[/]")
        except Exception as e:
            console.print(f"[{C_ERR}]  ✗ Compact error: {e}[/]")

    def run(self):
        def _make_system_prompt() -> str:
            project_context = load_project_context(self.work_dir)
            memories_text = self.memdb.format_for_prompt()
            override = self._read_system_prompt_override()
            if override:
                try:
                    return override.format(
                        work_dir=self.work_dir,
                        project_context=project_context,
                        memories=memories_text,
                    )
                except Exception as e:
                    self.logger.error(
                        "Falló el formateo del prompt externo",
                        extra={"error_details": str(e)}
                    )
                    return override
            return build_system_prompt(self.work_dir, project_context, memories_text)

        system_prompt = _make_system_prompt()
        self.messages = [{"role": "system", "content": system_prompt}]

        self.logger.info("Sesión iniciada", extra={"tool_args": {
            "model": self.model, "backend": self.router.force or "auto",
            "work_dir": self.work_dir, "critic": self.critic,
        }})

        # Detectar backend inicial para el header
        initial_backend, _ = self.router.route("hola", 0)
        print_header(self._model_for(initial_backend), initial_backend, self.work_dir, self.tag, self.ctx, self.temp, self.router)

        while True:
            user_input = self._get_input()
            if not user_input: continue

            # Comandos /slash
            if user_input.startswith("/"):
                if user_input.split(maxsplit=1)[0].lower() == "/clear":
                    system_prompt = _make_system_prompt()
                result = self._handle_slash(user_input, system_prompt)
                if result == "break": break
                if result:  # /plan devuelve prompt modificado
                    user_input = result
                else:
                    continue

            if user_input.lower() in ("salir", "exit", "quit"):
                console.print(f"\n[{C_DIM}]  Hasta luego. ({self.router.stats()})[/]\n")
                self.logger.info("Sesión finalizada")
                break
            if user_input.lower() in ("limpiar", "clear", "reset"):
                system_prompt = _make_system_prompt()
                self.messages = [{"role": "system", "content": system_prompt}]
                console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
                continue

            # Keyword mode detection (auto-activa modos especiales sin /slash)
            mode, user_input = detect_keyword_mode(user_input)
            if mode:
                console.print(f"[{C_CRITIC}]  ⚡ Modo [{mode}] activado automáticamente[/]")

            # Router: decidir backend
            history_chars = sum(len(str(m.get("content",""))) for m in self.messages)
            backend, reason = self.router.route(user_input, history_chars)
            self.router.record(backend)

            if self.router.force is None:  # solo mostrar si es automático
                console.print(f"[{C_DIM}]  → {self.router.icon(backend)}: {reason}[/]")

            self.logger.info("Mensaje usuario", extra={"user_input": user_input})
            self.messages.append({"role": "user", "content": user_input})

            heal_count = 0        # contador self-healing
            changed_files: list[str] = []  # para actor-crítico
            last_task = user_input
            self._compact_if_needed()

            while True:
                trimmed = self.messages[-80:]  # mantener últimos 80 mensajes
                full_content, tool_calls = self._stream_response(trimmed, backend)

                if full_content:
                    self.logger.info("Respuesta asistente", extra={"assistant_response": full_content[:2000]})

                if tool_calls:
                    console.print()
                    self.messages.append({
                        "role": "assistant",
                        "content": full_content or None,
                        "tool_calls": [{"id": tc["id"], "type": "function",
                                        "function": {"name": tc["name"],
                                                     "arguments": json.dumps(tc["arguments"])}}
                                       for tc in tool_calls]
                    })
                    for tc in tool_calls:
                        fn_name = tc["name"]; fn_args = tc["arguments"]
                        if not isinstance(fn_args, dict): fn_args = {}
                        if fn_name in TOOL_MAP:
                            fn_args = self._validate_tool_args(fn_name, fn_args)
                            if "error" in fn_args:
                                result = fn_args
                                print_tool_result(result)
                                self.logger.warning(
                                    "Validación de argumentos fallida",
                                    extra={"tool_name": fn_name, "error_details": result["error"]}
                                )
                            else:
                                print_tool_call(fn_name, fn_args)
                                result = self._invoke_tool(fn_name, fn_args)
                                print_tool_result(result)

                                # Registrar archivos modificados para crítico
                                if fn_name in ("edit_file", "write_file") and "error" not in result:
                                    if p := result.get("path"): changed_files.append(p)

                                # Self-healing: si run_command falla, inyectar contexto de error
                                if fn_name == "run_command" and result.get("returncode", 0) != 0 and "error" not in result:
                                    heal_count += 1
                                    if heal_count <= 3:
                                        stderr = result.get("stderr", ""); stdout = result.get("stdout", "")
                                        heal_msg = (f"[AUTO-HEAL #{heal_count}] El comando falló (rc={result['returncode']}).\n"
                                                    f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}\n"
                                                    f"Analiza el error y corrígelo con un enfoque diferente.")
                                        console.print(f"[{C_ERR}]  ↺ Auto-heal #{heal_count}/3[/]")
                                        self.logger.warning("Self-healing activado", extra={"error_details": stderr[:200]})
                                        result["_heal_hint"] = heal_msg
                        else:
                            result = {"error": f"Tool desconocida: {fn_name}"}
                            print_tool_result(result)

                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                else:
                    self.messages.append({"role": "assistant", "content": full_content})

                    # Actor-Crítico: revisar si hubo cambios de código
                    if self.critic and changed_files:
                        self._critic_review(last_task, list(set(changed_files)))
                        changed_files.clear()

                    heal_count = 0
                    break


# ── Entry point ───────────────────────────────────────────────────────────────
LOCAL_MODELS = [
    ("qwen2.5-coder:14b",  "Coding · 8.5GB VRAM · Mejor coder GPU",        "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:14b",    "Razonamiento · 8.5GB VRAM · Thinking model",    "⭐⭐⭐⭐⭐"),
    ("qwen3:14b",          "Coding+Razonamiento · 8.5GB VRAM · Equilibrado","⭐⭐⭐⭐⭐"),
    ("qwen2.5-coder:32b",  "Coding · 12+7GB RAM · Máxima calidad",          "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:32b",    "Razonamiento · 12+7GB RAM · Thinking máximo",   "⭐⭐⭐⭐⭐"),
    ("mistral-nemo:12b",   "General · 7.5GB VRAM · Multilingüe",            "⭐⭐⭐⭐ "),
    ("dolphin3:8b",        "Sin censura · 5GB VRAM · Rápido",               "⭐⭐⭐⭐ "),
]

GROQ_MODELS = [
    ("llama-3.3-70b-versatile",        "General · 128k ctx · El más capaz",         "⭐⭐⭐⭐⭐"),
    ("deepseek-r1-distill-llama-70b",  "Razonamiento · 128k ctx · Thinking model",  "⭐⭐⭐⭐⭐"),
    ("qwen-qwq-32b",                   "Razonamiento · 128k ctx · Alternativa R1",  "⭐⭐⭐⭐ "),
    ("llama-3.1-8b-instant",           "Rápido · 128k ctx · Tareas simples",        "⭐⭐⭐  "),
]

def select_model_menu(local_url: str) -> str:
    try:
        client = OpenAI(base_url=local_url, api_key=os.getenv("LOCAL_API_KEY","ollama"))
        installed = {m.id for m in client.models.list().data}
    except Exception:
        installed = set()

    console.print(f"\n[{C_LOGO}]  Selecciona modelo local/cloud (Enter = qwen2.5-coder:14b):[/]\n")
    for i, (model, desc, stars) in enumerate(LOCAL_MODELS, 1):
        tick = f"[{C_OK}]✓[/]" if model in installed else f"[{C_DIM}] [/]"
        console.print(f"  [{C_LOGO}]{i:2}[/]  {tick}  {stars}  [bold]{model}[/]")
        console.print(f"           [{C_DIM}]{desc}[/]")

    groq_key = os.getenv("GROQ_API_KEY","")
    if groq_key:
        console.print(f"\n  [{C_ROUTER}]☁  Groq disponible (GROQ_API_KEY detectada)[/]\n")
        for i, (gm, desc, stars) in enumerate(GROQ_MODELS, 100):
            console.print(f"  [{C_LOGO}]{i:3}[/]  [{C_ROUTER}]☁[/]  {stars}  [bold]{gm}[/]")
            console.print(f"           [{C_DIM}]{desc}[/]")

    console.print(f"\n  [{C_DIM}]Número, nombre exacto, o Enter [qwen2.5-coder:14b]:[/] ", end="")
    try:
        choice = input("").strip()
    except (EOFError, KeyboardInterrupt):
        console.print(); return "qwen2.5-coder:14b"

    if not choice: return "qwen2.5-coder:14b"
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(LOCAL_MODELS): return LOCAL_MODELS[idx-1][0]
        if 100 <= idx < 100+len(GROQ_MODELS): return GROQ_MODELS[idx-100][0]
    return choice


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Híbrido MEGA — RTX 5070 + Groq")
    parser.add_argument("--model",        default=None,                    help="Modelo local o Groq (omitir = menú)")
    parser.add_argument("--dir",          default=".",                     help="Directorio de trabajo")
    parser.add_argument("--tag",          default="MEGA",                  help="Tag en el header")
    parser.add_argument("--ctx",          type=int,   default=32768,       help="Tokens máximos de respuesta")
    parser.add_argument("--temp",         type=float, default=0.15,        help="Temperatura 0.0-1.0")
    parser.add_argument("--backend",    default="auto",                     choices=["auto","local","groq"])
    parser.add_argument("--local-url",  default="http://localhost:11434/v1", help="URL del servidor local (SGLang/vLLM/Ollama)")
    parser.add_argument("--groq-model", default="llama-3.3-70b-versatile",  help="Modelo de Groq")
    parser.add_argument("--critic",       action="store_true",             help="Activar modo Actor-Crítico")
    parser.add_argument("--system-prompt", default=None,
                        help="Ruta de archivo para usar como prompt de sistema")
    args = parser.parse_args()

    model = args.model if args.model else select_model_menu(args.local_url)
    groq_names = {name for name, *_ in GROQ_MODELS}
    selected_backend = args.backend
    selected_local_model = model
    selected_groq_model = args.groq_model
    if model in groq_names:
        selected_groq_model = model
        if args.backend == "auto":
            selected_backend = "groq"
        selected_local_model = LOCAL_MODELS[0][0]
    Agent(
        model=selected_local_model, work_dir=args.dir, tag=args.tag, ctx=args.ctx, temp=args.temp,
        local_url=args.local_url, groq_model=selected_groq_model,
        backend=selected_backend, critic=args.critic,
        system_prompt_path=args.system_prompt,
    ).run()

