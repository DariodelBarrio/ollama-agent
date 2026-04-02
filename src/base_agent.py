"""
Shared utilities extracted from src/agent.py and src/hybrid/agent.py.

Centralises:
- Color theme constants
- Rich console singleton
- JSON structured logger
- Tool runtime singleton + wrapped tool functions
- UI helpers: print_tool_call, print_tool_result, _render_inline
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional

# Ensure repo root is on the path so common_* modules are importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common_tools import WEB_AVAILABLE, ToolRuntime, build_tool_definitions

try:
    from rich.console import Console
    from rich.markup import escape  # noqa: F401 – re-exported for agents
    from rich.text import Text
except ImportError:
    print("pip install rich")
    raise


# ── Color theme ───────────────────────────────────────────────────────────────
C_PROMPT  = "#5B9BD5"
C_BULLET  = "#4EC9B0"
C_TOOL    = "#C586C0"
C_TOOLARG = "#9CDCFE"
C_OK      = "#6A9955"
C_ERR     = "#F44747"
C_DIM     = "#6E7681"
C_LOGO    = "#E8643B"
C_LOGO2   = "#C0391B"
C_BORDER  = "#30363D"
C_TEXT    = "#D4D4D4"
C_ROUTER  = "#FFD700"
C_CRITIC  = "#FF8C00"

console = Console()


# ── Structured JSON logger ────────────────────────────────────────────────────
class _JsonFmt(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        for key in (
            "user_input", "assistant_response", "tool_name",
            "tool_args", "tool_result", "error_details",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def make_logger(name: str, path: Path) -> logging.Logger:
    """Create (or retrieve) a JSON-lines file logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(_JsonFmt())
        logger.addHandler(handler)
    return logger


# ── Tool runtime ──────────────────────────────────────────────────────────────
# Module-level mutable state. A single ToolRuntime serves both agent variants
# in a given process (only one agent runs per process at a time).
_WORK_DIR: str = "."
_ROOT_DIR: str = str(Path(".").resolve())
_TOOL_RUNTIME: ToolRuntime = ToolRuntime(_WORK_DIR, _ROOT_DIR)


def sync_work_dir(work_dir: str, root_dir: Optional[str] = None) -> None:
    """Sync the shared tool runtime to a new working directory."""
    global _WORK_DIR, _ROOT_DIR
    _WORK_DIR = str(Path(work_dir).resolve())
    _ROOT_DIR = str(Path(root_dir).resolve()) if root_dir else _WORK_DIR
    _TOOL_RUNTIME.set_workspace(_WORK_DIR, _ROOT_DIR)


def get_work_dir() -> str:
    return _WORK_DIR


def get_root_dir() -> str:
    return _ROOT_DIR


def resolve_path(path: str) -> Path:
    """Resolve a path; raises ValueError if it escapes root."""
    _TOOL_RUNTIME.set_workspace(_WORK_DIR, _ROOT_DIR)
    return _TOOL_RUNTIME.resolve(path)


def _wrap_tool(method_name: str):
    """Wrap a ToolRuntime method so it auto-syncs work_dir before/after calls."""
    @wraps(getattr(_TOOL_RUNTIME, method_name))
    def _wrapped(*args, **kwargs):
        global _WORK_DIR
        _TOOL_RUNTIME.set_workspace(_WORK_DIR, _ROOT_DIR)
        result = getattr(_TOOL_RUNTIME, method_name)(*args, **kwargs)
        # Sync back: change_directory may have updated work_dir on the runtime
        _WORK_DIR = _TOOL_RUNTIME.work_dir
        return result
    return _wrapped


run_command      = _wrap_tool("run_command")
read_file        = _wrap_tool("read_file")
write_file       = _wrap_tool("write_file")
edit_file        = _wrap_tool("edit_file")
find_files       = _wrap_tool("find_files")
grep             = _wrap_tool("grep")
list_directory   = _wrap_tool("list_directory")
delete_file      = _wrap_tool("delete_file")
create_directory = _wrap_tool("create_directory")
move_file        = _wrap_tool("move_file")
search_web       = _wrap_tool("search_web")
fetch_url        = _wrap_tool("fetch_url")
change_directory = _wrap_tool("change_directory")

