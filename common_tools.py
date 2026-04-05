"""Runtime de herramientas locales/web consumidas por los agentes.

`ToolRuntime` concentra las operaciones con archivos, shell y web, y devuelve
siempre diccionarios serializables para que el modelo pueda razonar sobre
resultados y errores de forma uniforme.
"""

from __future__ import annotations

import difflib
import platform
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Optional

from common_runtime import build_shell_command, is_read_only_command, is_safe_command, resolve_in_root

try:
    import requests
    from bs4 import BeautifulSoup
    from duckduckgo_search import DDGS

    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False


# ── Output sanitization ───────────────────────────────────────────────────────
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[mGKHFJABCDEF]|\x1b\][^\x07]*\x07")


def _sanitize_output(text: str, max_chars: int = 20_000) -> str:
    """Strip ANSI escape sequences and truncate long output with head+tail context.

    Prevents the agent from processing garbage escape codes or running out of
    context window on huge outputs (e.g. test suites, build logs).
    """
    if not text:
        return text
    text = _ANSI_ESCAPE_RE.sub("", text)
    if len(text) <= max_chars:
        return text
    # Smart truncation: keep 2/3 head + 1/3 tail so both start and end are visible
    head = max_chars * 2 // 3
    tail = max_chars - head
    skipped = len(text) - max_chars
    return (
        text[:head]
        + f"\n\n[... {skipped:,} caracteres omitidos ...]\n\n"
        + text[-tail:]
    )


