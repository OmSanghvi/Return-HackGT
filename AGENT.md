# SketchScape — agent reference

Read this before touching anything. It tells you what the project is, what is
already built, what the rules are, and what to work on next.

**Doing implementation work right now? Go to `docs/BUILD_PLAN.md`.** It's the
concrete, ordered, step-by-step plan — every step names the exact files and
functions to touch and the `.claude/skills/<name>` skill that governs it.
This file (`AGENT.md`) explains the *why* and the standing rules; the build
plan is the *how* and the *what's next*.

---

## What this project does

**SketchScape / Shared Room** is a social product: two people who care about
each other each contribute one meaningful object (a photo or a Notability
sketch). AI infers why those two objects belong together — a shared theme, an
explanation, a placement rationale — and Unity turns that inference into one
explorable VR room the two of them can walk through on a Meta Quest headset.
The 3D reconstruction pipeline (SAM 3.1 → Fast-SAM3D → Gaussian-splat `.ply`)
is the plumbing underneath; the product is the connection the AI surfaces
between two people's contributions, not the reconstruction itself. Keep this
framing first in every doc, demo, and commit — see the primary competition
track below.

---

## Primary competition track: Meta — "Bringing People Closer Together with AI"

This is the track this repository is actively building for. `docs/PROJECT_STATUS.md`
is the authoritative, judge-facing status document for this track — read it
before doing any product work. `features.txt` at the repo root lists the exact
features to hit in the demo video. The summary here is only an agent-facing
pointer; do not let AGENT.md and PROJECT_STATUS.md drift apart.

**One-line pitch:** two long-distance friends, a couple, or family members
each contribute one meaningful object. AI figures out why those two objects
belong together, and Unity turns that connection into a room they can walk
through side by side — on a Meta Quest.

**Judging criteria and how this product answers them:**
- *Strengthens human connection* — the room is a private, spatial artifact of
  a relationship, not a feed post or message thread; it is meant to be
  revisited and extended (a third object later, an anniversary update).
- *AI is essential and well-integrated* — AI does three jobs a normal 3D
  editor can't: interpret an ambiguous photo/sketch, infer the shared theme
  between two people's contributions, and translate that theme into a room
  layout. The AI's reasoning must be perceivable — through the scene itself
  (lighting, staging, motion, sound, symbolic set dressing) or spoken
  narration — never hidden behind raw coordinates, and never reduced to a
  floating 2D text/HUD panel. See "The connection must be felt, not read"
  below.
- *Originality* — most "AI connection" submissions will be text/chat-based;
  this one is spatial and runs on Meta's own headset.
- *Strength of the demo* — one emotionally legible story, a working mock-mode
  path that needs no GPU or cloud credentials, one clean 2–3 minute video.

**What must exist for this track (see PROJECT_STATUS.md for full detail):**
- `Contributor`, `Contribution`, and `ConnectionInsight` records layered on
  top of the existing project/asset/blueprint contracts.
- `POST /v1/projects/{id}/connection/compose` — the endpoint that actually
  produces the shared theme, explanation, and placement rationale. This is
  the single most important missing piece; build the deterministic mock
  version first.
- **NemoClaw is the thing that actually understands and builds the scene —
  not a raw model API call.** `connection/compose` should invoke NemoClaw's
  own tools (`place_objects_in_scene`, optionally `read_sketch_layout`, and
  `stage_immersive_reveal`; see "NemoClaw integration" below) to produce the
  `ConnectionInsight` and the room layout together, since the theme and the
  staging come from the same reasoning pass. Do not build a separate
  standalone "composition backend" that bypasses NemoClaw and calls a model
  API directly — the tools *are* the composition mechanism.
