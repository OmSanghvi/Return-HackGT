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
.venv/bin/python -m unittest test_api.py test_storage.py test_subject_labeler.py test_auth.py test_jobs.py
```

176 tests (2 are skipped either way, depending on whether `boto3` is
installed). They exercise only `PIPELINE_MODE=mock`; they don't contact AWS,
make any network call, or load a model. `test_storage.py`'s
`DynamoDbStoreContractTests` and `S3ArtifactStoreContractTests` run the exact
same contract as the local-store tests against `moto`'s in-memory AWS
emulation (`mock_aws`) — a real `boto3` DynamoDB table shaped like
`infra/aws/main.tf`'s and a real S3 bucket, so `ConditionExpression`
evaluation, GSI `Query` semantics, and `LastEvaluatedKey` pagination are all
exercised for real, not approximated by a hand-written fake. `moto` is a
test-only dependency (`requirements-dev.txt`); it is never imported by
application code and those test classes are skipped automatically if
`moto`/`boto3` aren't installed. From the repo root, `bash scripts/verify_local.sh`
runs these plus the syntax, JSON, and secret checks.

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

Projects, assets, blueprint revisions, publication records, contributors,
contributions, connection insights, the LIVE-revision pointer, durable jobs,
project→asset links, and upload records are all durably persisted through
`backend/storage.py` (local JSON by default, DynamoDB in cloud mode; see
below), so all of this survives an API restart. Reconstruction/segmentation
*jobs* are durable too (Build Plan step 26: `save_job`/`get_job`/
`claim_next_job`/`renew_lease`/`complete_job`/`release_expired_leases`), so
more than one API instance can answer a poll for the same job and a restart
doesn't lose in-flight work. Publication history is append-only —
republishing an earlier revision appends a new record rather than rewriting
the log. Blueprint writes are conditional (Build Plan step 15): a duplicate
or stale revision raises `RevisionConflict` instead of silently overwriting,
and the LIVE pointer is a compare-and-set so two racing publishes can't move
the live room backwards. The schema is `shared/experience-blueprint.schema.json`.

### Storage backends

`backend/storage.py` defines one `AuthoringStore` surface with two backends,
selected by `SKETCHSCAPE_STORAGE_BACKEND`:

- `local` (default): `LocalJsonStore` writes `authoring-state.json` under
  `SKETCHSCAPE_DATA_DIR` with atomic replace-on-write. No external service or
  extra dependency is required. This powers the demo and the tests.
- `dynamodb`: `DynamoDbStore` gives cloud durability with real conditional
  writes (blueprint revisions, the LIVE pointer, job claims/completions all
  use a DynamoDB `ConditionExpression`, not just an in-process lock — the
  lock only serializes one instance; the condition is what actually
  protects against a second one). It reads `SKETCHSCAPE_DYNAMODB_TABLE`
  (and optional `AWS_REGION`) and uses the standard AWS credential chain.
  `boto3` is imported lazily and is *not* in the base install — add it with
  `pip install -r requirements-cloud.txt`. Selecting this backend without
  `boto3`, a table name, or the table's GSI1/GSI2 indexes fails with an
  actionable message (`DynamoDbStore.load()` calls `describe_table` and
  refuses to start otherwise).

The DynamoDB table uses a single-table `pk`/`sk` layout so a project's
assets, blueprint revisions, publication log, contributors, contributions,
jobs, and uploads are queryable together:

| pk | sk | item |
| --- | --- | --- |
| `PROJECT#<project_id>` | `META` | project record |
| `PROJECT#<project_id>` | `LIVE` | live-revision pointer (compare-and-set) |
| `PROJECT#<project_id>` | `BLUEPRINT#<0-padded revision>` | one blueprint revision |
| `PROJECT#<project_id>` | `PUBLICATION#<0-padded sequence>` | one append-only publication record |
| `PROJECT#<project_id>` | `CONTRIBUTOR#<contributor_id>` | one contributor |
| `PROJECT#<project_id>` | `CONTRIBUTION#<contribution_id>` | one contribution |
| `PROJECT#<project_id>` | `INSIGHT#<0-padded revision>` | one connection-insight revision |
| `PROJECT#<project_id>` | `ASSET#<asset_id>` | project→asset link (child item, not a list-in-blob) |
| `PROJECT#<project_id>` | `UPLOAD#<upload_id>` | one upload record |
| `ASSET#<asset_id>` | `META` | catalog asset |
| `JOB#<job_id>` | `META` | one durable job, with `gsi1pk=PROJECTJOBS#<project_id>` (batch polling) and `gsi2pk=JOBQ#<status>` (the claim query), both ordered by `<created_at>#<job_id>` |

Zero-padded sort keys keep ordered `Query` results (blueprints, publications,
insights) in creation order. Blueprint revisions and publication records are
never overwritten. A project's contributions/contributors/uploads/jobs are
always queried by project (`_query_children`/GSI1, one `Query` per project,
paginated with `LastEvaluatedKey`) and then filtered client-side by the
account that owns them (`Contributor.clerk_user_id`,
`UploadRecord.uploader_user_id`) — the two hardcoded demo accounts never
need a separate cross-project index for this, since every route is already
scoped to one project.

