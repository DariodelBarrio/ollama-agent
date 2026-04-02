"""
Session log analyzer for agent_session.jsonl files.

Usage:
    python scripts/analyze_session.py [path/to/agent_session.jsonl]

Without arguments it looks for agent_session.jsonl in the current directory.

Outputs:
- Session summary: duration, message counts, tool usage
- Error / self-healing events
- Top tools by invocation count
- Last N assistant responses (for quick audit)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ─── Loading ──────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    events = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # skip malformed lines
    return events


# ─── Analysis ─────────────────────────────────────────────────────────────────

def parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str)
    except Exception:
        return datetime.now(tz=timezone.utc)


def analyze(events: list[dict]) -> dict:
    if not events:
        return {}

    first_ts = parse_ts(events[0]["ts"])
    last_ts  = parse_ts(events[-1]["ts"])
    duration_s = (last_ts - first_ts).total_seconds()

    user_messages      = [e for e in events if e.get("msg") in ("Mensaje usuario", "Mensaje del usuario")]
    assistant_messages = [e for e in events if e.get("msg") in ("Respuesta asistente", "Respuesta del asistente")]
    tool_calls         = [e for e in events if e.get("msg") in ("Llamada a herramienta",)]
    tool_errors        = [e for e in events if e.get("level") == "ERROR"]
    heal_events        = [e for e in events if "Self-healing" in e.get("msg", "")]
    warnings           = [e for e in events if e.get("level") == "WARNING"]

    # Tool usage breakdown
    tool_counts: Counter = Counter()
    for e in tool_calls:
        name = e.get("tool_name") or (e.get("tool_args") or {}).get("name", "unknown")
        tool_counts[name] += 1

    # Session start/end info
    session_start = next((e for e in events if e.get("msg") == "Sesión iniciada"), None)

    return {
        "first_event":       first_ts.isoformat(),
        "last_event":        last_ts.isoformat(),
        "duration_s":        round(duration_s, 1),
        "total_events":      len(events),
        "user_turns":        len(user_messages),
        "assistant_turns":   len(assistant_messages),
        "tool_invocations":  sum(tool_counts.values()),
        "tool_counts":       dict(tool_counts.most_common()),
        "errors":            len(tool_errors),
        "heal_events":       len(heal_events),
        "warnings":          len(warnings),
        "session_meta":      session_start.get("tool_args") if session_start else {},
    }


# ─── Rendering ────────────────────────────────────────────────────────────────

def _bar(value: int, max_value: int, width: int = 20) -> str:
    if max_value == 0:
        return " " * width
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def render_report(stats: dict, events: list[dict], last_n: int = 5) -> str:
    lines = []
    lines.append("═" * 60)
    lines.append("  RESUMEN DE SESIÓN")
    lines.append("═" * 60)

    if not stats:
        lines.append("  (sin eventos)")
        return "\n".join(lines)

    dur = stats["duration_s"]
    dur_str = f"{dur:.0f}s" if dur < 120 else f"{dur/60:.1f}min"

    meta = stats.get("session_meta") or {}
    if meta:
        lines.append(f"  Modelo:       {meta.get('model', '?')}")
        lines.append(f"  Backend:      {meta.get('backend', '?')}")
        lines.append(f"  Directorio:   {meta.get('work_dir', '?')}")

    lines.append(f"  Inicio:       {stats['first_event']}")
    lines.append(f"  Fin:          {stats['last_event']}")
    lines.append(f"  Duración:     {dur_str}")
    lines.append("")
    lines.append(f"  Turnos usuario:     {stats['user_turns']}")
    lines.append(f"  Turnos asistente:   {stats['assistant_turns']}")
    lines.append(f"  Llamadas herr.:     {stats['tool_invocations']}")
    lines.append(f"  Errores:            {stats['errors']}")
    lines.append(f"  Auto-heals:         {stats['heal_events']}")
    lines.append(f"  Advertencias:       {stats['warnings']}")

    if stats["tool_counts"]:
        lines.append("")
        lines.append("  USO DE HERRAMIENTAS")
        lines.append("  " + "─" * 40)
        max_count = max(stats["tool_counts"].values())
        for tool, count in sorted(stats["tool_counts"].items(), key=lambda x: -x[1]):
            bar = _bar(count, max_count, 16)
            lines.append(f"  {tool:<22} {bar} {count:>4}×")

    # Last N assistant responses
    assistant_evts = [
        e for e in events
        if e.get("msg") in ("Respuesta asistente", "Respuesta del asistente")
        and e.get("assistant_response")
    ]
    if assistant_evts and last_n > 0:
        lines.append("")
        lines.append(f"  ÚLTIMAS {last_n} RESPUESTAS DEL ASISTENTE")
        lines.append("  " + "─" * 40)
        for e in assistant_evts[-last_n:]:
            ts = parse_ts(e["ts"]).strftime("%H:%M:%S")
            text = e["assistant_response"][:200].replace("\n", " ")
            lines.append(f"  [{ts}] {text}")

    # Errors
    err_evts = [e for e in events if e.get("level") == "ERROR"]
    if err_evts:
        lines.append("")
        lines.append("  ERRORES")
        lines.append("  " + "─" * 40)
        for e in err_evts[-10:]:
            ts = parse_ts(e["ts"]).strftime("%H:%M:%S")
            detail = e.get("error_details", e.get("msg", ""))[:150]
            lines.append(f"  [{ts}] {detail}")

    lines.append("═" * 60)
    return "\n".join(lines)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        log_path = Path(sys.argv[1])
    else:
        log_path = Path("agent_session.jsonl")

    if not log_path.exists():
        print(f"No encontrado: {log_path}")
        print("Uso: python scripts/analyze_session.py [ruta/agent_session.jsonl]")
        sys.exit(1)

    events = load_jsonl(log_path)
    if not events:
        print(f"El archivo está vacío o no contiene eventos JSON válidos: {log_path}")
        sys.exit(0)

    # Split into sessions by "Sesión iniciada" events
    session_starts = [i for i, e in enumerate(events) if e.get("msg") == "Sesión iniciada"]
    if not session_starts:
        session_starts = [0]

    sessions = []
    for i, start in enumerate(session_starts):
        end = session_starts[i + 1] if i + 1 < len(session_starts) else len(events)
        sessions.append(events[start:end])

    print(f"\nArchivo: {log_path.resolve()}")
    print(f"Sesiones encontradas: {len(sessions)}\n")

    for idx, sess in enumerate(sessions, 1):
        if len(sessions) > 1:
            print(f"{'─'*20} Sesión {idx}/{len(sessions)} {'─'*20}")
        stats = analyze(sess)
        print(render_report(stats, sess))
        print()


if __name__ == "__main__":
    main()
