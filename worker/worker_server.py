#!/usr/bin/env python3
"""Persistent Fast-SAM3D worker server.

Loads all models ONCE at startup, then accepts reconstruction jobs over a
simple HTTP interface on loopback. This eliminates the 2–3 minute cold-start
penalty from loading large checkpoints from disk on every job.

The worker server runs as a separate process alongside the FastAPI backend.
The backend's aws-local pipeline mode sends jobs to it; the worker posts
results back via the standard private callback endpoint.

Startup:  ~2–3 min (one-time model load)
Per-job:  ~35–60s on T4, ~20–35s on A10G (GPU compute only, no disk I/O)

Endpoints (loopback only, never exposed publicly):
  POST /worker/jobs   { job_id, subject_hint }  → 202 { status: queued }
  GET  /worker/health                           → 200 { status, models_loaded }
  GET  /worker/status/{job_id}                  → 200 { status, error? }
"""

from __future__ import annotations

import gc
import http.client
import json
import logging
import math
import mimetypes
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [worker] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("worker")


def required(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


API_URL = required("SKETCHSCAPE_API_URL").rstrip("/")
WORKER_TOKEN = required("SKETCHSCAPE_WORKER_TOKEN")
REPO_DIR = Path(required("FASTSAM3D_REPO_DIR"))
# sam3d_objects is imported from the source checkout, not an installed package.
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))
CHECKPOINT_DIR = Path(required("FASTSAM3D_CHECKPOINT_DIR"))
HF_HOME = os.environ.get("HF_HOME", str(REPO_DIR / "huggingface-cache"))
TORCH_HOME = os.environ.get("TORCH_HOME", str(REPO_DIR / "checkpoints/torch-cache"))
SAM31_ENV_DIR = Path(os.environ.get("SAM31_ENV_DIR", "/opt/sketchscape/runtime/sam31/venv"))
SAM31_MODEL = Path(os.environ.get("SAM31_MODEL_DIR", "/opt/sketchscape/runtime/sam31/models")) / "sam3.1_multiplex.pt"
WORK_DIR = Path(os.environ.get("SKETCHSCAPE_WORK_DIR", "/tmp/sketchscape-jobs"))
WORKER_PORT = int(os.environ.get("SKETCHSCAPE_WORKER_SERVER_PORT", "8001"))
MAX_SIDE = int(os.environ.get("FASTSAM3D_MAX_INPUT_SIDE", "512"))
STAGE1_STEPS = int(os.environ.get("FASTSAM3D_STAGE1_STEPS", "8"))
STAGE2_STEPS = int(os.environ.get("FASTSAM3D_STAGE2_STEPS", "8"))
SEED = int(os.environ.get("FASTSAM3D_SEED", "42"))
USE_FP16 = os.environ.get("FASTSAM3D_FP16", "1").strip().lower() not in {"0", "false", "no"}
# fp16 matches the validated Kaggle/T4 run; bf16 is available on Ampere+ GPUs.
AMP_DTYPE = os.environ.get("FASTSAM3D_AMP_DTYPE", "fp16").strip().lower()
# On a large-VRAM GPU (L40S, 46 GB) every stage fits at once. Keeping models
# resident skips several GB of CPU<->GPU copies per job; T4-class hosts keep
# the stage-by-stage offload.
KEEP_ON_GPU = os.environ.get("FASTSAM3D_KEEP_ON_GPU", "0").strip().lower() in {"1", "true", "yes"}
# Optional warm SAM 3.1 server (segment_sam31_local.py --serve). When it is
# unreachable the worker falls back to a one-shot SAM 3.1 subprocess.
SAM31_SERVER_URL = os.environ.get("SAM31_SERVER_URL", "").strip().rstrip("/")
# Build Plan step 27: how many `reconstruct` jobs this server accepts at
# once. Default 1 -- the ONLY value verified safe on any instance type. The
# stage-by-stage GPU offload below (`move`/`offload`) shares one `_pipeline`
# across whatever runs concurrently, so raising this past 1 is unverified
# and unsafe until an approved VRAM benchmark (Hard Rule 5, gpu-multi-object-
# worker skill item 5) proves the combined peak stays under 90% of VRAM on
# the actual instance type; a T4 (16 GB) always stays at 1. See
# worker/benchmark_concurrency.py for the (not-yet-run) benchmark hook.
GPU_CONCURRENCY = max(1, int(os.environ.get("SKETCHSCAPE_GPU_CONCURRENCY", "1")))
# Matches the GPU-host dispatcher's own worker_id (worker/gpu_dispatcher.py),
# so this server's result callbacks satisfy the API's lease-ownership check
# for jobs the dispatcher claimed through POST /v1/internal/jobs/claim. Empty
# (default) preserves the legacy same-host push path, whose jobs never have
# a lease_owner, so the API's ownership check is a no-op either way.
WORKER_ID = os.environ.get("SKETCHSCAPE_WORKER_ID", "").strip() or None

