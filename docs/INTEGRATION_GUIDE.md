# SketchScape integration guide

## Current integration versus target authoring flow

Sections 1–7 cover both the desktop demo and the first orchestration slice. Project/catalog APIs, typed blueprint validation/versioning/publication, an append-only publication log, base-scene compilation, and the Unity published-experience loader are implemented, with authoring state durably persisted through `backend/storage.py` (local JSON by default; DynamoDB and S3 backends are implemented and live-verified, but not yet switched on for the EC2 API). NemoClaw planning automation, review screenshots, and AR Foundation adapters are not yet implemented. For the ordered plan, see `docs/BUILD_PLAN.md`.

The target data flow is:

1. A project supplies multiple images, sketches, and optional text prompts.
2. SAM 3.1 segments each view; its memory is released before Fast-SAM3D reconstructs a reusable catalog asset with a stable `asset_id`.
3. NemoClaw uses only approved development tools to draft a versioned `shared/experience-blueprint.schema.json` document referencing catalog assets.
4. Validation checks schema, asset references, interaction allowlists, and platform constraints. Publishing an immutable revision requires approval; the published blueprint is the authoring source of truth.
5. A Unity **editor-time builder** reproducibly creates and saves scene/assets from that revision. OpenXR supplies Meta Quest VR input/navigation; AR Foundation can later supply surface placement/world anchors.
6. Unity compiles, runs EditMode and adapter tests, and captures deterministic review screenshots. Review feedback produces a new blueprint revision and repeats the authoring loop.
7. Unity builds a standalone APK. At runtime the authored scene needs no NemoClaw, MCP, reconstruction service, or authoring backend.

`config/nemoclaw/sketchscape-tools.json` documents the credential-free HTTP and Unity MCP inventory, including per-tool implementation status. It is not a claimed native NemoClaw import file. Operations marked `approval_required`, including GPU start/use and publication, must stop for explicit human approval.

## 1. Local, no-cost desktop demo

This is the only path required to work on Unity today. It never contacts AWS.

```bash
./scripts/start_mock_demo.sh
```

On its first local run only, the script creates `backend/.venv` and installs
the small FastAPI dependencies. It never installs SAM3D, downloads model
weights, or calls AWS.

Open `../HackGTUnity` in Unity 6. Select **Tools → SketchScape → Configure
Current Scene**. It adds `SketchScapeReconstructionClient` to the existing
loader object, but does not start a request. Assign the existing Tree, House,
and Portal references on `SketchSceneLoader` if they are blank.

### Equivalent Unity CLI setup

With Unity closed, this local batch-mode command compiles the project, adds
the SketchScape components to the active scene, and saves it. It does **not**
start the FastAPI server, a GPU, or AWS:

```bash
"/Applications/Unity/Hub/Editor/6000.2.10f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath /Users/shruti/HackGTUnity \
  -executeMethod SketchScapeSetupMenu.ConfigureCurrentScene \
  -logFile /Users/shruti/HackGTUnity/Logs/sketchscape-cli-setup.log
```

If Unity is installed at another path, replace only the first quoted path.

Set:

- **API Base URL:** `http://127.0.0.1:8000`
- **Loader:** the `SketchSceneLoader` component in the scene
- **Input texture:** `Assets/Resources/hackgttest.jpg`, or assign your own
  readable `Texture2D`
- **Subject hint:** a short noun phrase such as `blue backpack`

Enter Play mode and click **Reconstruct sketch**. The backend returns an
honest `pipeline: mock` scene, which the loader reveals through the portal.

To test any photo without adding it to Unity assets, paste or drag its local
PNG/JPEG/WebP path into **Optional: Use Any Local Photo**, click **Load photo
path**, then reconstruct. The photo stays local and is sent only to the API
base URL you configured.

The **Instant Showcase Worlds** panel is the judging-safe fallback. It opens
one of three local scenes through the same portal animation without uploading
or contacting the API. Use it for the opening hook, then demonstrate mock or
real reconstruction as the second beat.

