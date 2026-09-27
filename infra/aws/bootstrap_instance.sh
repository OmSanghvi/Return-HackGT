#!/usr/bin/env bash
# Run from an AWS SSM shell after publish_bundle.sh, with HF_TOKEN set only in
# that shell. It prepares both model stacks once and starts the local API.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo -E so the temporary HF_TOKEN remains available for gated downloads." >&2
  exit 1
fi

APP_DIR=/opt/sketchscape
APP_USER=ubuntu
RUNTIME_DIR="$APP_DIR/runtime"
test -d "$APP_DIR/backend" || { echo "Run publish_bundle.sh first." >&2; exit 1; }
command -v nvidia-smi >/dev/null 2>&1 || { echo "The selected AMI/instance has no NVIDIA driver." >&2; exit 1; }
nvidia-smi

# Pick the inference profile from GPU memory. A 16 GiB T4 needs the low-VRAM
# stage-by-stage profile; an L40S (g6e, ~46 GiB) keeps every model resident
# and spends the headroom on resolution and diffusion steps instead.
GPU_MEM_MIB="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')"
if [ "$GPU_MEM_MIB" -ge 40000 ]; then
  SAM31_IMAGE_SIZE=1008
  FASTSAM3D_MAX_INPUT_SIDE=768
  FASTSAM3D_STAGE1_STEPS=12
  FASTSAM3D_STAGE2_STEPS=12
  FASTSAM3D_KEEP_ON_GPU=1
else
  SAM31_IMAGE_SIZE=512
  FASTSAM3D_MAX_INPUT_SIDE=512
  FASTSAM3D_STAGE1_STEPS=8
  FASTSAM3D_STAGE2_STEPS=8
  FASTSAM3D_KEEP_ON_GPU=0
fi
echo "GPU memory ${GPU_MEM_MIB} MiB -> SAM ${SAM31_IMAGE_SIZE}px, Fast-SAM3D ${FASTSAM3D_MAX_INPUT_SIDE}px ${FASTSAM3D_STAGE1_STEPS}/${FASTSAM3D_STAGE2_STEPS} steps, resident=${FASTSAM3D_KEEP_ON_GPU}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y build-essential cmake ninja-build git curl libgl1 libglib2.0-0 python3.12-venv python3.12-dev

install -d -o "$APP_USER" -g "$APP_USER" "$RUNTIME_DIR" "$APP_DIR/data"
sudo -u "$APP_USER" python3.12 -m venv "$APP_DIR/backend/.venv"
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
sudo -u "$APP_USER" "$APP_DIR/backend/.venv/bin/pip" install boto3

# Fast-SAM3D and SAM 3.1 use different PyTorch/CUDA releases. Each bootstrap
# has an import preflight and a durable marker; rerunning after a failed setup
# repairs only the incomplete environment.
export FASTSAM3D_PERSIST_ROOT="$RUNTIME_DIR/fastsam3d"
export FASTSAM3D_REPO_DIR="$RUNTIME_DIR/fastsam3d/Fast-SAM3D"
export FASTSAM3D_ENV_DIR="$RUNTIME_DIR/fastsam3d/venv"
export FASTSAM3D_CHECKPOINT_DIR="$RUNTIME_DIR/fastsam3d/checkpoints/hf"
export HF_HOME="$RUNTIME_DIR/fastsam3d/huggingface-cache"
sudo -E -u "$APP_USER" bash "$APP_DIR/worker/bootstrap_fastsam3d.sh"
install -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_DIR/worker/run_fastsam3d_staged.py" "$FASTSAM3D_REPO_DIR/run_fastsam3d_staged.py"
# The staged runner imports this module, so it must sit next to the copy.
install -o "$APP_USER" -g "$APP_USER" -m 0644 "$APP_DIR/worker/gaussian_ply_safety.py" "$FASTSAM3D_REPO_DIR/gaussian_ply_safety.py"

export SAM31_PERSIST_ROOT="$RUNTIME_DIR/sam31"
export SAM31_ENV_DIR="$RUNTIME_DIR/sam31/venv"
export SAM31_MODEL_DIR="$RUNTIME_DIR/sam31/models"
export SAM31_PYTHON=python3.12
sudo -E -u "$APP_USER" bash "$APP_DIR/worker/bootstrap_sam31_local.sh"

ENV_FILE=/etc/sketchscape.env
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  WORKER_TOKEN="$(openssl rand -hex 32)"
  cat >"$ENV_FILE" <<EOF
