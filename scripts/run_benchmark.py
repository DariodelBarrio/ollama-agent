"""Minimal reproducible benchmark workflow for Ollama Agent.

Subcommands
-----------
setup
    Creates benchmark fixtures plus a manifest with exact prompts and criteria.
run-tests
    Runs the repository unit test suite and stores a JSON result for the
    benchmark session (for example `before` and `after`).
check
    Verifies the benchmark workspace outputs for the automated tasks.
report
    Produces a benchmark result JSON with environment, criteria, checks, and
    manually recorded metrics.

This script intentionally does not execute the agent itself. The benchmark is a
human-run workflow with automated verification around it.
"""
from __future__ import annotations

import argparse
import ast
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_DIR = REPO_ROOT / "benchmark_run"

T1_PATTERN_FILE = REPO_ROOT / "common_runtime.py"
T1_VAR_NAME = "BLOCKED_COMMAND_PATTERNS"
T2_FILE_NAME = "config.py"
T3_FILE_NAME = "utils.py"
TEST_COMMAND = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]

T2_FIXTURE = """\
# Fixture T2 - benchmark Ollama Agent (do not remove this comment)
MAX_RETRIES = 3
TIMEOUT_SECONDS = 30
"""


def _extract_t1_patterns() -> list[str]:
    tree = ast.parse(T1_PATTERN_FILE.read_text(encoding="utf-8"), filename=str(T1_PATTERN_FILE))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == T1_VAR_NAME:
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, list):
                        raise TypeError(f"{T1_VAR_NAME} is not a list")
                    return [str(item) for item in value]
    raise ValueError(f"{T1_VAR_NAME} not found in {T1_PATTERN_FILE}")


def _build_manifest(run_dir: Path) -> dict:
    rel = run_dir.relative_to(REPO_ROOT)
    patterns = _extract_t1_patterns()
    return {
        "benchmark_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "run_dir": str(run_dir),
        "agent_launch_examples": {
            "local": "python src/agent.py --model <MODEL> --dir .",
            "hybrid": "python src/hybrid/agent.py --model <MODEL> --dir . --backend <local|groq|auto>",
        },
        "tasks": {
            "T1": {
                "kind": "read_and_analyze",
                "verification": "manual",
                "target_file": str(T1_PATTERN_FILE.relative_to(REPO_ROOT)),
                "var_name": T1_VAR_NAME,
                "expected_pattern_count": len(patterns),
                "expected_patterns": patterns,
                "prompt": (
                    f"Lee {T1_PATTERN_FILE.relative_to(REPO_ROOT)}. "
                    f"¿Cuántos patrones regex tiene {T1_VAR_NAME}? "
                    "Lista todos con una descripción de qué bloquea cada uno."
                ),
                "success_criteria": [
                    "El agente lee el archivo y no responde de memoria.",
                    "El conteo coincide con el estado actual del repositorio.",
                    "No omite ni inventa patrones.",
                    "La explicación de cada patrón coincide con su intención real.",
                ],
            },
            "T2": {
                "kind": "targeted_edit",
                "verification": "automatic",
                "path": f"{rel}/T2/{T2_FILE_NAME}",
                "prompt": (
                    f"En {rel}/T2/{T2_FILE_NAME}, cambia el valor de MAX_RETRIES "
                    "de 3 a 5. No toques ninguna otra línea."
                ),
                "success_criteria": [
                    "MAX_RETRIES queda en 5.",
                    "El comentario del fixture sigue presente.",
                    "TIMEOUT_SECONDS sigue presente y sin cambios.",
                    "No queda ninguna línea con MAX_RETRIES = 3.",
                ],
            },
            "T3": {
                "kind": "file_creation",
                "verification": "automatic",
                "path": f"{rel}/T3/{T3_FILE_NAME}",
                "prompt": (
                    f"Crea {rel}/T3/{T3_FILE_NAME} con dos funciones:\n"
                    "  add(a, b) -> devuelve a + b\n"
                    "  multiply(a, b) -> devuelve a * b\n"
                    "Sin imports, sin docstrings, sin nada más."
                ),
                "success_criteria": [
                    f"El archivo {T3_FILE_NAME} existe.",
                    "La sintaxis Python es válida.",
                    "Define add y multiply.",
                    "No requiere imports para funcionar.",
                ],
            },
        },
        "test_command": TEST_COMMAND,
    }


