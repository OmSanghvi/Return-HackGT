# SketchScape backend

The only process clients (Unity, and later the web app) talk to, and the
authority for project state, blueprints, and safe scene edits. It works
without a GPU in `mock` mode, so upload, polling, scene loading, and safe
edits are demoable without AWS. Identity is selected by
`SKETCHSCAPE_AUTH_MODE` (`mock` default; `demo` — two hardcoded accounts —
is the real identity model for a live deployment of this track, no Clerk
or Meta account setup (decision 2026-09-26); see Auth and Membership
below). Planned additions (the room API, durable jobs) are in
`docs/BUILD_PLAN.md`.

## Run locally

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PIPELINE_MODE=mock .venv/bin/uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs`, submit a photo to
`POST /v1/reconstructions`, poll its `poll_url`, then read `/v1/scene`.

## Auth

`backend/auth.py` (Build Plan step 16), selected by `SKETCHSCAPE_AUTH_MODE`:

| Mode | Who calls | How |
| --- | --- | --- |
| `mock` (default) | local/dev | `X-SketchScape-Dev-User` header (default `dev-user`); no secrets; membership/ownership checks are no-ops |
| `demo` | the real identity model for this track (decision 2026-09-26) | same `X-SketchScape-Dev-User` header, restricted to exactly two hardcoded accounts (`SKETCHSCAPE_DEMO_USERS`, default `demo-alice,demo-bob`); real membership/ownership enforcement |
| `clerk` | unused by this plan, kept for a possible future upgrade | Clerk session tokens (`kind=user`) and M2M tokens (`kind=service`); requires `CLERK_SECRET_KEY` and an explicit `SKETCHSCAPE_WEB_ORIGINS` allowlist (no `*`) |

In `demo` and `clerk` mode, every `/v1/projects/**`, `/v1/reconstructions`,
and `/v1/artifacts/**` route requires a verified identity; CORS is locked to
`SKETCHSCAPE_WEB_ORIGINS`. Legacy demo routes (`/v1/scene`, `/scene`,
`/sketch`, `/modify-scene`, and the related `/v1/interactives` /
`/v1/scene/actions` / `/v1/scene/modify` surface) return 404 outside `mock`
mode. `/v1/internal/**` stays worker-token only and never accepts a Clerk
bearer or a demo header. Startup refuses unsafe combinations (e.g. `clerk`
without a secret, `demo` without `SKETCHSCAPE_WEB_ORIGINS`, or `mock` with
DynamoDB / a non-mock pipeline).

**`demo` mode is the real identity model for this track, not a stand-in for
something else** (decision 2026-09-26, `docs/KNOWN_ISSUES.md` R13). There is
no Clerk sign-in and no Meta account linking anywhere in the plan. The
`clerk` code path is untouched, still tested, and left in place only as a
possible future upgrade if this ever becomes a real multi-user product —
nothing in the active plan depends on it or should be built against it.

Both the website (step 19) and the Quest (steps 21/22) authenticate the
same way: an account picker/switcher chooses one of the two
`SKETCHSCAPE_DEMO_USERS`, and every request from then on carries that
account in `X-SketchScape-Dev-User` — the Quest sends it directly, with no
linking step and no room token. Both accounts read and write the same
project, so an image one account uploaded is owned by that account (step
17), and a letter one account addresses to the other is visible to its
recipient as soon as it's sent (sealed access already goes to the author
*and* the recipients, not the whole room — step 28). Full design in
`collab-vr-accounts-and-gates`.

`clerk-backend-api` is an optional cloud dependency
(`pip install -r requirements-cloud.txt`); the base install never needs it
in `mock` or `demo` mode.

## Membership and ownership (step 17)

Projects carry an `invite_code` (≥16 URL-safe chars) and optional
`room_prompt` (max 300). Creating a project auto-registers the caller as
the first contributor (bound via `clerk_user_id`). Others join with
`POST /v1/projects/{id}/contributors` + a valid invite code. Members can
`PATCH /v1/projects/{id}` to set `room_prompt` and
`POST .../invite/rotate` to rotate the code. Only members see the invite
code in project responses.

In `demo` and `clerk` mode every project-scoped route enforces membership
(403 if not a member). NemoClaw (`kind=service`) may read and draft
blueprints / `connection/compose`, but cannot upload, publish, or register
as a contributor. Ownership of scene objects is **derived**
(`owned_object_ids`) from contributions — not stored twice. Mock mode
skips membership enforcement so local demos keep working.

## Contract test

```bash
cd backend
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest test_api.py test_storage.py test_subject_labeler.py test_auth.py
```

151 tests (2 are skipped either way, depending on whether `boto3` is
installed). They exercise only `PIPELINE_MODE=mock`; they don't contact AWS
or load a model. From the repo root, `bash scripts/verify_local.sh` runs
these plus the syntax, JSON, and secret checks.

## Subject labeling

When an upload has no `subject_hint` and no mask, `subject_labeler.py`
(`identify_subject`) supplies the SAM 3.1 prompt, and the job records
`subject_hint_source: "nemoclaw"`. A typed hint always wins. Selected by
`SKETCHSCAPE_SUBJECT_LABELER`: `mock` (default, deterministic, offline) or
`nemoclaw` (live path, Build Plan step 4a, not built yet).

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

1. Upload a photo as `image`; `mask` and `subject_hint` are optional (the
   labeler fills in a missing hint). One object per job today; several
   objects per photo are Build Plan steps 26–27.
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

Projects, assets, blueprint revisions, and publication records are durably
persisted through `backend/storage.py` (local JSON by default, DynamoDB in
cloud mode; see below), so this authoring state survives an API restart.

Reconstruction *jobs* are still process-local: a restart loses them, and a
second API instance can't answer a poll for them. Durable, lease-based jobs
in the store are planned in Build Plan step 26, so run one API process
until then. Publication
history is append-only — republishing an earlier revision appends a new record
rather than rewriting the log. The schema is
`shared/experience-blueprint.schema.json`.

### Storage backends

`backend/storage.py` defines one `AuthoringStore` surface with two backends,
selected by `SKETCHSCAPE_STORAGE_BACKEND`:

- `local` (default): `LocalJsonStore` writes `authoring-state.json` under
  `SKETCHSCAPE_DATA_DIR` with atomic replace-on-write. No external service or
  extra dependency is required. This powers the demo and the tests.
- `dynamodb`: `DynamoDbStore` gives cloud durability, live-verified against
  the real table. Its appends aren't conditional yet, so two API instances
  can still overwrite each other's revisions; Build Plan step 15 fixes
  that. It reads
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

Both store backends persist metadata only. Reconstruction artifacts (PLY,
mask, preview) go through `backend/artifact_store.py`, selected by
`SKETCHSCAPE_ARTIFACTS_BACKEND`: `local` (default, the data directory) or
`s3` (`S3ArtifactStore`, presigned-redirect serving, live-verified).
Uploaded source images stay on the API host's disk in both modes until
Build Plan step 26. The full planned data layout is in
`docs/DATA_ARCHITECTURE.md`.

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

No HF credential or CUDA dependency is put in this API. The GPU worker
segments the object with SAM 3.1, runs Fast-SAM3D, saves its
PLY/mask/preview, and emits the manifest in `worker_contract.json`. Only
`mock` and `aws-local` pipeline modes exist; any other value fails the job
instead of falsely claiming a cloud result.

The worker reports privately to `POST /v1/internal/reconstructions/{job_id}/result`
with a `result` JSON form field, `ply`, `mask`, and optionally `preview`. Set
the same `SKETCHSCAPE_WORKER_TOKEN` in the backend and the worker; never put
it in Unity or the web app. The endpoint will publish safe relative asset URLs only after
it receives both the PLY and the aligned mask.

The same private token gives a worker temporary pull access to
`GET /v1/internal/reconstructions/{job_id}/input/image` and `/input/mask` via
the `X-SketchScape-Worker-Token` header. This lets a cloud job fetch inputs
without opening the upload directory to the public internet.

## Single-GPU AWS mode

`PIPELINE_MODE=aws-local` is the cost-controlled EC2 mode, verified
end-to-end on an L40S (g6e.xlarge). It sends one job at a time to
`worker/worker_server.py` on the same host as this API. The worker obtains the private image
and `subject_hint`, runs local SAM 3.1 concept segmentation to create the
mask, releases it, then runs staged Fast-SAM3D. Set a short noun phrase such
as `red backpack` as `subject_hint`; a missing hint with no uploaded mask ends
in `mask_review` rather than a guessed reconstruction.

The deployable EC2 files are in [`infra/aws`](../infra/aws). This is a
single-user hackathon deployment: job state is in process memory, so do not
restart the API while an inference is running.
