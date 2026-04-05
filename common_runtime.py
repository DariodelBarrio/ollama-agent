"""Primitivas compartidas de seguridad y resolución de comandos/rutas.

Este módulo contiene la política mínima que aplican ambos agentes antes de
delegar en `subprocess` o tocar el sistema de archivos.
"""

import os
import platform
import re
import shutil
from pathlib import Path


BLOCKED_COMMAND_PATTERNS = [
    # Borrado de archivos/directorios — \b captura también "rm " y 'rm ' (no solo tras espacio)
    r'\b(rm|rmdir|del|erase)\s',
    r'\brd\s',
    r'remove-item\b',
    r'format\b',
    r'reg\s+(delete|add)\b',
    r'shutdown\b',
    r'reboot\b',
    r'poweroff\b',
    r'mkfs\b',
    r'diskpart\b',
    r'\bdd\b.*\bof=/dev/',
    r'chmod\s+777\b',
    r'\bcmd\s*/c\s+.*\b(del|erase|rd|rmdir|format|shutdown)\b',
    r'\bpowershell(\.exe)?\b.*\b(remove-item|del|rm|rmdir)\b',
    r'\bpython(?:3)?\b.*\b(shutil\.rmtree|os\.(remove|unlink|rmdir)|pathlib\.path\([^)]*\)\.(unlink|rmdir))\b',
    r'\bnode\b.*\b(rmsync|rmdirsync|unlinksync)\b',
    # Descarga + ejecución inline vía pipe
    r'curl\b.*\|',
    r'wget\b.*\|',
    r'invoke-webrequest\b.*\|',
    # git clean destruye archivos no rastreados del workspace
    r'\bgit\s+clean\b',
    r'\bgit\s+reset\s+--hard\b',
    r'\bgit\s+checkout\s+--\b',
]

READ_ONLY_BLOCKED_COMMAND_PATTERNS = [
    r'(^|[\s;&|])mkdir\b',
    r'(^|[\s;&|])touch\b',
    r'(^|[\s;&|])(mv|move|ren|rename)\b',
    r'(^|[\s;&|])(cp|copy|xcopy|robocopy)\b',
    r'(^|[\s;&|])tee\b',
    r'(^|[\s;&|])sed\b[^\n]*\s-i\b',
    r'(^|[\s;&|])git\s+(add|commit|merge|rebase|cherry-pick|am|apply|stash|restore)\b',
    r'(^|[\s;&|])git\s+checkout\b',
    r'(^|[\s;&|])python(?:3)?\b[^\n]*\b(open|pathlib\.path)\b',
    r'(^|[\s;&|])node\b[^\n]*\b(writefile|appendfile|mkdir|rename|copyfile)\b',
]

_LEADING_PLACEHOLDER_RE = re.compile(
    r"^\s*\{\{\s*([a-zA-Z_]+)\s*\}\}(?P<rest>(?:[\\/].*)?)\s*$"
)
_UNRESOLVED_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}|\{\{|\}\}|\{|\}")
_PATH_ALIAS_TARGETS = {
    "workspace": "",
    "desktop": "desktop",
    "documents": "documents",
    "escritorio": "desktop",
    "documentos": "documents",
}


def special_workspace_paths(root_dir: str) -> dict[str, Path]:
    """Return deterministic workspace-local targets for supported aliases."""
    root = Path(root_dir).resolve()
    return {
        "workspace": root,
        "desktop": root / "desktop",
        "documents": root / "documents",
        "escritorio": root / "desktop",
        "documentos": root / "documents",
    }


