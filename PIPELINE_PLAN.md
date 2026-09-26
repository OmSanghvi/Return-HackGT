# SketchScape: reconstruction pipeline

How one photo becomes a Gaussian-splat PLY. This is the plumbing under
Shared Room; for the product and the ordered plan, see `AGENT.md` and
`docs/BUILD_PLAN.md`.

## Flow today (one object per job)

```text
Client upload (POST /v1/reconstructions or /v1/projects/{id}/assets)
  -> API validates the image and creates a job (202 + poll_url)
  -> subject_hint: typed by the person, or labelled by identify_subject
     (mock today; NemoClaw later, Build Plan step 4a)
  -> PIPELINE_MODE=mock: deterministic scene labelled `mock`, no GPU
  -> PIPELINE_MODE=aws-local: worker_server.py on the EC2 GPU host
       SAM 3.1 concept mask from subject_hint  (memory released)
       -> staged Fast-SAM3D -> PLY + mask + preview
       -> private worker callback to the API
  -> client polls GET /v1/reconstructions/{job_id} and loads asset_url
```

The API owns validation, job state, scene JSON, and artifact URLs. The GPU
worker owns model dependencies and the worker token. Unity and the web app
never hold an HF, AWS, or worker credential.

**Verified:** end-to-end on an NVIDIA L40S (g6e.xlarge, us-east-2): 70 s
total (42 s SAM 3.1 + 28 s Fast-SAM3D), a 53 MB, 814,432-vertex PLY.
`worker/worker_server.py` loads the models once, so there's no per-job
cold start.

## Constraints

- **Within a job, SAM 3.1 and Fast-SAM3D never hold GPU memory at the same
  time** (AGENT.md Hard Rule 5). `SKETCHSCAPE_GPU_CONCURRENCY` stays at 1
  until an approved VRAM benchmark on that instance type; a T4 always stays
  at 1.
- A missing or ambiguous subject never gets a guessed mask. The job goes to
  `mask_review` instead of spending GPU time on the wrong object.
- The output is a Gaussian-splat PLY, not a GLB. Unity renders it with
  UnitySplats.
- Failed objects are left out of the room, never replaced with placeholder
  primitives (Hard Rule 7).
- Jobs still live in the API process's memory, and uploads on its disk. Run
  one API process until durable jobs land (Build Plan step 26).

## What's planned next

- **Several objects per photo, chosen by the person** (Build Plan steps
  20, 26–27): the person clicks, boxes, or names each object on the
  website. One SAM 3.1 pass masks exactly those; then one Fast-SAM3D job
  runs per object through durable, leased jobs and a GPU-host dispatcher.
- **Notability sketches** (step 7): shown as a flat card, or reconstructed
  as a 3D memory plaque through this same pipeline. There is no
  image-generation step.
- **Cloud backends on the EC2 API** (step 10): DynamoDB and S3 are
  provisioned and verified; only the env vars on the host remain.

## Worker callback

The GPU worker posts multipart data to:

```text
POST /v1/internal/reconstructions/{job_id}/result
result={"status":"complete","object_label":"vase"}
worker_token=<private shared secret>
ply=@reconstruction.ply
mask=@mask.png
preview=@mask-preview.png
```

The backend only marks a job `complete` after both the PLY and the mask
arrive. For an unclear mask it posts `{"status":"mask_review", ...}`, and
for a failure `{"status":"failed","error":"..."}`. The worker reads its
inputs from `GET /v1/internal/reconstructions/{job_id}/input/{image|mask}`
and `/task` with the `X-SketchScape-Worker-Token` header. The exact result
shape is in `backend/worker_contract.json`.

## Acceptance checks

- Uploading PNG/JPEG/WebP returns `202` and a pollable job ID.
- A completed worker callback exposes a downloadable PLY and records
  `source: sam3d` in the scene.
- Clients never block while polling.
- No token appears in a Unity build, the web app, source control, a scene
  JSON response, or an asset URL.
