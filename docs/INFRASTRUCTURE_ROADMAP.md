# Infrastructure roadmap

## Target architecture and boundaries

The target is a versioned authoring pipeline, not a direct model-to-Unity shortcut:

```text
multiple images / sketches / prompts
  -> SAM 3.1 segmentation per view (release segmentation VRAM)
  -> Fast-SAM3D reconstruction
  -> project asset catalog (stable asset_id plus provenance and artifacts)
  -> NemoClaw planning in a development sandbox
  -> versioned experience blueprint (authoring source of truth)
  -> validate and publish immutable revision [approval required]
  -> Unity editor experience builder (authoring time)
       -> generated scenes/assets/interactions/environment
       -> OpenXR Meta Quest configuration
       -> optional AR Foundation adapter
  -> compile + EditMode/adapter tests + deterministic screenshots
  -> human/agent review -> revised blueprint -> repeat
  -> standalone APK/build with no NemoClaw, MCP, or authoring-backend dependency
```

`shared/experience-blueprint.schema.json` defines the target authoring contract. Published blueprint revisions, rather than mutable Unity scene state, are the source of truth. Generated Unity scenes and platform-specific settings are compiler outputs and must remain reproducible from a blueprint revision and its referenced asset catalog entries.

NemoClaw and Unity MCP remain development control-plane tools. NemoClaw drafts and revises blueprints; Unity MCP invokes bounded **editor-time** scene generation, screenshot, test, and build tasks. The final scene is authored and saved before the player is built. Neither service runs while an end user experiences the result, and the player has no model, AWS, NemoClaw, MCP, or authoring-backend dependency.

The repository now implements the first vertical slice: projects, multiple single-view reconstruction-backed catalog assets, validated/versioned blueprints, publication, an append-only publication log, base-scene compilation, and a Unity component that loads the published scene. This authoring state is now durably persisted to a single-process, JSON-file-backed local store (`backend/storage.py`) that survives an API restart and exposes the surface a future S3/DynamoDB backend would implement. True multi-view fusion, concurrency-safe cloud durability, screenshot-driven revision, Gaussian-splat rendering, OpenXR, and AR Foundation adapters remain future work.

## Implemented repository foundation

- `infra/aws`: one encrypted `g4dn.xlarge` (16 GiB T4 by default), SSM-only administration, restricted API ingress, private bundle bucket, IMDSv2, and a recurring boot-time shutdown guard.
- `scripts/aws_preflight.sh`: read-only authentication, CIDR, formatting, and Terraform readiness checks.
- `config/nemoclaw/mcp-servers.example.json`: credential-free desired MCP server inventory; it is intentionally not assumed to be a NemoClaw CLI import format.
- `config/nemoclaw/sketchscape-tools.json`: credential-free desired HTTP/menu-task inventory, with per-operation implementation and approval status; it is documentation, not a claimed native import format.
- `shared/experience-blueprint.schema.json`: JSON Schema for versioned, platform-neutral experience plans; the backend mirrors and validates this contract with typed models.
- `backend/storage.py`: one `AuthoringStore` surface with two backends for projects, catalog assets, blueprint revisions, and an append-only publication log. `LocalJsonStore` (default) uses atomic replace-on-write and quarantines a corrupt snapshot instead of crashing startup. `DynamoDbStore` (selected by `SKETCHSCAPE_STORAGE_BACKEND=dynamodb`) provides concurrency-safe cloud durability via a single-table `pk`/`sk` layout with ordered sort keys; `boto3` is imported lazily and stays an optional dependency. Both backends are **live-verified** against real AWS (`scripts/smoke_test_aws_storage.py`). Reconstruction jobs stay in memory by design.
- `backend/artifact_store.py`: one `ArtifactStore` surface with `LocalArtifactStore` (default) and `S3ArtifactStore` (lazy boto3, presigned-URL redirect serving). Both backends **live-verified**. Selected by `SKETCHSCAPE_ARTIFACTS_BACKEND`.
- `config/unity/sketchscape-scene.profile.json`: current scene desired state and acceptance checks for manual or MCP-driven setup.
- Unity `NamedSceneInteractive`, `SceneInteractionController`, and `SketchScapeMcpBridge`: an ID registry and bounded action bridge shared with the backend contract.
- Unity `SketchScapeExperienceCompiler`: a Play-mode preview path for a published base scene.
- Unity `SketchScapeOfflineExperienceBuilder` and `BuiltExperienceController`: editor-time scene materialization and backend-free runtime ownership.
- Unity `SketchScapeQuestBuild` and `SketchScapeOpenXRConfigurator`: pinned OpenXR Meta packages, ARM64/IL2CPP/Vulkan settings, Android OpenXR setup, readiness validation, and no-device APK build command.
- UnitySplats v1.2.0 plus `scripts/export_unity_experience.py`: pinned Quest-capable PLY renderer and a safe export path that packages published artifacts by object ID.
- XRI 3.0.11 Starter Assets and XR Device Simulator: generated scenes can use a configured rig and desktop simulation instead of an ad-hoc camera scaffold.
- `.agents/skills/sketchscape-infrastructure`: repository-specific operational guardrails for compatible coding agents.

