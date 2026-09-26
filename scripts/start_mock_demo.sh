#!/usr/bin/env bash
# Starts only the local mock API. No AWS CLI, Terraform, Docker, GPU, or model
# code is called from this script.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
VENV="$BACKEND/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi

"$VENV/bin/python" -c 'import fastapi, uvicorn, multipart' 2>/dev/null \
  || "$VENV/bin/python" -m pip install -r "$BACKEND/requirements.txt"

cd "$BACKEND"
exec env PIPELINE_MODE=mock "$VENV/bin/python" -m uvicorn main:app --reload --port 8000