PIPELINE_MODE=aws-local
SKETCHSCAPE_DATA_DIR=$APP_DIR/data
SKETCHSCAPE_API_URL=http://127.0.0.1:8000
SKETCHSCAPE_WORKER_TOKEN=$WORKER_TOKEN
SKETCHSCAPE_WORKER_SCRIPT=$APP_DIR/worker/run_job.py
SKETCHSCAPE_WORKER_PYTHON=$FASTSAM3D_ENV_DIR/bin/python
SKETCHSCAPE_WORK_DIR=$APP_DIR/data/jobs
SKETCHSCAPE_WORKER_SERVER_PORT=8001
SKETCHSCAPE_WORKER_STARTUP_TIMEOUT=600
# Build Plan step 27: shared by sketchscape-worker.service (so its result
# callbacks satisfy the API's lease-ownership check) and
# sketchscape-dispatcher.service (its own claim identity). One dispatcher
# per instance, so a fixed id is fine. SKETCHSCAPE_GPU_CONCURRENCY stays at
# 1 -- the only value verified safe on any instance type -- until an
# approved VRAM benchmark (worker/benchmark_concurrency.py) says otherwise
# for this specific instance type; record the result in docs/BUILD_PLAN.md
# step 27 (Hard Rule 5).
SKETCHSCAPE_WORKER_ID=gpu-host-1
SKETCHSCAPE_GPU_CONCURRENCY=1
# The dispatcher hands SAM 3.1 image *paths*, and its unit has PrivateTmp=true,
# so its work dir must live outside /tmp or SAM 3.1 can't see the files.
SKETCHSCAPE_DISPATCHER_WORK_DIR=$APP_DIR/data/dispatcher
SAM31_ENV_DIR=$SAM31_ENV_DIR
SAM31_MODEL_DIR=$SAM31_MODEL_DIR
SAM31_IMAGE_SIZE=$SAM31_IMAGE_SIZE
SAM31_FP16=1
SAM31_SERVER_URL=http://127.0.0.1:8002
FASTSAM3D_STAGED_RUNNER=$FASTSAM3D_REPO_DIR/run_fastsam3d_staged.py
FASTSAM3D_REPO_DIR=$FASTSAM3D_REPO_DIR
FASTSAM3D_CHECKPOINT_DIR=$FASTSAM3D_CHECKPOINT_DIR
FASTSAM3D_MAX_INPUT_SIDE=$FASTSAM3D_MAX_INPUT_SIDE
FASTSAM3D_STAGE1_STEPS=$FASTSAM3D_STAGE1_STEPS
FASTSAM3D_STAGE2_STEPS=$FASTSAM3D_STAGE2_STEPS
FASTSAM3D_SEED=42
# FP16 overflow was traced to ~28% of splats in a real reconstruction coming
# back with non-finite opacity (2026-09-26 GPU verification, see BUILD_PLAN.md
# step 11) -- FP32 avoids the overflow at the cost of more VRAM/time per job.
FASTSAM3D_FP16=0
FASTSAM3D_KEEP_ON_GPU=$FASTSAM3D_KEEP_ON_GPU
HF_HOME=$HF_HOME
TORCH_HOME=$FASTSAM3D_REPO_DIR/checkpoints/torch-cache
SKETCHSCAPE_AUTO_MASK_COMMAND="$SAM31_ENV_DIR/bin/python $APP_DIR/worker/segment_sam31_local.py --image {image} --output {mask} --prompt {prompt} --checkpoint $SAM31_MODEL_DIR/sam3.1_multiplex.pt"
SKETCHSCAPE_STORAGE_BACKEND=dynamodb
SKETCHSCAPE_DYNAMODB_TABLE=sketchscape-authoring
SKETCHSCAPE_ARTIFACTS_BACKEND=s3
SKETCHSCAPE_ARTIFACTS_BUCKET=sketchscape-artifacts-20260922133334256700000003
AWS_REGION=us-east-1
EOF
fi

# Preserve the generated worker token, but reconcile non-secret deployment
# settings on every bootstrap so an existing host does not silently keep stale
# performance values.
upsert_env() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >>"$ENV_FILE"
  fi
}
# Hosts created before the persistent worker existed have no token yet.
if ! grep -q '^SKETCHSCAPE_WORKER_TOKEN=.' "$ENV_FILE"; then
  upsert_env SKETCHSCAPE_WORKER_TOKEN "$(openssl rand -hex 32)"