- NemoClaw's underlying reasoning runtime defaults to a **Llama model**
  (Llama 4 Maverick/Scout — natively multimodal) for this track — submitting
  a Llama-backed agent to Meta's own challenge is a deliberate, judge-legible
  choice. **As of July 2026, Meta retired the public-preview Llama API** —
  there's no first-party Meta-hosted Llama endpoint anymore. Serve the model
  through a hosting provider (Together AI, Groq, or AWS Bedrock all offer
  current Llama 4 endpoints) or self-host it; confirm whichever host is
  chosen before implementing, since this landscape shifts. **Keep Grok
  configured as a switchable fallback runtime, not a deleted option**, for
  the alternate Resilience Commons framing below — this is a NemoClaw
  runtime/config choice (which model backs the agent's reasoning), not a
  second parallel API.
- The old **sketch → photorealistic image** pipeline is removed entirely —
  `POST /v1/sketches`, `backend/image_gen.py` (`mock`/`azure`/`hf`
  backends), and `backend/test_image_gen.py` are gone. Hallucinating a fake
  photorealistic object from a line drawing added a paid backend and a
  network hop for something a direct photo upload to `POST /v1/reconstructions`
  already does better and more honestly. **Do not reintroduce `image_gen.py`,
  an `azure`/`hf`/`grok` image-generation backend, `/v1/sketches`, or Meta
  Muse Image (still rejected on cost, moot now anyway).** A Notability
  sketch now takes one of two paths instead — direct display as a flat
  textured quad, or a SAM3D-reconstructed memory plaque with the
  contributor's memory text physically part of it — see `docs/BUILD_PLAN.md`
  step 7 and `sketch-image-gen-backends`. Neither is built yet.
- **The connection must be felt, not read.** Do not put the `ConnectionInsight`
  theme/explanation on a floating UI text card or HUD panel. Express it
  diegetically instead — through the room's lighting and mood, a symbolic
  element that visually links the two (or more) objects (a light path, a
  shared motif, matched materials), a short spoken narration when the room
  is entered, and/or a physically-modeled in-world text object (e.g. an
  engraved plaque prop) if any literal text is used at all. The judging
  criterion is "AI's reasoning is visible," not "AI's reasoning is a caption"
  — visibility can come from set design and sound, and should here.
- Unity must visibly attribute each object to its contributor (name near the
  object, not necessarily text — could be a small marker, material tint, or
  spoken introduction), without resorting to a generic UI overlay.
- **Per-object haptic and audio signatures.** Each contributed object gets
  its own distinct haptic pulse (on pickup/inspect/interact) and its own
  sound cue tied to its animation — see "Immersive scene craft" below. This
  is the felt-not-read principle applied at the object level, not just the
  room level.
- Use Meta's own **Unity MCP Extension** for Horizon
  (https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/)
  as the Unity MCP integration, rather than a generic/third-party Unity MCP
  server. Submitting to Meta's own challenge using Meta's own official Unity
  tooling is a deliberate, judge-legible choice, the same reasoning as the
  Llama requirement above. Follow that page's current setup instructions
  rather than a remembered/guessed configuration — the extension's install
  steps and tool surface can change.
- `PIPELINE_MODE=mock` must return a deterministic `ConnectionInsight` and
  layout from two labels/memory snippets, labelled `mock` in metadata, and
  must never claim a live model ran when it didn't.

**Definition of done for this track:** two named contributors can complete
the full flow in local mock mode, Unity visibly attributes their objects
without a UI text overlay, the AI theme is perceivable through the staged
scene (and/or spoken narration), the published blueprint loads successfully,
and one safe scene edit is demonstrated — all captured in a 2–3 minute video
that states who the product is for, how it strengthens connection, and why
AI (specifically NemoClaw's Llama-backed reasoning and scene-authoring
tools) is essential.

**Do not scope-creep this MVP** into accounts, chat, real-time multiplayer,
or notifications — those are explicitly post-hackathon.

## Secondary / alternate competition track: Resilience Commons with Grok

Only use this framing if a task explicitly asks for the SpaceXAI/Grok
competition instead of Meta. It reframes the same Shared Room interaction
pattern around a different fictional scenario (neighbourhood disaster
preparedness) and a different model provider (Grok, not Llama). Do not mix
this framing into Meta-track work — a judge reading a mixed pitch reads it as
unfocused. Full detail below is kept for reference but is not the current
priority.

---

## Product requirement: Shared Rooms

The user-facing product must be framed as a social experience, not only as an
object-reconstruction pipeline. The hackathon MVP is a **Shared Room** for two
or more people who are apart: each person contributes a meaningful photo or
sketch, then AI turns their contributions into one explorable room. Two is
the minimum and the demo default (it's the clearest 2–3 minute video); the
data model, storage layout, and NemoClaw contracts must support more than two
from the start — see "Scaling Shared Room from two contributors to N" in
`docs/ARCHITECTURE.md` before building the Contributor/Contribution layer or
any NemoClaw composition tool.

The social loop is deliberately small and demoable:

1. Create one project and register two or more display-name contributors.
2. Collect one contribution from each person, including an optional short
   memory/reason for the object.
3. Ask AI to infer a shared theme, write a connection explanation, and propose
   spatial placement for all of the contributed assets.
4. Validate and save the result as a normal versioned experience blueprint.
5. Publish the revision and show the attribution, theme, and explanation in
   Unity alongside every contributed object.
6. Let each person make a bounded edit, scoped to their own object(s), through
   the existing allowlisted scene actions.

This is sequential co-creation for the prototype — contributors add their
object at different times; nobody needs to be present simultaneously, and
there is no real-time networking anywhere in the shipped build. Do not expand
the MVP into accounts, chat, real-time multiplayer, notifications, or a new
social network. Those features are post-hackathon work; if real-time shared
presence is ever pursued, `docs/ARCHITECTURE.md` names the two candidate
paths (Meta's own colocation/Shared Spatial Anchors APIs, or Unity Cloud /
Unity Gaming Services) and the tradeoff between them.

## Competition track: Resilience Commons with Grok

When the task is framed around the SpaceXAI/Grok competition, use **Resilience
Commons** as the primary product story: a community-authored, explorable
preparedness space for a fictional neighbourhood facing an extreme-heat or
flood scenario. The existing Shared Room is the interaction pattern; the
societal outcome is turning fragmented local knowledge into understandable,
accessible preparedness communication.

### Required Grok use cases

- Use the Grok Responses API for structured synthesis of photos, sketches,
  memories, voice transcripts, and approved hazard context. The output must
  include evidence references, uncertainty, disagreements, missing information,
  and bounded scene annotations.
- Use Grok Imagine to generate or edit one clearly labelled possible-future
  visual from approved references. Never present generated imagery as observed
  evidence or an official forecast.
- Use Grok Voice for spoken community input and an accessible narrated
  walkthrough. Ground answers in the project evidence and state when the
  system does not know.

Keep all Grok calls behind the backend. Read the current xAI documentation
before selecting model names or request shapes; do not hard-code unverified
model identifiers. Add `SKETCHSCAPE_XAI_*` environment variables to local
documentation only as empty placeholders, never credentials.

### Safety and truthfulness rules

- The first demo uses a fictional or pre-seeded neighbourhood dataset.
- Every generated claim carries source references, timestamp, confidence, and
  an explicit generated/assumption label.
- The product is not emergency advice, a disaster predictor, a medical tool,
  or a replacement for local authorities. Show that boundary in the UI and
  demo.
- Never invent safe locations, evacuation routes, medical guidance, or hazard
  severity. Missing data must appear as missing data.
- Keep `PIPELINE_MODE=mock` deterministic and fully usable without an xAI key.
  The live Grok adapter must be a replaceable backend service, not a Unity
  runtime dependency.

### Competition definition of done

The competition prototype is complete when two contributions can produce a
schema-validated hazard brief, a Unity scene with attributed objects and
action markers, one labelled Imagine scenario visual, and one grounded Voice
walkthrough in mock mode. The demo must show provenance, uncertainty, and the
safety disclaimer. The public write-up must explain the societal problem, why
Grok is necessary, and which parts are live versus deterministic mock output.

### Social data and API boundary

When implementing the MVP, preserve the current ownership boundaries:

- Add project-scoped `Contributor`, `Contribution`, and `ConnectionInsight`
  records. A contribution points to an existing `asset_id` and includes the
  contributor ID, source type, and optional memory text.
- Add a project-scoped composition endpoint that accepts the two contributions
  and returns a shared theme, explanation, placement rationale, and an
  `ExperienceBlueprintInput` proposal.
- Reuse blueprint validation, immutable revisions, publication, and compiled
  scene loading. Do not let the AI write arbitrary Unity code or bypass the
  blueprint contract.
- Keep social metadata in the authoring blueprint or a versioned sidecar
  manifest. Do not change `shared/scene.schema.json` casually; only add runtime
  fields if Unity actually needs them to render the social context.
- Unity should display contributor attribution and the AI-generated connection
  explanation, while the backend remains the authority for project state and
  safe scene mutations.

### AI implementation rule

AI must be visible and necessary. It should perform three distinct jobs:

- interpret each sketch/photo and its memory;
- infer a shared theme or relationship between the contributions;
- compose the room and explain why each object was placed where it was.

The offline mock implementation must return deterministic output from labels
and memory text, mark its backend as `mock`, and use valid existing assets and
bounded transforms. A live model adapter may replace the composition step
later without changing Unity's blueprint contract. Never describe deterministic
mock output as a model result.

### Social-product definition of done

The feature is ready for the hackathon demo when two named contributors can
complete the flow in local mock mode, the UI/Unity scene visibly attributes
their objects, the AI theme and explanation are shown, the published blueprint
loads successfully, and one safe edit is demonstrated. The 2 to 3 minute video
must show the complete flow and explain who the product is for, how it
strengthens connection, and why AI is essential.

## Frontend app — the user's control surface

The user interacts with SketchScape through a **desktop app** built on the
same stack as the `logseq_new` repo (Electron + electron-vite + React 18 +
TypeScript + Zustand + Tailwind + lucide-react). The app is clean, dark, and
minimal — the same aesthetic as Obsidian / logseq_new.

**The app lives at `app/` inside this repository (to be created).**
It communicates only with the SketchScape backend API at
`http://127.0.0.1:8000` (or the EC2 public IP for the live demo).

### Stack
- **Electron + electron-vite** — cross-platform desktop shell, same as logseq_new
- **React 18 + TypeScript** — renderer
- **Zustand** — client state (current project, upload status, scene state)
- **Tailwind CSS** — styling, dark theme by default
- **lucide-react** — icons (same set as Obsidian / logseq_new)
- No Convex, no Next.js — the backend is the SketchScape FastAPI server

### Screens to build

**1 — Home / project list**
List of projects (name, object count, status badge). Button to create a new
project. Clean sidebar like logseq_new's file tree.

**2 — Object upload**
Drag-and-drop area or file picker. Accepts:
- Regular photos (JPEG / PNG / WebP)
- Notability sketch exports (same formats — shown directly as a flat card, or
  reconstructed as a 3D memory plaque; see `docs/BUILD_PLAN.md` step 7, not
  built yet)
User types a short label ("oak chair", "blue ceramic vase"). Submits. Shows a
live progress indicator while reconstruction runs (polls the job endpoint).

**3 — Project / scene manager**
Shows all objects in the current project with their status (processing /
ready / failed). Thumbnail of the mask-preview once ready. Button to add more
angles of the same object (adds a new view). Button to launch NemoClaw room
assembly once enough objects are ready.

**4 — NemoClaw assembly panel**
Triggers the NemoClaw `place_objects_in_scene` tool. Shows a live log of what
NemoClaw is deciding ("placing oak chair near the window…"). Displays the
resulting blueprint as a simple 2D top-down room diagram. One-click to push
to Unity.

**5 — VR launch**
"Export to Quest" button — runs `scripts/export_unity_experience.py`, packages
the scene, and opens instructions to build the APK or sideload to the headset.

### What the app must never do
- Store AWS credentials, HF tokens, or worker tokens
- Call Unity MCP or NemoClaw directly — those go through the backend
- Block the UI while polling — use non-blocking polling with a progress indicator

---

## The two input paths

**Photo upload**
```
Photo → SAM 3.1 (segmentation) → Fast-SAM3D (reconstruction) → .ply file
```

**Notability sketch** (see `docs/BUILD_PLAN.md` step 7 — not built yet)
```
Path 1 (default): Sketch → stored as a flat textured quad, placed directly in the room
Path 2 (memory plaque): Sketch + memory text (the whole page) → SAM 3.1 → Fast-SAM3D
                         → a 3D plaque/page object with the memory text physically on it
```

There is no image-generation conversion step anymore — a sketch is no longer
turned into a fake photorealistic photo first. Photo upload still produces a
`.ply` Gaussian-splat stored in S3 with metadata in DynamoDB; Path 2 for
sketches produces the same kind of `.ply`, just of the page itself.

---

## Pipeline after reconstruction

```
All .ply files in catalog
  → NemoClaw receives object names + labels
  → NemoClaw reasons about room layout (interior-design logic)
  → NemoClaw optionally reads Notability sketch layout as a placement hint
  → NemoClaw assigns positions, scales, rotations, animations per object
  → NemoClaw calls Unity MCP → scene updates live in Unity immediately
  → User enters VR room on Meta Quest
```

---

## Hard rules — never break these

1. **No credentials in source control.** AWS keys, HF tokens, worker tokens,
   Unity Cloud credentials, MCP secrets — none of these ever go in a file,
   a commit, a chat message, or a command argument.

2. **`PIPELINE_MODE=mock` is always the default** and must always work
   offline with no GPU and no AWS. Never break the mock path.

3. **Never call `terraform apply`, start an EC2 instance, run a GPU job, or
   install NemoClaw without explicit user approval.** These cost money or
   have irreversible effects. There is no paid image-gen backend in this
   project anymore — the old sketch → image-generation pipeline
   (`image_gen.py`, `azure`/`hf`/`grok` backends, Meta Muse Image) was
   removed entirely; do not reintroduce any of it (see `sketch-image-gen-backends`).

4. **NemoClaw and Unity MCP are development control-plane tools only.** The
   shipped Unity player must never call NemoClaw, Unity MCP, the authoring
   backend, or any AWS service at runtime. Only the public backend API is
   allowed in a shipped build.

5. **SAM 3.1 and Fast-SAM3D run sequentially on the GPU, never concurrently.**
   The T4 has 16 GB VRAM. Release SAM 3.1 memory before starting Fast-SAM3D.

6. **Published blueprint revisions are the source of truth.** Generated Unity
   scenes are reproducible compiler output. Never make opaque MCP edits the
   source of truth.

7. **Failed objects are omitted from the VR room — no placeholder primitives.**
   If an object's reconstruction fails, skip it. The experience still launches
   with whatever succeeded. Do not show cubes, capsules, or coloured shapes in
   place of failed objects.

8. **Run `bash scripts/verify_local.sh` after every backend change** and
   confirm all tests pass before reporting done. Currently 40 tests, all
   passing.

---

## Repository layout

```
backend/           FastAPI backend — the only process Unity talks to
  main.py          All API routes, models, job logic
  storage.py        AuthoringStore — LocalJsonStore + DynamoDbStore
  artifact_store.py ArtifactStore — LocalArtifactStore + S3ArtifactStore
  test_api.py       API contract tests (run these)
  test_storage.py   Storage + artifact store tests (run these)

worker/            GPU worker — runs on EC2, never in the API process
  run_job.py       Pulls image, runs SAM 3.1 + Fast-SAM3D, posts .ply back
  bootstrap_fastsam3d.sh  One-time GPU environment setup

shared/
  experience-blueprint.schema.json  Authoring contract (source of truth)
  scene.schema.json                 Runtime Unity scene contract

infra/aws/         Terraform — GPU EC2, DynamoDB, S3, IAM
  main.tf          All resources
  SMOKE_TEST_GUIDE.md  Step-by-step AWS verification guide

scripts/
  verify_local.sh           Run this after every change
  smoke_test_aws_storage.py Live DynamoDB + S3 verification
  export_unity_experience.py Package .ply files into Unity project
  aws_preflight.sh          Read-only AWS checks before Terraform

config/nemoclaw/
  sketchscape-tools.json    NemoClaw tool inventory (intent, not runtime state)

docs/
  PROJECT_STATUS.md  ← Start here for plain-language project status
  INFRASTRUCTURE_ROADMAP.md  Detailed slice-by-slice status
  INTEGRATION_GUIDE.md       How all the pieces connect
```

The Unity project lives at `../HackGTUnity` — outside this repository.

---

## What is fully built and tested

| Area | Status |
|---|---|
| Backend API (upload, poll, mock pipeline, safe edits) | ✅ done, 57 tests passing |
| Notability sketch direct display / SAM3D memory plaque | ⬜ not started — see Build Plan step 7 |
| Project + asset catalog with multi-view provenance | ✅ done |
| Versioned blueprint system with append-only publication log | ✅ done |
| Local JSON store (atomic writes, restart-safe) | ✅ done |
| DynamoDB store | ✅ done, live-verified against real AWS |
| S3 artifact store (presigned redirect serving) | ✅ done, live-verified against real AWS |
| Terraform: EC2, DynamoDB table, S3 bucket, IAM | ✅ provisioned and live |
| UnitySplats v1.2.0 in Unity project | ✅ installs and compiles |
| XRI 3.0.11 VR rig + XR Device Simulator | ✅ imported |
| Quest build config (ARM64, Vulkan, OpenXR) | ✅ configured |
| Offline experience builder (blueprint → Unity scene) | ✅ exists, needs fallback fix |

---

## What is partially built

| Area | What exists | What's missing |
|---|---|---|
| GPU worker | `worker/run_job.py` fully written | GPU not bootstrapped; no real `.ply` produced yet |
| Cloud backends on EC2 host | DynamoDB + S3 provisioned | Env vars not set on the running API process |
| Gaussian-splat rendering | UnitySplats installed | Never loaded a real Fast-SAM3D `.ply`; Quest perf unverified |
| Unity offline builder | Exists | Still falls back to placeholder primitives — needs that code removed |

---

## What needs to be built (priority order)

> **For Meta-track work, use `docs/BUILD_PLAN.md` instead of this list.** The
> list below predates the Shared Room / Meta framing and still describes a
> general-purpose multi-object room-assembly agent (item 4) rather than the
> N-contributor connection flow. It stays here for the underlying pipeline
> work (GPU verification, Unity splat rendering — `docs/BUILD_PLAN.md` steps
> 10–11) that both tracks share, but the concrete, file-by-file *social*
> steps (`connection/compose`, `Contributor`/`Contribution` models,
> NemoClaw's tools, immersive staging, in-scene attribution) live in
> `docs/BUILD_PLAN.md`, each with its own `.claude/skills/<name>` skill.

### 1 — Notability sketch direct display / SAM3D memory plaque
Replaces the old sketch → image-generation → reconstruction pipeline, which
was removed entirely (`POST /v1/sketches`, `backend/image_gen.py`). See
`docs/BUILD_PLAN.md` step 7 for the two-path plan (flat-quad direct display,
SAM3D-reconstructed memory plaque with embedded text). Not started.

### 2 — GPU instance end-to-end verification
Start EC2 → SSM + `nvidia-smi` → publish bundle → bootstrap with HF token
(one-time, unset immediately) → SAM 3.1 smoke test → Fast-SAM3D smoke test
→ full API callback → stop instance. See `infra/aws/SMOKE_TEST_GUIDE.md`.

### 3 — Activate cloud backends on EC2 host
Set `SKETCHSCAPE_STORAGE_BACKEND=dynamodb`, `SKETCHSCAPE_DYNAMODB_TABLE`,
`SKETCHSCAPE_ARTIFACTS_BACKEND=s3`, `SKETCHSCAPE_ARTIFACTS_BUCKET` on the
running API process. Step 5 of `infra/aws/SMOKE_TEST_GUIDE.md`.

### 4 — NemoClaw integration
Four tools need to be built and registered with NemoClaw:

**`place_objects_in_scene`**
Input: list of `{asset_id, label}` objects and optionally the Notability sketch.
Behaviour: reasons about realistic room layout (interior-design logic), assigns
`position`, `rotation`, `scale`, and `animations` to each object, constructs
an experience blueprint, and publishes it immediately via Unity MCP.

**`read_sketch_layout`**
Input: Notability sketch image.
Behaviour: extracts rough spatial relationships from the drawing (e.g. "lamp is
left of chair, window is behind"). Returns a layout hint for `place_objects_in_scene`.
This is optional — NemoClaw can skip it and reason purely from object names.

**`stage_immersive_reveal`** — see "Immersive scene craft" below for the
open-source toolkit this tool should be built on.
Input: the `ConnectionInsight` (theme, explanation, placement rationale) and
all of the contributed objects' positions from `place_objects_in_scene` —
two in the MVP demo, but the tool must accept a list, not a fixed pair (see
"Scaling Shared Room from two contributors to N" in `docs/ARCHITECTURE.md`).
Behaviour: NemoClaw does not just place objects — it choreographs the moment
the contributions are experienced together, so the connection is *felt*,
not just read. This means reasoning about: the reveal order across however
many objects exist, when ambient lighting shifts to mood-match the theme,
when/where an atmospheric particle effect (dust, light motes) should bloom
near the shared center of the contributed objects, when spatial audio should
swell, and when/where the on-screen theme + explanation text should fade in
relative to all of the above. This must degrade gracefully: if a scene-craft
package isn't available at runtime, the room still needs to load and read
correctly with plain lighting and no effects — never block the core
connection story on the immersive layer.

**`trigger_unity_scene_update`**
Input: compiled scene JSON from a published blueprint.
Behaviour: calls Unity MCP to apply the scene to the open Unity project
immediately. No waiting for manual publish review — changes go live at once.

NemoClaw setup: choose an agent runtime — three concrete, currently-real
open-source options, verified as of September 2026:
- [OpenClaw](https://github.com/openclaw/openclaw) — MIT-licensed,
  TypeScript, config-first (write a `SOUL.md`, run a command), the most
  widely adopted of the three (160k+ GitHub stars), multi-provider model
  support.
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous
  Research) — self-improving agent with a built-in Tool Gateway (web search,
  image generation, TTS, cloud browser) behind one subscription.
- [LangChain Deep Agents](https://github.com/langchain-ai/deepagents) — MIT,
  Python, built on LangGraph, provider-agnostic, with built-in planning,
  filesystem/computer access, and sub-agent delegation.

Follow whichever one's current official onboarding docs, then register Unity
MCP as a trusted local target. For the Meta track, "Unity MCP" means Meta's
official **Unity MCP Extension for Horizon**
(https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/) —
install and configure it per that page's current instructions rather than a
generic third-party Unity MCP server. **Requires Unity Editor 6000.0.66f2 or
later** (6.1+ recommended) — confirm the installed Unity version before
attempting setup. Never put credentials in this repo.

### Immersive scene craft — open-source toolkit for `stage_immersive_reveal`

The goal is emotional impact, not object placement: when two contributors'
objects and the AI's connection explanation come together in the room, the
scene should *feel* like something, not just render correctly. Build
`stage_immersive_reveal` on these open-source building blocks rather than a
from-scratch effects system — evaluate current license/version before
vendoring any of them, and confirm each addition doesn't grow the shipped
Unity player's runtime dependencies beyond the public backend API (Hard Rule
4 above still applies):

- **Guided reveal sequencing** — [VR Builder](https://github.com/MindPort-GmbH/VR-Builder)
  (MindPort, open source). Its step/workflow model — a sequence of steps
  connected by transitions, each step triggering behaviors like moving an
  object or playing audio — is a close match for "reveal Contributor A's
  object, pause, reveal Contributor B's object, pause, let the connecting
  light/motif resolve between them, let the narration play." Use its
  authoring model as the reference even if only a slice of it is adopted.
  This is diegetic staging, not a text-card sequencer — no step in this
  sequence should end in a floating UI panel.
- **Procedural / cinematic animation** — [PrimeTween](https://github.com/KyryloKuzyk/PrimeTween)
  for lightweight, allocation-free tweens (object entrance animations, camera
  drift, a connecting light path growing between the two objects), or
  [TweenPlayables](https://github.com/AnnulusGames/TweenPlayables) if the
  reveal sequence is authored on Unity's built-in Timeline instead — it adds
  tween tracks directly to Timeline. Pick one, not both.
- **Mood lighting** — an open-source URP volumetric light/fog shader such as
  [CristianQiu/Unity-URP-Volumetric-Light](https://github.com/CristianQiu/Unity-URP-Volumetric-Light)
  or [ramalingamthangamani/URP-Volumetric-Fog](https://github.com/ramalingamthangamani/URP-Volumetric-Fog)
  (built for real-time VR, XR-instancing-safe) to warm or cool the room's
  lighting to match the AI-inferred theme, and to put a soft light shaft or
  glow at the shared midpoint between the two objects during the reveal —
  this light/glow *is* the visible expression of the theme, doing the job a
  text card would otherwise do.
- **Atmospheric particles** — Unity's own official
  [VisualEffectGraph-Samples](https://github.com/Unity-Technologies/VisualEffectGraph-Samples)
  for ambient dust motes / floating light particles that bloom gently around
  the connection point during the reveal — restrained, not a game-VFX
  explosion.
- **Spatial audio and narration** — [Resonance Audio](https://github.com/resonance-audio/resonance-audio)
  (Google, Apache 2.0, open source) for 3D ambient sound and a directional
  audio swell timed to the reveal. Note Unity's own first-party Resonance
  Audio package is deprecated; integrate the standalone SDK/native plugin
  directly, or fall back to Unity's built-in audio spatializer if that
  integration proves too heavy for the hackathon timeline.
- **Spoken narration of the theme** — this is the primary channel replacing
  on-screen text, not just atmosphere. For the demo, a recorded human voice
  is the safest, fastest option. If synthesizing it instead, Meta's own
  [MMS (Massively Multilingual Speech)](https://github.com/facebookresearch/fairseq/tree/main/examples/mms)
  TTS models are open source and genuinely on-brand for this track — note
  they're released under **CC-BY-NC 4.0 (non-commercial)**, which is fine for
  a hackathon demo but worth flagging if this ever ships commercially. Any
  other TTS engine works too; the requirement is spoken narration, not a
  specific model.
- **Per-object haptic and sound signatures** — use Unity's XR Interaction
  Toolkit haptic API (`SendHapticImpulse` on the controller, or the Input
  System's haptic support) to give each contributed object its own distinct
  pulse pattern on pickup/inspect, and pair each object's idle animation
  (from the tween/Timeline layer above) with its own short sound cue. The
  goal: a contributor recognizes *their* object by feel and sound alone, not
  just sight — this is the felt-not-read principle applied per object, and
  it's cheap to build once the animation and audio layers above exist.

`stage_immersive_reveal` should treat all of the above as optional
enhancement layers on top of a working plain-lit, silent scene — the demo
must still tell the connection story correctly with zero of these installed.

### Hardware and production ideas that lean into Meta specifically

Small, mostly-optional additions that read as deliberate "why Meta" choices
rather than generic VR — add as time permits, in roughly this priority order:

0. **Use Meta XR Building Blocks for setup speed.** Both items 1 and 2 below
   have a drag-and-drop accelerator: with the Meta XR Core SDK installed,
   **Meta > Tools > Building Blocks** in the Unity menu lets you drop a
   pre-wired Passthrough or Hand Tracking block straight into the scene
   instead of hand-assembling the components — use it before reaching for a
   from-scratch implementation of either.
1. **Passthrough/mixed-reality closing beat.** End the room experience (or
   the demo video) with a brief Quest passthrough moment — the virtual room
   fading into the contributor's real physical space — using the [Meta XR
   SDK's Passthrough API](https://developers.meta.com/horizon/documentation/unity/unity-passthrough/)
   (enable via `OVRManager` → Quest Features → Passthrough Support, or the
   Building Blocks shortcut above). This is a Quest-specific capability
   nothing else in the demo touches and makes a strong, cheap closing shot.
2. **Hand tracking for the bounded edit.** Let at least one contributor's
   move/scale edit happen via the [Meta XR Interaction SDK](https://developers.meta.com/horizon/documentation/unity/unity-handtracking-overview/)
   (pinch to grab and place) instead of a controller trigger — more intimate
   on camera for an object that represents a relationship, and a hardware
   capability specific to Quest. Use the Interaction SDK's built-in grab/poke
   gestures rather than building custom hand-pose detection.
3. **Contributor identity from the logged-in Quest account**, via the Meta
   Platform SDK — concretely,
   `Oculus.Platform.Users.GetLoggedInUser().OnComplete(...)` returning a
   `User` with a `.DisplayName` field — instead of a manually typed display
   name. Nice-to-have, build only if time permits; typed names remain the
   fallback.
4. **Record with Quest's built-in Mixed Reality Capture (MRC)** instead of a
   separate screen-recording rig, for a clean composite third-person shot
   (headset-wearer + their in-headset view). Attempt this for the real demo
   recording, but keep a plain screen-record fallback ready — only use MRC
   footage if it comes out completely clean; a partially-broken MRC capture
   is worse than a simple screen recording.
5. **Moderate contributor memory text with [Llama Guard](https://github.com/meta-llama/PurpleLlama)**
   (Meta's open-source PurpleLlama project; Llama Guard 3 ships 1B and 8B
   variants) before it reaches the composition step. Costs almost nothing to
   add, and the write-up gets to state that user-submitted text is
   safety-checked with an open-source Meta model before another AI model
   reasons over it — a small, concrete "responsible AI" detail worth one
   sentence in the write-up.

### 5 — Fix Unity offline builder (remove fallback primitives)
In `SketchScapeOfflineExperienceBuilder`:
- If a `.ply` exists for an object → create a `GsplatRenderer` for it
- If no `.ply` exists → skip the object entirely, do not create a primitive
- The scene builds and launches regardless of how many objects were skipped

### 6 — Verify Gaussian-splat rendering with a real PLY
Load a real Fast-SAM3D `.ply` in Unity with UnitySplats. Confirm it renders.
Check splat count is within Quest 3 limits. Confirm acceptable framerate.
Blocked on step 2.

### 7 — Realistic VR room environment
The virtual room the user walks around in needs:
- Walls, floor, ceiling, window lighting (handcrafted or procedural Unity env)
- Ambient lighting approximating the objects' source photo lighting
- Walkable area with colliders on all objects (no walking through things)
- Controller interactions: pick up, inspect, resize objects using Quest controllers
- Smooth locomotion or teleport via the XRI rig already imported

### 8 — Multi-view fusion
Per-view provenance is already tracked (`AssetView` model, `views` list on
`ProjectAsset`). Missing: code to combine multiple READY views of the same
object into one better `.ply`. Lower priority than getting a single view
working. Requires a GPU-side fusion strategy.

### 9 — Desktop app (the user's control surface)
**Not started. Build this once the core pipeline is working end-to-end.**

Build `app/` in this repo using the same Electron + electron-vite + React 18
+ TypeScript + Zustand + Tailwind + lucide-react stack as the
[logseq_new](https://github.com/OmSanghvi/logseq_new) repo. Match that app's
clean dark aesthetic — sidebar, main content area, clear visual hierarchy.

The app talks to the SketchScape FastAPI backend only. No credentials in the
app. Non-blocking polling with visible progress.

Five screens: Home / project list → Object upload → Scene manager →
NemoClaw assembly panel → VR launch. See the "Frontend app" section above
for the full screen-by-screen breakdown.

### 10 — Production hardening (post-hackathon)
TLS termination, rate limiting, SQS job queue, auto-scaling. Not needed for
the demo.

---

## Key models and contracts

**`ProjectAsset`** — one real-world object in the catalog.
- `asset_id`: stable ID, never changes
- `label`: human name ("oak chair", "blue ceramic vase")
- `status`: `processing | ready | mask_review | failed`
- `views`: list of `AssetView` — one per submitted image/angle
- `artifact_url`: URL of the best `.ply` (promoted from first READY view)

**`AssetView`** — one reconstruction attempt (one photo, one job).
- `view_index`: 0-based order
- `reconstruction_job_id`: the job that produced this view's `.ply`
- `status`: `processing | ready | mask_review | failed`
- `artifact_url`: this view's `.ply` URL once ready

**`ExperienceBlueprint`** — NemoClaw's output; the room layout.
- `objects`: list of `{id, asset_id, position, rotation, scale, interactions}`
- `experience.mode`: `vr` for the Quest room
- `navigation.vr`: `teleport` or `smooth`
- Schema: `shared/experience-blueprint.schema.json`

**`SceneDocument`** — what Unity reads at runtime.
- Compiled from a published blueprint by the backend
- Schema: `shared/scene.schema.json`
- Unity never reads the blueprint directly; always reads the compiled scene

**`Contributor`** — one person participating in a Shared Room (not yet
implemented; see PROJECT_STATUS.md item 2 and ARCHITECTURE.md's N-contributor
section before building this).
- `contributor_id`, display name, project membership
- A project holds a **list** of contributors — never a fixed pair of fields

**`Contribution`** — one person's contributed object plus why it matters
(not yet implemented).
- `contributor_id`, `asset_id`, source type (`photo` | `sketch`), memory text
- A project holds a **list** of contributions, `len >= Project.min_contributors`
  (default `2`) before `connection/compose` may run

**`ConnectionInsight`** — NemoClaw's social reasoning output (not yet
implemented).
- Shared theme, explanation, and a placement rationale that references
  **every** contribution, not just two
- Produced by NemoClaw's tools, not a standalone API call; metadata records
  `mock` or the live NemoClaw run's underlying model (`llama` default,
  `grok` fallback via `NEMOCLAW_MODEL_BACKEND`)
- Feeds `stage_immersive_reveal`'s reveal-order and staging decisions

---

## Key environment variables

```bash
# Backend
PIPELINE_MODE=mock                     # always the default; use aws-local on EC2
SKETCHSCAPE_DATA_DIR=./data            # where uploads and local artifacts go
SKETCHSCAPE_WORKER_TOKEN=              # shared secret between API and GPU worker
SKETCHSCAPE_ALLOWED_ORIGINS=*         # CORS origins

# Shared Room contributor bounds (not yet implemented — see ARCHITECTURE.md)
SKETCHSCAPE_MIN_CONTRIBUTORS=2         # connection/compose refuses below this
SKETCHSCAPE_MAX_CONTRIBUTORS=6         # keeps NemoClaw layout + demo readable

# NemoClaw's underlying reasoning runtime (not yet implemented). NemoClaw's
# own tools (place_objects_in_scene, stage_immersive_reveal) are what build
# the scene; this only selects which model powers the agent's reasoning.
# "llama" is served via a hosting provider (Together AI / Groq / AWS Bedrock)
# or self-hosted — Meta's own Llama API public preview was retired July 2026.
NEMOCLAW_MODEL_BACKEND=llama           # llama (Meta track default) | grok (Resilience Commons)

# Storage backend (local is default; dynamodb for cloud)
SKETCHSCAPE_STORAGE_BACKEND=local
SKETCHSCAPE_DYNAMODB_TABLE=sketchscape-authoring
AWS_REGION=us-east-2

# Artifact backend (local is default; s3 for cloud)
SKETCHSCAPE_ARTIFACTS_BACKEND=local
SKETCHSCAPE_ARTIFACTS_BUCKET=sketchscape-artifacts-<suffix>
```

There is no image-generation env var block anymore — the old sketch →
photorealistic-image pipeline (`SKETCHSCAPE_IMAGE_GEN_BACKEND`,
`SKETCHSCAPE_AZURE_OPENAI_*`, `SKETCHSCAPE_HF_*`) was removed along with
`backend/image_gen.py`. Do not re-add these vars; see `docs/BUILD_PLAN.md`
step 7 for what replaces this.

---

## How to validate your changes

```bash
# After any backend Python change:
bash scripts/verify_local.sh          # must pass, currently 57 tests

# After any Terraform change:
cd infra/aws
terraform fmt -check -recursive
terraform validate

# After provisioning real AWS resources:
SKETCHSCAPE_DYNAMODB_TABLE=... \
SKETCHSCAPE_ARTIFACTS_BUCKET=... \
AWS_REGION=us-east-2 \
backend/.venv/bin/python scripts/smoke_test_aws_storage.py
```

Never report a task as done until the relevant validation passes.

---

## What to read before working on each area

| Area | Read first |
|---|---|
| Backend API changes | `backend/main.py`, `backend/README.md` |
| Storage / persistence | `backend/storage.py`, `backend/artifact_store.py` |
| AWS infrastructure | `infra/aws/README.md`, `infra/aws/SMOKE_TEST_GUIDE.md` |
| Blueprint / scene contract | `shared/experience-blueprint.schema.json`, `shared/scene.schema.json` |
| NemoClaw tools | `config/nemoclaw/sketchscape-tools.json`, `docs/INTEGRATION_GUIDE.md` |
| Unity scene builder | `docs/INTEGRATION_GUIDE.md` sections 5–7 |
| Meta track status, priorities, demo plan | `docs/PROJECT_STATUS.md` |
| Concrete, step-by-step build plan | `docs/BUILD_PLAN.md` |
| Demo-video feature checklist (Meta + AR/VR tracks) | `features.txt` |
| Full picture | `docs/PROJECT_STATUS.md` |

## Claude Code skills for this repo

`meta-track-alignment` is the standing gate — load it for any product,
feature, backend, or Unity judgment call. Every other skill below maps 1:1
to a step in `docs/BUILD_PLAN.md`; load the one matching the step you're
building, not a skill for the whole project at once.

| Skill | Build Plan step |
|---|---|
| `meta-track-alignment` | standing gate, all steps |
| `contributor-data-model` | 1 |
| `contributor-api-endpoints` | 2 |
| `nemoclaw-agent-setup` | 3 |
| `nemoclaw-scene-tools` | 4 |
| `connection-compose-endpoint` | 5 |
| `immersive-reveal-staging` | 6 |
| `sketch-image-gen-backends` | 7 (parallel) |
| `unity-diegetic-attribution` | 8 |
| `meta-hardware-polish` | 9 |
| `gpu-cloud-activation` | 10 (parallel) |
| `unity-offline-builder-and-rendering` | 11 (parallel) |
| `demo-video-prep` | 12 |
