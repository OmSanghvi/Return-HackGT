---
title: SketchScape SAM 3D Demo
emoji: ✏️
colorFrom: purple
colorTo: pink
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
python_version: "3.10"
license: other
short_description: Turn a masked object image into a 3D Gaussian splat
---

# SketchScape SAM 3D Demo

Turn one masked object image into a Gaussian-splat PLY with Meta's
[`facebook/sam-3d-objects`](https://huggingface.co/facebook/sam-3d-objects)
model. Download the result and use it as the reconstruction asset in the
SketchScape pipeline.

Inputs:

- An RGB image.
- A binary mask image for the object to reconstruct. White pixels are treated as the object.
- A seed.

Output:

- A Gaussian splat PLY file.

Operational notes:

- The official setup requires a Linux NVIDIA GPU with at least 32 GB VRAM.
- This Space runs on Hugging Face ZeroGPU (48 GB `large` allocation).
- The model checkpoints are gated. The Space needs an `HF_TOKEN` secret that has access to `facebook/sam-3d-objects`.
- If the Space starts on CPU or a small GPU, the app will show diagnostics instead of failing silently.
- The official output is a Gaussian-splat PLY, not a GLB mesh. Convert it in a
  separate mesh-processing step before importing with a glTF-only Unity loader.

References:

- https://github.com/facebookresearch/sam-3d-objects
- https://huggingface.co/facebook/sam-3d-objects
- https://ai.meta.com/blog/sam-3d/
