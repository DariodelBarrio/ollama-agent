"""Benchmark local reproducible para Ollama Agent.

Subcomandos
-----------
setup   Crea los fixtures y muestra los prompts exactos para cada tarea.
check   Verifica automáticamente los resultados de T2 y T3.
report  Genera un JSON con entorno + resultados para archivar y comparar.

Flujo completo
--------------
1.  python scripts/run_benchmark.py setup
2.  Lanzar el agente y ejecutar cada tarea manualmente (ver prompts que imprime setup).
3.  python scripts/run_benchmark.py check
4.  python scripts/run_benchmark.py report --model qwen2.5-coder:14b
"""
from __future__ import annotations

import argparse
import ast
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = REPO_ROOT / "benchmark_run"

# Ground truth para T1 (no tocar sin actualizar common_runtime.py)
T1_PATTERN_COUNT = 15
T1_PATTERN_FILE = "common_runtime.py"
T1_VAR_NAME = "BLOCKED_COMMAND_PATTERNS"

# Fixture para T2
T2_FIXTURE = """\
# Fixture T2 — benchmark Ollama Agent (no eliminar este comentario)
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
"""

# Nombre de archivo esperado en T3
T3_FILE = "utils.py"
T3_EXPECTED_FUNCTIONS = {"add", "multiply"}


# ── setup ─────────────────────────────────────────────────────────────────────

def cmd_setup(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    # T2
    t2_dir = run_dir / "T2"
    t2_dir.mkdir(exist_ok=True)
    t2_file = t2_dir / "config.py"
    t2_file.write_text(T2_FIXTURE, encoding="utf-8")

    # T3: directorio vacío (el agente debe crear el archivo)
    t3_dir = run_dir / "T3"
    t3_dir.mkdir(exist_ok=True)

    rel = run_dir.relative_to(REPO_ROOT)

    _hr()
    print(f"Fixtures creados en:  {run_dir}")
    print()
    print("Lanza el agente desde la raíz del repo con --dir apuntando a la raíz,")
    print("para que pueda acceder tanto al código fuente como a los fixtures.")
    print()
    print("  python src/agent.py --model <MODEL> --dir .")
    print()
    _hr()
    print("T1 — Lectura y análisis  [verificación manual]")
    _hr()
    print()
    print("Prompt:")
    print()
    print(f'  Lee {T1_PATTERN_FILE}. ¿Cuántos patrones regex tiene {T1_VAR_NAME}?')
    print( '  Lista todos con una descripción de qué bloquea cada uno.')
    print()
    print(f"Criterio: el agente lista los {T1_PATTERN_COUNT} patrones correctamente")
    print( "sin inventar ni omitir ninguno. La verificación es manual.")
    print()
    _hr()
    print("T2 — Edición puntual  [verificación automática]")
    _hr()
    print()
    print("Prompt:")
    print()
    print(f'  En {rel}/T2/config.py, cambia el valor de MAX_RETRIES')
    print( '  de 3 a 5. No toques ninguna otra línea.')
    print()
    print("Criterio: MAX_RETRIES = 5, comentario de fixture intacto,")
    print("          TIMEOUT_SECONDS sin cambios.")
    print()
    _hr()
    print("T3 — Creación de archivo  [verificación automática]")
    _hr()
    print()
    print("Prompt:")
    print()
    print(f'  Crea {rel}/T3/utils.py con dos funciones:')
    print( '    add(a, b)      -> devuelve a + b')
    print( '    multiply(a, b) -> devuelve a * b')
    print( '  Sin imports, sin docstrings, sin nada más.')
    print()
    print("Criterio: archivo existe, define add y multiply,")
    print("          sintaxis Python válida.")
    print()
    _hr()
    print("Tras ejecutar las tres tareas, verifica con:")
    print()
    print(f"  python scripts/run_benchmark.py check --run-dir {run_dir}")
    _hr()


# ── check ─────────────────────────────────────────────────────────────────────

def cmd_check(run_dir: Path) -> dict[str, dict]:
    results: dict[str, dict] = {}

    # T1: manual, no hay archivo que verificar
    results["T1"] = {
        "pass": None,
        "auto": False,
        "reason": (
            f"Verificación manual: el agente debe listar los {T1_PATTERN_COUNT} patrones "
            f"de {T1_VAR_NAME} en {T1_PATTERN_FILE} sin inventar ni omitir ninguno."
        ),
    }

    # T2: MAX_RETRIES = 5, comentario intacto, no queda el valor viejo
    t2_file = run_dir / "T2" / "config.py"
    if not t2_file.exists():
        results["T2"] = {"pass": False, "auto": True, "reason": "archivo no encontrado"}
    else:
        lines = t2_file.read_text(encoding="utf-8").splitlines()
        has_new = any(ln.strip() == "MAX_RETRIES = 5" for ln in lines)
        has_old = any(ln.strip() == "MAX_RETRIES = 3" for ln in lines)
        has_comment = any("Fixture T2" in ln for ln in lines)
        has_timeout = any("TIMEOUT_SECONDS" in ln for ln in lines)

        if has_new and not has_old and has_comment and has_timeout:
            results["T2"] = {"pass": True, "auto": True, "reason": "edición correcta, contexto intacto"}
        elif not has_new:
            results["T2"] = {"pass": False, "auto": True, "reason": "MAX_RETRIES no fue cambiado a 5"}
        elif has_old:
            results["T2"] = {"pass": False, "auto": True, "reason": "valor antiguo (= 3) sigue presente"}
        elif not has_comment:
            results["T2"] = {"pass": False, "auto": True, "reason": "comentario de fixture eliminado"}
        else:
            results["T2"] = {"pass": False, "auto": True, "reason": "TIMEOUT_SECONDS fue eliminado"}

    # T3: utils.py existe, define add y multiply, sintaxis válida
    t3_file = run_dir / "T3" / T3_FILE
    if not t3_file.exists():
        results["T3"] = {"pass": False, "auto": True, "reason": f"{T3_FILE} no encontrado"}
    else:
        content = t3_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            results["T3"] = {"pass": False, "auto": True, "reason": f"SyntaxError: {exc}"}
        else:
            defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
            missing = T3_EXPECTED_FUNCTIONS - defined
            if missing:
                results["T3"] = {"pass": False, "auto": True, "reason": f"funciones ausentes: {sorted(missing)}"}
            else:
                results["T3"] = {"pass": True, "auto": True, "reason": "add y multiply definidas, sintaxis válida"}

    _hr()
    for task, r in sorted(results.items()):
        if r["pass"] is True:
            label = "PASS  "
        elif r["pass"] is False:
            label = "FAIL  "
        else:
            label = "MANUAL"
        auto = "auto" if r["auto"] else "manual"
        print(f"  {task}  [{label}] ({auto})  {r['reason']}")
    _hr()

    return results


# ── report ────────────────────────────────────────────────────────────────────

def cmd_report(run_dir: Path, model: str, out_file: Path | None, t1_pass: bool | None) -> None:
    env = _capture_env(model)
    task_results = cmd_check(run_dir)

    # Incorporar decisión manual de T1 si se pasó por flag
    if t1_pass is not None:
        task_results["T1"]["pass"] = t1_pass
        task_results["T1"]["reason"] += f" — registrado manualmente como {'PASS' if t1_pass else 'FAIL'}"

    payload = {"env": env, "tasks": task_results}

    if out_file is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        slug = model.replace(":", "-").replace("/", "-")
        out_file = run_dir / f"result_{ts}_{slug}.json"

    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nInforme guardado en: {out_file}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _capture_env(model: str) -> dict:
    env: dict = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
    }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        env["git_commit"] = commit
        env["git_dirty"] = bool(dirty)
    except Exception:
        env["git_commit"] = "unknown"
        env["git_dirty"] = None
    return env


