# SketchScape — Shared Room — Meta Track Status

What the project is, what is built, what works right now, and what still
needs to be done to submit to Meta's **"Bringing People Closer Together with
AI"** challenge. Written in plain language.

This document covers **one product**: Shared Room. Earlier drafts of this
project explored a second direction (a community-disaster-preparedness tool
for a different competition track). That material has been removed here —
mixing pitches reads as unfocused to a judge with 2–3 minutes of your time,
and Shared Room is the stronger, more original fit for Meta specifically:
it's a spatial, VR-native product built for Meta's own hardware, not another
chatbot or summarizer.

See `features.txt` at the repo root for the exact feature checklist to hit
while recording the demo video — it covers both this Meta track and the
Immersive AR/VR track, since the same prototype is being submitted to both.
`AGENT.md` is the agent-facing pointer to this document; keep the two from
drifting apart. **`docs/BUILD_PLAN.md` is the concrete, ordered, step-by-step
plan for everything below marked not-started or partially built** — each
step names exact files/functions and the `.claude/skills/<name>` skill that
governs it. This document stays the judge-facing narrative and the source of
truth for *what* the product must do; the build plan is *how* to build it.

---

## Dual-track submission: Meta + Immersive AR/VR

This prototype is being submitted to two tracks from one working build:

- **Meta — "Bringing People Closer Together with AI"** (this document): the
  pitch leads with the two-contributor connection story — the AI-inferred
  theme and explanation are the emotional core, and the VR room is the
  medium that expresses it.
- **Immersive AR/VR track**: the same build, pitched instead on the strength
  of the spatial/VR execution — real Gaussian-splat reconstruction of
  physical objects, a Meta Quest-native room, hand/controller interaction,
  and the technical pipeline (SAM 3.1 → Fast-SAM3D → UnitySplats) that makes
  walking around real objects in VR possible at all.

Do not write two different demo videos. Record one video that shows the full
flow; the write-up for each track selects which framing to lead with. See
`features.txt` for which features to emphasize for each track's judges.

---

## The pitch, in one line

**Two long-distance friends, a couple, or family members each contribute one
meaningful object. AI figures out why those objects belong together, and
Unity turns that connection into a room they can walk through side by side —
on a Meta Quest.**

This isn't "AI turns a photo into 3D." A human could do that with a 3D
scanning app. What a person *can't* easily do is notice, from an old bicycle
photo and a childhood-kitchen sketch, that the shared theme is "home and
independence," and then translate that insight into where each object should
sit in a room. That inference is the product's emotional core, and it's the
part only AI can do.

---

## How this maps to Meta's judging criteria

- **Strengthens human connection:** the product exists entirely to give two
  people a private, spatial artifact that represents their relationship —
  not a feed post, not a message thread. The room is meant to be revisited
  and added to over time (a third object later, an anniversary update),
  turning a one-time build into an ongoing shared space rather than a
  single artifact.
- **AI is essential and well-integrated:** AI does three jobs a normal 3D
  editor can't — interpret an ambiguous photo/sketch, infer the shared theme
  across everyone's contributions, and translate that theme into a room
  layout. The AI's reasoning is perceivable — through lighting, staging, a
  connecting motif, sound, and spoken narration — not hidden behind the
  scenes, and deliberately not reduced to a floating text card either. The
  connection is meant to be *felt*, not read off a caption.
- **Originality:** almost every "AI connection" submission to this track
  will be text- or chat-based. Shared Room is spatial and runs on Meta's own
  headset — you put it on and walk into the relationship.
- **Strength of the demo:** one emotionally legible story, one clean 2–3
  minute video, a working mock-mode path that needs no GPU or cloud
  credentials to run for judges.

---

## What Shared Room does

1. Contributor A starts a project and adds a photo or sketch of a
   meaningful object.
2. Contributor B adds a second photo or sketch and a short memory or reason
   for contributing it.
3. AI identifies a shared theme, explains why the objects belong together,
   and proposes a room layout.
