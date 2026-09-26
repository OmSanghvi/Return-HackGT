# GPU worker

Runs SAM 3.1 segmentation and staged Fast-SAM3D reconstruction on the EC2 GPU
host, never in the API process. Verified end-to-end on an NVIDIA L40S
(g6e.xlarge): 70 s per object (42 s SAM 3.1 + 28 s Fast-SAM3D), producing a
53 MB PLY. Starting the instance or running any GPU job needs explicit
approval (AGENT.md Hard Rule 3).

## How it runs on EC2 (`PIPELINE_MODE=aws-local`)

`infra/aws/bootstrap_instance.sh` installs three systemd services on the GPU
host, all on loopback except the API:

| Service | Process | Port |
| --- | --- | --- |
| `sketchscape-sam31` | `segment_sam31_local.py --serve` (warm SAM 3.1, its own venv) | 8002 |
| `sketchscape-worker` | `worker_server.py` (warm Fast-SAM3D, its own venv) | 8001 |
| `sketchscape` | the FastAPI backend | 8000 |

For each job the API posts `{job_id, subject_hint}` to
`worker_server.py`, which:

1. Pulls the job's private image (and mask, if one was uploaded) from the
   API's `/v1/internal/...` routes with the worker token.
2. If there's no mask, asks the warm SAM 3.1 server for one using
   `subject_hint` as a concept prompt (falling back to running
   `segment_sam31_local.py` as a subprocess). SAM 3.1 picks one centre-most
   instance and returns `mask_review` rather than guess when that's unsafe
   or the hint is empty.
3. Runs staged Fast-SAM3D with the models already loaded, so there's no
   per-job cold start.
4. Streams the PLY, mask, and preview back to
   `POST /v1/internal/reconstructions/{job_id}/result`.

Within a job, SAM 3.1 and Fast-SAM3D never hold GPU memory at the same time
(Hard Rule 5). `worker_server.py` takes one job at a time; a second gets
429. Several objects per photo, a durable job queue, a GPU-host dispatcher,
and benchmarked concurrency are Build Plan steps 26–27
(`gpu-multi-object-worker` skill).

## One-time bootstrap

Follow `infra/aws/README.md` and `infra/aws/SMOKE_TEST_GUIDE.md`.
`bootstrap_instance.sh` runs `bootstrap_fastsam3d.sh` and
`bootstrap_sam31_local.sh`, which build two separate virtual environments
with pinned packages, apply the Fast-SAM3D source corrections, cache the
gated model weights using a one-time `HF_TOKEN` (unset it right after), and
require an import preflight before writing their success markers. Nothing is
installed or downloaded during inference.

## Other files

- `run_job.py`: the original one-shot job entrypoint (pull input, mask,
  staged Fast-SAM3D, post back). Still works; the persistent
  `worker_server.py` replaced it for the EC2 path.
- `run_fastsam3d_staged.py`, `prepare_fastsam3d_source.py`: the staged
  runner and its source patches.
- `segment_centered.py`: an older conservative mask for one centred
  foreground object, from the Kaggle experiments.
- `SKETCHSCAPE_AUTO_MASK_COMMAND`: a command template (`{image}`, `{mask}`,
  `{prompt}`) that `run_job.py` uses to make a white-on-black mask; the
  bootstrap points it at `segment_sam31_local.py`.

`fastsam3d_kaggle_notebook.ipynb` and `sam3d_kaggle_notebook.ipynb` in the
repo root are where the pinned dependency set was first proven on a 16 GB
Kaggle T4. They're history, not the live path.
