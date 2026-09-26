---
title: SAM 3D Objects for SketchScape
emoji: 🪄
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 7860
suggested_hardware: l40sx1
---

# SAM 3D Objects for SketchScape

This is a Hugging Face **Docker GPU Space** for the official Meta SAM 3D Objects
release. It takes an RGB object image and matching binary mask, then returns a
Gaussian-splat `.ply` suitable for the reconstruction pipeline.

## Why this is not a ZeroGPU Space

SAM 3D Objects needs CUDA-built PyTorch3D, FlashAttention, and Kaolin. The
official setup explicitly notes that parts of the environment may need to be
built on a GPU node. ZeroGPU only supports Gradio Spaces and its build image has
no `nvcc`, so it cannot build SAM 3D Objects' CUDA extensions reliably. The
`l40sx1` recommendation supplies 48 GB VRAM, above the project's 32 GB minimum,
and Docker gives the build the CUDA development toolchain it needs.

## Deploy

1. Create a new Hugging Face Space using this directory, with **Docker** SDK.
2. Select **L40S (48 GB)** hardware (or larger) in the Space settings.
3. Request access to [`facebook/sam-3d-objects`](https://huggingface.co/facebook/sam-3d-objects).
4. Add a Space secret named `HF_TOKEN` containing a read token from that account.
5. Give the Space a persistent storage volume if you want the gated checkpoint
   download to survive restarts. It is cached at `/data/sam3d-objects`.

The Space is deliberately not configured to bake gated checkpoints or a token
into its image.

## Unity handoff

The official output is a Gaussian-splat PLY, not a GLB. Keep it as a splat for
rendering, or run a separate mesh-reconstruction/conversion step before passing
an asset to the current glTFast loader.
