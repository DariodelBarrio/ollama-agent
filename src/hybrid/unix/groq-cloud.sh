#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -z "${GROQ_API_KEY:-}" ]; then
  echo "[ERROR] Variable GROQ_API_KEY no definida." >&2
  echo "Definela con: export GROQ_API_KEY=tu_clave" >&2
  exit 1
fi

python "${SCRIPT_DIR}/../agent.py" --model qwen2.5-coder:14b --groq-model llama-3.3-70b-versatile --dir "${PWD}" --tag GROQ --ctx 32768 --backend groq
