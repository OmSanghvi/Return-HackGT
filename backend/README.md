# SketchScape backend

This is the stable boundary between Unity and reconstruction infrastructure. It
works without a GPU in `mock` mode, so the portal reveal, polling, scene
loading, and safe edit flow are demoable before SAM 3D is deployed.

## Run locally

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PIPELINE_MODE=mock .venv/bin/uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs`, submit a photo to
`POST /v1/reconstructions`, poll its `poll_url`, then read `/v1/scene`.

## Contract test

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest test_api.py test_storage.py
```

This exercises only `PIPELINE_MODE=mock`; it does not contact AWS or load a
model.

## Notability sketches

There is no sketch → image-generation → reconstruction step anymore (the old
`POST /v1/sketches` endpoint and `backend/image_gen.py`'s mock/Azure/HF
backends were removed — trying to hallucinate a photorealistic object out of
a line drawing was more trouble than it was worth, and a real photo upload to
`POST /v1/reconstructions` is simpler and more reliable). A Notability export
is now used for what it actually is — a sketch/page, not a fake photo — via a
direct-display path and a SAM3D memory-plaque path. See
`docs/BUILD_PLAN.md` step 7 and `.claude/skills/sketch-image-gen-backends` for
the plan; neither is built yet.

## Unity contract

1. Upload one centred-object photo as `image`; `mask` and `subject_hint` are optional.
2. Poll `GET /v1/reconstructions/{job_id}` every 1–2 seconds.
3. On completion, load each `asset_url`. A real SAM 3D result is a
   Gaussian-splat `.ply`, so Unity needs a splat renderer rather than a GLB loader.
4. Fetch `GET /v1/scene` after a Unity reload.

## Projects, assets, multi-view provenance, and experience blueprints

The full authoring orchestration slice:

1. `POST /v1/projects` creates a project.
2. Multipart `POST /v1/projects/{project_id}/assets` queues a reconstruction and creates a stable catalog `asset_id`. The first uploaded image is automatically registered as **view 0** with full per-view provenance.
3. `GET /v1/projects/{project_id}/assets` reports readiness and artifact metadata for all assets.
4. `GET /v1/projects/{project_id}/assets/{asset_id}` returns a single asset including its full `views` list.
5. `GET /v1/projects/{project_id}/assets/{asset_id}/views` returns per-view reconstruction provenance (image key, subject hint, job ID, status, artifact URL, mask URL) sorted by `view_index`.
6. `POST /v1/projects/{project_id}/assets/{asset_id}/views` adds a new view (additional angle of the same subject) and queues its own reconstruction job. The asset stays READY from its first successful view; additional views may later be used for fusion. Returns the new `AssetView` immediately at 202.
7. `POST /v1/projects/{project_id}/blueprints/validate` validates a proposed experience.
8. `POST /v1/projects/{project_id}/blueprints` creates the next revision.
9. `POST /v1/projects/{project_id}/blueprints/{revision}/publish` selects and compiles a revision.
10. `GET /v1/projects/{project_id}/compiled-scene` returns the Unity runtime scene.
11. `GET /v1/projects/{project_id}/publications` returns the append-only publication history.

### Multi-view asset status rules

| Views state | Asset status |
|---|---|
| Any view is READY | READY (top-level `artifact_url` promoted from first READY view) |
| Any view is MASK_REVIEW (none READY) | MASK_REVIEW |
| All views FAILED | FAILED |
| All views PROCESSING | PROCESSING |

A failed additional view never demotes an asset that already has a READY view.
The legacy `reconstruction_job_id` field mirrors `views[0].reconstruction_job_id`
for backward compatibility.

Projects, assets, blueprint revisions, and publication records are now durably
persisted, so this authoring state survives an API restart. The store is a
single-process, JSON-file-backed implementation (`backend/storage.py`) that
writes `authoring-state.json` under `SKETCHSCAPE_DATA_DIR` with atomic
replace-on-write. It intentionally implements the same surface a future
S3/DynamoDB backend would expose; concurrency-safe multi-writer durability
remains the roadmap's S3+DynamoDB slice.

