#!/usr/bin/env bash
# Run once on a GPU node backed by persistent storage, never during a live demo.
# It creates the Python/CUDA dependency set used by the working Kaggle notebook,
# caches model weights, then verifies imports before writing a marker.
set -euo pipefail

ROOT_DIR="${FASTSAM3D_PERSIST_ROOT:?Set this to persistent Camber/Stash-backed storage}"
REPO_DIR="${FASTSAM3D_REPO_DIR:-$ROOT_DIR/Fast-SAM3D}"
ENV_DIR="${FASTSAM3D_ENV_DIR:-$ROOT_DIR/venv}"
CHECKPOINT_DIR="${FASTSAM3D_CHECKPOINT_DIR:-$ROOT_DIR/checkpoints/hf}"
HF_HOME="${HF_HOME:-$ROOT_DIR/huggingface-cache}"
MARKER="$ROOT_DIR/.fastsam3d-ready-v1"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ENV_DIR/bin/python"

mkdir -p "$ROOT_DIR" "$HF_HOME"
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "A CUDA GPU node is required for this bootstrap." >&2
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
# Compile pytorch3d/gsplat for the GPU actually present (T4 = 7.5, L40S = 8.9).
# A 7.5+PTX build still runs on an L40S, but through slower JIT'd PTX.
GPU_ARCH="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1 | tr -d ' ')"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-${GPU_ARCH}+PTX}"
export MAX_JOBS="${MAX_JOBS:-$(nproc)}"
echo "Building CUDA extensions for TORCH_CUDA_ARCH_LIST=$TORCH_CUDA_ARCH_LIST with MAX_JOBS=$MAX_JOBS"
FREE_GB=$(df -Pk "$ROOT_DIR" | awk 'NR==2 {print int($4/1024/1024)}')
if [ "$FREE_GB" -lt 35 ]; then
  echo "Need at least 35 GB free in FASTSAM3D_PERSIST_ROOT; found ${FREE_GB} GB." >&2
  exit 1
fi

# Do not trust a marker alone: a replaced environment must import correctly.
if [ -f "$MARKER" ] && [ -x "$PYTHON" ]; then
  if "$PYTHON" -c 'import torch, spconv, pytorch3d, kaolin, sam3d_objects.pipeline.inference_pipeline; print(torch.__version__)'; then
    echo "Fast-SAM3D environment already passed its import preflight."
    exit 0
  fi
  mv "$MARKER" "$MARKER.stale.$(date +%s)"
fi

if [ ! -d "$REPO_DIR/.git" ]; then
  git clone --depth 1 https://github.com/wlfeng0509/Fast-SAM3D.git "$REPO_DIR"
fi
git -C "$REPO_DIR" rev-parse HEAD
if [ ! -x "$PYTHON" ]; then
  python3 -m venv "$ENV_DIR"
fi
# setuptools 81+ drops pkg_resources, which lightning still imports.
"$PYTHON" -m pip install --upgrade pip 'setuptools<81' wheel

# Pins prevent the NumPy 2 / torchvision mismatch that broke earlier attempts.
"$PYTHON" -m pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
"$PYTHON" -m pip install --no-cache-dir \
  numpy==1.26.4 astor==0.8.1 easydict einops-exts fvcore 'huggingface-hub[cli]<1.0' \
  hydra-core==1.3.2 igraph==0.11.8 lightning==2.3.3 loguru==0.7.2 matplotlib==3.9.2 \
  omegaconf open3d==0.19.0 optree==0.14.1 opencv-python-headless==4.9.0.80 pillow \
  plotly==5.24.1 plyfile pymeshfix==0.17.0 pyvista==0.44.2 roma==1.5.1 safetensors \
  scipy seaborn==0.13.2 timm==0.9.16 transformers==4.46.3 tqdm trimesh xatlas==0.0.9
