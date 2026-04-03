"""
Agente de programacion local con Ollama - UI estilo Claude Code
Uso: python src/agent.py [--model qwen3:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import logging
import sys
import re
import argparse
import time
import inspect
from pathlib import Path
from typing import Optional

# ── Shared base (colors, console, logger, tools, UI helpers) ──────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from base_agent import (
    # colors
    C_PROMPT, C_BULLET, C_TOOL, C_TOOLARG, C_OK, C_ERR, C_DIM,
    C_LOGO, C_LOGO2, C_BORDER, C_TEXT,
    # rich
    console, escape,
    # logger
    _JsonFmt, make_logger as _make_logger,
    # tool runtime
    sync_work_dir, get_work_dir,
    run_command, read_file, write_file, edit_file, find_files, grep,
    list_directory, delete_file, create_directory, move_file,
    search_web, fetch_url, change_directory,
    BASE_TOOL_MAP as TOOL_MAP,
    BASE_TOOLS as TOOLS,
    # UI
    _render_inline, _TOOL_LABELS, _rel,
    print_tool_call, print_tool_result,
)

from agent_prompting import build_system_prompt as render_shared_prompt, load_project_context
from common_tool_schemas import PYDANTIC_AVAILABLE, TOOL_SCHEMA_MAP, ValidationError

try:
    from openai import OpenAI
except ImportError:
    print("Instala openai: pip install openai")
    sys.exit(1)

try:
    from rich.live import Live
    from rich.spinner import Spinner
    from rich.text import Text
    from rich.padding import Padding
    from rich.columns import Columns
    from rich.rule import Rule
    import threading
except ImportError:
    print("Instala rich: pip install rich")
    sys.exit(1)

from common_tools import WEB_AVAILABLE


# ── UI ────────────────────────────────────────────────────────────────────────
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


def get_input(color: str = C_PROMPT) -> str:
    console.print()
    try:
        console.print(f"[{color}]>[/] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        return "salir"


# ── Prompts ───────────────────────────────────────────────────────────────────
def build_system_prompt(work_dir: str, project_context: str,
                        mode: str = "", mode_snippet: str = "") -> str:
    desktop = str(Path.home() / "Desktop")
    mode_section = ""
    if mode and mode_snippet:
        mode_section = (
            "\n═══════════════════════════════════════════════════════\n"
            f"MODO ACTUAL: {mode.upper()}\n"
            "═══════════════════════════════════════════════════════\n"
            f"{mode_snippet}\n"
        )
    return render_shared_prompt(
        template_name="local_system_prompt.txt",
        work_dir=work_dir,
        logger=logging.getLogger("agent.prompt.local"),
        fallback_builder=lambda: (
            f"Eres un agente autónomo de programación. Directorio de trabajo: {work_dir}\n"
            "Responde en español y usa herramientas para completar tareas.\n"
        ),
        desktop=desktop,
        project_context=project_context,
        mode_section=mode_section,
    )


# ── Agent class ───────────────────────────────────────────────────────────────
class Agent:
    """Agente local sobre backend OpenAI-compatible (p.ej. Ollama).

    Mantiene el historial de mensajes, publica tools al modelo y ejecuta el
    bucle tool-call -> resultado -> siguiente respuesta hasta cerrar la tarea.
    """
    MODE_CONFIGS = {
        "code": {
            "temperature": 0.05,
            "color": "bold blue",
            "spinner_color": "blue",
            "system_prompt_snippet": (
                "Eres un ingeniero de software experto. Tu objetivo principal es escribir, depurar y refactorizar código. "
                "Prioriza la precisión, la eficiencia y las mejores prácticas de ingeniería. "
                "Cuando escribas código, piensa en tests y en la robustez. "
                "Usa las herramientas de archivo y shell de forma agresiva para interactuar con el sistema de archivos y ejecutar comandos."
            ),
        },
        "architect": {
            "temperature": 0.7,
            "color": "bold magenta",
            "spinner_color": "magenta",
            "system_prompt_snippet": (
                "Eres un arquitecto de software experimentado. Tu objetivo principal es diseñar sistemas, proponer estructuras "
                "y evaluar soluciones de alto nivel. Prioriza la escalabilidad, la mantenibilidad y la visión a largo plazo. "
                "Usa las herramientas de búsqueda y análisis para investigar patrones de diseño y tecnologías. "
                "Evita interactuar directamente con el código a menos que sea para un análisis estructural."
            ),
        },
        "research": {
            "temperature": 0.3,
            "color": "bold green",
            "spinner_color": "green",
            "system_prompt_snippet": (
                "Eres un investigador experto. Tu objetivo principal es recopilar información, analizar datos y sintetizar conocimientos. "
                "Prioriza la exhaustividad y la verificación de fuentes. "
                "Usa las herramientas de búsqueda web y lectura de archivos para explorar y comprender nuevos temas. "
                "Resume la información de manera concisa y objetiva."
            ),
        },
    }

    def __init__(self, model: str, work_dir: str, tag: str,
                 num_ctx: int, temperature: float,
                 api_base: str = "http://localhost:11434/v1",
                 system_prompt_path: Optional[str] = None):
        self.model        = model
        self.work_dir     = str(Path(work_dir).resolve())
        self.tag          = tag
        self.num_ctx      = num_ctx
        self.temperature  = temperature
        self.api_base     = api_base
        self.current_mode = "code"
        self.client       = OpenAI(base_url=api_base, api_key="sk-no-key-required")
        self.messages: list = []
        self.system_prompt_path = Path(system_prompt_path).resolve() if system_prompt_path else None

        # Sync shared tool runtime to this agent's work directory
        sync_work_dir(self.work_dir)

        log_path = Path(self.work_dir) / "agent_session.jsonl"
        self.logger = _make_logger(f"agent.{id(self)}", log_path)

    def _build_options(self) -> dict:
        """Devuelve parámetros de generación ligados al modo activo."""
        return {
            "temperature": self.MODE_CONFIGS[self.current_mode]["temperature"],
            "top_p":       0.85,
            "top_k":       20,
        }

    def _trim_history(self, max_pairs: int = 20) -> list:
        """Recorta el historial manteniendo el system prompt intacto.

        Cada iteración puede añadir mensajes `assistant` y `tool`, así que el
        recorte se hace en bloques de conversación en lugar de por mensaje suelto.
        """
        system = [m for m in self.messages if m["role"] == "system"]
        rest   = [m for m in self.messages if m["role"] != "system"]
        return system + rest[-(max_pairs * 4):]

    def _stream_response(self, messages: list, tools: list):
        """Stream LLM response, parse <think>/<thought> blocks, return (content, tool_calls)."""
        collected: list[str] = []
        tc_accum:  dict      = {}
        opts = self._build_options()
        first_output = [True]
        t_start = time.monotonic()

        def _drain(stream_iter):
            # El stream puede mezclar texto visible, bloques de pensamiento y
            # tool calls parciales. Este parser recompone esas tres señales.
            state = None
            thought_buf: list[str] = []
            buf = ""
            for chunk in stream_iter:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "args": []}
                        if tc_delta.id:
                            tc_accum[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tc_accum[idx]["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                tc_accum[idx]["args"].append(tc_delta.function.arguments)
                content = delta.content or ""
                if not content:
                    continue
                if first_output[0]:
                    live.stop()
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    first_output[0] = False
                buf += content
                while True:
                    if state is None:
                        ti  = buf.find("<think>")
                        thi = buf.find("<thought>")
                        first_tag = None
                        first_pos = len(buf)
                        if ti  != -1 and ti  < first_pos: first_pos, first_tag = ti,  "think"
                        if thi != -1 and thi < first_pos: first_pos, first_tag = thi, "thought"
                        if first_tag is None:
                            cut = max(0, len(buf) - 9)
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
                            cut = max(0, len(buf) - 10)
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
                    else:  # think
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

        spinner_color = self.MODE_CONFIGS[self.current_mode]["spinner_color"]
        with Live(Spinner("dots", text="Pensando... 0s", style=spinner_color),
                  console=console, transient=True, refresh_per_second=4) as live:
            def _tick():
                # El spinner vive en un thread aparte para no bloquear el stream.
                while first_output[0]:
                    elapsed = time.monotonic() - t_start
                    live.update(Spinner("dots", text=f"Pensando... {elapsed:.0f}s", style=spinner_color))
                    time.sleep(0.25)
            threading.Thread(target=_tick, daemon=True).start()

            _ollama_extra = {"options": {
                "num_ctx":        self.num_ctx,
                "num_gpu":        99,
                "top_k":          opts["top_k"],
                "repeat_penalty": 1.05,
                "num_predict":    -1,
            }}
            try:
                # Se usa la API chat.completions porque varios servidores locales
                # compatibles con OpenAI todavía exponen esta superficie.
                _drain(self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools or None,
                    temperature=opts["temperature"],
                    top_p=opts["top_p"],
                    stream=True,
                    extra_body=_ollama_extra,
                ))
            except Exception as e:
                if first_output[0]:
                    live.stop()
                    first_output[0] = False
                if "tool" in str(e).lower():
                    console.print(f"\n[{C_BULLET}]●[/] ", end="")
                    _drain(self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=opts["temperature"],
                        top_p=opts["top_p"],
                        stream=True,
                        extra_body=_ollama_extra,
                    ))
                else:
                    console.print(f"\n[{C_ERR}]Error: {e}[/]")
                    self.logger.error("Error en streaming LLM",
                                      extra={"error_details": str(e)}, exc_info=True)

        elapsed_total = time.monotonic() - t_start
        tool_calls = []
        for idx in sorted(tc_accum):
            entry = tc_accum[idx]
            args_str = "".join(entry["args"])
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": entry["id"] or entry["name"],
                                "name": entry["name"], "arguments": args})

        if not tool_calls:
            console.print()
        console.print(f"[{C_DIM}]✳ Brewed for {elapsed_total:.0f}s[/]")
        return "".join(collected), tool_calls

    def _validate_tool_args(self, fn_name: str, args: dict) -> dict:
        """Validate args with Pydantic when available; falls back to inspect.signature."""
        if PYDANTIC_AVAILABLE:
            model_cls = TOOL_SCHEMA_MAP.get(fn_name)
            if model_cls:
                try:
                    validated = model_cls(**args)
                    return validated.model_dump()
                except ValidationError as e:
                    msgs = "; ".join(
                        f"{err['loc'][0]}: {err['msg']}" for err in e.errors()
                    )
                    return {
                        "error": (
                            f"[VALIDATION] Argumentos inválidos para '{fn_name}': {msgs}. "
                            f"Corrige los parámetros e inténtalo de nuevo."
                        )
                    }
        fn = TOOL_MAP.get(fn_name)
        if fn:
            try:
                inspect.signature(fn).bind(**args)
            except TypeError as e:
                return {
                    "error": (
                        f"[VALIDATION] Firma incorrecta para '{fn_name}': {e}. "
                        f"Revisa los parámetros requeridos."
                    )
                }
        return args

    def _invoke_tool(self, fn_name: str, fn_args: dict) -> dict:
        """Ejecuta una tool capturando excepciones en formato uniforme."""
        fn = TOOL_MAP[fn_name]
        try:
            return fn(**fn_args)
        except Exception as e:
            self.logger.error("Excepción en herramienta",
                              extra={"tool_name": fn_name, "error_details": str(e)},
                              exc_info=True)
            return {"error": f"Excepción ejecutando '{fn_name}': {e}"}

    def _validate_model(self) -> bool:
        """Comprueba si el modelo pedido existe en el backend local."""
        try:
            available = [m.id for m in self.client.models.list().data]
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
        except Exception:
            return True

    def run(self):
        """Bucle principal REPL del agente local."""
        if not self._validate_model():
            sys.exit(1)

        project_context = load_project_context(self.work_dir)

        def _make_system_prompt() -> str:
            cfg = self.MODE_CONFIGS[self.current_mode]
            return render_shared_prompt(
                template_name="local_system_prompt.txt",
                work_dir=self.work_dir,
                logger=self.logger,
                fallback_builder=lambda: build_system_prompt(
                    self.work_dir, project_context,
                    self.current_mode, cfg["system_prompt_snippet"]
                ),
                system_prompt_path=self.system_prompt_path,
                desktop=str(Path.home() / "Desktop"),
                project_context=project_context,
                mode=self.current_mode,
                mode_snippet=cfg["system_prompt_snippet"],
                mode_section=(
                    "\n═══════════════════════════════════════════════════════\n"
                    f"MODO ACTUAL: {self.current_mode.upper()}\n"
                    "═══════════════════════════════════════════════════════\n"
                    f"{cfg['system_prompt_snippet']}\n"
                ),
            )

        system_prompt = _make_system_prompt()
        self.messages = [{"role": "system", "content": system_prompt}]

        self.logger.info("Sesión iniciada", extra={"tool_args": {
            "model": self.model, "work_dir": self.work_dir,
            "tag": self.tag, "num_ctx": self.num_ctx,
            "temperature": self.temperature,
        }})

        print_header(self.model, self.work_dir, self.tag, self.num_ctx, self.temperature)

        while True:
            prompt_color = self.MODE_CONFIGS[self.current_mode]["color"]
            user_input = get_input(prompt_color)

            if not user_input:
                continue
            if user_input.lower() in ("salir", "exit", "quit"):
                console.print(f"\n[{C_DIM}]  Hasta luego.[/]\n")
                self.logger.info("Sesión finalizada por el usuario")
                break
            if user_input.lower() in ("limpiar", "clear", "reset"):
                system_prompt = _make_system_prompt()
                self.messages = [{"role": "system", "content": system_prompt}]
                console.print(f"[{C_OK}]  ✓ Sesión limpiada[/]")
                self.logger.info("Historial limpiado")
                continue
            if user_input.lower().startswith("/mode"):
                parts = user_input.split(maxsplit=1)
                if len(parts) == 2 and parts[1].lower() in self.MODE_CONFIGS:
                    self.current_mode = parts[1].lower()
                    system_prompt = _make_system_prompt()
                    self.messages[0] = {"role": "system", "content": system_prompt}
                    color = self.MODE_CONFIGS[self.current_mode]["color"]
                    console.print(f"[{color}]  ✓ Modo: {self.current_mode.upper()}[/]")
                    self.logger.info("Modo cambiado",
                                     extra={"tool_args": {"mode": self.current_mode}})
                else:
                    modes = " | ".join(self.MODE_CONFIGS.keys())
                    console.print(f"[{C_ERR}]  Uso: /mode [{modes}][/]")
                continue

            self.logger.info("Mensaje del usuario", extra={"user_input": user_input})
            self.messages.append({"role": "user", "content": user_input})

            while True:
                trimmed = self._trim_history()
                full_content, tool_calls = self._stream_response(trimmed, TOOLS)

                if full_content:
                    self.logger.info("Respuesta del asistente",
                                     extra={"assistant_response": full_content[:2000]})

                if tool_calls:
                    console.print()
                    # Se registra el mensaje asistente con `tool_calls` para
                    # conservar un historial compatible con la API OpenAI.
                    self.messages.append({
                        "role": "assistant",
                        "content": full_content or None,
                        "tool_calls": [
                            {"id": tc["id"], "type": "function",
                             "function": {"name": tc["name"],
                                          "arguments": json.dumps(tc["arguments"])}}
                            for tc in tool_calls
                        ]
                    })
                    for tc in tool_calls:
                        fn_name = tc["name"]
                        fn_args = tc["arguments"]
                        if fn_name in TOOL_MAP:
                            fn_args = self._validate_tool_args(fn_name, fn_args)
                            if "error" in fn_args:
                                result = fn_args
                                self.logger.warning(
                                    "Validación de argumentos fallida",
                                    extra={"tool_name": fn_name, "error_details": fn_args["error"]}
                                )
                            else:
                                self.logger.debug("Llamada a herramienta",
                                                  extra={"tool_name": fn_name, "tool_args": fn_args})
                                print_tool_call(fn_name, fn_args)
                                result = self._invoke_tool(fn_name, fn_args)
                                self.logger.debug(
                                    "Resultado de herramienta",
                                    extra={
                                        "tool_name": fn_name,
                                        "tool_result": {
                                            k: (str(v)[:500] if isinstance(v, str) else v)
                                            for k, v in result.items()
                                        },
                                    }
                                )
                                if "error" in result:
                                    self.logger.error(
                                        "Herramienta devolvió error",
                                        extra={"tool_name": fn_name, "error_details": result["error"]}
                                    )
                        else:
                            result = {"error": f"Tool desconocida: {fn_name}"}
                            self.logger.error("Tool desconocida",
                                              extra={"tool_name": fn_name,
                                                     "error_details": result["error"]})
                        print_tool_result(result)
                        self.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                else:
                    self.messages.append({"role": "assistant", "content": full_content})
                    break


# ── Entry point ───────────────────────────────────────────────────────────────
RECOMMENDED_MODELS = [
    ("qwen2.5-coder:14b",     "Coding · ~8.5GB VRAM · Mejor coder todo-GPU",   "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:14b",       "Razonamiento · ~8.5GB VRAM · Thinking model",   "⭐⭐⭐⭐⭐"),
    ("deepseek-coder-v2:16b", "Coding MoE · ~10GB VRAM · Muy eficiente",       "⭐⭐⭐⭐⭐"),
    ("mistral-nemo:12b",      "General+Coding · ~7.5GB VRAM · Multilingüe",    "⭐⭐⭐⭐ "),
    ("dolphin3:8b",           "Sin censura · ~5GB VRAM · Llama3-based",        "⭐⭐⭐⭐ "),
    ("qwen2.5-coder:7b",      "Coding · ~4.5GB VRAM · Más rápido",             "⭐⭐⭐⭐ "),
    ("qwen2.5-coder:32b",     "Coding · ~12+7GB RAM · Máxima calidad",         "⭐⭐⭐⭐⭐"),
    ("codestral:22b",         "Coding · ~13GB VRAM+RAM · Mistral coding",      "⭐⭐⭐⭐⭐"),
    ("deepseek-r1:32b",       "Razonamiento · ~12+7GB RAM · Thinking máximo",  "⭐⭐⭐⭐⭐"),
    ("dolphin-mistral:7b",    "Sin censura · ~4.5GB VRAM · Mistral-based",     "⭐⭐⭐⭐ "),
]


def select_model_menu(api_base: str = "http://localhost:11434/v1") -> str:
    try:
        _client = OpenAI(base_url=api_base, api_key="sk-no-key-required")
        installed = {m.id for m in _client.models.list().data}
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


def run_agent(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float,
              api_base: str = "http://localhost:11434/v1",
              system_prompt_path: Optional[str] = None):
    Agent(model, work_dir, tag, num_ctx, temperature, api_base, system_prompt_path).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente local con Ollama/vLLM/LMDeploy/LM Studio")
    parser.add_argument("--model",    default=None,  help="Modelo (omitir para menú interactivo)")
    parser.add_argument("--dir",      default=".")
    parser.add_argument("--tag",      default="AGENTE")
    parser.add_argument("--ctx",      type=int,   default=16384)
    parser.add_argument("--temp",     type=float, default=0.15)
    parser.add_argument("--api-base", default="http://localhost:11434/v1")
    parser.add_argument("--system-prompt", default=None)
    args = parser.parse_args()
    model = args.model if args.model else select_model_menu(args.api_base)
    run_agent(model, args.dir, args.tag, args.ctx, args.temp, args.api_base, args.system_prompt)