Reconstruction *jobs* remain process-local by design: a live inference cannot
survive a restart, so persisting job state would be misleading. Publication
history is append-only — republishing an earlier revision appends a new record
rather than rewriting the log. The schema is
`shared/experience-blueprint.schema.json`.

### Storage backends

`backend/storage.py` defines one `AuthoringStore` surface with two backends,
selected by `SKETCHSCAPE_STORAGE_BACKEND`:

- `local` (default): `LocalJsonStore` writes `authoring-state.json` under
  `SKETCHSCAPE_DATA_DIR` with atomic replace-on-write. No external service or
  extra dependency is required. This powers the demo and the tests.
- `dynamodb`: `DynamoDbStore` gives concurrency-safe cloud durability. It reads
  `SKETCHSCAPE_DYNAMODB_TABLE` (and optional `AWS_REGION`) and uses the standard
  AWS credential chain. `boto3` is imported lazily and is *not* in the base
  install — add it with `pip install -r requirements-cloud.txt`. Selecting this
  backend without `boto3` or a table name fails with an actionable message.

The DynamoDB table uses a single-table `pk`/`sk` layout so a project's assets,
blueprint revisions, and publication log are queryable together:

| pk | sk | item |
| --- | --- | --- |
| `PROJECT#<project_id>` | `META` | project record |
| `PROJECT#<project_id>` | `BLUEPRINT#<0-padded revision>` | one blueprint revision |
| `PROJECT#<project_id>` | `PUBLICATION#<0-padded sequence>` | one append-only publication record |
| `ASSET#<asset_id>` | `META` | catalog asset |

Zero-padded sort keys keep `Query` results in creation order. Blueprint
revisions and publication records are never overwritten, preserving the
append-only publication history.

Both backends persist metadata only; uploaded images and reconstruction
artifacts stay on the local data directory. Migrating local state to DynamoDB
(and artifacts to S3) is the roadmap's concurrency-safe durability slice.

## Named interactive actions

`GET /v1/interactives` returns the current object IDs, semantic types, and their
allowlisted actions. Unity and MCP authoring tools use the same structured
mutation endpoint:

```json
POST /v1/scene/actions
{
  "target_id": "tree_1",
  "action": "scale_by",
  "value": [1, 2, 1]
}
```

Supported actions are `scale_by`, `translate_by`, and `rotate_by`. Their inputs
and resulting transforms are bounded by the backend. No endpoint accepts a
Unity component name, method name, property path, reflection expression, or
arbitrary script. The legacy natural-language demo edit is only an adapter to
this structured policy.

## GPU-worker boundary

No HF/Camber credential or CUDA dependency is put in this API. A single GPU
worker must auto-segment a centred object (or request a one-tap selection for
ambiguous images), run SAM 3D Objects, save its PLY/mask/preview, and emit the
manifest in `worker_contract.json`. Non-mock mode intentionally fails until a
real worker adapter is connected; this avoids falsely claiming a cloud result.

The worker reports privately to `POST /v1/internal/reconstructions/{job_id}/result`
with a `result` JSON form field, `ply`, `mask`, and optionally `preview`. Set
the same `SKETCHSCAPE_WORKER_TOKEN` in the backend and the Camber job; do not
put it in Unity. The endpoint will publish safe relative asset URLs only after
it receives both the PLY and the aligned mask.

The same private token gives a worker temporary pull access to
`GET /v1/internal/reconstructions/{job_id}/input/image` and `/input/mask` via
the `X-SketchScape-Worker-Token` header. This lets a cloud job fetch inputs
without opening the upload directory to the public internet.

## Single-GPU AWS mode

`PIPELINE_MODE=aws-local` is the cost-controlled EC2 mode. It runs one worker
at a time on the same host as this API. The worker obtains the private image
and `subject_hint`, runs local SAM 3.1 concept segmentation to create the
mask, releases it, then runs staged Fast-SAM3D. Set a short noun phrase such
as `red backpack` as `subject_hint`; a missing hint with no uploaded mask ends
in `mask_review` rather than a guessed reconstruction.

The deployable EC2 files are in [`infra/aws`](../infra/aws). This is a
single-user hackathon deployment: job state is in process memory, so do not
restart the API while an inference is running.
