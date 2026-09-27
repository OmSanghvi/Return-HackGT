#!/usr/bin/env bash
# Install the whole-photo scene capture stack (worker/scene_capture.py) into
# its OWN environment: Apple SHARP (single image -> 3D Gaussians), Microsoft
# MoGe-2 (metric pointmap + intrinsics + normals) and GeoCalib (gravity prior).
# It never touches the Fast-SAM3D or SAM 3.1 venvs.
#
#   sudo SCENE_ROOT=/opt/sketchscape/runtime/scene APP_USER=ubuntu \
#        bash worker/bootstrap_scene_capture.sh [--install-service]
#
# --install-service also installs and (re)starts sketchscape-scene.service
# (loopback 127.0.0.1:8004, runs $APP_DIR/worker/scene_capture.py --serve)
# and waits for /health.
#
# Idempotent: re-running with everything present only runs the preflight.
# Needs: NVIDIA driver (CUDA 12.8+), git, curl, internet (GitHub, PyPI,
# download.pytorch.org, huggingface.co, ml-site.cdn-apple.com). ~12 GB disk.
set -euo pipefail

SCENE_ROOT="${SCENE_ROOT:-/opt/sketchscape/runtime/scene}"
APP_USER="${APP_USER:-ubuntu}"
APP_DIR="${APP_DIR:-/opt/sketchscape}"
ENV_FILE="${ENV_FILE:-/etc/sketchscape.env}"
ENV_DIR="$SCENE_ROOT/venv"
SRC_DIR="$SCENE_ROOT/src"
MODEL_DIR="$SCENE_ROOT/models"
HF_CACHE="$SCENE_ROOT/huggingface-cache"
TORCH_CACHE="$SCENE_ROOT/torch-cache"
PY_VERSION="${SCENE_PYTHON_VERSION:-3.13}"
TORCH_INDEX="${SCENE_TORCH_INDEX:-https://download.pytorch.org/whl/cu128}"
SHARP_REPO="https://github.com/apple/ml-sharp.git"
SHARP_URL="https://ml-site.cdn-apple.com/models/sharp/sharp_2572gikvuh.pt"
MOGE_REPO="https://github.com/microsoft/MoGe.git"
MOGE_MODEL="Ruicheng/moge-2-vitl-normal"
GEOCALIB_PIN="97b8968e7798a66bf04fcf791fb535624241bda7"
SHARP_PIN="${SHARP_PIN:-aed6527499ef91cba3b54c18d49a870f25947190}"
MOGE_PIN="${MOGE_PIN:-74fbce054ebed49800de42d0ad0e83495065719a}"
MARKER="$SCENE_ROOT/.scene-ready-v1"
INSTALL_SERVICE=0
[ "${1:-}" = "--install-service" ] && INSTALL_SERVICE=1

command -v nvidia-smi >/dev/null 2>&1 || { echo "A CUDA GPU is required." >&2; exit 1; }
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
mkdir -p "$SRC_DIR" "$MODEL_DIR" "$HF_CACHE" "$TORCH_CACHE"
chown -R "$APP_USER:$APP_USER" "$SCENE_ROOT"

as_app() {
  sudo -u "$APP_USER" -H env HF_HOME="$HF_CACHE" TORCH_HOME="$TORCH_CACHE" \
    UV_PYTHON_INSTALL_DIR="$SCENE_ROOT/python" bash -lc "$1"
}

preflight() {
  as_app "'$ENV_DIR/bin/python' - <<'PY'
import torch
from sharp.models import PredictorParams, create_predictor  # noqa: F401
from moge.model.v2 import MoGeModel  # noqa: F401
from geocalib import GeoCalib  # noqa: F401
import cv2, scipy, PIL, numpy, boto3  # noqa: F401
assert torch.cuda.is_available(), 'CUDA unavailable in the scene env'
print('scene env ready', torch.__version__, torch.version.cuda)
PY"
}