# ---------------------------------------------------------------------------
# Global pipeline (loaded once at startup)
# ---------------------------------------------------------------------------

_pipeline = None
_pipeline_ready = threading.Event()
_pipeline_error: str | None = None
_job_queue: queue.Queue = queue.Queue(maxsize=GPU_CONCURRENCY)
_job_status: dict[str, dict] = {}
_job_lock = threading.Lock()


def _download_input(job_id: str, kind: str, destination: Path, *, optional: bool = False) -> bool:
    request = Request(
        f"{API_URL}/v1/internal/reconstructions/{job_id}/input/{kind}",
        headers={"X-SketchScape-Worker-Token": WORKER_TOKEN},
    )
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        return True
    except HTTPError as error:
        if optional and error.code == 404:
            return False
        raise


def _load_pipeline():
    global _pipeline, _pipeline_error
    try:
        # These switches are read while Fast-SAM3D modules import, so they must
        # be present before importing InferencePipeline.
        os.environ.update({
            "ATTN_BACKEND": "sdpa",
            "SPARSE_ATTN_BACKEND": "sdpa",
            "CUMM_DISABLE_JIT": "1",
            "SPCONV_DISABLE_JIT": "1",
            "LIDRA_SKIP_INIT": "true",
            "TORCH_HOME": TORCH_HOME,
            "HF_HOME": HF_HOME,
        })

        import torch
        from hydra.utils import instantiate
        from omegaconf import OmegaConf
        from sam3d_objects.pipeline.inference_pipeline import InferencePipeline
        torch.backends.cudnn.benchmark = True

        log.info("Loading pipeline config...")
        InferencePipeline.init_slat_decoder_mesh = lambda self, *a, **kw: None

        def gaussian_only_decode(self, map_tokens, slat, formats):
            with torch.no_grad():
                return {"gaussian": self.models["slat_decoder_gs"](slat)}

        InferencePipeline.decode_slat = gaussian_only_decode

        config = OmegaConf.load(REPO_DIR / "checkpoints/hf/pipeline.yaml")
        config.workspace_dir = str(CHECKPOINT_DIR)
        config.device = "cpu"
        config.depth_model.device = "cpu"
        config.depth_model.model.pretrained_model_name_or_path = "Ruicheng/moge-vitl"
        config.compile_model = False
        config.decode_formats = ["gaussian"]
        config.slat_decoder_gs_4_config_path = None
        config.slat_decoder_gs_4_ckpt_path = None
        config.slat_decoder_mesh_config_path = None
        config.slat_decoder_mesh_ckpt_path = None
        config.ss_decoder_config_path = str(REPO_DIR / "checkpoints/hf/ss_decoder.yaml")
        config.slat_decoder_gs_config_path = str(REPO_DIR / "checkpoints/hf/slat_decoder_gs.yaml")
        config.ss_generator_config_path = str(REPO_DIR / "checkpoints/hf/ss_generator_faster.yaml")
        config.slat_generator_config_path = str(REPO_DIR / "checkpoints/hf/slat_generator_faster.yaml")

        log.info("Instantiating pipeline (loading checkpoints ~2 min)...")
        t0 = time.time()
        p = instantiate(config)
        log.info(f"Pipeline loaded in {time.time()-t0:.1f}s")

        gpu = torch.device("cuda:0")
        p.device = gpu
        p.ss_params = {"ss_faster_stride": 3, "ss_warmup": 2, "ss_order": 1, "ss_momentum_beta": 0.5}
        p.slat_params = {"slat_thresh": 1.5, "slat_warmup": 3, "slat_token_ratio": 0.1}
        p.mesh_params, p.enable_mesh, p.hfer_2d = {}, False, 0.0
        token_args = p.models["slat_generator"].args
        token_args.effective_steps = STAGE2_STEPS
        token_args.full_sampling_end_steps = math.ceil(STAGE2_STEPS * 0.75)
        token_args.anchor_step = max(1, math.floor(STAGE2_STEPS * 0.2))

        if USE_FP16:
            # MoGe is pure PyTorch and safe to cast once, not on every job.
            p.depth_model.model.half()
        if KEEP_ON_GPU:
            t0 = time.time()
            p.depth_model.model.to(gpu)
            p.depth_model.device = gpu
            for model in p.models.values():
                if model is not None:
                    model.to(gpu)
            for embedder in getattr(p, "condition_embedders", {}).values():
                if embedder is not None:
                    embedder.to(gpu)
            log.info(
                "All models resident on GPU in %.1fs (allocated=%.2fGB)",
                time.time() - t0,
                torch.cuda.memory_allocated() / 2**30,
            )

        _pipeline = p
        _pipeline_ready.set()
        log.info("Pipeline ready — worker accepting jobs.")
    except Exception as exc:
        _pipeline_error = str(exc)
        _pipeline_ready.set()
        log.exception("Pipeline load failed: %s", exc)
        # A loaded-but-unhealthy HTTP process would make systemd think the
        # worker is healthy forever. Exit so Restart=on-failure can recover.
        os._exit(1)