4. The project stores the AI result as a versioned blueprint, and Unity
   renders both contributions in one explorable room.
5. Each contributor can make one bounded edit (move or scale their own
   object), and the final room is viewable on a Meta Quest headset or
   through a local desktop simulator.

This is intentionally sequential co-creation, not real-time multiplayer. It
can be demonstrated locally with two named contributors and does not require
accounts, chat, notifications, or a production sharing service. Live
multi-headset rooms with accounts are a separate, gated post-MVP track
(`docs/BUILD_PLAN.md` steps 13–29).

### The two input paths

**Path A — Photo upload**
```
User uploads a photo of an object (e.g. a chair)
  → SAM 3.1 segments the object out of the photo
  → Fast-SAM3D reconstructs it as a 3D Gaussian-splat (.ply file)
  → Object is stored in the catalog with a stable ID
```

**Path B — Notability sketch** (see `docs/BUILD_PLAN.md` step 7 — not built yet)
```
User exports a drawing (and any memory text) from Notability
  → Default: shown directly in the room as a flat textured card, no
    reconstruction, no image-generation, no GPU, no cost
  → Optional "memory plaque" path: the whole page goes into SAM 3.1 →
    Fast-SAM3D exactly like Path A, producing a 3D plaque object with the
    memory text physically part of it
  → Object stored in the catalog with a stable ID
```

There is no image-generation conversion step — the old sketch → fake
photorealistic image → reconstruction pipeline was removed; it hallucinated
a fabricated object from a line drawing when a direct photo upload (Path A)
already does that job better and more honestly. Path A always produces a
`.ply` Gaussian-splat; Path B's memory-plaque option produces one too, of
the page itself, while its default flat-card option does not.

### Why AI is essential

- **Interpretation:** turn an ambiguous photo or sketch into a usable object
  label and semantic description.
- **Connection-making:** infer a shared theme from both contributions and
  produce a concise connection explanation. For the demo, a pair such as
  "childhood kitchen sketch" and "old bicycle photo" should produce a result
  like "home and independence," with the bicycle placed near the kitchen
  entrance.
- **Expression:** arrange the objects into a coherent scene and explain the
  placement rationale.

The AI output must be **perceivable in the product**, not only used invisibly
to generate coordinates — but not as a floating on-screen caption either. The
demo should linger on the moment the connection becomes apparent through the
scene itself: the lighting shift, the motif linking the two objects, the
narration — since that's the moment that proves AI did something a person
hadn't already said out loud. See "The connection must be felt, not read" in
AGENT.md for the concrete rule against UI text panels.