fi
upsert_env PIPELINE_MODE aws-local
upsert_env SKETCHSCAPE_DATA_DIR "$APP_DIR/data"
upsert_env SKETCHSCAPE_API_URL http://127.0.0.1:8000
upsert_env SKETCHSCAPE_WORK_DIR "$APP_DIR/data/jobs"
upsert_env SKETCHSCAPE_WORKER_SERVER_PORT 8001
upsert_env SKETCHSCAPE_WORKER_STARTUP_TIMEOUT 600
# Hosts created before step 27 have neither var; a fixed dispatcher id is
# fine (one dispatcher per instance), concurrency stays at 1 until benchmarked.
if ! grep -q '^SKETCHSCAPE_WORKER_ID=.' "$ENV_FILE"; then
  upsert_env SKETCHSCAPE_WORKER_ID gpu-host-1
fi
if ! grep -q '^SKETCHSCAPE_GPU_CONCURRENCY=.' "$ENV_FILE"; then
  upsert_env SKETCHSCAPE_GPU_CONCURRENCY 1
fi
upsert_env SAM31_ENV_DIR "$SAM31_ENV_DIR"
upsert_env SAM31_MODEL_DIR "$SAM31_MODEL_DIR"
upsert_env SAM31_IMAGE_SIZE "$SAM31_IMAGE_SIZE"
upsert_env SAM31_FP16 1
upsert_env SAM31_SERVER_URL http://127.0.0.1:8002
upsert_env FASTSAM3D_STAGED_RUNNER "$FASTSAM3D_REPO_DIR/run_fastsam3d_staged.py"
upsert_env FASTSAM3D_REPO_DIR "$FASTSAM3D_REPO_DIR"
upsert_env FASTSAM3D_CHECKPOINT_DIR "$FASTSAM3D_CHECKPOINT_DIR"
upsert_env FASTSAM3D_MAX_INPUT_SIDE "$FASTSAM3D_MAX_INPUT_SIDE"
upsert_env FASTSAM3D_STAGE1_STEPS "$FASTSAM3D_STAGE1_STEPS"
upsert_env FASTSAM3D_STAGE2_STEPS "$FASTSAM3D_STAGE2_STEPS"
upsert_env FASTSAM3D_SEED 42
upsert_env FASTSAM3D_FP16 0
upsert_env FASTSAM3D_KEEP_ON_GPU "$FASTSAM3D_KEEP_ON_GPU"
upsert_env HF_HOME "$HF_HOME"
upsert_env TORCH_HOME "$FASTSAM3D_REPO_DIR/checkpoints/torch-cache"
upsert_env SKETCHSCAPE_STORAGE_BACKEND dynamodb
upsert_env SKETCHSCAPE_DYNAMODB_TABLE sketchscape-authoring
upsert_env SKETCHSCAPE_ARTIFACTS_BACKEND s3
upsert_env SKETCHSCAPE_ARTIFACTS_BUCKET sketchscape-artifacts-20260922133334256700000003
upsert_env AWS_REGION us-east-1
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

cat >/etc/systemd/system/sketchscape-sam31.service <<EOF
[Unit]
Description=SketchScape warm SAM 3.1 segmentation server (loopback only)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
Environment=HOME=/home/$APP_USER
EnvironmentFile=$ENV_FILE
ExecStart=$SAM31_ENV_DIR/bin/python $APP_DIR/worker/segment_sam31_local.py --serve --port 8002 --checkpoint $SAM31_MODEL_DIR/sam3.1_multiplex.pt
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/sketchscape-worker.service <<EOF
[Unit]
Description=SketchScape persistent Fast-SAM3D worker
After=network-online.target sketchscape-sam31.service
Wants=network-online.target sketchscape-sam31.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$FASTSAM3D_REPO_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$FASTSAM3D_ENV_DIR/bin/python $APP_DIR/worker/worker_server.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/sketchscape-dispatcher.service <<EOF
[Unit]
Description=SketchScape GPU-host job dispatcher (Build Plan step 27)
After=network-online.target sketchscape-sam31.service sketchscape-worker.service
Wants=network-online.target sketchscape-sam31.service sketchscape-worker.service

[Service]
Type=simple
User=$APP_USER
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/backend/.venv/bin/python3 $APP_DIR/worker/gpu_dispatcher.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/sketchscape.service <<EOF
[Unit]
Description=SketchScape single-GPU API
After=network-online.target sketchscape-worker.service
Wants=network-online.target sketchscape-worker.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/backend/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable sketchscape-sam31.service sketchscape-worker.service sketchscape-dispatcher.service sketchscape.service
systemctl restart sketchscape-sam31.service
systemctl restart sketchscape-worker.service
systemctl restart sketchscape-dispatcher.service
systemctl restart sketchscape.service
systemctl --no-pager --full status sketchscape-sam31.service
systemctl --no-pager --full status sketchscape-worker.service
systemctl --no-pager --full status sketchscape-dispatcher.service
systemctl --no-pager --full status sketchscape.service
echo "Bootstrap complete. Check readiness:"
echo "  curl http://127.0.0.1:8002/health          # SAM 3.1 (warm)"
echo "  curl http://127.0.0.1:8001/worker/health   # Fast-SAM3D"
echo "  journalctl -u sketchscape-dispatcher -f    # step 27 claim/lease loop"

