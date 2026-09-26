# Build plan and next steps

## Completed foundation

- Job-based FastAPI contract: upload, polling, artifact serving, scene JSON,
  and safe sample edit.
- Mock mode for a fully free, repeatable portal demo.
- Isolated worker scripts for prompt-driven SAM 3.1 masking and staged
  Fast-SAM3D reconstruction.
- Terraform and an EC2 bootstrap design with SSM access and a bounded
  auto-stop timer.
- Unity job client that uses the current API rather than the legacy `/sketch`
  endpoint.

## Build in this order

1. **Prove the desktop experience locally.** Start the backend in `mock` mode,
   set Unity's API base URL to `http://127.0.0.1:8000`, and record a short
   portal-reveal video. This is the base demo.
2. **Create two beautiful precomputed scenes.** Use the already-successful
   Fast-SAM3D outputs or handcrafted Unity assets. Give the UI a demo picker
   so connectivity/model failure cannot ruin judging.
3. **Choose and test one Gaussian-splat renderer.** Add it to Unity in an
   isolated branch, then implement its adapter behind `GaussianSplatBridge`.
   Do not change the API contract for renderer-specific code.
4. **Run one deliberate AWS smoke test.** Start the stopped instance, test SSM
   and `nvidia-smi`, then stop it. Only after that bootstrap models using the
   explicit AWS runbook. Never test with a live judge-facing flow first.
5. **Run one real object end to end.** Supply a centred photo plus short noun
   phrase (for example `red backpack`). Save the PLY, mask, preview, elapsed
   time, and failure logs.
6. **Harden the demo.** Put a 90-second UI timeout around live jobs, surface
   `mask_review`, provide a visible fallback button, and stop EC2 immediately
   after tests.

## Deferred by design

- Multi-user queues, persistent DynamoDB/S3 job state, authentication, and
  mobile AR. They are valuable post-hackathon but would reduce demo reliability.
- Fully automatic multi-object segmentation. The current product contract is
  one prominent object or a user-provided mask.
- Live Notability automation. Export/share an image into Unity instead.

## Definition of done for judging

- A judge can select a photo, enter a noun phrase, and see a clear progress
  state.
- An offline instant-showcase scene and a mock reconstruction both reliably
  open through the portal.
- “Make the tree twice as tall” visibly changes the world.
- The UI truthfully distinguishes real SAM3D output from fallback content.
