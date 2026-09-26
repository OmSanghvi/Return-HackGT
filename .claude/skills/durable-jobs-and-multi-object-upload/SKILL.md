---
name: durable-jobs-and-multi-object-upload
description: Use for Build Plan step 26 — replacing the in-memory reconstruction job dict with durable, lease-based jobs in the AuthoringStore; moving uploads to shared storage (S3 in cloud); the upload → person selects objects (points/box/text) → SAM 3.1 masks → refine → generate API (one reconstruction job per selected object); project-level batch job polling with ETags; and removing list-in-blob writes that lose data under concurrent uploads.
---

# Durable jobs and multi-object upload (step 26)

## Gate

`python3 scripts/check_collab_gates.py 26` (needs 15). BLOCKED means stop.
Read `docs/DATA_ARCHITECTURE.md` first; it defines every item, key, and
the polling contract used here.

## Bugs in today's code this step fixes

- `jobs: dict[str, ReconstructionJob] = {}` and `job_inputs` in `main.py`
  live in process memory. A restart loses every job, and with more than
  one API instance a poll can land on an instance that has never seen the
  job (404).
- Uploads are written to `UPLOAD_ROOT` on the API host's disk, so the
  worker can't fetch an input held by a different instance.
- `create_reconstruction` does `project.asset_ids.append(...)` and then
  `store.save_project(project)` (whole blob). Two uploads at once, which
  multi-object and multi-user make normal, silently drop one asset.
- `local_worker_lock` + `BackgroundTasks` serialize GPU work inside one API
  process and die with it.

## Store changes (both backends)

- Jobs:
  - `save_job`, `get_job`.
  - `list_project_jobs(project_id, active_only)` (GSI1
    `PROJECTJOBS#<id>`).
  - `claim_next_job(worker_id, kinds, lease_seconds)` (GSI2 `JOBQ#queued`
    + conditional update).
  - `renew_lease`.
  - `complete_job(job_id, lease_owner, result)` (conditional on the owner).
  - `release_expired_leases()`.
- Assets:
  - `link_asset(project_id, asset_id)` writes the child item
    `PROJECT#<id>/ASSET#<id>` (conditional).
  - `list_project_assets` reads the child items.
  - Keep reading the legacy `ProjectRecord.asset_ids` for old data, but
    never write it again.
- Uploads: `save_upload_record` / `get_upload_record`.
- Upload bytes: extend `ArtifactStore` with
  `put_upload(project_id, upload_id, name, UploadFile)` and
  `open_upload(...)`. Local = disk, S3 = `uploads/...`. Streaming, no full
  buffering, same as the PLY path.
- DynamoDB GSIs and TTL need the Terraform change described in
  DATA_ARCHITECTURE.md. Write the Terraform diff, but **do not apply it**
  without explicit approval (Hard Rule 3). Until it's applied, the
  DynamoDB backend refuses to start if the GSIs are missing (check with
  `describe_table`), and the error says what to apply.

## API: the person picks the objects, then SAM 3.1 masks them

The person chooses, on the website, **which objects** in a photo to turn
into 3D. Their selections become the SAM 3.1 prompts. Auto-detect is an
optional helper, not the default.

1. `POST /v1/projects/{id}/uploads` (multipart `image`, JPEG/PNG/WebP
   ≤16 MB; or several `masks` if the person already has them).
   - Server applies **EXIF orientation** (`ImageOps.exif_transpose`) before
     storing, so the image the browser shows and the one SAM sees have the
     same pixel grid.
   - Stores the image and the `UPLOAD` record.
   - **No GPU work yet** (unless `?auto=1`, see 6).
   - Returns 201 `{upload_id, image_url, width, height}`. The web app draws
     its selection canvas on `image_url`.
2. `POST /v1/projects/{id}/uploads/{upload_id}/selections` with body
   `{selections: [{selection_id, prompt, label?, memory_text?}]}`.
   - `selection_id`: a client UUID; resending the same one is idempotent.
   - `prompt` is exactly one of:
     - `{"type": "points", "points": [[x, y, 1|0], ...]}`: 1 includes the
       spot, 0 excludes it.
     - `{"type": "box", "box": [x0, y0, x1, y1]}`
     - `{"type": "text", "text": "blue vase"}` (≤100 chars)
   - Coordinates are **normalized 0–1** to the stored image. The server
     validates the range and converts to pixels.
   - One request may carry many selections, capped by
     `SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD` (default 8). This is a per-photo
     safety cap, not a per-user quota.
   - Server enqueues **one** `segment` job for the image with all the
     pending selections (SAM loads the image once).
   - Returns 202 `{job_id}`.
