"""
DEPRECADO: este punto de entrada se mantendrá por compatibilidad hacia atrás
pero será eliminado en una versión futura.

Usa directamente:
    python src/hybrid/agent.py [argumentos]
"""
from __future__ import annotations

import runpy
import warnings
from pathlib import Path

warnings.warn(
    "IA/MEGA/agent.py está deprecado. "
    "Usa 'python src/hybrid/agent.py' directamente.",
    DeprecationWarning,
    stacklevel=2,
)

TARGET = Path(__file__).resolve().parents[2] / "src" / "hybrid" / "agent.py"

if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