# ---------------------------------------------------------------------------
# Job runner (runs in a dedicated thread, one job at a time)
# ---------------------------------------------------------------------------

def _run_one_job(job_id: str, subject_hint: str) -> None:
    import numpy as np
    import torch
    from PIL import Image

    with _job_lock:
        _job_status[job_id] = {"status": "running"}

    gpu, cpu = torch.device("cuda:0"), torch.device("cpu")
    work = WORK_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)
    image_path = work / "image.png"
    mask_path = work / "mask.png"
    output_dir = work / "output"
    output_dir.mkdir(exist_ok=True)
    restart_after_job = False

    try:
        # 1. Pull image and an optional user-provided mask from the API.
        log.info("[%s] Fetching inputs...", job_id[:8])
        _download_input(job_id, "image", image_path)
        has_mask = _download_input(job_id, "mask", mask_path, optional=True)

        # 2. Generate a mask only when the user did not provide one. Never
        # replace a missing concept with a guessed generic prompt.
        if not has_mask:
            if not subject_hint.strip():
                _report(job_id, "mask_review", label="unknown")
                with _job_lock:
                    _job_status[job_id] = {"status": "mask_review"}
                return

            log.info("[%s] Running SAM 3.1 segmentation...", job_id[:8])
            t0 = time.monotonic()
            returncode = _segment_via_server(image_path, mask_path, subject_hint.strip())
            if returncode is None:
                returncode = _segment_via_subprocess(image_path, mask_path, subject_hint.strip())
            log.info(
                "[%s] SAM 3.1: %.1fs (exit=%s)",
                job_id[:8],
                time.monotonic() - t0,
                returncode,
            )

            if returncode == 2 or not mask_path.is_file():
                _report(job_id, "mask_review", label="unknown")
                with _job_lock:
                    _job_status[job_id] = {"status": "mask_review"}
                return
            if returncode:
                raise RuntimeError(f"SAM 3.1 exited with status {returncode}.")

        # 3. Fast-SAM3D reconstruction using the already-loaded pipeline
        log.info(f"[{job_id[:8]}] Running Fast-SAM3D (models already in memory)...")
        t0 = time.time()
        amp = torch.autocast(
            "cuda",
            dtype=torch.bfloat16 if AMP_DTYPE == "bf16" else torch.float16,
            enabled=USE_FP16,
        )

        image = np.asarray(Image.open(image_path).convert("RGB"))
        mask = np.asarray(Image.open(mask_path).convert("L")) > 127
        if image.shape[:2] != mask.shape[:2]:
            raise ValueError("Image and mask dimensions must match.")
        if not mask.any():
            raise ValueError("Segmentation mask is empty.")
        h, w = image.shape[:2]
        if max(h, w) > MAX_SIDE:
            scale = MAX_SIDE / max(h, w)
            size = (round(w * scale), round(h * scale))
            image = np.asarray(Image.fromarray(image).resize(size, Image.Resampling.LANCZOS))
            mask = np.asarray(
                Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
            ) > 127
        rgba = np.concatenate([image, (mask.astype(np.uint8) * 255)[..., None]], axis=-1)

        def move(names):
            if KEEP_ON_GPU:
                return
            for n in names:
                try:
                    m = _pipeline.models[n]
                    if m is not None:
                        m.to(gpu)
                except (KeyError, AttributeError):
                    pass
                conditioner_key = {"ss_generator": "ss_condition_embedder",
                                   "slat_generator": "slat_condition_embedder"}.get(n, "")
                try:
                    c = _pipeline.condition_embedders[conditioner_key]
                    if c is not None:
                        c.to(gpu)
                except (KeyError, AttributeError):
                    pass

        def offload(names):
            if KEEP_ON_GPU:
                return
            for n in names:
                try:
                    m = _pipeline.models[n]
                    if m is not None:
                        m.to(cpu)
                except (KeyError, AttributeError):
                    pass
                conditioner_key = {"ss_generator": "ss_condition_embedder",
                                   "slat_generator": "slat_condition_embedder"}.get(n, "")
                try:
                    c = _pipeline.condition_embedders[conditioner_key]
                    if c is not None:
                        c.to(cpu)
                except (KeyError, AttributeError):
                    pass
            gc.collect()
            torch.cuda.empty_cache()

        # MoGe depth — autocast only around the ViT forward pass, not
        # around pytorch3d's look_at_view_transform which creates float32
        # tensors internally and breaks under autocast context.
        _pipeline.depth_model.model.to(gpu)
        _pipeline.depth_model.device = gpu
        t_moge = time.time()
        with torch.inference_mode():
            pointmap = _pipeline.compute_pointmap(rgba)["pointmap"]
        if not KEEP_ON_GPU:
            _pipeline.depth_model.model.to(cpu)
            gc.collect()
            torch.cuda.empty_cache()
        log.info(f"[{job_id[:8]}] MoGe done {time.time()-t_moge:.1f}s")

        # Sparse structure
        ss_input = _pipeline.preprocess_image(rgba, _pipeline.ss_preprocessor, pointmap=pointmap)
        del pointmap
        move(("ss_generator", "ss_decoder"))
        torch.manual_seed(SEED)
        t1 = time.time()
        with torch.inference_mode(), amp:
            ss_return, map_tokens, coords_scores = _pipeline.sample_sparse_structure(
                ss_input, inference_steps=STAGE1_STEPS)
        log.info(f"[{job_id[:8]}] SS done {time.time()-t1:.1f}s")
        with torch.inference_mode():
            ss_return.update(_pipeline.pose_decoder(
                ss_return,
                scene_scale=ss_input.get("pointmap_scale"),
                scene_shift=ss_input.get("pointmap_shift"),
            ))
        ss_return["scale"] = ss_return["scale"].clone() * ss_return["downsample_factor"]
        coords = ss_return["coords"]
        offload(("ss_generator", "ss_decoder"))
        del ss_input, ss_return

        # SLaT
        slat_input = _pipeline.preprocess_image(rgba, _pipeline.slat_preprocessor)
        move(("slat_generator",))
        t1 = time.time()
        with torch.inference_mode(), amp:
            slat = _pipeline.sample_slat(
                slat_input,
                coords,
                inference_steps=STAGE2_STEPS,
                map_tokens=map_tokens,
                coords_scores=coords_scores,
            )
        log.info(f"[{job_id[:8]}] SLaT done {time.time()-t1:.1f}s")
        offload(("slat_generator",))
        del slat_input, coords, map_tokens, coords_scores

        # Decode
        move(("slat_decoder_gs",))
        with torch.inference_mode(), amp:
            gaussian = _pipeline.decode_slat(None, slat, ["gaussian"])["gaussian"][0]
        offload(("slat_decoder_gs",))

        ply_path = output_dir / "fastsam3d_reconstruction.ply"
        gaussian.save_ply(ply_path)
        del gaussian, slat
        gc.collect()
        torch.cuda.empty_cache()
        log.info(
            "[%s] Total Fast-SAM3D: %.1fs PLY: %sKB idle_cuda=%.2fGB",
            job_id[:8],
            time.time() - t0,
            ply_path.stat().st_size // 1024,
            torch.cuda.memory_allocated() / 2**30,
        )

        _report(job_id, "complete",
                label=subject_hint or "gaussian_splat",
                files={"ply": ply_path, "mask": mask_path})
        with _job_lock:
            _job_status[job_id] = {"status": "complete"}

    except Exception as exc:
        restart_after_job = isinstance(exc, torch.cuda.OutOfMemoryError)
        log.exception("[%s] Job failed: %s", job_id[:8], exc)
        try:
            _report(job_id, "failed", error=str(exc)[:500])
        except Exception:
            log.exception("[%s] Failed to report job failure", job_id[:8])
        with _job_lock:
            _job_status[job_id] = {"status": "failed", "error": str(exc)[:500]}
    finally:
        # Return every model to CPU even when a stage fails midway. A CUDA OOM
        # can leave library state unreliable, so restart after reporting it.
        try:
            if _pipeline is not None and not (KEEP_ON_GPU and not restart_after_job):
                _pipeline.depth_model.model.to(cpu)
                _pipeline.depth_model.device = cpu
                for model in _pipeline.models.values():
                    if model is not None:
                        model.to(cpu)
                for name in list(getattr(_pipeline, "condition_embedders", {}).keys()):
                        try:
                            c = _pipeline.condition_embedders[name]
                            if c is not None:
                                c.to(cpu)
                        except (KeyError, AttributeError):
                            pass
            gc.collect()
            torch.cuda.empty_cache()
            log.info(
                "[%s] GPU cleanup complete; allocated=%.2fGB",
                job_id[:8],
                torch.cuda.memory_allocated() / 2**30,
            )
        except Exception:
            log.exception("[%s] GPU cleanup failed", job_id[:8])
            restart_after_job = True
        if restart_after_job:
            log.error("[%s] Restarting worker after CUDA failure", job_id[:8])
            os._exit(1)