3. `GET /v1/projects/{id}/uploads/{upload_id}` returns the image plus, per
   selection:
   - `status`: pending | segmented | failed | generated
   - `mask_preview_url`, `score`
   - for text prompts, `alternatives[]` (other instances found; the person
     can switch)
4. `POST /v1/projects/{id}/uploads/{upload_id}/selections/{selection_id}/refine`
   with extra include/exclude points or a new box. Re-segments only that
   selection (a small `segment` job). `DELETE .../selections/{selection_id}`
   removes one.
5. `POST /v1/projects/{id}/uploads/{upload_id}/generate` with body
   `{selection_ids: [...]}`. For each **segmented** selection it creates:
   - an asset (`kind=reconstruction`, label from the selection or NemoClaw)
     and its project link item
   - a `reconstruct` job (Fast-SAM3D with that selection's mask)
   - a contribution with the selection's `memory_text`

   Returns 202 with assets and job ids. Selections that aren't segmented →
   409.
6. **Auto-detect (optional):** `?auto=1` on upload, or
   `POST .../uploads/{upload_id}/detect`. NemoClaw `identify_subject`
   labels (step 4a) run as text prompts. The results show up as
   *suggested* selections the person can keep or delete. Nothing
   generates without the person choosing.
7. `GET /v1/projects/{id}/jobs?active=1&since=<iso>` returns every job
   for the project (segment and reconstruct), newest first, with an `ETag`.
   `If-None-Match` → 304. This is the web app's single polling call.
8. Keep `POST /v1/projects/{id}/assets` and `POST /v1/reconstructions`
   (single object) working as thin wrappers: an upload plus one automatic
   selection. The Unity desktop panel and existing tests use them.
9. Internal (worker token only):
   - `POST /v1/internal/jobs/claim` with `{worker_id, kinds}` → a job or
     204.
   - `POST /v1/internal/jobs/{id}/lease`: renew the lease.
   - The result callback carries per-selection masks and scores for
     segment jobs, and the PLY for reconstruct jobs. It's accepted only
     from the lease owner.
10. **Mock mode:** an in-process dispatcher. Segment jobs make
    deterministic masks: a box becomes a filled rectangle, points become
    discs of fixed radius, and text becomes a fixed centered ellipse.
    Reconstruct jobs complete with the existing mock PLY. No network, no
    GPU.

Every route requires identity and membership outside `mock` mode (`demo` or
`clerk` — steps 16 and 17). The uploader owns their upload's selections, and
other members can't edit them.

## Tests

- **Restart durability:** create a job, rebuild the app and store from
  disk, and the job is still pollable.
- **Two uploads racing:** both assets are listed (the child items fixed the
  lost-append bug).
- One image, 3 selections (one points, one box, one text) → one segment
  job → 3 masks. Refine one with an exclude point → only it re-segments.
  Generate 2 → 2 assets, 2 reconstruct jobs, and 2 contributions with
  memory text.
- Validation:
  - Coordinates outside 0–1 → 422, as is an empty prompt or two prompt
    types in one selection.
  - Generating an unsegmented selection → 409.
  - Resending the same `selection_id` creates nothing new.
- An EXIF-rotated photo: the stored image is upright, and the mask lines
  up with the selection (fixture with orientation tag 6).
- Leases:
  - An expired lease is re-queued.
  - A callback from the non-owner is ignored.
  - After max attempts the job is `failed`.
- Jobs endpoint:
  - The ETag gives a 304 when unchanged.
  - The endpoint lists every job for the project.
- The object cap is enforced.
- Legacy single-object routes still pass the existing tests.
- Mock mode stays fully offline.

## Definition of done

`python3 scripts/check_collab_gates.py --done 26` and
`bash scripts/verify_local.sh` pass. `main.py` no longer has a module-level
`jobs` dict.