def _hr() -> None:
    print("-" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    # Forzar UTF-8 en stdout para que los acentos se muestren correctamente
    # en terminales Windows que usan cp1252 por defecto.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Benchmark local reproducible para Ollama Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--run-dir", type=Path, default=DEFAULT_RUN_DIR,
        metavar="DIR",
        help=f"Directorio de trabajo del benchmark (default: {DEFAULT_RUN_DIR})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Crea fixtures e imprime prompts exactos")
    sub.add_parser("check", help="Verifica resultados de T2 y T3 automáticamente")

    rp = sub.add_parser("report", help="Genera informe JSON archivable")
    rp.add_argument("--model", required=True, metavar="MODEL",
                    help="Nombre del modelo usado (ej. qwen2.5-coder:14b)")
    rp.add_argument("--out", type=Path, default=None, metavar="FILE",
                    help="Ruta de salida del JSON (se genera automáticamente si se omite)")
    rp.add_argument("--t1-pass", choices=["yes", "no"], default=None,
                    help="Resultado manual de T1 (yes/no)")

    args = parser.parse_args()

    if args.cmd == "setup":
        cmd_setup(args.run_dir)
    elif args.cmd == "check":
        cmd_check(args.run_dir)
    elif args.cmd == "report":
        t1 = {"yes": True, "no": False, None: None}[args.t1_pass]
        cmd_report(args.run_dir, args.model, args.out, t1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
