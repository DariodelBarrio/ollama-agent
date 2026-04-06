"""
Agente local de Ollama Agent.
Uso: python src/agent.py [--model qwen3:14b] [--dir C:\\mi\\proyecto] [--ctx 16384] [--temp 0.15]
"""
import json
import logging
import sys
import re
import argparse
import os
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
    sync_work_dir, get_work_dir, build_agent_tools,
    run_command, read_file, write_file, edit_file, find_files, grep,
    list_directory, delete_file, create_directory, move_file,
    search_web, fetch_url, change_directory,
    BASE_TOOL_MAP as TOOL_MAP,
    BASE_TOOLS as TOOLS,
    extract_tool_calls_from_text,
    detect_file_creation_intent,
    extract_candidate_paths,
    classify_destination_intent,
    select_target_directory,
    get_workspace_placeholder_targets,
    normalize_path_in_workspace,
    resolve_in_workspace,
    should_plan_task,
    should_verify_task,
    should_run_critic,
    requested_test_validation,
    emit_role_event,
    emit_role_result,
    summarize_text,
    snapshot_workspace_files,
    verify_workspace_changes,
    build_recovery_instruction,
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

SIMPLE_INPUT = os.getenv("OLLAMA_AGENT_SIMPLE_INPUT", "").strip().lower() in {"1", "true", "yes"}


def print_header(model: str, work_dir: str, tag: str, num_ctx: int, temperature: float, read_only: bool = False):
    if SIMPLE_INPUT:
        console.print()
        console.print(f"[bold]{tag}[/]  {model}")
        mode = "  read-only" if read_only else ""
        console.print(f"[{C_DIM}]ctx:{num_ctx}  temp:{temperature}{mode}  {work_dir}[/]")
        console.print(f"[{C_DIM}]Escribe y pulsa Enter. 'salir' termina. 'limpiar' reinicia.[/]")
        console.print(f"[{C_BORDER}]" + ("-" * 72) + "[/]")
        console.print()
        return
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
    if SIMPLE_INPUT:
        try:
            return input().strip()
        except (KeyboardInterrupt, EOFError):
            return "salir"
    console.print()
    try:
        console.print(f"[{color}]>[/] ", end="")
        return input().strip()
    except (KeyboardInterrupt, EOFError):
        return "salir"