The **Furniture Portal (Blender)** button loads the curated room exported from
`Furniture_FREE.blend`; it is your polished opening destination and is fully
local. Its reproducible export script is
`scripts/export_furniture_portal_world.py`.

If Unity runs on a different device, replace `127.0.0.1` with the laptop's
LAN IP and start Uvicorn with `--host 0.0.0.0`. This is for local trusted demo
networks only.

## 2. Current API contract

The legacy-compatible reconstruction contract remains available. Project-scoped clients should use `POST /v1/projects`, then multipart `POST /v1/projects/{project_id}/assets`, and list readiness through `GET /v1/projects/{project_id}/assets`. `POST /v1/reconstructions` is multipart:

```text
image=<PNG/JPEG/WebP>
mask=<optional matching PNG mask>
subject_hint=red backpack
```

It returns:

```json
{
  "job_id": "...",
  "status": "queued",
  "poll_url": "/v1/reconstructions/...",
  "scene_url": "/v1/scene"
}
```

Poll the returned URL. Terminal states are `complete`, `mask_review`, and
`failed`. A complete result includes a scene with `asset_url`, never `asset`.

## 3. Named interactives and safe actions

Spawned Unity objects receive a `NamedSceneInteractive` identity matching the
backend scene object ID. `SceneInteractionController` owns the runtime registry
and submits only `scale_by`, `translate_by`, or `rotate_by` to
`POST /v1/scene/actions`. The backend remains the policy authority and returns
the complete updated scene.

**Per-contributor edits (Build Plan step 8).** A compiled project scene carries
a social manifest at `scene.meta.social` (`shared/social-manifest.schema.json`)
saying which contributor owns each object. Set `SceneInteractionController`'s
active contributor (`SetActiveContributor`) and every action it sends includes
`contributor_id`; the backend then returns `403` for any object not attributed
to that contributor. Requests without `contributor_id` (MCP/editor authoring)
are unaffected. The id is self-asserted until the room API (step 21) replaces
it with the account the headset authenticated as (the hardcoded-account
header — no room token; see `collab-vr-accounts-and-gates`). The offline
builder adds a `ContributorAttribution`
component per attributed object, which draws a glowing base ring in the
contributor's color — attribution is diegetic, never a name tag or panel.

The Unity project also includes `SketchScapeMcpBridge` and constrained menu
entries under **Tools → SketchScape → MCP**. MCP automation may inspect the
registry or execute the bridge's configured safe action; it cannot name an
arbitrary component, method, or property. Keep **Route Through Backend** enabled
in Play mode so MCP and user actions use the same policy and scene state.

## 4. Real GPU path—only when explicitly ready

No action in this document starts AWS. The provisioned Terraform state and
stopped instance are intentionally left alone.

When you explicitly choose to test, follow `infra/aws/README.md` in this
order: start → SSM/nvidia test → stop; then separately start → publish bundle
→ bootstrap with a manually supplied `HF_TOKEN` → test a single object → stop.

AWS Budget alerts may be delayed and are not a hard spend cap unless a Budget
Action has been configured. The instance's Linux shutdown timer is a separate
backup, not a replacement for manually stopping the GPU.

## 5. Gaussian splats in Unity

The backend returns a `.ply` for real reconstruction. `glTFast` only loads
GLTF/GLB; it cannot render Gaussian-splat PLY files. The chosen renderer is
UnitySplats (section 6), used by the offline builder. For the Play-mode
loader, attach an adapter component with a public `LoadPly(string url)`
method to the same GameObject as `GaussianSplatBridge`; the bridge calls it
only for `.ply` artifacts. No adapter is attached yet, so Play mode keeps
its demo fallback. That fallback is for the desktop demo only; the VR room
never shows placeholder primitives (AGENT.md Hard Rule 7).

## 6. Offline authoring and Meta Quest

Export the published scene and package all referenced PLY files with:

```bash
./scripts/export_unity_experience.py \
  --project-id <published-project-id> \
  --unity-project ../HackGTUnity
```

