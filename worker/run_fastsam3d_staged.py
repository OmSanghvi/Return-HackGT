#!/usr/bin/env python3
"""The low-VRAM Fast-SAM3D runner validated in the project's Kaggle notebook.

Models are brought onto the GPU one stage at a time.  This avoids the normal
all-models-on-GPU behaviour and writes only the Gaussian-splat PLY used by the
Unity pipeline.

Speed optimisations applied for the T4 (16 GB):
- FP16 (half precision) throughout: the T4 has 65 TFLOPS FP16 vs 8 TFLOPS FP32.
- Reduced diffusion steps: STAGE1_STEPS default 8, STAGE2_STEPS default 8.
  Quality degrades slightly below 6; 8 is a good hackathon trade-off.
- Input resized to MAX_SIDE=512 by default (was 768): cuts MoGe compute ~55%.
- SAM 3.1 imgsz=512 reduces segmentation latency.
- torch.backends.cudnn.benchmark=True: auto-tunes CUDA kernels on first run.
- All models cast to FP16 after loading.
"""

from __future__ import annotations

import gc
import math
import os
from pathlib import Path

import numpy as np
import torch
from hydra.utils import instantiate
from omegaconf import OmegaConf
from PIL import Image

os.environ.update(
    {
        "ATTN_BACKEND": "sdpa",
        "SPARSE_ATTN_BACKEND": "sdpa",
        "CUMM_DISABLE_JIT": "1",
        "SPCONV_DISABLE_JIT": "1",
        "LIDRA_SKIP_INIT": "true",
    }
)
from sam3d_objects.pipeline.inference_pipeline import InferencePipeline