BASE_TOOL_MAP: dict = {
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

BASE_TOOLS: list = build_tool_definitions(include_web=True)


# ── UI helpers ────────────────────────────────────────────────────────────────
_TOOL_LABELS: dict = {
    "edit_file":        ("Update",    "path"),
    "write_file":       ("Write",     "path"),
    "read_file":        ("Read",      "path"),
    "run_command":      ("Bash",      "command"),
    "find_files":       ("Glob",      "pattern"),
    "grep":             ("Grep",      "pattern"),
    "list_directory":   ("LS",        "path"),
    "delete_file":      ("Delete",    "path"),
    "create_directory": ("Mkdir",     "path"),
    "move_file":        ("Move",      "src"),
    "search_web":       ("Web",       "query"),
    "fetch_url":        ("Fetch",     "url"),
    "change_directory": ("CD",        "path"),
    "save_memory":      ("Memory+",   "key"),
    "memory_search":    ("MemSearch", "query"),
    "delete_memory":    ("Memory-",   "key"),
}


def _rel(path_str: str) -> str:
    """Return path relative to current work_dir when possible."""
    try:
        return str(Path(path_str).relative_to(Path(_WORK_DIR)))
    except ValueError:
        return path_str


def _render_inline(text: str) -> Text:
    """Apply inline Rich markup: ``code`` → bold cyan, ``**text**`` → bold white."""
    result = Text()
    i = 0
    while i < len(text):
        if text[i] == "`":
            j = text.find("`", i + 1)
            if j != -1:
                result.append(text[i + 1 : j], style=f"bold {C_TOOLARG}")
                i = j + 1
                continue
        if text[i : i + 2] == "**":
            j = text.find("**", i + 2)
            if j != -1:
                result.append(text[i + 2 : j], style="bold white")
                i = j + 2
                continue
        result.append(text[i], style=C_TEXT)
        i += 1
    return result


def print_tool_call(name: str, args: dict) -> None:
    t = Text()
    if name in _TOOL_LABELS:
        label, key = _TOOL_LABELS[name]
        val = _rel(str(args.get(key, "")))[:90]
        t.append("● ", style=f"bold {C_BULLET}")
        t.append(label, style=f"bold {C_TOOL}")
        t.append("(", style=C_DIM)
        t.append(val, style=C_TOOLARG)
        t.append(")", style=C_DIM)
    else:
        t.append("● ", style=f"bold {C_BULLET}")
        t.append(name, style=f"bold {C_TOOL}")
        t.append(
            "(" + ", ".join(f"{k}={repr(v)[:60]}" for k, v in args.items()) + ")",
            style=C_TOOLARG,
        )
    console.print(t)


def _print_diff(result: dict) -> None:
    la = result.get("added", 0)
    lr = result.get("removed", 0)
    s = Text()
    s.append("  └ ", style=C_DIM)
    parts = []
    if la:
        parts.append(Text(f"+{la}", style=C_OK))
    if lr:
        parts.append(Text(f"-{lr}", style=C_ERR))
    for i, p in enumerate(parts):
        if i:
            s.append("  ", style=C_DIM)
        s.append_text(p)
    console.print(s)
    for ln, kind, content in result.get("diff", []):
        row = Text(overflow="fold")
        if kind == "removed":
            row.append(f"{ln:4} ", style=C_DIM)
            row.append("- ", style=f"bold {C_ERR}")
            row.append(f"  {content}", style=f"{C_ERR} on #2d0000")
        elif kind == "added":
            row.append(f"{ln:4} ", style=C_DIM)
            row.append("+ ", style=f"bold {C_OK}")
            row.append(f"  {content}", style=f"{C_OK} on #002d00")
        else:
            row.append(f"{ln:4}   ", style=C_DIM)
            row.append(f"  {content}", style=C_DIM)
        console.print(row)


def print_tool_result(result: dict) -> None:
    t = Text()
    if "error" in result:
        t.append("  ✗ ", style=C_ERR)
        t.append(result["error"], style=C_ERR)
    elif "diff" in result:
        _print_diff(result)
        if result.get("warning"):
            console.print(f"[{C_DIM}]  ⚠ {result['warning']}[/]")
        return
    elif "stdout" in result:
        out = result.get("stdout", "")
        err = result.get("stderr", "")
        rc  = result.get("returncode", 0)
        t.append("  ✓ ", style=C_OK)
        if out:
            max_out = 8_000 if rc != 0 else 1_200
            t.append(out[:max_out] + ("…" if len(out) > max_out else ""), style=C_TEXT)
        if err:
            t.append(f"\n    stderr: {err[:2_000]}", style=C_ERR)
        if rc != 0:
            t.append(f"  [rc={rc}]", style=C_ERR)
    elif "content" in result and "url" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result.get('chars', 0)} chars · {result['url'][:60]}", style=C_DIM)
    elif "content" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{result['lines']} líneas · {result['path']}", style=C_DIM)
    elif "query" in result and "results" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{len(result['results'])} resultados: {result['query']}\n", style=C_DIM)
        for r in result["results"][:3]:
            t.append(f"    · {r.get('title', '')[:70]}\n", style=C_TEXT)
    elif "files" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{len(result['files'])} archivos", style=C_DIM)
    elif "results" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"{len(result['results'])} coincidencias", style=C_DIM)
    elif "cwd" in result:
        t.append("  ✓ ", style=C_OK)
        t.append(f"dir → {result['cwd']}", style=C_TOOLARG)
    elif "success" in result:
        t.append("  ✓ ", style=C_OK)
        detail = result.get("to") or result.get("path") or result.get("deleted") or "ok"
        t.append(str(detail), style=C_DIM)
    else:
        t.append("  ✓ ok", style=C_DIM)
    console.print(t)
