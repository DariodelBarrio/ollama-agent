"""Instala dependencias de forma multiplataforma.

Uso:
  python scripts/install.py               # instala requirements.txt
  python scripts/install.py --mega        # instala requirements-mega.txt
  python scripts/install.py --file path   # instala desde un requirements específico
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def pip_install(requirements_file: Path) -> int:
    if not requirements_file.exists():
        print(f"[ERROR] No existe: {requirements_file}")
        return 1
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)]
    print(f"[INFO] Ejecutando: {' '.join(cmd)}")
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Instalador multiplataforma de dependencias")
    parser.add_argument("--mega", action="store_true", help="Instala requirements-mega.txt")
    parser.add_argument("--file", type=Path, default=None,
                        help="Ruta a un requirements.txt específico (anula --mega)")
    args = parser.parse_args()

    if args.file:
        requirements_file = args.file.resolve()
    elif args.mega:
        requirements_file = REPO_ROOT / "requirements-mega.txt"
    else:
        requirements_file = REPO_ROOT / "requirements.txt"

    return pip_install(requirements_file)


if __name__ == "__main__":
    raise SystemExit(main())
