from __future__ import annotations

import difflib
import platform
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Optional

from common_runtime import build_shell_command, is_safe_command, resolve_in_root

try:
    import requests
    from bs4 import BeautifulSoup
    from duckduckgo_search import DDGS

    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False


class ToolRuntime:
    def __init__(self, work_dir: str = ".", root_dir: Optional[str] = None, os_name: Optional[str] = None):
        self.os_name = os_name or platform.system()
        self.work_dir = str(Path(work_dir).resolve())
        self.root_dir = str(Path(root_dir).resolve()) if root_dir else self.work_dir

    def set_workspace(self, work_dir: str, root_dir: Optional[str] = None) -> None:
        self.work_dir = str(Path(work_dir).resolve())
        self.root_dir = str(Path(root_dir).resolve()) if root_dir else self.work_dir

    def resolve(self, path: str) -> Path:
        return resolve_in_root(path, self.work_dir, self.root_dir)

    def run_command(self, command: str, shell: str = "auto", timeout: int = 60) -> dict:
        try:
            ok, reason = is_safe_command(command)
            if not ok:
                return {"error": reason}
            cmd, effective_shell = build_shell_command(shell, command, self.os_name)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.work_dir,
            )
            return {
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout: el comando tardo mas de {timeout}s"}
        except FileNotFoundError as exc:
            return {"error": f"Shell no encontrado ({effective_shell}): {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def read_file(self, path: str) -> dict:
        try:
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"Archivo no encontrado: {path}"}
            if resolved.stat().st_size > 2_000_000:
                return {"error": "Archivo demasiado grande (>2MB)"}
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
            return {
                "content": "\n".join(f"{idx + 1:4}: {line}" for idx, line in enumerate(lines)),
                "path": str(resolved),
                "lines": len(lines),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def write_file(self, path: str, content: str) -> dict:
        try:
            resolved = self.resolve(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(resolved), "lines": len(content.splitlines())}
        except Exception as exc:
            return {"error": str(exc)}

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        use_regex: bool = False,
    ) -> dict:
        try:
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"Archivo no encontrado: {path}"}
            content = resolved.read_text(encoding="utf-8", errors="replace")

            if use_regex:
                try:
                    pattern = re.compile(old_text, re.MULTILINE)
                except re.error as exc:
                    return {"error": f"Regex invalida: {exc}"}
                if not pattern.search(content):
                    return {"error": "Patron regex no encontrado en el archivo."}
                count = len(pattern.findall(content))
                new_content = pattern.sub(new_text, content) if replace_all else pattern.sub(new_text, content, count=1)
            else:
                if old_text not in content:
                    return {"error": "Texto no encontrado. Debe ser exacto (incluyendo espacios e indentacion)."}
                count = content.count(old_text)
                new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)

            old_lines = content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            raw_diff = list(difflib.unified_diff(old_lines, new_lines, n=2))

            diff_entries: list[tuple[int, str, str]] = []
            lines_added = 0
            lines_removed = 0
            old_ln = 0
            new_ln = 0
            for line in raw_diff:
                if line.startswith("@@"):
                    match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                    if match:
                        old_ln, new_ln = int(match.group(1)), int(match.group(2))
                elif line.startswith(("---", "+++")):
                    continue
                elif line.startswith("-"):
                    diff_entries.append((old_ln, "removed", line[1:].rstrip("\n")))
                    old_ln += 1
                    lines_removed += 1
                elif line.startswith("+"):
                    diff_entries.append((new_ln, "added", line[1:].rstrip("\n")))
                    new_ln += 1
                    lines_added += 1
                elif line.startswith(" "):
                    diff_entries.append((old_ln, "context", line[1:].rstrip("\n")))
                    old_ln += 1
                    new_ln += 1

            resolved.write_text(new_content, encoding="utf-8")
            return {
                "success": True,
                "path": str(resolved),
                "replaced": count if replace_all else 1,
                "added": lines_added,
                "removed": lines_removed,
                "diff": diff_entries[:30],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def find_files(self, pattern: str, path: str = ".") -> dict:
        try:
            resolved = self.resolve(path)
            matches = sorted(resolved.glob(pattern))
            return {
                "pattern": pattern,
                "path": str(resolved),
                "files": [str(file.relative_to(resolved)) for file in matches if file.is_file()][:50],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def grep(self, pattern: str, path: str = ".", extension: str = "") -> dict:
        try:
            resolved = self.resolve(path)
            results = []
            glob_pattern = f"**/*{extension}" if extension else "**/*"
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return {"error": f"Regex invalida: {exc}"}
            for file in sorted(resolved.glob(glob_pattern)):
                if not file.is_file() or file.stat().st_size > 1_000_000:
                    continue
                try:
                    for line_number, line in enumerate(file.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                        if regex.search(line):
                            results.append(
                                {
                                    "file": str(file.relative_to(resolved)),
                                    "line": line_number,
                                    "content": line.strip(),
                                }
                            )
                            if len(results) >= 50:
                                break
                except Exception:
                    pass
                if len(results) >= 50:
                    break
            return {"pattern": pattern, "results": results}
        except Exception as exc:
            return {"error": str(exc)}

    def list_directory(self, path: str = ".") -> dict:
        try:
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"No encontrado: {path}"}
            entries = []
            for item in sorted(resolved.iterdir()):
                entries.append(
                    {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": item.stat().st_size if item.is_file() else None,
                    }
                )
            return {"path": str(resolved), "entries": entries}
        except Exception as exc:
            return {"error": str(exc)}

    def delete_file(self, path: str) -> dict:
        try:
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"No existe: {path}"}
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
            return {"success": True, "deleted": str(resolved)}
        except Exception as exc:
            return {"error": str(exc)}

    def create_directory(self, path: str) -> dict:
        try:
            resolved = self.resolve(path)
            resolved.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(resolved)}
        except Exception as exc:
            return {"error": str(exc)}

    def move_file(self, src: str, dst: str) -> dict:
        try:
            source = self.resolve(src)
            target = self.resolve(dst)
            if not source.exists():
                return {"error": f"No existe: {src}"}
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return {"success": True, "from": str(source), "to": str(target)}
        except Exception as exc:
            return {"error": str(exc)}

    def search_web(self, query: str, max_results: int = 5) -> dict:
        if not WEB_AVAILABLE:
            return {"error": "Instala: pip install duckduckgo-search requests beautifulsoup4"}
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return {"results": [], "message": "Sin resultados"}
            return {
                "query": query,
                "results": [
                    {
                        "title": result.get("title", ""),
                        "url": result.get("href", ""),
                        "snippet": result.get("body", ""),
                    }
                    for result in results
                ],
            }
        except Exception as exc:
            return {"error": str(exc)}

    def fetch_url(self, url: str, max_chars: int = 4000) -> dict:
        if not WEB_AVAILABLE:
            return {"error": "Instala: pip install requests beautifulsoup4"}
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = " ".join(soup.get_text(separator=" ").split())
            suffix = "..." if len(text) > max_chars else ""
            return {"url": url, "content": text[:max_chars] + suffix, "chars": len(text)}
        except Exception as exc:
            return {"error": str(exc)}

    def change_directory(self, path: str) -> dict:
        try:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path(self.work_dir) / candidate
            resolved = resolve_in_root(str(candidate.resolve()), self.work_dir, self.root_dir)
            if not resolved.exists():
                return {"error": f"Directorio no encontrado: {path}"}
            if not resolved.is_dir():
                return {"error": f"No es un directorio: {path}"}
            self.work_dir = str(resolved)
            return {"success": True, "cwd": str(resolved)}
        except Exception as exc:
            return {"error": str(exc)}


