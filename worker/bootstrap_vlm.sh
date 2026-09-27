#!/usr/bin/env bash
# Install the GPU vision-language server (worker/vlm_server.py, loopback :8003)
# into its own venv. Kept separate from Fast-SAM3D and SAM 3.1 on purpose:
# Qwen3-VL needs a newer transformers than either of them pins.
#
#   VLM_PERSIST_ROOT=/opt/sketchscape/runtime/vlm bash worker/bootstrap_vlm.sh
#
# Idempotent: re-running with the marker present only runs the preflight.
set -euo pipefail

ROOT_DIR="${VLM_PERSIST_ROOT:?Set this to persistent local storage, e.g. /opt/sketchscape/runtime/vlm}"
ENV_DIR="${VLM_ENV_DIR:-$ROOT_DIR/venv}"
MODEL_ID="${VLM_MODEL_ID:-Qwen/Qwen3-VL-4B-Instruct}"
MODEL_DIR="${VLM_MODEL_DIR:-$ROOT_DIR/models/$(basename "$MODEL_ID")}"
export HF_HOME="${VLM_HF_HOME:-$ROOT_DIR/huggingface-cache}"
PYTHON="${VLM_PYTHON:-python3.12}"
MARKER="$ROOT_DIR/.vlm-ready-v1"

command -v nvidia-smi >/dev/null 2>&1 || { echo "A CUDA GPU is required." >&2; exit 1; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo "$PYTHON is required." >&2; exit 1; }
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader
mkdir -p "$ROOT_DIR" "$(dirname "$MODEL_DIR")" "$HF_HOME"

preflight() {
  "$ENV_DIR/bin/python" - "$MODEL_DIR" <<'PY'
import sys, torch, transformers
from transformers import AutoProcessor
assert torch.cuda.is_available(), "CUDA is unavailable in the VLM environment"
AutoProcessor.from_pretrained(sys.argv[1])
print("VLM environment ready: torch", torch.__version__, "cuda", torch.version.cuda,
      "transformers", transformers.__version__, "model", sys.argv[1])
PY
}

if [ -f "$MARKER" ] && [ -x "$ENV_DIR/bin/python" ] && [ -f "$MODEL_DIR/config.json" ]; then
  preflight
  exit 0
fi

if [ ! -x "$ENV_DIR/bin/python" ]; then
  "$PYTHON" -m venv "$ENV_DIR"
fi
"$ENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
# Exact versions of the verified install (2026-09-27, L40S, CUDA 12.8 wheels).
"$ENV_DIR/bin/python" -m pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0 \
  --index-url https://download.pytorch.org/whl/cu128
# Qwen3-VL needs transformers >= 4.57; verified with 5.17.0. vlm_server.py
# serves with the stdlib http.server, so no web framework is installed.
"$ENV_DIR/bin/python" -m pip install --no-cache-dir \
  transformers==5.17.0 accelerate==1.15.0 'huggingface-hub[cli]==1.33.0' \
  tokenizers==0.23.2 safetensors==0.8.0 pillow==12.3.0 numpy==2.5.2

if [ ! -f "$MODEL_DIR/config.json" ]; then
  "$ENV_DIR/bin/hf" download "$MODEL_ID" --local-dir "$MODEL_DIR" \
    --exclude '*.md' --exclude '.gitattributes'
fi
preflight
touch "$MARKER"
