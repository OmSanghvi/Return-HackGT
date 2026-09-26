"""Gradio front end for the official SAM 3D Objects inference pipeline.

The model files are gated.  On a Hugging Face Space, add an `HF_TOKEN` secret
for an account that has been granted access to facebook/sam-3d-objects.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

import gradio as gr
import numpy as np
from huggingface_hub import snapshot_download


MODEL_REPO = "facebook/sam-3d-objects"
MODEL_CACHE = Path(os.environ.get("SAM3D_MODEL_DIR", "/data/sam3d-objects"))
SOURCE_ROOT = Path("/opt/sam3d")
_inference = None
_model_lock = threading.RLock()


def _pipeline_config() -> Path:
    """Download gated weights once and return their official pipeline config."""
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise gr.Error(
            "Set the HF_TOKEN Space secret to a token whose account has access to "
            "facebook/sam-3d-objects, then restart the Space."
        )

    snapshot_download(
        repo_id=MODEL_REPO,
        repo_type="model",
        local_dir=MODEL_CACHE,
        token=token,
        max_workers=1,
    )
    configs = list(MODEL_CACHE.glob("**/checkpoints/hf/pipeline.yaml"))
    if len(configs) != 1:
        raise RuntimeError("The downloaded model did not contain checkpoints/hf/pipeline.yaml.")
    return configs[0]


def get_inference():
    """Initialize the pipeline exactly once; concurrent Gradio requests share it."""
    global _inference
    with _model_lock:
        if _inference is None:
            config = _pipeline_config()
            if not SOURCE_ROOT.is_dir():
                raise RuntimeError("SAM 3D Objects source was not found in the container.")
            # The official notebook exposes Inference from this file rather than
            # as an installed public package API.
            import sys

            notebook_dir = SOURCE_ROOT / "notebook"
            if str(notebook_dir) not in sys.path:
                sys.path.insert(0, str(notebook_dir))
            from inference import Inference  # pylint: disable=import-outside-toplevel

            _inference = Inference(str(config), compile=False)
    return _inference


def _binary_mask(mask: np.ndarray | None) -> np.ndarray:
    if mask is None:
        raise gr.Error("Upload a black-and-white mask; white selects the object to reconstruct.")
    if mask.ndim == 3:
        # A Gradio PNG mask often carries the drawn area in alpha.  Otherwise any
        # non-black RGB pixel denotes foreground.
        alpha = mask[..., 3] if mask.shape[-1] == 4 else None
        mask = alpha if alpha is not None and np.any(alpha) else np.any(mask[..., :3] > 0, axis=-1)
    result = np.asarray(mask) > 0
    if not np.any(result):
        raise gr.Error("The mask is empty. Paint or upload a white object mask.")
    return result


def reconstruct(image: np.ndarray | None, mask: np.ndarray | None, seed: int):
    if image is None:
        raise gr.Error("Upload an image first.")
    image = np.asarray(image, dtype=np.uint8)
    if image.ndim != 3 or image.shape[-1] < 3:
        raise gr.Error("Use an RGB or RGBA input image.")

    object_mask = _binary_mask(mask)
    if object_mask.shape != image.shape[:2]:
        raise gr.Error("The mask must have the same width and height as the input image.")

    # The official model is not safe for concurrent inference. `get_inference`
    # uses the same lock for initialization and each generation.
    with _model_lock:
        output = get_inference()(image[..., :3], object_mask, seed=int(seed))
        output_dir = Path(tempfile.mkdtemp(prefix="sam3d-output-"))
        ply_path = output_dir / "object.splat.ply"
        output["gs"].save_ply(str(ply_path))

    # Gradio's Model3D displays Gaussian-splat PLY files, and File makes the
    # result available to the Unity import/conversion stage.
    return str(ply_path), str(ply_path)


with gr.Blocks(title="SAM 3D Objects") as demo:
    gr.Markdown(
        "# SAM 3D Objects\n"
        "Upload an object image and an aligned black-and-white mask. The output is "
        "a Gaussian-splat `.ply`, not a GLB mesh."
    )
    with gr.Row():
        image_input = gr.Image(label="Object image", type="numpy", image_mode="RGB")
        mask_input = gr.Image(label="Object mask (white = object)", type="numpy", image_mode="RGBA")
    seed_input = gr.Slider(0, 2_147_483_647, value=42, step=1, label="Seed")
    run_button = gr.Button("Reconstruct", variant="primary")
    with gr.Row():
        preview = gr.Model3D(label="Gaussian splat preview")
        download = gr.File(label="Download .ply")
    run_button.click(reconstruct, [image_input, mask_input, seed_input], [preview, download])


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(server_name="0.0.0.0", server_port=7860)
