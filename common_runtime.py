"""Primitivas compartidas de seguridad y resolución de comandos/rutas.

Este módulo contiene la política mínima que aplican ambos agentes antes de
delegar en `subprocess` o tocar el sistema de archivos.
"""

import platform
import re
from pathlib import Path


BLOCKED_COMMAND_PATTERNS = [
    r'(^|\s)(rm|rmdir|del|erase)\s',
    r'(^|\s)rd\s',
    r'remove-item\b',
    r'format\b',
    r'reg\s+(delete|add)\b',
    r'shutdown\b',
    r'reboot\b',
    r'poweroff\b',
    r'mkfs\b',
    r'diskpart\b',
    r'chmod\s+777\b',
    r'\bcmd\s*/c\s+.*\b(del|erase|rd|rmdir|format|shutdown)\b',
    r'\bpowershell(\.exe)?\b.*\b(remove-item|del|rm|rmdir)\b',
    r'curl\b.*\|',
    r'invoke-webrequest\b.*\|',
]


def is_within_root(path: Path, root_dir: str) -> bool:
    """Comprueba que una ruta resuelta no escape del workspace permitido."""
    try:
        path.resolve().relative_to(Path(root_dir).resolve())
        return True
    except ValueError:
        return False


def resolve_in_root(path: str, work_dir: str, root_dir: str) -> Path:
    """Resuelve una ruta absoluta/relativa y la valida contra `root_dir`."""
    p = Path(path)
    resolved = p.resolve() if p.is_absolute() else (Path(work_dir) / p).resolve()
    if not is_within_root(resolved, root_dir):
        raise ValueError(f"Ruta fuera del directorio permitido: {path}")
    return resolved


def is_safe_command(command: str) -> tuple[bool, str]:
    """Bloquea comandos claramente destructivos antes de ejecutarlos."""
    lowered = command.lower()
    for pattern in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, lowered):
            return False, "Comando bloqueado por seguridad"
    return True, ""


def build_shell_command(shell: str, command: str, os_name: str | None = None) -> tuple[list[str], str]:
    """Normaliza el shell solicitado a la forma concreta que usa subprocess."""
    active_os = os_name or platform.system()
    effective_shell = shell if shell != "auto" else ("powershell" if active_os == "Windows" else "bash")
    if effective_shell == "powershell":
        return ["powershell", "-NoProfile", "-Command", command], effective_shell
    if effective_shell == "bash":
        return ["bash", "-c", command], effective_shell
    if effective_shell == "sh":
        return ["sh", "-c", command], effective_shell
    return ["cmd", "/c", command], effective_shell