def cmd_setup(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    t2_dir = run_dir / "T2"
    t2_dir.mkdir(exist_ok=True)
    (t2_dir / T2_FILE_NAME).write_text(T2_FIXTURE, encoding="utf-8")

    t3_dir = run_dir / "T3"
    t3_dir.mkdir(exist_ok=True)
    t3_file = t3_dir / T3_FILE_NAME
    if t3_file.exists():
        t3_file.unlink()

    manifest = _build_manifest(run_dir)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    prompts_lines = [
        "Ollama Agent benchmark prompts",
        "",
        f"Run directory: {run_dir}",
        "",
        "Launch examples:",
        f"  {manifest['agent_launch_examples']['local']}",
        f"  {manifest['agent_launch_examples']['hybrid']}",
        "",
    ]
    for task_name, task in manifest["tasks"].items():
        prompts_lines.append(f"{task_name} [{task['verification']}]")
        prompts_lines.append(task["prompt"])
        prompts_lines.append("")
    (run_dir / "prompts.txt").write_text("\n".join(prompts_lines), encoding="utf-8")

    _hr()
    print(f"Benchmark workspace prepared at: {run_dir}")
    print(f"Manifest: {run_dir / 'manifest.json'}")
    print(f"Prompts:  {run_dir / 'prompts.txt'}")
    print()
    print("Recommended flow:")
    print(f"  1. {sys.executable} scripts/run_benchmark.py --run-dir {run_dir} run-tests --label before")
    print("  2. Launch the agent from the repository root with --dir .")
    print("  3. Execute the exact prompts from prompts.txt")
    print(f"  4. {sys.executable} scripts/run_benchmark.py --run-dir {run_dir} check")
    print(f"  5. {sys.executable} scripts/run_benchmark.py --run-dir {run_dir} run-tests --label after")
    print(f"  6. {sys.executable} scripts/run_benchmark.py --run-dir {run_dir} report --model <MODEL> --backend <BACKEND> --hardware \"<CPU/GPU/RAM>\"")
    _hr()


def _check_t2(run_dir: Path) -> dict:
    t2_file = run_dir / "T2" / T2_FILE_NAME
    if not t2_file.exists():
        return {"pass": False, "auto": True, "reason": "benchmark_run/T2/config.py not found"}

    lines = t2_file.read_text(encoding="utf-8").splitlines()
    has_new = any(line.strip() == "MAX_RETRIES = 5" for line in lines)
    has_old = any(line.strip() == "MAX_RETRIES = 3" for line in lines)
    has_comment = any("Fixture T2 - benchmark Ollama Agent" in line for line in lines)
    timeout_lines = [line.strip() for line in lines if line.strip().startswith("TIMEOUT_SECONDS")]
    timeout_ok = timeout_lines == ["TIMEOUT_SECONDS = 30"]

    if has_new and not has_old and has_comment and timeout_ok:
        return {"pass": True, "auto": True, "reason": "targeted edit applied without obvious collateral changes"}
    if not has_new:
        return {"pass": False, "auto": True, "reason": "MAX_RETRIES was not changed to 5"}
    if has_old:
        return {"pass": False, "auto": True, "reason": "old MAX_RETRIES = 3 line is still present"}
    if not has_comment:
        return {"pass": False, "auto": True, "reason": "fixture comment was removed"}
    return {"pass": False, "auto": True, "reason": "TIMEOUT_SECONDS changed or was removed"}


def _check_t3(run_dir: Path) -> dict:
    t3_file = run_dir / "T3" / T3_FILE_NAME
    if not t3_file.exists():
        return {"pass": False, "auto": True, "reason": f"benchmark_run/T3/{T3_FILE_NAME} not found"}

    content = t3_file.read_text(encoding="utf-8")
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return {"pass": False, "auto": True, "reason": f"SyntaxError: {exc}"}

    funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    names = {func.name for func in funcs}
    expected = {"add", "multiply"}
    missing = expected - names
    if missing:
        return {"pass": False, "auto": True, "reason": f"missing functions: {sorted(missing)}"}

    disallowed = [node.__class__.__name__ for node in tree.body if not isinstance(node, ast.FunctionDef)]
    if disallowed:
        return {"pass": False, "auto": True, "reason": f"unexpected top-level nodes: {disallowed}"}

    return {"pass": True, "auto": True, "reason": "expected file exists with the required functions only"}


def cmd_check(run_dir: Path, json_out: Path | None = None) -> dict[str, dict]:
    patterns = _extract_t1_patterns()
    results = {
        "T1": {
            "pass": None,
            "auto": False,
            "reason": (
                "Manual verification required. The answer must match "
                f"{len(patterns)} current regex patterns from {T1_PATTERN_FILE.relative_to(REPO_ROOT)}."
            ),
        },
        "T2": _check_t2(run_dir),
        "T3": _check_t3(run_dir),
    }

    _hr()
    for task_name, result in sorted(results.items()):
        label = "MANUAL" if result["pass"] is None else ("PASS" if result["pass"] else "FAIL")
        mode = "auto" if result["auto"] else "manual"
        print(f"{task_name}: {label:<6} ({mode})  {result['reason']}")
    _hr()

    if json_out is not None:
        json_out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Check results written to: {json_out}")

    return results


def cmd_run_tests(run_dir: Path, label: str, json_out: Path | None = None) -> dict:
    started = time.perf_counter()
    proc = subprocess.run(
        TEST_COMMAND,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    duration_s = round(time.perf_counter() - started, 3)
    payload = {
        "label": label,
        "command": TEST_COMMAND,
        "returncode": proc.returncode,
        "pass": proc.returncode == 0,
        "duration_s": duration_s,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if json_out is None:
        json_out = run_dir / f"unit_tests_{label}.json"
    json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    _hr()
    print(f"Unit tests [{label}]: {'PASS' if payload['pass'] else 'FAIL'} in {duration_s}s")
    print(f"Saved: {json_out}")
    _hr()
    return payload


def _capture_env(model: str, backend: str, hardware: str, agent_entry: str, api_base: str | None) -> dict:
    env = {
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "backend": backend,
        "agent_entry": agent_entry,
        "api_base": api_base,
        "hardware": hardware,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
    }
    try:
        env["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        env["git_dirty"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except Exception:
        env["git_commit"] = "unknown"
        env["git_dirty"] = None
    return env


def _load_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cmd_report(
    run_dir: Path,
    model: str,
    backend: str,
    hardware: str,
    agent_entry: str,
    api_base: str | None,
    out_file: Path | None,
    t1_pass: bool | None,
    t1_time_s: float | None,
    t2_time_s: float | None,
    t3_time_s: float | None,
    t1_tool_calls: int | None,
    t2_tool_calls: int | None,
    t3_tool_calls: int | None,
    notes: str | None,
) -> None:
    manifest = _build_manifest(run_dir)
    checks = cmd_check(run_dir)

    if t1_pass is not None:
        checks["T1"]["pass"] = t1_pass
        checks["T1"]["reason"] += f" Recorded manually as {'PASS' if t1_pass else 'FAIL'}."

    unit_tests = {
        "before": _load_optional_json(run_dir / "unit_tests_before.json"),
        "after": _load_optional_json(run_dir / "unit_tests_after.json"),
    }

    payload = {
        "benchmark_version": manifest["benchmark_version"],
        "env": _capture_env(model, backend, hardware, agent_entry, api_base),
        "manifest": {
            "tasks": manifest["tasks"],
            "test_command": manifest["test_command"],
        },
        "results": {
            "tasks": checks,
            "metrics": {
                "T1": {"time_s": t1_time_s, "tool_calls": t1_tool_calls},
                "T2": {"time_s": t2_time_s, "tool_calls": t2_tool_calls},
                "T3": {"time_s": t3_time_s, "tool_calls": t3_tool_calls},
            },
            "unit_tests": unit_tests,
            "notes": notes or "",
        },
    }

    if out_file is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        slug = model.replace(":", "-").replace("/", "-")
        out_file = run_dir / f"result_{ts}_{slug}.json"

    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Benchmark report written to: {out_file}")


def _hr() -> None:
    print("-" * 72)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Minimal reproducible benchmark workflow for Ollama Agent")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=DEFAULT_RUN_DIR,
        metavar="DIR",
        help=f"Benchmark working directory (default: {DEFAULT_RUN_DIR})",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Create fixtures, prompts, and benchmark manifest")

    tp = sub.add_parser("run-tests", help="Run the repository unit test suite and save the result")
    tp.add_argument("--label", required=True, choices=["before", "after"], help="Benchmark stage label")
    tp.add_argument("--json-out", type=Path, default=None, help="Optional JSON output path")

    cp = sub.add_parser("check", help="Verify the automated benchmark tasks")
    cp.add_argument("--json-out", type=Path, default=None, help="Optional JSON output path")

    rp = sub.add_parser("report", help="Write a benchmark result JSON")
    rp.add_argument("--model", required=True, help="Model used for the benchmark run")
    rp.add_argument("--backend", required=True, help="Backend used, for example ollama, groq, auto, local")
    rp.add_argument("--hardware", required=True, help="Hardware summary, for example CPU/GPU/RAM")
    rp.add_argument("--agent-entry", default="src/agent.py", help="Agent entry point used for the run")
    rp.add_argument("--api-base", default=None, help="API base URL when relevant")
    rp.add_argument("--out", type=Path, default=None, help="Optional output JSON path")
    rp.add_argument("--t1-pass", choices=["yes", "no"], default=None, help="Manual result for T1")
    rp.add_argument("--t1-time-s", type=float, default=None, help="Manual elapsed time for T1")
    rp.add_argument("--t2-time-s", type=float, default=None, help="Manual elapsed time for T2")
    rp.add_argument("--t3-time-s", type=float, default=None, help="Manual elapsed time for T3")
    rp.add_argument("--t1-tool-calls", type=int, default=None, help="Manual tool-call count for T1")
    rp.add_argument("--t2-tool-calls", type=int, default=None, help="Manual tool-call count for T2")
    rp.add_argument("--t3-tool-calls", type=int, default=None, help="Manual tool-call count for T3")
    rp.add_argument("--notes", default=None, help="Optional free-form notes")

    args = parser.parse_args()

    if args.cmd == "setup":
        cmd_setup(args.run_dir)
    elif args.cmd == "run-tests":
        cmd_run_tests(args.run_dir, args.label, args.json_out)
    elif args.cmd == "check":
        cmd_check(args.run_dir, args.json_out)
    elif args.cmd == "report":
        t1_pass = {"yes": True, "no": False, None: None}[args.t1_pass]
        cmd_report(
            run_dir=args.run_dir,
            model=args.model,
            backend=args.backend,
            hardware=args.hardware,
            agent_entry=args.agent_entry,
            api_base=args.api_base,
            out_file=args.out,
            t1_pass=t1_pass,
            t1_time_s=args.t1_time_s,
            t2_time_s=args.t2_time_s,
            t3_time_s=args.t3_time_s,
            t1_tool_calls=args.t1_tool_calls,
            t2_tool_calls=args.t2_tool_calls,
            t3_tool_calls=args.t3_tool_calls,
            notes=args.notes,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