Both store backends persist metadata only. Reconstruction artifacts (PLY,
mask, preview) go through `backend/artifact_store.py`, selected by
`SKETCHSCAPE_ARTIFACTS_BACKEND`: `local` (default, the data directory) or
`s3` (`S3ArtifactStore`, presigned-redirect serving, live-verified). Upload
input bytes (source photos, masks) go through the same `ArtifactStore` via
`put_upload`/`open_upload` under a separate `uploads/<project_id>/<upload_id>/`
key prefix (distinct from `artifacts/<job_id>/`) so more than one API
instance, and the GPU worker, can all reach the same upload — see
`infra/aws/main.tf`'s `artifacts_bucket` IAM policy, which must grant both
prefixes. The full planned data layout is in `docs/DATA_ARCHITECTURE.md`.

## Cloud backend activation (Build Plan step 10)

Everything above is code-side prep, verified offline with `moto` — **no real
AWS resource has been touched or paid for.** Turning the cloud backends on
against the real, already-provisioned `sketchscape-authoring` table and
`sketchscape-artifacts-*` bucket is a separate, irreversible-adjacent action
that costs real (if small) money and must not be done without the person's
explicit approval first — see `AGENT.md`'s hard rules and the
`gpu-cloud-activation` skill. This section is the checklist for *that*
person to run later; it is not run as part of this change.

### Env vars this backend reads for cloud mode

| Variable | Values | Read by |
| --- | --- | --- |
| `SKETCHSCAPE_STORAGE_BACKEND` | `local` (default) \| `dynamodb` | `storage.create_store` |
| `SKETCHSCAPE_DYNAMODB_TABLE` | the table name, e.g. `sketchscape-authoring` | `storage.DynamoDbStore` (required when the backend above is `dynamodb`) |
| `SKETCHSCAPE_ARTIFACTS_BACKEND` | `local` (default) \| `s3` | `artifact_store.create_artifact_store` |
| `SKETCHSCAPE_ARTIFACTS_BUCKET` | the bucket name, e.g. `sketchscape-artifacts-<random>` | `artifact_store.S3ArtifactStore` (required when the backend above is `s3`) |
| `AWS_REGION` | e.g. `us-east-2` | both backends above; optional — falls back to the standard AWS credential/region chain if unset |

There is no separate env var for AWS credentials: both backends use the
standard `boto3` credential chain (an EC2 instance role in the deployed
case, per `infra/aws/main.tf`'s `aws_iam_role.instance`). Never put an AWS
access key in `/etc/sketchscape.env`, Unity, or the web app.

### Step-by-step activation checklist

1. **Get explicit approval** for this specific action before doing anything
   below — it is not covered by having approved code changes or a prior
   Terraform review.
2. Confirm the table/bucket are already provisioned (per `AGENT.md`'s "what
   is fully built" table, they should be — this does **not** need a new
   `terraform apply` unless `infra/aws/DATA_ARCHITECTURE.md`'s GSI1/GSI2
   change or this change's IAM-policy fix (see below) haven't been applied
   yet, in which case that specific `terraform apply` also needs its own
   explicit approval):
   ```bash
   cd infra/aws
   terraform output -raw dynamodb_table_name
   terraform output -raw artifacts_bucket
   ```
3. **If the IAM policy fix in this change hasn't been applied to the real
   AWS account yet**, apply it before activating — otherwise the API will
   get `AccessDenied` on every upload (`uploads/` prefix) or every job poll
   (`gsi1`/`gsi2` index Query), instead of the base `artifacts/` PLY path
   that was previously the only thing exercised:
   ```bash
   cd infra/aws
   terraform plan   # review: only the two aws_iam_role_policy resources should change
   terraform apply  # requires its own explicit approval
   ```
4. Run the **live** smoke test (real AWS, real (small) cost, self-cleaning)
   from `backend/`, following `infra/aws/SMOKE_TEST_GUIDE.md` exactly:
   ```bash
   SKETCHSCAPE_DYNAMODB_TABLE=$(terraform -chdir=../infra/aws output -raw dynamodb_table_name) \
   SKETCHSCAPE_ARTIFACTS_BUCKET=$(terraform -chdir=../infra/aws output -raw artifacts_bucket) \
   AWS_REGION=$(terraform -chdir=../infra/aws output -raw aws_region) \
   python ../scripts/smoke_test_aws_storage.py
   ```
   This is the one thing the offline `moto` tests cannot confirm: that the
   real table actually has GSI1/GSI2 provisioned and the real bucket's IAM
   policy actually permits both the `artifacts/` and `uploads/` prefixes.
5. Only once step 4 passes, set the env vars from the table above on the
   **running** API process (`/etc/sketchscape.env` on the EC2 host, or the
   process environment locally) and restart it:
   ```bash
   sudo grep -E 'SKETCHSCAPE_(STORAGE|DYNAMODB|ARTIFACTS)|AWS_REGION' /etc/sketchscape.env
   sudo systemctl restart sketchscape.service
   curl -s http://127.0.0.1:8000/health
   ```
6. Confirm a real end-to-end request (project create, an upload, a poll)
   against the running process, then stop here — nothing further is
   automated, and no GPU instance needs to be running just to activate
   these two backends.

None of steps 1–6 were run as part of this change; no AWS credentials were
used and no network call was made producing it.

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
