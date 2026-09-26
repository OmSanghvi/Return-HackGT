import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path

import spaces
import gradio as gr
import numpy as np
from PIL import Image


MODEL_REPO = "facebook/sam-3d-objects"
CHECKPOINT_DIR = Path("checkpoints/hf")
SOURCE_DIR = Path("sam-3d-objects")


def run(cmd, cwd=None):
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout)
    return proc.stdout


def diagnostic_text():
    lines = []
    lines.append(f"Python: {sys.version.split()[0]}")
    lines.append(f"HF_TOKEN set: {'yes' if os.getenv('HF_TOKEN') else 'no'}")
    try:
        import torch

        lines.append(f"Torch: {torch.__version__}")
        lines.append(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            vram_gb = props.total_memory / (1024**3)
            lines.append(f"GPU: {props.name} ({vram_gb:.1f} GB VRAM)")
    except Exception as exc:
        lines.append(f"Torch import failed: {exc}")
    lines.append(f"Source present: {SOURCE_DIR.exists()}")
    lines.append(f"Checkpoints present: {(CHECKPOINT_DIR / 'pipeline.yaml').exists()}")
    return "\n".join(lines)


def ensure_repo():
    if SOURCE_DIR.exists():
        return
    run(["git", "clone", "--depth", "1", "https://github.com/facebookresearch/sam-3d-objects.git", str(SOURCE_DIR)])


def ensure_checkpoints():
    if (CHECKPOINT_DIR / "pipeline.yaml").exists():
        return
    from huggingface_hub import snapshot_download

    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN secret is not set. Add a token with access to facebook/sam-3d-objects.")

    tmp = snapshot_download(
        repo_id=MODEL_REPO,
        repo_type="model",
        token=token,
        local_dir="checkpoints/hf-download",
        max_workers=1,
    )
    nested = Path(tmp) / "checkpoints"
    CHECKPOINT_DIR.parent.mkdir(parents=True, exist_ok=True)
    if CHECKPOINT_DIR.exists():
        shutil.rmtree(CHECKPOINT_DIR)
    shutil.move(str(nested), str(CHECKPOINT_DIR))


def ensure_runtime():
    ensure_repo()
    if str(SOURCE_DIR / "notebook") not in sys.path:
        sys.path.append(str(SOURCE_DIR / "notebook"))
    ensure_checkpoints()


_inference = None


def get_inference():
    global _inference
    if _inference is not None:
        return _inference

    ensure_runtime()
    from inference import Inference

    _inference = Inference(str(CHECKPOINT_DIR / "pipeline.yaml"), compile=False)
    return _inference


def prepare_mask(mask_image):
    if mask_image is None:
        raise gr.Error("Provide a binary mask image. White pixels should mark the object.")
    mask = Image.fromarray(mask_image).convert("L")
    mask = mask.point(lambda value: 255 if value > 127 else 0)
    return mask


@spaces.GPU(duration=120)
def reconstruct(
    image: np.ndarray | None, mask_image: np.ndarray | None, seed: int = 42
) -> tuple[str | None, str]:
    """Reconstruct the white-masked object as a downloadable Gaussian-splat PLY."""
    try:
        if image is None:
            raise gr.Error("Upload an input image.")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            image_path = tmp / "image.png"
            mask_path = tmp / "mask.png"
            output_path = tmp / "sam3d-output.ply"

            Image.fromarray(image).convert("RGB").save(image_path)
            prepare_mask(mask_image).save(mask_path)

            inference = get_inference()

            from inference import load_image, load_mask

            loaded_image = load_image(str(image_path))
            loaded_mask = load_mask(str(mask_path))
            output = inference(loaded_image, loaded_mask, seed=int(seed))
            output["gs"].save_ply(str(output_path))

            # Keep a unique result after the staging directory closes; fixed
            # filenames would let simultaneous visitors overwrite one another.
            final_path = Path(tempfile.mkdtemp(prefix="sam3d-output-")) / f"{uuid.uuid4().hex}.ply"
            shutil.copyfile(output_path, final_path)
            return str(final_path), diagnostic_text()
    except Exception:
        return None, diagnostic_text() + "\n\n" + traceback.format_exc()


with gr.Blocks(title="SketchScape SAM 3D") as demo:
    gr.Markdown("# SketchScape SAM 3D")
    gr.Markdown("Upload an image and an object mask. White mask pixels are reconstructed.")
    with gr.Row():
        image = gr.Image(label="Image", type="numpy")
        mask = gr.Image(label="Object mask", type="numpy", image_mode="L")
    seed = gr.Number(label="Seed", value=42, precision=0)
    run_button = gr.Button("Reconstruct")
    model_output = gr.File(label="Gaussian splat PLY")
    status = gr.Textbox(label="Diagnostics", lines=8, value=diagnostic_text)
    run_button.click(reconstruct, inputs=[image, mask, seed], outputs=[model_output, status], api_name="reconstruct")


if __name__ == "__main__":
    demo.queue(max_size=4, default_concurrency_limit=1).launch(mcp_server=True)