class ToolRuntime:
    """Contenedor con estado mínimo del workspace activo.

    El runtime guarda `work_dir` y `root_dir` para que los agentes puedan
    cambiar de directorio sin perder el perímetro de seguridad.
    """
    def __init__(
        self,
        work_dir: str = ".",
        root_dir: Optional[str] = None,
        os_name: Optional[str] = None,
        read_only: bool = False,
    ):
        self.os_name = os_name or platform.system()
        self.work_dir = str(Path(work_dir).resolve())
        self.root_dir = str(Path(root_dir).resolve()) if root_dir else self.work_dir
        self.read_only = read_only

    def set_workspace(self, work_dir: str, root_dir: Optional[str] = None) -> None:
        """Actualiza el directorio actual y el límite raíz permitido."""
        self.work_dir = str(Path(work_dir).resolve())
        self.root_dir = str(Path(root_dir).resolve()) if root_dir else self.work_dir

    def set_mode(self, read_only: bool = False) -> None:
        self.read_only = read_only

    def _read_only_error(self, action: str) -> dict:
        return {
            "error": (
                f"Modo solo lectura activo: '{action}' estÃ¡ bloqueado. "
                "Solo se permiten lectura, bÃºsqueda, listado y shell de inspecciÃ³n."
            )
        }

    def resolve(self, path: str) -> Path:
        """Resuelve una ruta dentro del workspace validando escapes."""
        return resolve_in_root(path, self.work_dir, self.root_dir)

    def run_command(self, command: str, shell: str = "auto", timeout: int = 60) -> dict:
        """Ejecuta un comando respetando shell, timeout y sanitización."""
        try:
            ok, reason = is_safe_command(command)
            if not ok:
                return {"error": reason}
            if self.read_only:
                ok, reason = is_read_only_command(command)
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
                "stdout": _sanitize_output(result.stdout.strip(), 20_000),
                "stderr": _sanitize_output(result.stderr.strip(), 5_000),
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout: el comando tardo mas de {timeout}s"}
        except FileNotFoundError as exc:
            return {"error": f"Shell no encontrado ({effective_shell}): {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    def read_file(self, path: str) -> dict:
        """Lee un archivo devolviendo contenido numerado para referencias estables."""
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

    # Límite simétrico con read_file (2 MB lectura) — previene escrituras accidentales enormes
    _MAX_WRITE_BYTES = 10 * 1024 * 1024  # 10 MB

    def write_file(self, path: str, content: str) -> dict:
        """Escribe un archivo completo creando directorios intermedios si faltan."""
        try:
            if self.read_only:
                return self._read_only_error("write_file")
            encoded = content.encode("utf-8")
            if len(encoded) > self._MAX_WRITE_BYTES:
                return {
                    "error": (
                        f"Contenido demasiado grande ({len(encoded):,} bytes). "
                        f"Límite: {self._MAX_WRITE_BYTES // 1_000_000} MB."
                    )
                }
            resolved = self.resolve(path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(resolved), "lines": len(content.splitlines())}
        except Exception as exc:
            return {"error": str(exc)}

    # ── edit_file ─────────────────────────────────────────────────────────────

    @staticmethod
    def _rstrip_lines(text: str) -> str:
        """Strip trailing whitespace from every line (preserves line count)."""
        return "\n".join(line.rstrip() for line in text.splitlines())

    @staticmethod
    def _best_fuzzy_match(content: str, old_text: str) -> tuple[float, int]:
        """Return (best_ratio, best_line_start) for the closest contiguous block."""
        old_lines = old_text.splitlines()
        content_lines = content.splitlines()
        n = len(old_lines)
        best_ratio = 0.0
        best_start = 0
        for i in range(max(1, len(content_lines) - n + 1)):
            window = "\n".join(content_lines[i : i + n])
            ratio = difflib.SequenceMatcher(None, old_text, window, autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i
        return best_ratio, best_start

    def edit_file(
        self,
        path: str,
        old_text: str,
        new_text: str,
        replace_all: bool = False,
        use_regex: bool = False,
    ) -> dict:
        """Edit a file by replacing ``old_text`` with ``new_text``.

        Match strategy (in order):
        1. Exact match.
        2. Trailing-whitespace-normalised match (rstrip each line).
        3. Fail with a diagnostic: shows the most similar block so the LLM can
           copy the exact text.

        Returns a unified-diff summary on success.
        """
        try:
            if self.read_only:
                return self._read_only_error("edit_file")
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"Archivo no encontrado: {path}"}
            content = resolved.read_text(encoding="utf-8", errors="replace")

            # ── regex branch (unchanged) ───────────────────────────────────────
            if use_regex:
                # El branch regex mantiene semántica explícita y no intenta
                # heurísticas adicionales para no introducir reemplazos ambiguos.
                try:
                    pattern = re.compile(old_text, re.MULTILINE)
                except re.error as exc:
                    return {"error": f"Regex invalida: {exc}"}
                if not pattern.search(content):
                    return {"error": "Patron regex no encontrado en el archivo."}
                count = len(pattern.findall(content))
                new_content = (
                    pattern.sub(new_text, content)
                    if replace_all
                    else pattern.sub(new_text, content, count=1)
                )
                applied_fuzzy = False

            # ── literal branch ────────────────────────────────────────────────
            else:
                applied_fuzzy = False

                if old_text in content:
                    # Fast path: exact match
                    target_content = content
                    target_old = old_text
                else:
                    # Try whitespace-normalised match (rstrip each line)
                    norm_content = self._rstrip_lines(content)
                    norm_old = self._rstrip_lines(old_text)

                    if norm_old in norm_content:
                        applied_fuzzy = True
                        target_content = content
                        target_old = old_text.rstrip()
                    else:
                        # Neither exact nor normalised — build a helpful error
                        best_ratio, best_start = self._best_fuzzy_match(content, old_text)
                        hint = ""
                        if best_ratio > 0.5:
                            content_lines = content.splitlines()
                            n = len(old_text.splitlines())
                            snippet = "\n".join(content_lines[best_start : best_start + n])
                            hint = (
                                f"\n\nBloque más parecido (similitud {best_ratio:.0%}, "
                                f"línea ~{best_start + 1}):\n{snippet[:400]}"
                            )
                        return {
                            "error": (
                                "Texto no encontrado (ni exacto ni con normalización de espacios). "
                                "Solución: usa read_file() para obtener el contenido actual y "
                                f"copia old_text exactamente como aparece en el archivo.{hint}"
                            )
                        }

                count = target_content.count(target_old)
                new_content = (
                    target_content.replace(target_old, new_text)
                    if replace_all
                    else target_content.replace(target_old, new_text, 1)
                )

            # ── diff generation ───────────────────────────────────────────────
            old_lines = content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)
            raw_diff = list(difflib.unified_diff(old_lines, new_lines, n=2))

            diff_entries: list[tuple[int, str, str]] = []
            lines_added = 0
            lines_removed = 0
            old_ln = new_ln = 0

            for line in raw_diff:
                if line.startswith("@@"):
                    m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                    if m:
                        old_ln, new_ln = int(m.group(1)), int(m.group(2))
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

            result: dict = {
                "success": True,
                "path": str(resolved),
                "replaced": count if replace_all else 1,
                "added": lines_added,
                "removed": lines_removed,
                "diff": diff_entries[:30],
            }
            if applied_fuzzy:
                result["warning"] = (
                    "Coincidencia por normalización: se eliminaron espacios "
                    "al final de línea en el archivo."
                )
            return result

        except Exception as exc:
            return {"error": str(exc)}

    # ── rest of tools (unchanged) ─────────────────────────────────────────────

    def find_files(self, pattern: str, path: str = ".") -> dict:
        """Busca archivos por glob relativo a un directorio concreto."""
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
        """Busca coincidencias regex acotando tamaño y número de resultados."""
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
        """Lista entradas del directorio con tipo y tamaño básico."""
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
        """Elimina un archivo o directorio dentro del workspace permitido."""
        try:
            if self.read_only:
                return self._read_only_error("delete_file")
            resolved = self.resolve(path)
            if not resolved.exists():
                return {"error": f"No existe: {path}"}
            # Impide borrar el workspace raíz completo de una sola llamada.
            if str(resolved) == self.root_dir:
                return {"error": "No se puede eliminar el directorio raíz del workspace."}
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
            return {"success": True, "deleted": str(resolved)}
        except Exception as exc:
            return {"error": str(exc)}

    def create_directory(self, path: str) -> dict:
        """Crea un directorio y sus padres si no existen."""
        try:
            if self.read_only:
                return self._read_only_error("create_directory")
            resolved = self.resolve(path)
            resolved.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(resolved)}
        except Exception as exc:
            return {"error": str(exc)}

    def move_file(self, src: str, dst: str) -> dict:
        """Mueve o renombra una ruta manteniéndose dentro del workspace."""
        try:
            if self.read_only:
                return self._read_only_error("move_file")
            source = self.resolve(src)
            target = self.resolve(dst)
            if not source.exists():
                return {"error": f"No existe: {src}"}
            if str(source) == self.root_dir:
                return {"error": "No se puede mover ni renombrar el directorio raíz del workspace."}
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            return {"success": True, "from": str(source), "to": str(target)}
        except Exception as exc:
            return {"error": str(exc)}

    def search_web(self, query: str, max_results: int = 5) -> dict:
        """Realiza una búsqueda web simple y devuelve resultados resumidos."""
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
        """Descarga una URL y extrae texto legible para el modelo."""
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
        """Actualiza el `cwd` activo sin permitir salir de `root_dir`."""
        try:
            resolved = self.resolve(path)
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
            "description": "Ejecuta comandos en el shell del SO con filtro básico contra patrones claramente destructivos.",
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
            "description": (
                "Edita texto en un archivo existente. Soporta reemplazo multiple y regex. "
                "Si old_text no se encuentra exactamente, intenta normalización de espacios "
                "y muestra el bloque más similar para ayudar a corregir."
            ),
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
            "description": "Mueve o renombra un archivo o carpeta dentro del workspace; no permite mover la raíz del workspace.",
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


_MUTATING_TOOL_NAMES = {"write_file", "edit_file", "delete_file", "create_directory", "move_file"}


def build_tool_definitions(
    include_web: bool = True,
    extra_tools: Optional[list[dict]] = None,
    read_only: bool = False,
) -> list[dict]:
    """Construye la lista final de tools publicada al modelo.

    Se clona la definición base para evitar que un agente mutile estructuras
    compartidas entre sesiones o entre backends.
    """
    tools = deepcopy(_BASE_TOOL_DEFINITIONS)
    if read_only:
        tools = [
            tool
            for tool in tools
            if tool.get("function", {}).get("name") not in _MUTATING_TOOL_NAMES
        ]
    if include_web and WEB_AVAILABLE:
        tools.extend(deepcopy(_WEB_TOOL_DEFINITIONS))
    if extra_tools:
        tools.extend(deepcopy(extra_tools))
    return tools