# ── Prompts ───────────────────────────────────────────────────────────────────
def build_system_prompt(work_dir: str, project_context: str,
                        mode: str = "", mode_snippet: str = "") -> str:
    placeholder_targets = get_workspace_placeholder_targets()
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
        desktop=placeholder_targets["desktop"],
        documents=placeholder_targets["documents"],
        workspace=placeholder_targets["workspace"],
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
                 system_prompt_path: Optional[str] = None,
                 read_only: bool = False,
                 guided_mode: bool = False):
        self.model        = model
        self.work_dir     = str(Path(work_dir).resolve())
        self.tag          = tag
        self.num_ctx      = num_ctx
        self.temperature  = temperature
        self.api_base     = api_base
        self.current_mode = "code"
        self.read_only    = read_only
        self.guided_mode  = guided_mode
        self.max_recovery_attempts = 2
        self.client       = OpenAI(base_url=api_base, api_key="sk-no-key-required")
        self.messages: list = []
        self.system_prompt_path = Path(system_prompt_path).resolve() if system_prompt_path else None

        # Sync shared tool runtime to this agent's work directory
        sync_work_dir(self.work_dir, read_only=read_only)
        self.tools = build_agent_tools(include_web=True, read_only=read_only)

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
            tool_calls = extract_tool_calls_from_text("".join(collected))
            if tool_calls:
                collected.clear()
            else:
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

    def _role_subcall(self, role: str, prompt: str, max_tokens: int = 260) -> str:
        role_prompts = {
            "planner": (
                "Eres PLANNER. Devuelve un plan breve y accionable en español. "
                "Incluye solo: artefactos, tools probables, validación y riesgo principal."
            ),
            "critic": (
                "Eres CRITIC. Revisa el resultado con dureza técnica pero brevemente. "
                "Si está bien responde solo '✓ Sin problemas.'. Si no, da hasta 3 hallazgos concretos."
            ),
            "recovery": (
                "Eres FIXER. Devuelve una única instrucción de reintento, concreta y distinta del intento fallido."
            ),
        }
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": role_prompts[role]},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            self.logger.warning(
                "Subcall de rol no disponible",
                extra={"tool_args": {"role": role}, "error_details": str(exc)},
            )
            return ""

    def plan_task(self, user_input: str) -> str:
        if not self.guided_mode or not should_plan_task(user_input):
            return ""
        emit_role_event("planner", user_input)
        plan = self._role_subcall(
            "planner",
            f"Tarea: {user_input}\nWorkspace: {self.work_dir}\n"
            "Planifica para ejecutar de verdad, no para explicar teoría.",
            max_tokens=220,
        )
        if plan:
            emit_role_result("planner", "ok", plan)
        else:
            emit_role_result("planner", "skip", "sin plan adicional")
        return plan

    def critic_review(self, task_summary: str, changed_files: list[str]) -> str:
        if not self.guided_mode or not should_run_critic(task_summary, changed_files):
            return ""
        emit_role_event("critic", f"{len(changed_files)} archivos")
        review = self._role_subcall(
            "critic",
            "Tarea: {task}\nArchivos cambiados: {files}\n"
            "Evalúa bugs, validación faltante y supuestos débiles.".format(
                task=task_summary,
                files=", ".join(sorted(set(changed_files))) or "(ninguno)",
            ),
            max_tokens=220,
        )
        if review:
            status = "ok" if "sin problemas" in review.lower() or review.strip().startswith("✓") else "issue"
            emit_role_result("critic", status if status == "ok" else "fail", review)
        else:
            emit_role_result("critic", "skip", "sin review")
        return review

    def recovery_retry(self, reason: str) -> str:
        emit_role_event("recovery", reason)
        retry = self._role_subcall("recovery", reason, max_tokens=140)
        if retry:
            emit_role_result("recovery", "ok", retry)
            return retry
        emit_role_result("recovery", "skip", "usando instrucción determinista")
        return reason

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
                desktop=get_workspace_placeholder_targets()["desktop"],
                documents=get_workspace_placeholder_targets()["documents"],
                workspace=get_workspace_placeholder_targets()["workspace"],
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
            "temperature": self.temperature, "guided_mode": self.guided_mode,
        }})

        print_header(self.model, self.work_dir, self.tag, self.num_ctx, self.temperature, self.read_only)

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
            plan = self.plan_task(user_input)
            guidance_messages = []
            if plan:
                guidance_messages.append({"role": "system", "content": f"[PLAN INTERNO]\n{plan}"})

            candidates = extract_candidate_paths(user_input)
            expected_paths: list[str] = candidates[:1]
            changed_files: list[str] = []
            test_results: list[dict] = []
            recovery_count = 0
            critic_fix_used = False

            # ── Destination directive ─────────────────────────────────────────
            # Classify where the user wants the file, then inject a directive so
            # the LLM knows the right directory without guessing from cwd.
            if detect_file_creation_intent(user_input):
                intent_kind, intent_value = classify_destination_intent(user_input)
                if intent_kind == "explicit":
                    destination_msg = f"Ruta exacta solicitada: {intent_value}"
                elif intent_kind == "alias":
                    resolved_alias = normalize_path_in_workspace(intent_value)
                    destination_msg = (
                        f"El usuario indicó destino alias '{intent_value}'. "
                        f"Ruta resuelta dentro del workspace: {resolved_alias}"
                    )
                else:  # implicit
                    target_dir, reasoning = select_target_directory(intent_value, self.work_dir)
                    destination_msg = (
                        f"No se especificó ruta de destino. "
                        f"Directorio seleccionado por inspección del proyecto: {target_dir} "
                        f"({reasoning}). "
                        f"Crea el archivo ahí salvo que haya un motivo más específico."
                    )
                    self.logger.debug(
                        "Destino implícito inferido",
                        extra={"tool_args": {"artifact": intent_value, "dir": target_dir, "reason": reasoning}},
                    )
                guidance_messages.append({
                    "role": "system",
                    "content": f"[DESTINO]\n{destination_msg}",
                })

            before_snapshots = snapshot_workspace_files(expected_paths)

            while True:
                emit_role_event("executor", user_input if recovery_count == 0 else f"retry {recovery_count}: {user_input}")
                file_created = False
                file_recovery_done = False

                while True:
                    trimmed = self._trim_history() + guidance_messages
                    full_content, tool_calls = self._stream_response(trimmed, self.tools)

                    if full_content:
                        self.logger.info("Respuesta del asistente",
                                         extra={"assistant_response": full_content[:2000]})

                    if tool_calls:
                        console.print()
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
                                    tracked_paths: list[str] = []
                                    if fn_name in {"write_file", "edit_file", "read_file", "delete_file", "create_directory", "change_directory"}:
                                        if fn_args.get("path"):
                                            tracked_paths.append(str(fn_args["path"]))
                                    if fn_name == "move_file":
                                        tracked_paths.extend([str(fn_args.get("src", "")), str(fn_args.get("dst", ""))])
                                    before_snapshots.update(snapshot_workspace_files(tracked_paths))

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
                                    if fn_name in {"write_file", "edit_file", "move_file", "delete_file"} and "error" not in result:
                                        path_hint = result.get("path") or result.get("to") or fn_args.get("path") or fn_args.get("dst")
                                        if path_hint:
                                            changed_files.append(str(path_hint))
                                    if fn_name == "run_command":
                                        command_text = str(fn_args.get("command", ""))
                                        if requested_test_validation(user_input) or re.search(r"\b(test|pytest|unittest|cargo test)\b", command_text, re.I):
                                            test_results.append(result)
                                    if fn_name == "write_file" and "error" not in result:
                                        target = result.get("path") or fn_args.get("path")
                                        if target:
                                            try:
                                                target_path = resolve_in_workspace(str(target)).resolve()
                                            except ValueError:
                                                target_path = None
                                            expected_resolved = None
                                            if expected_paths:
                                                try:
                                                    expected_resolved = resolve_in_workspace(expected_paths[0]).resolve()
                                                except ValueError:
                                                    expected_resolved = None
                                            if target_path is not None and (
                                                expected_resolved is None or target_path == expected_resolved
                                            ):
                                                file_created = True
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
                        if detect_file_creation_intent(user_input) and not file_created and not file_recovery_done:
                            file_recovery_done = True
                            recovery = build_recovery_instruction(
                                "El usuario pidió crear un archivo y todavía no existe en disco."
                            )
                            self.messages.append({"role": "user", "content": recovery})
                            console.print(f"[{C_DIM}]  ↺ El modelo no usó write_file() — reintentando...[/]")
                            self.logger.warning(
                                "Recuperación file-creation: modelo devolvió texto sin write_file()",
                                extra={"tool_args": {"user_input": user_input[:200]}},
                            )
                            continue
                        break

                emit_role_result("executor", "ok", f"{len(changed_files)} cambios rastreados")
                report = None
                if self.guided_mode and should_verify_task(user_input, changed_files):
                    emit_role_event("verifier", user_input)
                    report = verify_workspace_changes(
                        expected_paths=expected_paths,
                        changed_paths=changed_files,
                        before_snapshots=before_snapshots,
                        test_results=test_results,
                        require_tests=requested_test_validation(user_input),
                    )
                    emit_role_result(
                        "verifier",
                        "ok" if report.ok else "fail",
                        report.summary if report.ok else "; ".join(report.errors[:3]) or report.summary,
                    )
                    if not report.ok and recovery_count < self.max_recovery_attempts:
                        recovery_count += 1
                        retry_instruction = self.recovery_retry(
                            build_recovery_instruction("La verificación falló.", report)
                        )
                        self.messages.append({"role": "user", "content": retry_instruction})
                        continue

                review = self.critic_review(user_input, changed_files)
                if review and not critic_fix_used and "sin problemas" not in review.lower() and not review.strip().startswith("✓"):
                    critic_fix_used = True
                    correction = self.recovery_retry(
                        f"Corrige estos hallazgos del crítico y vuelve a verificar: {summarize_text(review, 220)}"
                    )
                    self.messages.append({"role": "user", "content": correction})
                    continue
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
              system_prompt_path: Optional[str] = None,
              read_only: bool = False,
              guided_mode: bool = False):
    Agent(model, work_dir, tag, num_ctx, temperature, api_base, system_prompt_path, read_only, guided_mode).run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agente Local sobre backend OpenAI-compatible")
    parser.add_argument("--model",    default=None,  help="Modelo (omitir para menú interactivo)")
    parser.add_argument("--dir",      default=".", help="Directorio de trabajo")
    parser.add_argument("--tag",      default="AGENTE", help="Etiqueta visible en el header")
    parser.add_argument("--ctx",      type=int,   default=16384, help="Ventana de contexto o presupuesto de tokens del backend")
    parser.add_argument("--temp",     type=float, default=0.15, help="Temperatura 0.0-1.0")
    parser.add_argument("--api-base", default="http://localhost:11434/v1", help="URL OpenAI-compatible del backend local")
    parser.add_argument("--system-prompt", default=None, help="Ruta opcional a un prompt de sistema custom")
    parser.add_argument("--read-only", action="store_true", help="Bloquea tools mutantes y shell de escritura")
    parser.add_argument("--guided-mode", action="store_true", help="Activa planner/verifier/critic/recovery ligeros")
    args = parser.parse_args()
    model = args.model if args.model else select_model_menu(args.api_base)
    run_agent(
        model,
        args.dir,
        args.tag,
        args.ctx,
        args.temp,
        args.api_base,
        args.system_prompt,
        args.read_only,
        args.guided_mode,
    )
