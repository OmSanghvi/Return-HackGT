# GPU worker

`run_job.py` is the job entrypoint for a pre-baked Fast-SAM3D GPU image. It:

1. Pulls a job's private input from the backend.
2. Uses a supplied aligned mask, or calls a separate automatic-mask command.
3. Runs the staged Fast-SAM3D runner that has already been validated on the
   16 GB Kaggle T4.
4. Streams the resulting PLY and mask back to the private callback endpoint.

## Required environment

```text
SKETCHSCAPE_API_URL=https://api.example.com
SKETCHSCAPE_JOB_ID=<backend job id>
SKETCHSCAPE_WORKER_TOKEN=<shared secret>
FASTSAM3D_STAGED_RUNNER=/opt/Fast-SAM3D/run_fastsam3d_staged.py
FASTSAM3D_REPO_DIR=/opt/Fast-SAM3D
FASTSAM3D_CHECKPOINT_DIR=/models/sam3d-checkpoints
```

The staged runner also expects the source patches and CUDA/Python dependency
set from `fastsam3d_kaggle_notebook.ipynb`; bake and smoke-test those in the
image/volume before accepting live jobs. This worker deliberately does not run
`pip install`, clone a repo, or download model weights during inference.

For automatic segmentation, set `SKETCHSCAPE_AUTO_MASK_COMMAND` to an absolute
command template. It receives `{image}`, `{mask}`, and `{prompt}`, and must create a
white-object/black-background PNG of identical dimensions:

```text
SKETCHSCAPE_AUTO_MASK_COMMAND='python /opt/mask/segment.py --image {image} --output {mask} --prompt {prompt}'
```

If the command is absent or declines an ambiguous photo, the worker reports
`mask_review`; Unity should then show a one-tap object picker rather than make
a wrong reconstruction.

The included command is the conservative default for one centred object:

```bash
export SKETCHSCAPE_AUTO_MASK_COMMAND="$FASTSAM3D_ENV_DIR/bin/python /path/to/worker/segment_centered.py --image {image} --output {mask}"
```

`segment_centered.py` downloads no model during the demo—the bootstrap caches
its SAM ViT-B weights. It intentionally exits with `mask_review` for an image
where it cannot identify a plausible centred foreground object.

For the AWS local-SAM 3.1 mode, use `segment_sam31_local.py` from the separate
SAM 3.1 virtual environment. It uses the short `subject_hint` supplied to the
public job as a concept prompt, chooses one centre-most instance, and exits
with `mask_review` when that selection would be unsafe. It has no third-party
per-image API call.

## One-time GPU bootstrap

The staged runner is [run_fastsam3d_staged.py](run_fastsam3d_staged.py).
Before any demo, copy this `worker/` folder to persistent storage and run
`bootstrap_fastsam3d.sh` once on a Camber GPU node:

```bash
export FASTSAM3D_PERSIST_ROOT=/persistent/sketchscape-sam3d
export HF_TOKEN='approved-token-in-job-secret-store'
bash worker/bootstrap_fastsam3d.sh
```

It installs the exact pinned CUDA/Python packages from the Kaggle success,
applies three source corrections, caches SAM 3D and MoGe weights, and requires
an import preflight before it writes its success marker. It does **not** install
or download anything during `run_job.py` inference.

Run that bootstrap as a dedicated Camber GPU job, then run one supplied photo
and mask through `run_job.py` before connecting Unity. Camber documents a
single-GPU `XSMALL` GPU node as one L4/24 GB VRAM; this project uses staged
loading because Meta's default SAM 3D setup says 32 GB VRAM minimum.