_BASE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Ejecuta comandos en el shell del SO (auto-detecta powershell/bash).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "shell": {
                        "type": "string",
                        "enum": ["auto", "powershell", "bash", "sh", "cmd"],
                        "description": "Shell a usar. 'auto' selecciona el correcto para el SO.",
                    },
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee un archivo con numeros de linea.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea un archivo nuevo.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edita texto en un archivo existente. Soporta reemplazo multiple y regex.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean", "description": "Si true, reemplaza todas las ocurrencias"},
                    "use_regex": {"type": "boolean", "description": "Si true, old_text es una expresion regular"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Busca archivos por patron glob.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Busca texto/regex en el proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"},
                    "extension": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "Lista carpetas.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Elimina un archivo o carpeta (recursivo para carpetas no vacias).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "Crea una carpeta y subcarpetas si es necesario.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_file",
            "description": "Mueve o renombra un archivo o carpeta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "Ruta origen"},
                    "dst": {"type": "string", "description": "Ruta destino"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_directory",
            "description": "Cambia el directorio de trabajo activo. Usalo cuando el usuario mencione un directorio especifico distinto al actual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta o relativa del nuevo directorio de trabajo"}
                },
                "required": ["path"],
            },
        },
    },
]

_WEB_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Busca en internet con DuckDuckGo para info actual, documentacion, noticias.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Descarga y lee el contenido de una URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}},
                "required": ["url"],
            },
        },
    },
]


def build_tool_definitions(include_web: bool = True, extra_tools: Optional[list[dict]] = None) -> list[dict]:
    tools = deepcopy(_BASE_TOOL_DEFINITIONS)
    if include_web and WEB_AVAILABLE:
        tools.extend(deepcopy(_WEB_TOOL_DEFINITIONS))
    if extra_tools:
        tools.extend(deepcopy(extra_tools))
    return tools