## NemoClaw setup (manual approval required)

NemoClaw is a sandbox manager for supported agents using NVIDIA OpenShell. Do not install it on the GPU inference host merely to run SAM models.

1. Choose the supported agent runtime (OpenClaw, Hermes, or LangChain Deep Agents Code).
2. Follow the current official onboarding guide. NemoClaw changes quickly, so do not pin an installer command copied from an old runbook.
3. Optionally load NVIDIA's official `nemoclaw-user-*` skills from the NemoClaw repository. Keep the SketchScape skill in this repository.
4. Register the official documentation MCP endpoint only if documentation lookup is needed.
5. Start Unity locally and determine the Unity MCP implementation's actual endpoint and transport.
6. Register Unity MCP as a **trusted-private** target. Review DNS/address pins and advertised tools before enabling write groups.
7. Permit only the hosts needed for the selected inference provider, NemoClaw docs, GitHub package retrieval, and AWS APIs. Deny arbitrary egress.
8. Keep credentials in NemoClaw/OpenShell credential providers; never place them in this repository or an MCP manifest.

The inventories in `config/nemoclaw/mcp-servers.example.json` and `config/nemoclaw/sketchscape-tools.json` record intent only. They contain no credentials and are not claimed to be native NemoClaw import formats. Use the current agent-specific NemoClaw commands to register and inspect actual tools, because command names and adapters differ by selected runtime. GPU start/use, bundle or blueprint publication, and any other operation marked `approval_required` require explicit human approval.

## Unity MCP and scene configuration

The Unity project currently lives outside this repository, so scene mutation must be performed from that project with Unity open.

1. Choose either Unity's official MCP server (requires its current Unity AI prerequisites) or a reviewed third-party package such as CoplayDev MCP for Unity. Pin a release; do not track a moving `main` branch for the demo.
2. Keep the bridge bound locally. Do not expose it on the public EC2 security group.
3. Ask MCP for a read-only hierarchy, active scene path, compile status, and component inventory.
4. Save/checkpoint the active scene.
5. Reconcile it against `config/unity/sketchscape-scene.profile.json`; do not invent object references when multiple candidates exist.
6. Save, compile, inspect console errors, run EditMode tests, and then exercise the mock API.
7. Add `GaussianSplatBridge` only after a renderer can load runtime Gaussian-splat PLY files. `glTFast` is not sufficient.

## AWS GPU rollout

1. Run `./scripts/aws_preflight.sh` (read-only).
2. Run `terraform init`, `terraform plan`, and review estimated resources. No apply is automated.
3. Apply only after checking GPU quota/capacity and cost in the selected region.
4. Verify SSM and `nvidia-smi`, then stop the instance.
5. In a separate bounded session, publish the bundle and bootstrap with a temporary approved Hugging Face token.
6. Smoke-test SAM 3.1 alone, release it, then smoke-test Fast-SAM3D using one known image/mask.
7. Run one end-to-end callback, retain timings and non-secret logs, and stop the instance.

A T4 has 16 GiB VRAM. The supported path is staged and sequential. The official full SAM 3D setup may require more memory; do not replace staged loading until it is benchmarked. If capacity or memory is insufficient, use `g5.xlarge` rather than silently reducing correctness.