- **Expression, extended — immersive staging:** placement rationale is not
  enough on its own for two or more contributors to *feel* the connection;
  NemoClaw must also choreograph the reveal — lighting mood, a soft
  atmosphere effect, spatial audio and spoken narration, per-object haptic
  and sound signatures, and the timing of all of it relative to the
  contributed objects — so the emotional beat lands the way it would in a
  well-directed short film, not a spreadsheet of coordinates or a text card.
  See AGENT.md's "Immersive scene craft" section for the specific open-source
  building blocks (VR Builder's guided-step model, PrimeTween/TweenPlayables
  for animation, open-source URP volumetric lighting, Unity's own
  VisualEffectGraph samples, and Google's open-source Resonance Audio) this
  should be built from. This layer is additive: the room must still tell the
  correct connection story with none of it installed.

**NemoClaw is what actually understands and builds the scene.** The
composition step is not a standalone model API call — it's NemoClaw's own
tools (`place_objects_in_scene`, optionally `read_sketch_layout`, and
`stage_immersive_reveal`) reasoning over the contributions together, since
the theme and the room's staging come from the same pass. `connection/compose`
should invoke NemoClaw, not a separate composition backend that bypasses it.

For the reasoning model that powers NemoClaw, use **Meta's Muse Spark** on
the **Meta Model API** (`https://api.meta.ai/v1`, `muse-spark-1.3`, tool
calling and image input) as the default. Submitting to Meta's own challenge
running Meta's own current model through Meta's own API is a small,
deliberate choice that reads well to judges. Two alternatives stay
switchable with `NEMOCLAW_MODEL_PROVIDER=meta|xai|nebius`:
- **Grok API** (`xai`), for the alternate Resilience Commons framing.
- **Nebius Token Factory** (`nebius`), for open models such as Llama.

This is a NemoClaw configuration choice, not a second parallel API path.
See the `nemoclaw-model-providers` skill.

Separately, the old **sketch → photorealistic image** step (`POST /v1/sketches`,
`backend/image_gen.py`, and its `mock`/`azure`/`hf` backends) has been
removed entirely — converting a sketch into a fabricated photorealistic
object was more trouble than it was worth (a paid backend, a network hop, a
visibly fake result) for a case a direct photo upload already handles
better. Meta Muse Image remains rejected on cost, and is doubly moot now.
A Notability sketch instead takes one of two paths — shown directly as a
flat card, or reconstructed via the existing SAM 3.1 → Fast-SAM3D pipeline
as a 3D "memory plaque" with the contributor's memory text physically part
of it — see `docs/BUILD_PLAN.md` step 7. Neither is built yet; there is no
paid or free image-generation backend anywhere in this project anymore.

For the Unity integration, use Meta's official **Unity MCP Extension for
Horizon**
(https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/)
as the Unity MCP layer rather than a generic/third-party Unity MCP server.
Same reasoning as the Muse Spark default above: running Meta's own model *and*
Meta's own Unity tooling for a Meta challenge is a small, deliberate,
judge-legible choice. Follow that page's current setup instructions directly
rather than a remembered configuration, since the extension's install steps
and tool surface can change over time.

### Built for two, architected for more

The demo and write-up lead with exactly two contributors because it's the
clearest story in 2–3 minutes. The underlying data model, storage layout, and
NemoClaw contracts should not hard-code that number — a family or friend
group growing the same room later (the "ongoing, not one-time" arc below) is
a natural extension, not a rebuild. `docs/ARCHITECTURE.md`'s "Scaling Shared
Room from two contributors to N" section is the reference for this: a project
holds a *list* of contributors and contributions (never fixed
`contributor_a`/`contributor_b` fields), gated by a configurable
`SKETCHSCAPE_MIN_CONTRIBUTORS` (default 2), stored in the existing
`DynamoDbStore` single-table layout by extending its sort-key families
(`CONTRIBUTOR#<id>`, `CONTRIBUTION#<id>`, `INSIGHT#<revision>`) rather than
adding a second table. This stays sequential co-creation — no real-time
multiplayer is needed to support more than two people, since contributors
still add their object at different times. Live shared presence is planned
separately as the gated Collaborative VR track (Unity Multiplayer Services
with Distributed Authority, Clerk accounts, Meta sign-in on the Quest) —
see ARCHITECTURE.md and `docs/BUILD_PLAN.md` steps 13–29.

### Exact MVP implementation slice

Reuse the existing project, asset, blueprint, and publication contracts. Add
a social authoring layer around them with these target records:

- `Contributor`: `contributor_id`, display name, and project membership.
- `Contribution`: `contributor_id`, `asset_id`, source type, memory text,
  and optional privacy/display label.
- `ConnectionInsight`: shared theme, explanation, placement rationale, and
  model/backend metadata.

Target API flow:

```text
POST /v1/projects
  -> create Shared Room project
POST /v1/projects/{project_id}/contributors
  -> register two display names
POST /v1/projects/{project_id}/assets
  -> reconstruct one contribution per person
POST /v1/projects/{project_id}/connection/compose
  -> AI returns ConnectionInsight + ExperienceBlueprintInput
POST /v1/projects/{project_id}/blueprints
  -> save the proposed layout as a revision
POST /v1/projects/{project_id}/blueprints/{revision}/publish
  -> compile the authoritative Unity scene
GET /v1/projects/{project_id}/compiled-scene
  -> Unity loads the shared room
```

The existing blueprint remains the source of truth for transforms and
interactions. Social metadata should be added to the authoring blueprint or a
versioned sidecar manifest, not to the low-level runtime scene contract
unless Unity needs to display it. The Unity scene should stage each object's
contributor attribution and the AI-generated theme diegetically (see "The
connection must be felt, not read" in AGENT.md) — not as on-screen text.

`PIPELINE_MODE=mock` must return a deterministic insight and layout from two
labels/memory snippets so the entire social flow works offline, with no
NemoClaw agent runtime required. A live NemoClaw run (Muse Spark by
default) can later replace only this composition step. The mock result must
be labelled as mock in metadata and must never claim that a live model ran.

### Social MVP acceptance checks

- Two contributors can add one contribution each to the same project.
- The project shows who contributed each object.
- The composition response contains a shared theme, explanation, placement
  rationale, and a valid blueprint proposal.
- The proposal references only ready assets and is validated before saving.
- Publishing creates an immutable blueprint revision and a compiled scene.
- Unity visibly presents both objects, contributor attribution, and the AI
  connection theme — expressed through the staged scene (lighting, a
  connecting motif, spoken narration) rather than a UI text panel.
- A contributor can perform one allowlisted scene edit without raw code or
  arbitrary Unity commands.
- The full flow runs in mock mode without AWS, a GPU, or credentials.

---

## Demo plan (2–3 minutes)

One emotionally legible story, not a generic object showcase: **"Two
long-distance friends build a room from the objects that represent home to
them."**

1. **0:00–0:20** — State the audience and the connection problem: people
   who care about each other but are far apart, and don't have a good way to
   share what something *means*, only that it happened.
2. **0:20–0:50** — Contributor A adds a sketch/photo (with a brief memory
   note). Contributor B adds theirs.
3. **0:50–1:20** — Let the connection land in the room itself: the lighting
   shift, the motif linking the two objects, the spoken narration of the
   theme — slow down here, this is the moment that proves AI did the
   noticing.
4. **1:20–2:10** — Put on the Meta Quest headset (show it on a real head,
   even briefly — this is the single strongest "why Meta" beat in the
   video), walk into the room, inspect both objects (feel each one's own
   haptic/sound signature if built), make one edit — pinch/hand-tracking if
   built, controller otherwise.
5. **2:10–2:40** — Optionally close on a passthrough moment (the room fading
   into the contributor's real space), then state plainly why AI was
   necessary: neither contributor said "home and independence" out loud —
   the AI noticed it.

Use the local mock path and precomputed, attractive assets as the
judging-safe recording path — no live GPU or cloud dependency during
recording. Prefer recording the headset shots with Quest's built-in Mixed
Reality Capture (MRC) for a clean composite of the wearer and their in-headset
view; only use MRC footage if it comes out completely clean, otherwise fall
back to a plain screen recording rather than ship a broken composite.

### Write-up (matches Meta's exact ask)

- **Who it's for:** long-distance friends, couples, or family who want to
  share meaning, not just updates.
- **How it strengthens connection:** two people, two objects, one shared
  space that neither could have built alone — with an AI-authored connection
  expressed through the room itself, not a caption, of a relationship
  neither person stated.
- **Why AI is essential:** interpretation, connection-making, and
  expression — three things a shared photo album or file-share can't do.
- **What's live vs. mocked:** be upfront that `PIPELINE_MODE=mock` powers the
  judged demo, with the real GPU reconstruction pipeline verified
  separately. There is no image-generation backend or per-call billed image
  API anywhere in this project (the old sketch → photorealistic-image step
  was removed; see `docs/BUILD_PLAN.md` step 7). This is a strength, not a
  weakness — it shows the product works without excuses and isn't dependent
  on a live GPU or a billed API at judging time.
- **A responsible-AI detail, if built:** contributor memory text is
  moderated with [Llama Guard](https://github.com/meta-llama/PurpleLlama)
  (Meta's own open-source safety model) before it reaches the composition
  step — one sentence, costs little to build, worth stating plainly.

---

## What is fully built and tested right now

### ✅ Backend API
- Upload a photo, get a job ID back, poll until reconstruction is done.
- Mock pipeline — returns a working scene instantly without a GPU, for
  testing and demos when the GPU is not running.

Notability sketch upload (direct-display flat card, or a SAM3D-reconstructed
memory plaque) is **not built** — see `docs/BUILD_PLAN.md` step 7. The old
`POST /v1/sketches` sketch → image-generation → reconstruction endpoint was
removed.
- Multiple objects per project — each gets a stable catalog ID.
- Multi-view provenance — several photos of the same object from different
  angles can be submitted; each angle is tracked separately and the best
  one is used automatically.
- Versioned blueprints — the experience layout is saved as numbered
  revisions; publishing is intentional and history is never overwritten.
- Safe scene edits — Unity can move, scale, or rotate objects via
  structured commands; no raw code is ever accepted.
- Private worker endpoint — the GPU posts its result back through a
  token-protected route; Unity never sees credentials.
- **51 automated tests, all passing** (2 are skipped either way, depending
  on whether `boto3` is installed).
- Automatic subject labeling for uploads (`identify_subject`, mock path):
  a photo with no typed subject still gets a label for SAM 3.1. The live
  NemoClaw path waits on `docs/BUILD_PLAN.md` step 3.

### ✅ Storage — all live-verified against real AWS
- **Local store** (default): project and asset data saved to disk, survives
  restarts, atomic writes.
- **DynamoDB store**: same data in AWS DynamoDB for cloud durability —
  provisioned and smoke-tested live.
- **S3 artifact store**: `.ply`, mask, and preview files stored in S3,
  served via short-lived presigned URLs — provisioned and smoke-tested
  live.

### ✅ AWS infrastructure
- GPU EC2 instance, SSM-only access, auto-shutdown timer, encrypted disk.
- DynamoDB authoring table — live.
- S3 artifacts bucket — live.
- IAM roles scoped to exactly what each piece needs.

### ✅ Unity (in the external HackGTUnity project)

HackGTUnity is being cleaned up and much of it will be removed; re-check
these items against the project before relying on them.

- `UnitySplats` v1.2.0 — loads `.ply` Gaussian-splat files at runtime,
  works on Quest 3/3S, Android Vulkan, Unity 6. Package installed and
  compiles.
- XRI (XR Interaction Toolkit) 3.0.11 — full VR rig with controllers,
  locomotion, and a desktop simulator for testing without a headset.
- Quest build configuration — Android ARM64, IL2CPP, Vulkan, 72 Hz, OpenXR.
- Offline experience builder — takes a published blueprint and creates a
  self-contained Unity scene with no runtime dependency on the API or
  internet.
- Export script — fetches a published project's `.ply` files and writes
  them into the Unity project safely.

### ✅ Tooling
- `scripts/verify_local.sh` — runs all syntax checks and tests in one
  command, no GPU or AWS needed.
- `scripts/smoke_test_aws_storage.py` — live AWS verification script.
- `infra/aws/SMOKE_TEST_GUIDE.md` — step-by-step guide for provisioning and
  verifying the cloud resources.

### ✅ GPU reconstruction pipeline — verified end-to-end
**Verified on NVIDIA L40S (g6e.xlarge, us-east-2, 45 GB VRAM, 32 GB RAM):**
- SAM 3.1 segmented a real photo and produced a clean mask.
- Fast-SAM3D reconstructed it into a **53 MB Gaussian-splat PLY (814,432
  vertices)**.
- Total time: **70 seconds** end-to-end (42s SAM 3.1 + 28s Fast-SAM3D).
- The persistent worker server (`worker/worker_server.py`) loads models
  once at startup — no per-job cold-start penalty.
- Instance is stopped. Models and the worker service are installed on the
  EBS volume.

---

## What is partially built (code exists but not end-to-end verified)

| Item | What exists | What's missing |
|---|---|---|
| **Cloud backends on EC2** | DynamoDB + S3 provisioned and verified locally | The API running on EC2 still uses the local store; env vars need to be set on the instance |
| **Gaussian-splat rendering** | `UnitySplats` installed and compiles | Never loaded a real Fast-SAM3D `.ply` inside the *social* Shared Room flow specifically; Quest performance for a two-object room unverified |

---

## What needs to be built, in order — reprioritized for the Meta submission

Everything below is ordered by what's actually needed to get a strong,
judgeable Shared Room demo out the door. Items from the old roadmap that
only matter for a different product direction (a general-purpose room
assembly agent, multi-object interior design, disaster-prep data ingestion)
have been cut or demoted — they're not what this track is judging.

The numbered items below are the *narrative* priority order. For the
concrete, file-by-file execution of each one — exact endpoint signatures,
Pydantic models, storage methods, test names — use `docs/BUILD_PLAN.md`,
which maps each item here to numbered build-plan steps and a
`.claude/skills/<name>` skill: item 1 (connection compose) → BUILD_PLAN step
5, item 2 (Contributor/Contribution model) → BUILD_PLAN steps 1–2, item 3
(N-object blueprint/publish) → BUILD_PLAN step 4, item 4 (diegetic
attribution) → BUILD_PLAN steps 6 and 8, item 5 (bounded edit per
contributor) → BUILD_PLAN step 8, item 6 (activate cloud backends) →
BUILD_PLAN step 10, item 7 (record demo) → BUILD_PLAN step 12. Item 8
(production hardening) is intentionally not in `docs/BUILD_PLAN.md` — it's
post-hackathon scope, not part of the judged submission.

### 1 — Connection composition endpoint (`/v1/projects/{id}/connection/compose`)
**Not started — this is the most important missing piece.**

This is the single most important gap: it's the endpoint that actually
produces the `ConnectionInsight` (shared theme, explanation, placement
rationale) that the whole pitch depends on. Build the mock version first —
deterministic output from two labels/memory snippets — so the full social
flow works offline before touching a live model. Wire NemoClaw in afterward
as the live path for this endpoint: its own tools (`place_objects_in_scene`,
`stage_immersive_reveal`) produce the insight and the layout together,
running on Muse Spark (Meta Model API) by default, with Grok or Nebius
switchable via `NEMOCLAW_MODEL_PROVIDER` — not a separate model-API backend
bolted on next to NemoClaw.

### 2 — Contributor / Contribution data model
**Not started.**

Add the `Contributor` and `Contribution` records on top of the existing
project/asset contracts. This is mostly plumbing — the reconstruction
pipeline underneath doesn't change, only the layer that tracks who
contributed what and why.

### 3 — N-object blueprint + publish flow
**Partially built — the single-object blueprint/publish path already works
and needs to carry a list of contributions (two for the demo, more if the
architecture is exercised) instead of exactly one.**

Extend the existing versioned-blueprint and publish contracts to accept the
`ConnectionInsight` output and lay out however many objects were contributed
— see `docs/ARCHITECTURE.md`'s N-contributor section; do not hard-code two.
Reuse the offline Unity experience builder from the existing single-object
flow. Concrete steps: `docs/BUILD_PLAN.md` step 4 (NemoClaw's
`place_objects_in_scene` must take a list, tested with both 2 and 5 objects).

### 4 — Unity: stage contributor attribution + the connection diegetically
**Not started.**

The Unity scene needs to make each object's contributor and the AI-generated
theme perceivable — not just render the splats side by side, and *not* as a
floating UI text panel. Use the staging layer instead: lighting/mood tied to
the theme, a connecting motif or light path between the objects, spoken
narration of the explanation, and per-object attribution cues (a marker,
material tint, or brief spoken introduction) rather than name tags. This is
what makes the AI's reasoning visible in the product rather than hidden
behind the coordinates — and felt rather than read — which matters directly
for the "AI is essential and well-integrated" judging criterion. See
AGENT.md's "Immersive scene craft" and "The connection must be felt, not
read" for the concrete toolkit and rule.

### 5 — One bounded scene edit per contributor
**Mostly built.** The existing safe-scene-edit commands (move/scale/rotate
via structured commands, no raw code) already cover this — confirm each
contributor can only edit their own object and wire it into the two-object
flow.

### 6 — Activate cloud backends on the EC2 host
**3 env vars to set, ~5 minutes of work.** Not required for the mock-mode
judging path, but worth doing so a live version of the demo can also run if
useful. Instructions are in `infra/aws/SMOKE_TEST_GUIDE.md` Step 5.

### 7 — Record the demo video and finalize the write-up
Follow the demo plan and write-up structure above. Use the local mock path
and precomputed, attractive assets as the judging-safe recording path.

### 8 — Production hardening (post-hackathon, not needed for the demo)
- HTTPS / TLS termination (currently plain HTTP on port 8000).
- Rate limiting. (Client authentication is planned as Build Plan step 16.)
- Durable jobs so the API doesn't lose jobs on restart — planned in the
  store itself as Build Plan step 26, not SQS.
- The "revisit and add to the room later" arc mentioned in the pitch — not
  required for the MVP demo, but worth building afterward since it's the
  feature that turns Shared Room from a one-time build into an ongoing
  relationship artifact.
- Generalizing from two contributors to a small group (family/friend rooms)
  — see "Built for two, architected for more" above and
  `docs/ARCHITECTURE.md`'s N-contributor section. Build the data/storage
  layer N-ary from day one so this is a config change (`SKETCHSCAPE_MIN_CONTRIBUTORS`/
  `SKETCHSCAPE_MAX_CONTRIBUTORS`) and a NemoClaw prompt update later, not a
  schema migration.

---

## The full Shared Room pipeline

```
Contributor A uploads object (photo or Notability sketch) + a short memory note
Contributor B uploads object (photo or Notability sketch) + a short memory note
  │
  ├─ Photo path:   Photo  → SAM 3.1 (segment) → Fast-SAM3D → .ply file
  └─ Sketch path (not built — docs/BUILD_PLAN.md step 7):
       ├─ Default: shown directly as a flat textured card, no reconstruction
       └─ Memory-plaque option: whole page (sketch + memory text)
                            → SAM 3.1 (segment) → Fast-SAM3D → .ply plaque
  │
  ↓
Both .ply files stored (local disk, or S3 + DynamoDB in cloud mode)
  │
  ↓
POST /v1/projects/{id}/connection/compose → invokes NemoClaw's tools
  ├─ Interpretation: labels/descriptions for each object
  ├─ Connection-making: shared theme + explanation, via
  │  place_objects_in_scene + stage_immersive_reveal (mock, or a live
  │  NemoClaw run — Muse Spark by default; Grok or Nebius
  │  switchable via NEMOCLAW_MODEL_PROVIDER)
  └─ Expression: proposed room layout (positions, rationale)
  │
  ↓
Blueprint saved as a versioned revision → published → compiled Unity scene
  │
  ↓
Unity (Meta Quest, or desktop simulator)
  ├─ Both objects rendered as Gaussian splats
  ├─ Connection staged diegetically: mood lighting, connecting motif,
  │  spoken narration, per-object haptic/sound signature — no UI text panel
  ├─ Each contributor can make one bounded edit to their own object
  │  (hand-tracking pinch if built, controller otherwise)
  └─ User walks around freely with Quest controllers
```

---

## How to run what exists right now (no GPU needed)

```bash
# Start the API in mock mode
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PIPELINE_MODE=mock .venv/bin/uvicorn main:app --reload --port 8000

# Run all tests
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest test_api.py test_storage.py test_subject_labeler.py

# Or run the full validation suite from the repo root
bash scripts/verify_local.sh
```

Open `http://127.0.0.1:8000/docs` to explore the API.
In Unity, set the API base URL to `http://127.0.0.1:8000`, enter Play mode
— the mock pipeline returns a scene immediately so the full flow can be
demonstrated without a GPU or cloud credentials.