# >>> gpu-scene: whole-photo scene capture (SHARP + MoGe-2 + GeoCalib) >>>
# Own venv under $RUNTIME_DIR/scene (Python 3.13 via uv); installs and starts
# sketchscape-scene.service on loopback :8004 (docs/IMMERSIVE_SCENE_PIPELINE.md 1b).
# Needs ~12 GB disk and <= 12 GB VRAM. Non-fatal: the rest of the stack works
# without it (scenes are simply not produced).
if SCENE_ROOT="$RUNTIME_DIR/scene" APP_USER="$APP_USER" APP_DIR="$APP_DIR" ENV_FILE=/etc/sketchscape.env \
     bash "$APP_DIR/worker/bootstrap_scene_capture.sh" --install-service; then
  echo "  curl http://127.0.0.1:8004/health          # scene capture (SHARP + MoGe-2)"
else
  echo "WARNING: scene capture bootstrap failed; see journalctl -u sketchscape-scene" >&2
fi
# <<< gpu-scene <<<

# ---- BEGIN gpu-vlm: sketchscape-vlm (Qwen3-VL vision server, loopback :8003) ----
# Names every object in a photo (auto-detect for uploads with no typed names)
# and writes the scene analysis (lighting, materials, mood). Own venv; ~9 GB
# VRAM resident (peak ~9.8 GB) next to Fast-SAM3D, SAM 3.1 and the scene
# service on the L40S. Clients: backend POST /v1/detect (SKETCHSCAPE_VLM_URL,
# default http://127.0.0.1:8003), worker POST /v1/analyze.
export VLM_PERSIST_ROOT="$RUNTIME_DIR/vlm"
export VLM_MODEL_ID="${VLM_MODEL_ID:-Qwen/Qwen3-VL-4B-Instruct}"
VLM_MODEL_DIR="$VLM_PERSIST_ROOT/models/$(basename "$VLM_MODEL_ID")"
# Host RAM safety: the resident GPU services use most of the 32 GB, so give
# the kernel a swapfile (keeping >= 5 GB of disk free) rather than let the OOM
# killer pick a service; the VLM itself is the preferred OOM victim below.
if [ -z "$(swapon --show --noheadings)" ] && [ ! -e /swapfile ]; then
  VLM_FREE_GB=$(df -BG --output=avail / | tail -1 | tr -dc 0-9)
  VLM_SWAP_GB=$(( VLM_FREE_GB - 5 )); [ "$VLM_SWAP_GB" -gt 6 ] && VLM_SWAP_GB=6
  if [ "$VLM_SWAP_GB" -ge 2 ]; then
    fallocate -l "${VLM_SWAP_GB}G" /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
fi
install -d -o "$APP_USER" -g "$APP_USER" "$VLM_PERSIST_ROOT"
sudo -E -u "$APP_USER" bash "$APP_DIR/worker/bootstrap_vlm.sh"
cat >/etc/systemd/system/sketchscape-vlm.service <<EOF_VLM
[Unit]
Description=SketchScape GPU vision-language server (Qwen3-VL, loopback :8003)
After=network-online.target sketchscape-sam31.service sketchscape-worker.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR/worker
EnvironmentFile=$ENV_FILE
Environment=HF_HUB_OFFLINE=1
Environment=HF_HOME=$VLM_PERSIST_ROOT/huggingface-cache
Environment=TRANSFORMERS_VERBOSITY=error
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
Environment=VLM_MODEL_ID=$(basename "$VLM_MODEL_ID")
ExecStart=$VLM_PERSIST_ROOT/venv/bin/python $APP_DIR/worker/vlm_server.py --serve --host 127.0.0.1 --port 8003 --model $VLM_MODEL_DIR
Restart=on-failure
RestartSec=10
OOMScoreAdjust=800
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF_VLM
systemctl daemon-reload
systemctl enable sketchscape-vlm.service
systemctl restart sketchscape-vlm.service
echo "  curl http://127.0.0.1:8003/health          # Qwen3-VL vision server (loads in ~1-3 min)"
# ---- END gpu-vlm ----
