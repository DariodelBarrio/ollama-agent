"""Helpers para construir prompts del agente y cargar contexto del proyecto.

El objetivo de este módulo es desacoplar el renderizado del prompt de los
agentes concretos. Así ambos backends comparten la misma lógica de plantillas
y el mismo fallback cuando falta Jinja2 o cuando una plantilla falla.
"""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Callable, Optional

try:
    from jinja2 import Environment, FileSystemLoader, Undefined
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False


REPO_ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = REPO_ROOT / "prompts"
DEFAULT_CONTEXT_FILES = ("CLAUDE.md", "README.md", ".cursorrules")


def load_project_context(work_dir: str, max_chars: int = 16_000) -> str:
    """Carga el primer archivo de contexto conocido que exista en el proyecto.

    Se priorizan archivos estilo instrucciones globales (`CLAUDE.md`,
    `README.md`, `.cursorrules`) para inyectar solo una vista resumida del
    proyecto en el prompt de sistema.
    """
    base = Path(work_dir)
    for name in DEFAULT_CONTEXT_FILES:
        candidate = base / name
        if not candidate.exists():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            continue
        return f"Contexto del proyecto ({name}):\n{content}\n"
    return ""


def _jinja_env(loader=None) -> "Environment":
    """Create a Jinja2 Environment that silently ignores undefined variables."""
    return Environment(
        loader=loader,
        undefined=Undefined,     # silently renders undefined vars as ""
        keep_trailing_newline=True,
    )


def render_prompt_template(template_name: str, **values: str) -> str:
    """Render a template from the prompts/ directory.

    Templates use Jinja2 syntax: ``{{ variable }}``, ``{% if cond %}...{% endif %}``.
    Falls back to ``string.Template`` (``$variable``) when Jinja2 is unavailable.
    """
    normalized = {key: "" if value is None else str(value) for key, value in values.items()}

    if JINJA2_AVAILABLE:
        env = _jinja_env(FileSystemLoader(str(PROMPTS_DIR)))
        return env.get_template(template_name).render(**normalized)

    # Fallback: string.Template
    template_path = PROMPTS_DIR / template_name
    raw_template = template_path.read_text(encoding="utf-8")
    return Template(raw_template).safe_substitute(**normalized)


def build_system_prompt(
    *,
    template_name: str,
    work_dir: str,
    logger,
    fallback_builder: Callable[[], str],
    system_prompt_path: Optional[Path] = None,
    **values: str,
) -> str:
    """Build a system prompt from a template or an override file.

    Override files support both syntaxes:
    - Jinja2 (``{{ variable }}``) — detected when ``{{`` is present
    - Legacy ``string.Template`` (``$variable``) — used as fallback
    """
    # Include work_dir explicitly so templates can reference {{ work_dir }}
    normalized = {
        "work_dir": work_dir,
        **{key: "" if value is None else str(value) for key, value in values.items()},
    }
    try:
        if system_prompt_path:
            # Los overrides permiten personalizar el prompt sin editar el repo.
            raw_override = system_prompt_path.read_text(encoding="utf-8")
            if JINJA2_AVAILABLE and any(token in raw_override for token in ("{{", "{%", "{#")):
                env = _jinja_env()
                return env.from_string(raw_override).render(**normalized)
            # Legacy: $variable syntax
            return Template(raw_override).safe_substitute(**normalized)
        return render_prompt_template(template_name, **normalized)
    except Exception as exc:
        logger.error(
            "No se pudo renderizar el prompt",
            extra={"error_details": str(exc)},
        )
        return fallback_builder()
