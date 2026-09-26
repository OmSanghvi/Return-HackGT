# SketchScape: demo-safe reconstruction pipeline

## Product flow

```text
Unity photo upload
  -> SketchScape API creates a job
  -> GPU worker auto-selects one centred object
  -> SAM 3D Objects produces a Gaussian-splat PLY
  -> worker privately uploads PLY + mask + preview
  -> Unity polls job, downloads PLY, triggers portal reveal
```

The API owns validation, job state, scene JSON, and artifact URLs. The GPU
worker owns model dependencies and secrets. Unity owns the user experience and
must never contain an HF or cloud token.

## Explicit constraints

- SAM 3D Objects requires an image and an aligned object mask. Automatic mask
  selection is reliable only for one prominent, centred object; multi-object
  images need a one-tap/box choice rather than a silent guess.
- The native SAM 3D output is a Gaussian-splat PLY, not a GLB. Unity therefore
  needs a splat renderer that can load a runtime PLY, or a separate conversion
  stage.
- A Camber L4 has 24 GB VRAM. Use the already-tested staged/Fast-SAM3D runtime
  first; do not promise the full official model will fit or compile until it is
  benchmarked in the Camber image.

## What exists now

- `backend/main.py`: working upload, job polling, artifact-serving, safe scene
  edit, and authenticated worker callback API.
- `backend/worker_contract.json`: the exact result a GPU worker must emit.
- `worker/run_job.py`: a token-protected Camber-compatible job entrypoint that
  pulls the image, executes the pre-baked staged runner, and streams back PLY
  artifacts without loading them all into memory.
- `worker/bootstrap_fastsam3d.sh`: one-time persistent GPU bootstrap with pinned
  dependencies, cached weights, and an import preflight. It is never invoked by
  a live reconstruction request.
- `shared/scene.schema.json`: the Unity/backend scene contract.
- `PIPELINE_MODE=mock`: a deliberate fast fallback for the portal reveal. It
  labels its scene `pipeline: mock`; it does not pretend a PLY was generated.

## Delivery order

1. **Unity contract (next)** — point Unity at `/v1/reconstructions`, show a
   bounded progress state, poll, load `asset_url`, then reveal the portal.
   Keep the placeholder scene as a one-click fallback.
2. **Camber worker smoke test** — bake the *known working* Fast-SAM3D
   environment into one image/volume, cache model weights, reconstruct one
   supplied object, and post a real PLY through the worker callback.
3. **Automatic segmentation** — add a dedicated segmentation model/runtime
   isolated from Fast-SAM3D dependencies. Save `mask-preview.png`; if the
   candidate is ambiguous, return `mask_review` instead of spending GPU on the
   wrong object.
4. **Artifact persistence** — move in-memory jobs and local files to a shared
   store before relying on cloud jobs longer than a single API process.
5. **Demo hardening** — precompute two attractive examples, put a 90-second
   timeout on live inference, and automatically fall back to placeholders.

## Worker callback

After it creates an output, the GPU worker posts multipart data to:

```text
POST /v1/internal/reconstructions/{job_id}/result
result={"status":"complete","object_label":"vase"}
worker_token=<private shared secret>
ply=@reconstruction.ply
mask=@mask.png
preview=@mask-preview.png
```

The backend only changes a job to `complete` after both PLY and mask arrive.
For an uncertain automatic mask, it instead posts:

```json
{"status":"mask_review","object_label":"unknown"}
```

## Acceptance checks

- Uploading PNG/JPEG produces a `202` and a pollable job ID.
- A completed worker callback exposes a downloadable PLY and records
  `source: sam3d` in `GET /v1/scene`.
- Unity never blocks its render loop; it polls every 1–2 seconds.
- No token appears in a Unity build, source control, a scene JSON response, or
  an asset URL.