## Next implementation slices

1. **Durable multi-view asset catalog:** projects and catalog assets persist across restarts through `AuthoringStore`, with both a local JSON backend (`LocalJsonStore`) and a DynamoDB backend (`DynamoDbStore`). The DynamoDB table (`sketchscape-authoring`, PAY_PER_REQUEST, PITR, AES-256 SSE, deletion-protection policy) is provisioned and **live-verified** against real AWS via `scripts/smoke_test_aws_storage.py` — all 9 DynamoDB checks passed. Each `ProjectAsset` now carries a `views: list[AssetView]` list tracking per-view image key, subject hint, reconstruction job ID, status, artifact URL, and mask URL. `POST /v1/projects/{id}/assets/{asset_id}/views` adds additional angles; `GET …/views` exposes the full provenance list. The asset promotes to READY from the first successful view; a failed additional view never demotes a READY asset. Remaining work: define and implement how multiple READY views fuse into one consolidated Fast-SAM3D asset (the multi-view fusion step in the target pipeline).
2. **Durable blueprint service:** blueprint revisions, the publication pointer, and an append-only publication log persist through the same store on either backend. The S3 artifacts bucket (`sketchscape-artifacts-…`) is provisioned and **live-verified** — all 9 S3 checks passed, including presigned redirect serving. `SKETCHSCAPE_ARTIFACTS_BACKEND=s3` routes PLY/mask/preview writes to S3. Remaining work: enforce human approval in the deployment control plane and deploy the cloud backends to the EC2 host (Step 5 in `infra/aws/SMOKE_TEST_GUIDE.md`).
3. **Unity offline authoring:** extend the implemented generated-scene builder with real packaged Gaussian-splat assets, portals, audio, progression, imported XR Interaction Toolkit starter assets, and deterministic screenshots. The Play-mode compiler remains preview-only.
4. **Review loop:** add bounded Unity MCP menu tasks for compile, deterministic screenshots, compile/EditMode/adapter tests, and revision feedback. Failed review creates a new draft; it never mutates a published revision.
5. **Platform adapters:** retain desktop support, then add OpenXR for VR navigation/input and AR Foundation for surface placement/world anchors. Keep platform details out of the neutral blueprint except for declared mode and navigation policy.
6. **Unity project access:** install/pin the selected MCP package, reconcile the real active scene, and commit its package lock/scene changes in the Unity repository.
7. **Renderer verification:** benchmark the pinned UnitySplats adapter with real Fast-SAM3D PLYs, cap/LOD splat counts for Quest, and add importer/scene EditMode tests. Hardware performance remains unverified.
8. **GPU smoke evidence:** ✅ **Fully verified end-to-end on NVIDIA L40S (g6e.xlarge, us-east-2, 45 GB VRAM).** The persistent worker server (`worker/worker_server.py`) loads all Fast-SAM3D checkpoints once at startup (~2 min cold start), then accepts jobs over loopback with zero per-job cold-start penalty. Verified result: a real **53 MB Gaussian-splat PLY (814,432 vertices)** produced in **70 seconds total** — SAM 3.1 segmentation 42s + MoGe depth 2.8s + sparse structure 1.5s + SLaT + decode. Pipeline confirmed as `sam3d`, source `sam3d`. Instance is stopped. Three bugs found and fixed during live verification: `ModuleDict` key access (`[]` not `.get()`), pytorch3d `look_at_view_transform` float32 conflict (autocast scoped to MoGe only), `ss_return["scale"]` tensor aliasing (`.clone()` before in-place multiply).
9. **Durability (post-demo):** replace in-memory jobs/local artifacts with S3 plus DynamoDB/SQS before introducing more than one API process.
10. **Public deployment hardening:** terminate TLS, add client authentication/rate limits, and stop exposing Uvicorn directly before any non-demo use.

## Non-goals for the first deployment

- Letting an agent modify production AWS resources autonomously.
- Giving Unity builds AWS/Hugging Face/worker credentials.
- Calling Unity MCP from a shipped player.
- Running concurrent jobs on one 16 GiB GPU.
- Claiming PLY rendering before a renderer is selected and tested.