# Hold these pins for every later install: unpinned git deps (utils3d, MoGe)
# otherwise pull NumPy 2 and huggingface-hub 1.x, breaking kaolin/transformers.
PIP_CONSTRAINT="$ROOT_DIR/pip-constraints.txt"
printf '%s\n' numpy==1.26.4 'huggingface-hub<1.0' 'setuptools<81' torch==2.5.1 torchvision==0.20.1 >"$PIP_CONSTRAINT"
export PIP_CONSTRAINT
PIP_FIND_LINKS=https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html \
  "$PYTHON" -m pip install --no-cache-dir kaolin==0.17.0 spconv-cu121==2.3.8
# pytorch3d and gsplat compile CUDA extensions that import torch at build time
# and require Python headers. Use --no-build-isolation so pip uses the venv's
# already-installed torch instead of a fresh isolated env that has none.
# CUB_HOME must point to NVIDIA CUB headers (bundled with CUDA on the DL AMI).
_CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
_CUB_HOME="${CUB_HOME:-$_CUDA_HOME/targets/x86_64-linux/include}"
CUDA_HOME="$_CUDA_HOME" CUB_HOME="$_CUB_HOME" \
  "$PYTHON" -m pip install --no-cache-dir --no-build-isolation \
  "git+https://github.com/facebookresearch/pytorch3d.git@75ebeeaea0908c5527e7b1e305fbc7681382db47"
"$PYTHON" -m pip install --no-cache-dir moderngl \
  "git+https://github.com/EasternJournalist/utils3d.git@3913c65d81e05e47b9f367250cf8c0f7462a0900#egg=utils3d" \
  "MoGe @ git+https://github.com/microsoft/MoGe.git@a8c37341bc0325ca99b9d57981cc3bb2bd3e255b"
CUDA_HOME="$_CUDA_HOME" CUB_HOME="$_CUB_HOME" \
  "$PYTHON" -m pip install --no-cache-dir --no-build-isolation \
  "gsplat @ git+https://github.com/nerfstudio-project/gsplat.git@2323de5905d5e90e035f792fe65bad0fedd413e7"

"$PYTHON" "$SOURCE_DIR/prepare_fastsam3d_source.py" "$REPO_DIR"
PIP_EXTRA_INDEX_URL='https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121' \
  "$PYTHON" "$REPO_DIR/patching/hydra"

if [ ! -f "$CHECKPOINT_DIR/slat_generator.ckpt" ]; then
  : "${HF_TOKEN:?Set an approved Hugging Face token only in this GPU job environment}"
  download_dir="$ROOT_DIR/checkpoints/download"
  if [ -e "$download_dir" ]; then
    echo "Refusing to reuse partial checkpoint download at $download_dir; move it aside, then retry." >&2
    exit 1
  fi
  HF_HOME="$HF_HOME" HF_TOKEN="$HF_TOKEN" "$ENV_DIR/bin/hf" download \
    --repo-type model --local-dir "$download_dir" --max-workers 1 facebook/sam-3d-objects
  mkdir -p "$(dirname "$CHECKPOINT_DIR")"
  mv "$download_dir/checkpoints/hf" "$CHECKPOINT_DIR"
fi
HF_HOME="$HF_HOME" "$ENV_DIR/bin/hf" download Ruicheng/moge-vitl --cache-dir "$HF_HOME" >/dev/null
HF_HOME="$HF_HOME" "$ENV_DIR/bin/hf" download facebook/sam-vit-base --cache-dir "$HF_HOME" >/dev/null

cd "$REPO_DIR"
HF_HOME="$HF_HOME" TORCH_HOME="$REPO_DIR/checkpoints/torch-cache" \
  "$PYTHON" -c '
import importlib
import numpy, torch
assert numpy.__version__ == "1.26.4"
for name in (
    "spconv",
    "pytorch3d",
    "kaolin",
    "gsplat",
    "moge.model.v1",
    "sam3d_objects.pipeline.inference_pipeline",
    "sam3d_objects.model.backbone.generator.shortcut.model",
):
    importlib.import_module(name)
print("Fast-SAM3D import preflight passed", torch.__version__, torch.version.cuda)
'
touch "$MARKER"
echo "Ready. Do not re-run this during a live demo."