install_service() {
  install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR/data/scene-cache" "$APP_DIR/data/scene-backfill"
  # EnvironmentFile= overrides Environment=, and the shared env file points
  # HF_HOME/TORCH_HOME at Fast-SAM3D, so the caches are set on the command line.
  local unit=/etc/systemd/system/sketchscape-scene.service
  {
    echo "[Unit]"
    echo "Description=SketchScape warm scene capture (SHARP + MoGe-2 + GeoCalib, loopback :8004)"
    echo "After=network-online.target"
    echo "Wants=network-online.target"
    echo
    echo "[Service]"
    echo "Type=simple"
    echo "User=$APP_USER"
    echo "WorkingDirectory=$APP_DIR/worker"
    echo "EnvironmentFile=$ENV_FILE"
    echo "ExecStart=/usr/bin/env HF_HOME=$HF_CACHE TORCH_HOME=$TORCH_CACHE SKETCHSCAPE_SCENE_ROOT=$SCENE_ROOT SKETCHSCAPE_SCENE_CACHE=$APP_DIR/data/scene-cache SKETCHSCAPE_SCENE_VRAM_GB=12 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True $ENV_DIR/bin/python $APP_DIR/worker/scene_capture.py --serve --host 127.0.0.1 --port 8004"
    echo "Restart=on-failure"
    echo "RestartSec=10"
    echo "NoNewPrivileges=true"
    echo "PrivateTmp=true"
    echo
    echo "[Install]"
    echo "WantedBy=multi-user.target"
  } > "$unit"
  systemctl daemon-reload
  systemctl enable sketchscape-scene.service
  systemctl restart sketchscape-scene.service
  for _ in $(seq 1 100); do
    if curl -fsS http://127.0.0.1:8004/health; then echo; return 0; fi
    sleep 3
  done
  echo "sketchscape-scene did not become healthy" >&2
  journalctl -u sketchscape-scene --no-pager -n 40 >&2
  return 1
}

if [ -f "$MARKER" ] && [ -x "$ENV_DIR/bin/python" ] && [ -f "$MODEL_DIR/sharp_2572gikvuh.pt" ]; then
  preflight
  if [ "$INSTALL_SERVICE" = 1 ]; then install_service; fi
  exit 0
fi

# Sources, pinned to the commits verified on 2026-09-26 (override with *_PIN).
clone_pinned() {  # repo dir pin
  [ -d "$2/.git" ] || as_app "git clone --depth 1 $1 '$2'"
  as_app "git -C '$2' fetch --depth 1 origin $3 && git -C '$2' checkout -q $3"
}
clone_pinned "$SHARP_REPO" "$SRC_DIR/ml-sharp" "$SHARP_PIN"
clone_pinned "$MOGE_REPO" "$SRC_DIR/MoGe" "$MOGE_PIN"
as_app "git -C '$SRC_DIR/ml-sharp' rev-parse HEAD > '$SCENE_ROOT/ml-sharp.commit'; git -C '$SRC_DIR/MoGe' rev-parse HEAD > '$SCENE_ROOT/moge.commit'"

# Python 3.13 (SHARP's documented version) managed by uv, local to SCENE_ROOT.
if [ ! -x "$ENV_DIR/bin/python" ]; then
  as_app "uv python install $PY_VERSION && uv venv --python $PY_VERSION '$ENV_DIR'"
fi
PIP="uv pip install --python '$ENV_DIR/bin/python'"
as_app "$PIP torch torchvision --index-url $TORCH_INDEX"
# SHARP and its deps (gsplat is only used by SHARP's own renderer).
as_app "$PIP -e '$SRC_DIR/ml-sharp' --index-strategy unsafe-best-match --extra-index-url $TORCH_INDEX"
# MoGe: HEAD is MoGe-3, whose extra deps (flex-gemm, gradio) the v2 model does
# not need. Install the package without deps plus what v2 inference uses.
as_app "$PIP --no-deps -e '$SRC_DIR/MoGe'"
as_app "$PIP 'numpy>=2' opencv-python-headless scipy pillow huggingface-hub trimesh click tqdm requests boto3 'utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@62f09d58509485564e24d5d9f6aac9ee9ebc0c37' 'pipeline @ git+https://github.com/EasternJournalist/pipeline.git@1c511390d90226c00c101f34b84df26a0f8789b4'"
# GeoCalib pulls full opencv-python, which clashes with the headless build
# (both own cv2): keep only the headless one.
as_app "$PIP 'geocalib @ git+https://github.com/cvg/GeoCalib.git@$GEOCALIB_PIN'"
as_app "uv pip uninstall --python '$ENV_DIR/bin/python' opencv-python || true"
as_app "$PIP --reinstall opencv-python-headless"

# Weights: SHARP (Apple CDN), MoGe-2 (Hugging Face), GeoCalib (GitHub release).
if [ ! -f "$MODEL_DIR/sharp_2572gikvuh.pt" ]; then
  as_app "curl -fsSL --retry 3 -o '$MODEL_DIR/sharp_2572gikvuh.pt.part' '$SHARP_URL' && mv '$MODEL_DIR/sharp_2572gikvuh.pt.part' '$MODEL_DIR/sharp_2572gikvuh.pt'"
fi
as_app "'$ENV_DIR/bin/python' -c \"from huggingface_hub import snapshot_download; print(snapshot_download('$MOGE_MODEL'))\""
as_app "'$ENV_DIR/bin/python' -c 'from geocalib import GeoCalib; GeoCalib()'"

preflight
touch "$MARKER"
echo "Scene capture environment ready in $SCENE_ROOT"
if [ "$INSTALL_SERVICE" = 1 ]; then install_service; fi
exit 0