This writes `Assets/SketchScape/Authoring/compiled-scene.json` and one
`Artifacts/{object-id}.ply` per reconstructed object. Then invoke **Tools →
SketchScape → Authoring → Build Offline Experience Scene** (or the matching MCP
menu command). Unity creates
`Assets/Generated/SketchScape/Scenes/Experience.unity`, adds it to build
settings, and records source project/revision metadata. The generated scene is
the build input; `SketchScapeExperienceCompiler` is only a Play-mode preview
path.

The project pins Unity OpenXR Meta, OpenXR, XR Plug-in Management, and XR
Interaction Toolkit. Quest configuration uses Android ARM64, IL2CPP, Vulkan,
linear color, and a 72 Hz runtime target. Build readiness and a no-device APK
build are under **Tools → SketchScape → Quest**.

This machine currently lacks Unity Android Build Support, SDK/NDK Tools, and
OpenJDK. Install those modules through Unity Hub, rerun **Enable Android
OpenXR**, then run validation and **Build APK Without Device**. Import XRI Starter Assets and the XR Device Simulator using **Tools →
SketchScape → Quest → Import XRI Starter Assets and Simulator**. Generated
scenes use the configured XRI rig prefab, including controller actions and
locomotion setup, while the simulator supports desktop input checks.

A successful APK build verifies compilation and packaging only; controller
input, tracking, comfort, Gaussian-splat performance, and visual quality remain
unverified without Quest hardware.

The project pins MIT-licensed `UnitySplats` v1.2.0, which imports packaged PLY
files and supports Unity 6, XR, Android Vulkan, and a CPU sorting fallback. The
offline builder creates `GsplatRenderer` objects for successfully imported local
PLYs and, today, semantic primitives when an expected local artifact is
missing. That fallback breaks AGENT.md Hard Rule 7 and is removed in Build
Plan step 11 (missing objects are skipped).
Quest readiness fails while any remote reconstruction placeholder remains.
Quest rendering is still hardware-unverified and splat counts must be profiled
on the target device.

## 7. Blueprint and platform contract

The blueprint schema is `shared/experience-blueprint.schema.json`; the backend mirrors it with typed validation and durably persisted revisions (see `backend/storage.py`). It fixes units to meters and records experience mode (`desktop`, `ar`, `vr`, or `ar_vr`), environment, catalog-backed objects, allowlisted interactions, portals, and navigation policy. `shared/scene.schema.json` remains the currently implemented runtime response contract; the two schemas are not interchangeable.

Compiler/adapters must apply these ownership rules:

- The published `(project_id, revision)` blueprint and referenced catalog entries are authoritative.
- The Unity compiler may derive GameObjects, renderer bindings, colliders, interaction components, and platform settings, but generated state must be reproducible and must not silently change the blueprint.
- The desktop adapter uses ordinary screen/input controls. The OpenXR adapter maps blueprint VR navigation to teleport, smooth locomotion, or none. The AR Foundation adapter maps AR navigation to surface placement, world anchors, or none.
- A compiler or adapter failure blocks publication/deployment feedback and creates a proposed next revision; it must not patch an already published blueprint.
- Screenshot review complements compile and automated tests; it does not replace them.

## 8. Secrets and files

- Keep `HF_TOKEN`, AWS credentials, and `SKETCHSCAPE_WORKER_TOKEN` outside
  source control. Root `.gitignore` now protects common local forms.
- Do not commit `infra/aws/terraform.tfstate`, `terraform.tfvars`, plans, PLYs,
  model weights, logs, or `token.txt`.
- Keep the current user-facing runtime scene schema in `shared/scene.schema.json`; changing it requires matching backend and Unity changes.
- Treat `shared/experience-blueprint.schema.json` as the authoring contract. Keep backend models and Unity compiler behavior synchronized with it, and add explicit schema versioning before persistent deployments.
- Keep `config/nemoclaw/sketchscape-tools.json` credential-free. It describes desired operations only and must not be presented as runtime state or a native import format.