def _segment_via_server(image_path: Path, mask_path: Path, prompt: str) -> int | None:
    """Ask the warm SAM 3.1 server for a mask; None means use the subprocess."""
    if not SAM31_SERVER_URL:
        return None
    body = json.dumps({"image": str(image_path), "output": str(mask_path), "prompt": prompt}).encode()
    request = Request(
        f"{SAM31_SERVER_URL}/segment",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            return int(json.loads(response.read())["code"])
    except Exception as exc:
        log.warning("SAM 3.1 server unavailable (%s); using one-shot subprocess", exc)
        return None


def _segment_via_subprocess(image_path: Path, mask_path: Path, prompt: str) -> int:
    seg_cmd = [
        str(SAM31_ENV_DIR / "bin/python"),
        str(Path(__file__).parent / "segment_sam31_local.py"),
        "--image", str(image_path),
        "--output", str(mask_path),
        "--prompt", prompt,
        "--checkpoint", str(SAM31_MODEL),
    ]
    return subprocess.run(
        seg_cmd,
        timeout=180,
        env={**os.environ, "HOME": "/home/ubuntu"},
    ).returncode


def _job_worker_thread():
    while True:
        job_id, hint = _job_queue.get()
        try:
            _run_one_job(job_id, hint)
        except Exception as exc:
            log.error(f"Unhandled error in job {job_id}: {exc}")
        finally:
            _job_queue.task_done()


def _report(job_id: str, status: str, *, label: str = "gaussian_splat",
             error: str | None = None, files: dict | None = None) -> None:
    """Stream callbacks so a large PLY is never duplicated in host memory."""
    target = urlparse(f"{API_URL}/v1/internal/reconstructions/{job_id}/result")
    if target.scheme not in {"http", "https"} or not target.hostname:
        raise RuntimeError(f"Invalid API URL: {API_URL}")

    boundary = f"----SketchScape{uuid.uuid4().hex}"

    def field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode()

    payload = json.dumps({
        "status": status,
        "object_label": label,
        **({"error": error} if error else {}),
    })
    pieces: list[tuple[bytes, Path | None]] = [
        (field("worker_token", WORKER_TOKEN), None),
        (field("result", payload), None),
    ]
    if WORKER_ID:
        # Required when the job was claimed through the lease queue (Build
        # Plan step 27's dispatcher); harmless for the legacy same-host push
        # path, whose jobs have no lease_owner for the API to check against.
        pieces.append((field("worker_id", WORKER_ID), None))
    for name, path in (files or {}).items():
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        prefix = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        pieces.append((prefix, path))

    closing = f"--{boundary}--\r\n".encode()
    content_length = sum(
        len(prefix) + (path.stat().st_size + 2 if path else 0)
        for prefix, path in pieces
    ) + len(closing)
    connection_type = (
        http.client.HTTPSConnection if target.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_type(target.hostname, target.port, timeout=300)
    try:
        connection.putrequest("POST", target.path)
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.endheaders()
        for prefix, path in pieces:
            connection.send(prefix)
            if path:
                with path.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        connection.send(block)
                connection.send(b"\r\n")
        connection.send(closing)
        response = connection.getresponse()
        body = response.read().decode(errors="replace")
        if response.status >= 300:
            raise RuntimeError(f"Worker callback failed ({response.status}): {body}")
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.debug(fmt % args)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/worker/health":
            ready = _pipeline_ready.is_set()
            body = json.dumps({
                "status": "ready" if (ready and not _pipeline_error) else
                          "error" if _pipeline_error else "loading",
                "models_loaded": _pipeline is not None,
                "error": _pipeline_error,
                "queue_size": _job_queue.qsize(),
                "gpu_concurrency": GPU_CONCURRENCY,
                "worker_id": WORKER_ID,
            }).encode()
            self._respond(200, body)
        elif path.startswith("/worker/status/"):
            job_id = path.split("/")[-1]
            with _job_lock:
                info = _job_status.get(job_id, {"status": "unknown"})
            self._respond(200, json.dumps(info).encode())
        else:
            self._respond(404, b"not found")

    def do_POST(self):
        if self.path != "/worker/jobs":
            self._respond(404, b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 16 * 1024:
                raise ValueError("invalid content length")
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._respond(400, b'{"error":"invalid JSON request"}')
            return
        job_id = str(body.get("job_id", "")).strip()
        hint = str(body.get("subject_hint", "") or "").strip()
        if not job_id:
            self._respond(400, b'{"error":"missing job_id"}')
            return
        with _job_lock:
            if job_id in _job_status:
                self._respond(409, b'{"error":"job already submitted"}')
                return
        if not _pipeline_ready.is_set() or _pipeline_error:
            self._respond(503, b'{"error":"models not ready"}')
            return
        try:
            _job_queue.put_nowait((job_id, hint))
            with _job_lock:
                _job_status[job_id] = {"status": "queued"}
            self._respond(202, json.dumps({"status": "queued", "job_id": job_id}).encode())
        except queue.Full:
            self._respond(429, b'{"error":"worker busy"}')

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    # Load models in background thread so HTTP server starts immediately
    threading.Thread(target=_load_pipeline, daemon=True, name="pipeline-loader").start()
    # Job execution: always exactly one runner thread. GPU_CONCURRENCY only
    # sizes the accept queue above (how many jobs may sit queued instead of
    # getting 429); `_run_one_job` mutates the shared `_pipeline`'s GPU/CPU
    # placement (`move`/`offload`) with no lock, so actually running two
    # reconstructions at once needs a benchmarked, pipeline-isolated change
    # this server does not yet have (Hard Rule 5) -- raising the queue size
    # alone is safe (jobs still run one at a time) but gives no throughput
    # benefit until that work lands.
    threading.Thread(target=_job_worker_thread, daemon=True, name="job-runner").start()
    log.info(
        "Worker server on 127.0.0.1:%s; profile=%spx/%s/%s amp=%s(%s) resident=%s sam31=%s "
        "gpu_concurrency=%s(queue only) worker_id=%s — waiting for model load...",
        WORKER_PORT,
        MAX_SIDE,
        STAGE1_STEPS,
        STAGE2_STEPS,
        USE_FP16,
        AMP_DTYPE,
        KEEP_ON_GPU,
        SAM31_SERVER_URL or "subprocess",
        GPU_CONCURRENCY,
        WORKER_ID or "(none, legacy push mode)",
    )
    server = HTTPServer(("127.0.0.1", WORKER_PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
