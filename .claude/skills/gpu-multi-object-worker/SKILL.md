---
name: gpu-multi-object-worker
description: Use for Build Plan step 27 — making the GPU worker process several objects from one image and several uploads in flight. SAM 3.1 semantic segmentation driven by the person's typed names (text prompts only, one SAM 3.1 pass per photo, alternatives per prompt), optional auto-detect, one Fast-SAM3D reconstruction per selected object, a GPU-host dispatcher that claims durable jobs with leases, and a benchmarked, configurable GPU concurrency. Requires explicit approval before any GPU run (Hard Rule 3).
---

# GPU worker: many objects, many uploads (step 27)

## Gate

`python3 scripts/check_collab_gates.py 27` (needs 26). BLOCKED means stop.
**Starting an EC2 GPU instance or running a GPU job always needs explicit
user approval first** (Hard Rule 3), and so does every benchmark in this
step.

## What "simultaneous" means here

- **From the person's point of view:** they upload one photo with several
  objects (or several photos, or several people upload at once), type a
  name for each object, and all of it is accepted immediately and tracked
  in one progress view.
- **On the GPU:**
  - One SAM 3.1 semantic pass per image masks every named object.
  - Reconstructions run through the durable queue.
  - Within one job, SAM 3.1 and Fast-SAM3D still never share GPU memory at
    the same time (Hard Rule 5).
  - Several reconstructions run **in parallel only if a benchmark proves
    the GPU has room**. Default parallelism is 1.

## Verified facts

- Ultralytics `SAM3SemanticPredictor` accepts several concept prompts in one
  call (`predictor(text=["mug", "lamp"])`) and returns zero or more
  instance masks with scores for each prompt. The current worker already
  gets all candidates (`candidate_masks`) and then keeps one
  (`choose_one`).
- **Decision (user, 2026-09-26): object selection is text-only.** There is
  no click-to-include/exclude and no drag-a-box, on the website or here —
  the person always types a name. This is also the only SAM 3.1 path this
  repo has ever run for real (`segment_sam31_local.py` uses only
  `SAM3SemanticPredictor`), so there is no interactive predictor to add,
  and no VRAM-sharing question between two predictors (superseded
  `docs/KNOWN_ISSUES.md` N28).
- Meta's SAM 3D Objects supports multi-object generation from one image
  plus several masks, including layout. **Whether the staged Fast-SAM3D
  pipeline in this repo supports a joint multi-mask call is unverified.**
  The baseline is one Fast-SAM3D run per mask. A joint multi-object run is
  an optional experiment after the baseline works.
- The verified live run was on an **L40S (g6e.xlarge, 45 GB)**: one object
  took 70 s end to end, and the PLY was 53 MB. The Terraform default
  instance is still `g4dn.xlarge` (T4, 16 GB).
- `worker_server.py` today: `queue.Queue(maxsize=1)` and a single job lock.
  The consumer thread takes a job off the queue before running it, so one
  job runs, one more waits in the queue, and a **third** concurrent submit
  gets 429 "worker busy". Models stay warm between jobs.

## Build

1. **Segmentation from the person's typed names (`segment_sam31_local.py`).**
   Add `segment_selections(image, selections[]) -> {selection_id: mask, score, alternatives}`:
   - Load the image **once** per job.
   - `SAM3SemanticPredictor`, `predictor(text=[selection.text for each
     selection])`, in one batched call per image — every selection is a
     text prompt, so this is the only path (no branching on selection
     type). The highest score per prompt becomes that selection's mask,
     and the rest (after the filters below) are returned as
     `alternatives` for the person to switch to.
   - Filters: area between 0.5% and 90% of the image; drop exact duplicates
     across selections (IoU > 0.85 → keep the higher score and flag the
     other as a duplicate). A selection with no usable mask → `failed` with
     a reason ("nothing found matching that name; try being more
     specific").
   - Write a mask and preview per selection.
   - Keep `choose_one` for the legacy single-object path, and add
     `segment_many(image, prompts[])` only for the optional auto-detect
     helper.
2. **Reconstruction:** unchanged per job (one mask → one PLY), models kept
   warm. Reuse the loaded pipeline across jobs.
3. **Dispatcher (`worker/gpu_dispatcher.py`, runs on the GPU host next to
   `worker_server.py`):**
   - Loop: `POST /v1/internal/jobs/claim` (worker token) → run → renew the
     lease every 60 s → post the result.
   - Idle backoff when there are no jobs: 1 s growing to 10 s.
   - It talks only to the API's internal routes, so the data layer stays in
     one place.
4. **Concurrency:** `SKETCHSCAPE_GPU_CONCURRENCY` (default **1**).
   `worker_server.py`'s queue size and worker threads follow it. Segment
   jobs are short, so they can take priority over reconstruct jobs (claim
   `segment` first) and the object picker appears quickly.
5. **Raising concurrency above 1 needs a benchmark**, with approval, on the
   actual instance type:
   - Run 1, then 2 parallel reconstructions.
   - Record peak VRAM (`nvidia-smi --query-gpu=memory.used`), time per
     object, and whether the outputs match the single run.
   - Allow 2 only if the combined peak is under 90% of VRAM and the outputs
     are unchanged.
   - Record the results in BUILD_PLAN step 27. A **T4 stays at 1**.
6. **systemd:** add a `sketchscape-dispatcher` unit alongside the existing
   worker unit in `infra/aws/bootstrap_instance.sh`, with a restart policy.
   The recurring shutdown guard still applies.
7. **Failures:**
   - A selection with no usable mask → that selection is `failed` with a reason, and the person refines it on the website. Other selections continue. Legacy single-object path: no candidates → `needs_review` with the prompt
     shown.
   - A Fast-SAM3D failure fails only that object. Other objects from the
     same image continue, and failed objects are left out of the room
     (Hard Rule 7).

## Tests (no GPU)

Unit-test `segment_selections` with a stubbed predictor:
- a text selection returns the best instance plus alternatives
- the area filter
- a duplicate across selections is flagged
- a selection with no usable mask fails with a reason
- several selections batch into one predictor call

Also unit-test `segment_many` (the auto-detect helper): threshold, area
bounds, dedupe by IoU, cap, sort order.

Test the dispatcher against a stub API:
- claim → run (fake) → renew → complete
- the lease is lost mid-run
- a 204 when idle leads to backoff

Existing worker tests must still pass.

## Definition of done

`python3 scripts/check_collab_gates.py --done 27` passes. The user
confirms `gpu_multi_object_verified` after an approved GPU run where:
- one photo where the person named 3 objects produced 3 correct masks and
  3 PLYs, and
- two uploads submitted together both completed.

The concurrency benchmark results (or "kept at 1") are recorded in the
Build Plan.
