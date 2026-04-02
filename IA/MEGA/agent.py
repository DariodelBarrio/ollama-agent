"""Compat shim: usa src/hybrid/agent.py."""
from __future__ import annotations

import runpy
from pathlib import Path


TARGET = Path(__file__).resolve().parents[2] / "src" / "hybrid" / "agent.py"


if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