def normalize_workspace_path(path: str, root_dir: str) -> str:
    """Resolve supported placeholders/aliases to safe workspace-local paths.

    Supported forms:
    - ``{{ desktop }}``, ``{{ documents }}``, ``{{ workspace }}``
    - ``desktop/...``, ``documents/...``, ``escritorio/...``, ``documentos/...``

    Unknown or malformed placeholders are rejected explicitly instead of being
    treated as literal path segments.
    """
    raw = str(path).strip()
    if not raw:
        return raw

    mapped = special_workspace_paths(root_dir)

    placeholder_match = _LEADING_PLACEHOLDER_RE.match(raw)
    if placeholder_match:
        alias = placeholder_match.group(1).strip().lower()
        if alias not in mapped:
            raise ValueError(
                f"Placeholder de ruta no soportado: '{{{{ {alias} }}}}'. "
                "Usa workspace, desktop/documents o una ruta real dentro del workspace."
            )
        rest = (placeholder_match.group("rest") or "").lstrip("\\/")
        target = mapped[alias]
        return str(target / rest) if rest else str(target)

    if "{{" in raw or "}}" in raw:
        raise ValueError(
            f"Ruta con placeholder sin resolver: {path}. "
            "Usa workspace, desktop/documents o una ruta real dentro del workspace."
        )

    if any(ch in raw for ch in "{}"):
        raise ValueError(
            f"Ruta con sintaxis de plantilla inválida: {path}. "
            "No se permiten llaves sin resolver en rutas de herramientas."
        )

    candidate = Path(raw)
    if candidate.is_absolute():
        return raw

    parts = candidate.parts
    if not parts:
        return raw

    alias = parts[0].lower()
    if alias in mapped:
        target = mapped[alias]
        if len(parts) == 1:
            return str(target)
        return str(target.joinpath(*parts[1:]))

    return raw


def is_within_root(path: Path, root_dir: str) -> bool:
    """Comprueba que una ruta resuelta no escape del workspace permitido."""
    try:
        path.resolve().relative_to(Path(root_dir).resolve())
        return True
    except ValueError:
        return False


def resolve_in_root(path: str, work_dir: str, root_dir: str) -> Path:
    """Resuelve una ruta absoluta/relativa y la valida contra `root_dir`."""
    normalized = normalize_workspace_path(path, root_dir)
    p = Path(normalized)
    resolved = p.resolve() if p.is_absolute() else (Path(work_dir) / p).resolve()
    if not is_within_root(resolved, root_dir):
        raise ValueError(f"Ruta fuera del directorio permitido: {path}")
    return resolved


def is_safe_command(command: str) -> tuple[bool, str]:
    """Bloquea comandos claramente destructivos antes de ejecutarlos."""
    lowered = command.lower()
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, lowered):
            return False, f"Comando bloqueado por seguridad: coincide con '{pattern}'"
    return True, ""


def is_read_only_command(command: str) -> tuple[bool, str]:
    """Reject shell commands that are likely to mutate the workspace."""
    lowered = command.lower()
    if re.search(r'(^|[^<])>>?', lowered):
        return False, "Modo solo lectura: no se permiten redirecciones de escritura en shell."
    for pattern in READ_ONLY_BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, lowered):
            return False, f"Modo solo lectura: comando bloqueado ({pattern})."
    return True, ""


def build_shell_command(shell: str, command: str, os_name: str | None = None) -> tuple[list[str], str]:
    """Normaliza el shell solicitado a la forma concreta que usa subprocess."""
    active_os = os_name or platform.system()
    effective_shell = shell if shell != "auto" else ("powershell" if active_os == "Windows" else "bash")
    if active_os == "Windows":
        comspec = os.getenv("COMSPEC") or shutil.which("cmd") or r"C:\Windows\System32\cmd.exe"
        powershell = (
            shutil.which("powershell")
            or str(Path(os.getenv("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        )
    else:
        comspec = "cmd"
        powershell = "powershell"
    if effective_shell == "powershell":
        return [powershell, "-NoProfile", "-Command", command], effective_shell
    if effective_shell == "bash":
        return ["bash", "-c", command], effective_shell
    if effective_shell == "sh":
        return ["sh", "-c", command], effective_shell
    return [comspec, "/c", command], effective_shell
