#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

echo "Instalando dependencias del agente hibrido..."
python "${SCRIPT_DIR}/../../../scripts/install.py" --hybrid
