# GPU worker

Runs SAM 3.1 segmentation and staged Fast-SAM3D reconstruction on the EC2 GPU
host, never in the API process. Verified end-to-end on an NVIDIA L40S
(g6e.xlarge): 70 s per object (42 s SAM 3.1 + 28 s Fast-SAM3D), producing a
53 MB PLY. Starting the instance or running any GPU job needs explicit
approval (AGENT.md Hard Rule 3).

## How it runs on EC2 (`PIPELINE_MODE=aws-local`)

`infra/aws/bootstrap_instance.sh` installs four systemd services on the GPU
host, all on loopback except the API:

| Service | Process | Port |
| --- | --- | --- |
| `sketchscape-sam31` | `segment_sam31_local.py --serve` (warm SAM 3.1, its own venv) | 8002 |
| `sketchscape-worker` | `worker_server.py` (warm Fast-SAM3D, its own venv) | 8001 |
| `sketchscape-dispatcher` | `gpu_dispatcher.py` (claim/lease loop, Build Plan step 27) | -- |
| `sketchscape` | the FastAPI backend | 8000 |

**Legacy single-object path (`reconstruct` jobs from `POST
/v1/reconstructions`, unchanged since before step 26):** the API posts
`{job_id, subject_hint}` directly to `worker_server.py`'s `/worker/jobs`,
which:

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

**Several objects per photo, several uploads in flight (Build Plan step 27,
`gpu_dispatcher.py`):** the person types a name per object on the website;
the API enqueues one durable `segment` job (all pending selections for one
photo) and, once selections are generated, one `reconstruct` job per chosen
object. Nothing pushes these -- `gpu_dispatcher.py` runs a claim/lease loop
against the API (`POST /v1/internal/jobs/claim`, worker token), claiming
`segment` jobs first every iteration since they're short:

- `segment` job: the dispatcher fetches the pending selections' typed names
  (`GET /v1/internal/reconstructions/{job_id}/selections`) and the image,
  asks the warm SAM 3.1 server's `/segment_many` route to batch every name
  into one predictor call (`segment_selections` in
  `segment_sam31_local.py`), and reports each selection's outcome
  individually (`POST .../selections/{selection_id}/result`) -- a selection
  with no usable mask fails with a reason and never blocks the others (Hard
  Rule 7).
- `reconstruct` job: unchanged Fast-SAM3D path (skill item 2) -- the
  dispatcher hands it to the already-warm `worker_server.py` over the same
  `/worker/jobs` contract as the legacy path above and only babysits the
  API-side lease (renewing every 60 s) while it runs; `worker_server.py`
  reports the result itself, now including `worker_id` so the callback
  satisfies the API's lease-ownership check.
- Idle backoff: 1 s growing to 10 s when there's no work.

Within a job, SAM 3.1 and Fast-SAM3D never hold GPU memory at the same time
(Hard Rule 5). `worker_server.py` runs one reconstruct job at a time;
`SKETCHSCAPE_GPU_CONCURRENCY` (default 1) sizes its accept queue, but two
Fast-SAM3D jobs never run truly concurrently yet -- `_run_one_job` moves
shared pipeline state between GPU/CPU with no lock, so raising concurrency
needs a benchmark (`worker/benchmark_concurrency.py`, gated on explicit
approval) and further pipeline-isolation work, not just a config change. A
T4 always stays at 1.

See `worker/gpu_dispatcher.py`'s module docstring for the full design, and
`worker/test_gpu_dispatcher.py` / `worker/test_segment_sam31_local.py` for
the CPU-only unit tests (fake API/SAM3.1/worker-server clients, no GPU, no
network).

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
- `gpu_dispatcher.py` (Build Plan step 27): the claim/lease loop described
  above. Only needs the standard library -- runs fine under
  `backend/.venv`'s interpreter, no torch/ultralytics import.
- `benchmark_concurrency.py`: the (not-yet-run) `SKETCHSCAPE_GPU_CONCURRENCY`
  benchmark hook, gated on `SKETCHSCAPE_BENCHMARK_APPROVED=1` plus a real
  CUDA GPU. Never invoked automatically; see its module docstring.
- `test_segment_sam31_local.py`, `test_gpu_dispatcher.py`: CPU-only unit
  tests for the two files above (`python -m unittest test_*.py` from this
  directory, using `backend/.venv`'s Python, which has `numpy`/`Pillow`).

`fastsam3d_kaggle_notebook.ipynb` and `sam3d_kaggle_notebook.ipynb` in the
repo root are where the pinned dependency set was first proven on a 16 GB
Kaggle T4. They're history, not the live path.
