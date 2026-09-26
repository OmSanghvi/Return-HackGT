#!/usr/bin/env bash
# Install SAM 3.1 into its own environment. Do not combine it with Fast-SAM3D:
# their PyTorch/CUDA requirements are intentionally different.
set -euo pipefail

ROOT_DIR="${SAM31_PERSIST_ROOT:?Set this to persistent local storage}"
ENV_DIR="${SAM31_ENV_DIR:-$ROOT_DIR/venv}"
MODEL_DIR="${SAM31_MODEL_DIR:-$ROOT_DIR/models}"
HF_HOME="${HF_HOME:-$ROOT_DIR/huggingface-cache}"
PYTHON="${SAM31_PYTHON:-python3.12}"
MARKER="$ROOT_DIR/.sam31-ready-v1"

command -v nvidia-smi >/dev/null 2>&1 || { echo "A CUDA GPU is required." >&2; exit 1; }
command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python 3.12 is required for SAM 3.1." >&2; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
mkdir -p "$ROOT_DIR" "$MODEL_DIR" "$HF_HOME"

if [ -f "$MARKER" ] && [ -x "$ENV_DIR/bin/python" ] && [ -f "$MODEL_DIR/sam3.1_multiplex.pt" ]; then
  "$ENV_DIR/bin/python" -c 'from ultralytics.models.sam import SAM3SemanticPredictor; print("SAM 3.1 import preflight passed")'
  exit 0
fi

if [ ! -x "$ENV_DIR/bin/python" ]; then
  "$PYTHON" -m venv "$ENV_DIR"
fi
"$ENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
# Meta currently documents Python 3.12, CUDA 12.6+, and current PyTorch for
# SAM 3. The T4 is supported by CUDA; use the model in FP16, then free it.
"$ENV_DIR/bin/python" -m pip install --no-cache-dir torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
"$ENV_DIR/bin/python" -m pip install --no-cache-dir ultralytics 'huggingface-hub[cli]<1.0'
"$ENV_DIR/bin/python" -m pip uninstall --yes clip >/dev/null 2>&1 || true
"$ENV_DIR/bin/python" -m pip install --no-cache-dir 'git+https://github.com/ultralytics/CLIP.git'

if [ ! -f "$MODEL_DIR/sam3.1_multiplex.pt" ]; then
  : "${HF_TOKEN:?Set an approved Hugging Face token for facebook/sam3.1 in this bootstrap shell}"
  HF_HOME="$HF_HOME" HF_TOKEN="$HF_TOKEN" "$ENV_DIR/bin/hf" download \
    facebook/sam3.1 sam3.1_multiplex.pt --local-dir "$MODEL_DIR"
fi
"$ENV_DIR/bin/python" - <<'PY'
import torch
from ultralytics.models.sam import SAM3SemanticPredictor
assert torch.cuda.is_available(), "CUDA is unavailable in the SAM 3.1 environment"
print("SAM 3.1 local environment ready", torch.__version__, torch.version.cuda)
PY
touch "$MARKER"