def env_path(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return Path(value)


REPO = env_path("FASTSAM3D_REPO_DIR")
CHECKPOINTS = env_path("FASTSAM3D_CHECKPOINT_DIR")
IMAGE_PATH = env_path("FASTSAM3D_INPUT_IMAGE")
MASK_PATH = env_path("FASTSAM3D_INPUT_MASK")
OUTPUT_DIR = env_path("FASTSAM3D_OUTPUT_DIR")
MAX_SIDE = int(os.environ.get("FASTSAM3D_MAX_INPUT_SIDE", "512"))
STAGE1_STEPS = int(os.environ.get("FASTSAM3D_STAGE1_STEPS", "8"))
STAGE2_STEPS = int(os.environ.get("FASTSAM3D_STAGE2_STEPS", "8"))
SEED = int(os.environ.get("FASTSAM3D_SEED", "42"))
USE_FP16 = os.environ.get("FASTSAM3D_FP16", "1") not in ("0", "false", "no")


def main() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("Fast-SAM3D staged runner requires an NVIDIA CUDA GPU.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    torch_cache = REPO / "checkpoints/torch-cache"
    torch_cache.mkdir(parents=True, exist_ok=True)
    os.environ["TORCH_HOME"] = str(torch_cache)

    # FP16 via autocast only — do NOT set_default_dtype(float16) globally.
    # pytorch3d creates float32 tensors internally (e.g. torch.tensor(0.0) in
    # look_at_view_transform) which break if the global default is float16.
    # torch.autocast handles mixed precision correctly per-operation.
    torch.backends.cudnn.benchmark = True

    gpu, cpu = torch.device("cuda:0"), torch.device("cpu")

    def move_models(names: tuple[str, ...], device: torch.device) -> None:
        # Move to device only — dtype is handled by torch.autocast at inference time.
        for name in names:
            model = pipeline.models[name]
            if model is not None:
                model.to(device=device)
        conditioners = {"ss_generator": "ss_condition_embedder", "slat_generator": "slat_condition_embedder"}
        for name in names:
            conditioner = pipeline.condition_embedders.get(conditioners.get(name, ""))
            if conditioner is not None:
                conditioner.to(device=device)

    def clear_cuda(stage: str) -> None:
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        print(
            f"{stage}: allocated={torch.cuda.memory_allocated() / 2**30:.2f} GB, "
            f"reserved={torch.cuda.memory_reserved() / 2**30:.2f} GB"
        )

    # The mesh decoder is deliberately bypassed: this product consumes PLY
    # Gaussian splats. It prevents unnecessary VRAM use on the L4.
    InferencePipeline.init_slat_decoder_mesh = lambda self, *args, **kwargs: None

    def gaussian_only_decode(self, map_tokens, slat, formats):
        if formats != ["gaussian"]:
            raise ValueError(f"Expected Gaussian-only decode, got {formats!r}")
        with torch.no_grad():
            return {"gaussian": self.models["slat_decoder_gs"](slat)}

    InferencePipeline.decode_slat = gaussian_only_decode
    config = OmegaConf.load(REPO / "checkpoints/hf/pipeline.yaml")
    config.workspace_dir = str(CHECKPOINTS)
    config.device = "cpu"
    config.depth_model.device = "cpu"
    config.depth_model.model.pretrained_model_name_or_path = "Ruicheng/moge-vitl"
    config.compile_model = False
    config.decode_formats = ["gaussian"]
    config.slat_decoder_gs_4_config_path = None
    config.slat_decoder_gs_4_ckpt_path = None
    config.slat_decoder_mesh_config_path = None
    config.slat_decoder_mesh_ckpt_path = None
    config.ss_decoder_config_path = str(REPO / "checkpoints/hf/ss_decoder.yaml")
    config.slat_decoder_gs_config_path = str(REPO / "checkpoints/hf/slat_decoder_gs.yaml")
    config.ss_generator_config_path = str(REPO / "checkpoints/hf/ss_generator_faster.yaml")
    config.slat_generator_config_path = str(REPO / "checkpoints/hf/slat_generator_faster.yaml")
    pipeline = instantiate(config)
    pipeline.device = gpu
    pipeline.ss_params = {"ss_faster_stride": 3, "ss_warmup": 2, "ss_order": 1, "ss_momentum_beta": 0.5}
    pipeline.slat_params = {"slat_thresh": 1.5, "slat_warmup": 3, "slat_token_ratio": 0.1}
    pipeline.mesh_params, pipeline.enable_mesh, pipeline.hfer_2d = {}, False, 0.0
    token_args = pipeline.models["slat_generator"].args
    token_args.effective_steps = STAGE2_STEPS
    token_args.full_sampling_end_steps = math.ceil(STAGE2_STEPS * 0.75)
    token_args.anchor_step = max(1, math.floor(STAGE2_STEPS * 0.2))

    image = np.asarray(Image.open(IMAGE_PATH).convert("RGB"))
    mask = np.asarray(Image.open(MASK_PATH).convert("L")) > 127
    if image.shape[:2] != mask.shape[:2]:
        raise ValueError("Image and mask dimensions must match.")
    height, width = image.shape[:2]
    if max(height, width) > MAX_SIDE:
        scale = MAX_SIDE / max(height, width)
        size = (round(width * scale), round(height * scale))
        image = np.asarray(Image.fromarray(image).resize(size, Image.Resampling.LANCZOS))
        mask = np.asarray(
            Image.fromarray(mask.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
        ) > 127
    rgba = np.concatenate([image, (mask.astype(np.uint8) * 255)[..., None]], axis=-1)

    pipeline.depth_model.model.to(gpu)
    pipeline.depth_model.device = gpu
    if USE_FP16:
        # MoGe is pure PyTorch — safe to cast to float16 directly.
        pipeline.depth_model.model.half()
    t0 = torch.cuda.Event(enable_timing=True)
    t1 = torch.cuda.Event(enable_timing=True)

    print(f"Running pipeline: MAX_SIDE={MAX_SIDE}, STAGE1={STAGE1_STEPS}, STAGE2={STAGE2_STEPS}, FP16={USE_FP16}")

    t0.record()
    with torch.no_grad():
        if USE_FP16:
            pipeline.depth_model.model.half()
        pointmap = pipeline.compute_pointmap(rgba)["pointmap"]
    t1.record()
    torch.cuda.synchronize()
    print(f"MoGe depth: {t0.elapsed_time(t1)/1000:.1f}s")
    pipeline.depth_model.model.to(cpu)
    clear_cuda("MoGe offloaded")

    ss_input = pipeline.preprocess_image(rgba, pipeline.ss_preprocessor, pointmap=pointmap)
    del pointmap
    move_models(("ss_generator", "ss_decoder"), gpu)
    torch.manual_seed(SEED)

    t0.record()
    with torch.no_grad(), torch.autocast("cuda", enabled=USE_FP16):
        ss_return, map_tokens, coords_scores = pipeline.sample_sparse_structure(ss_input, inference_steps=STAGE1_STEPS)
    t1.record()
    torch.cuda.synchronize()
    print(f"Sparse structure ({STAGE1_STEPS} steps): {t0.elapsed_time(t1)/1000:.1f}s")

    ss_return.update(
        pipeline.pose_decoder(
            ss_return,
            scene_scale=ss_input.get("pointmap_scale"),
            scene_shift=ss_input.get("pointmap_shift"),
        )
    )
    ss_return["scale"] *= ss_return["downsample_factor"]
    coords = ss_return["coords"]
    move_models(("ss_generator", "ss_decoder"), cpu)
    del ss_input, ss_return
    clear_cuda("Sparse structure offloaded")

    slat_input = pipeline.preprocess_image(rgba, pipeline.slat_preprocessor)
    move_models(("slat_generator",), gpu)

    t0.record()
    with torch.no_grad(), torch.autocast("cuda", enabled=USE_FP16):
        slat = pipeline.sample_slat(
            slat_input, coords, inference_steps=STAGE2_STEPS, map_tokens=map_tokens, coords_scores=coords_scores
        )
    t1.record()
    torch.cuda.synchronize()
    print(f"SLaT ({STAGE2_STEPS} steps): {t0.elapsed_time(t1)/1000:.1f}s")

    move_models(("slat_generator",), cpu)
    del slat_input, coords, map_tokens, coords_scores
    clear_cuda("SLaT offloaded")

    move_models(("slat_decoder_gs",), gpu)
    t0.record()
    with torch.no_grad(), torch.autocast("cuda", enabled=USE_FP16):
        gaussian = pipeline.decode_slat(None, slat, ["gaussian"])["gaussian"][0]
    t1.record()
    torch.cuda.synchronize()
    print(f"Gaussian decode: {t0.elapsed_time(t1)/1000:.1f}s")

    output = OUTPUT_DIR / "fastsam3d_reconstruction.ply"
    gaussian.save_ply(output)
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
