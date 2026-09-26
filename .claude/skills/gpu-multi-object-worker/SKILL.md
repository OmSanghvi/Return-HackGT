---
name: gpu-multi-object-worker
description: Use for Build Plan step 27 — making the GPU worker process several objects from one image and several uploads in flight. SAM 3.1 segmentation driven by the person's selections from the website (points/box → interactive predictor, one mask each; text → semantic predictor with alternatives), optional auto-detect, one Fast-SAM3D reconstruction per selected object, a GPU-host dispatcher that claims durable jobs with leases, and a benchmarked, configurable GPU concurrency. Requires explicit approval before any GPU run (Hard Rule 3).
---

# GPU worker: many objects, many uploads (step 27)

## Gate

`python3 scripts/check_collab_gates.py 27` (needs 26). BLOCKED means stop.
**Starting an EC2 GPU instance or running a GPU job always needs explicit
user approval first** (Hard Rule 3), and so does every benchmark in this
step.

## What "simultaneous" means here

- **From the person's point of view:** they upload one photo with several
  objects (or several photos, or several people upload at once), and all of
  it is accepted immediately and tracked in one progress view.
- **On the GPU:**
  - One SAM 3.1 pass per image masks every object the person selected.
  - Reconstructions run through the durable queue.
  - Within one job, SAM 3.1 and Fast-SAM3D still never share GPU memory at
    the same time (Hard Rule 5).
  - Several reconstructions run **in parallel only if a benchmark proves
    the GPU has room**. Default parallelism is 1.

## Verified facts

- Ultralytics SAM 3 has two modes (docs.ultralytics.com/models/sam-3):
  - **Interactive/visual:** `SAM("sam3.pt").predict(points=, labels=, bboxes=)`
    returns **one object per prompt**. Label 0 marks an excluded point.
  - **Semantic:** see the next bullet; it returns **every instance** of a
    concept. The website's points/box selections use the interactive mode.
- Ultralytics `SAM3SemanticPredictor` accepts several concept prompts in one
  call (`predictor(text=["mug", "lamp"])`) and returns zero or more
  instance masks with scores for each prompt. The current worker already
  gets all candidates (`candidate_masks`) and then keeps one
  (`choose_one`).
- Meta's SAM 3D Objects supports multi-object generation from one image
  plus several masks, including layout. **Whether the staged Fast-SAM3D
  pipeline in this repo supports a joint multi-mask call is unverified.**
  The baseline is one Fast-SAM3D run per mask. A joint multi-object run is
  an optional experiment after the baseline works.
- The verified live run was on an **L40S (g6e.xlarge, 45 GB)**: one object
  took 70 s end to end, and the PLY was 53 MB. The Terraform default
  instance is still `g4dn.xlarge` (T4, 16 GB).
- `worker_server.py` today: `queue.Queue(maxsize=1)` and a single job lock.
  A second job gets 429 "worker busy". Models stay warm between jobs.

## Build

1. **Segmentation from the person's selections (`segment_sam31_local.py`).**
   Add `segment_selections(image, selections[]) -> {selection_id: mask, score, alternatives}`:
   - Load the image **once** per job.
   - **Points / box selections** → the interactive predictor,
     `SAM("sam3.pt").predict(source, points=[...], labels=[1|0...])` or
     `bboxes=[...]`. That's **one mask per selection**, and label 0
     excludes a region. Batch every point/box selection of the image into
     one call where the API allows it.
   - **Text selections** → `SAM3SemanticPredictor`, `predictor(text=[...])`,
     which finds all instances. The highest score becomes the selection's
     mask, and the rest (after the filters below) are returned as
     `alternatives` for the person to switch to.
   - Filters: area between 0.5% and 90% of the image; drop exact duplicates
     across selections (IoU > 0.85 → keep the higher score and flag the
     other as a duplicate). A selection with no usable mask → `failed` with
     a reason ("nothing found at that point; try a box").
   - Write a mask and preview per selection.
   - **Model memory:** check whether the interactive `SAM` and
     `SAM3SemanticPredictor` can share one loaded `sam3.pt`. If they can't,
     load the interactive predictor lazily, and measure VRAM for both while
     Fast-SAM3D is offloaded (Hard Rule 5 still applies within a job).
     Record the result in step 27.
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
- a points selection passes include and exclude labels through unchanged
- a box selection maps to `bboxes`
- a text selection returns the best instance plus alternatives
- the area filter
- a duplicate across selections is flagged
- a selection with no usable mask fails with a reason
- normalized → pixel conversion, including rounding at the edges

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
- one photo where the person selected 3 objects (a point, a box, and a
  text prompt) produced 3 correct masks and 3 PLYs, and
- two uploads submitted together both completed.

The concurrency benchmark results (or "kept at 1") are recorded in the
Build Plan.
