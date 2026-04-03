"""Helpers compartidos para prompting y filtrado de razonamiento interno."""

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


class HiddenReasoningFilter:
    """Strip hidden reasoning blocks without depending on model cooperation.

    The filter removes `<think>...</think>` and `<thought>...</thought>` blocks
    from streamed text. If the model never emits these tags, the content passes
    through unchanged.
    """

    _START_TAGS = {
        "<think>": "</think>",
        "<thought>": "</thought>",
    }
    _MAX_TAG_LEN = max(len(tag) for pair in (
        list(_START_TAGS.keys()) + list(_START_TAGS.values())
    ) for tag in [pair])

    def __init__(self) -> None:
        self._buffer = ""
        self._hidden_end_tag: str | None = None

    def feed(self, text: str) -> str:
        self._buffer += text
        return self._drain(final=False)

    def finish(self) -> str:
        return self._drain(final=True)

    def _drain(self, final: bool) -> str:
        visible: list[str] = []
        while self._buffer:
            if self._hidden_end_tag:
                end_idx = self._buffer.find(self._hidden_end_tag)
                if end_idx == -1:
                    if final:
                        self._buffer = ""
                        self._hidden_end_tag = None
                    break
                self._buffer = self._buffer[end_idx + len(self._hidden_end_tag):]
                self._hidden_end_tag = None
                continue

            matches = [
                (idx, start_tag, end_tag)
                for start_tag, end_tag in self._START_TAGS.items()
                for idx in [self._buffer.find(start_tag)]
                if idx != -1
            ]
            if not matches:
                if final:
                    visible.append(self._buffer)
                    self._buffer = ""
                else:
                    cut = max(0, len(self._buffer) - self._MAX_TAG_LEN)
                    if cut:
                        visible.append(self._buffer[:cut])
                        self._buffer = self._buffer[cut:]
                break

            start_idx, start_tag, end_tag = min(matches, key=lambda item: item[0])
            if start_idx:
                visible.append(self._buffer[:start_idx])
            self._buffer = self._buffer[start_idx + len(start_tag):]
            self._hidden_end_tag = end_tag
        return "".join(visible)


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


def build_mode_section(mode: str, summary: str) -> str:
    """Return a short mode section for the local agent prompt."""
    if not mode or not summary:
        return ""
    return f"Modo actual: {mode.upper()}\nPrioridad: {summary}\n"


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
