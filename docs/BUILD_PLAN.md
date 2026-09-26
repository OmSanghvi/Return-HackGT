# Build Plan — Shared Room (Meta track)

This is the single, concrete, ordered plan for turning the current
reconstruction pipeline into the judgeable Shared Room MVP described in
`docs/PROJECT_STATUS.md`. `AGENT.md`, `docs/ARCHITECTURE.md`, and
`features.txt` explain the *why*; this document is the *how*, broken into
steps small enough to hand to one Claude Code session at a time.

**How to use this plan:** each step below names a Claude Code skill under
`.claude/skills/`. Load that skill before starting the step — it carries the
concrete file-by-file instructions, gotchas, and the step's definition of
done. This document is the map; the skills are the turn-by-turn directions.
Steps are numbered in dependency order — do not start a step whose
dependencies aren't done, and re-run `bash scripts/verify_local.sh` after
every backend step regardless of what the step touches.

Every design decision referenced here was made in prior conversation and is
recorded in `AGENT.md` / `docs/PROJECT_STATUS.md` / `docs/ARCHITECTURE.md` —
this plan does not re-litigate them, only sequences the work.

---

## Status at a glance

| # | Step | Depends on | Status | Skill |
|---|------|-----------|--------|-------|
| 1 | Contributor/Contribution/ConnectionInsight data model + storage | — | Done | `contributor-data-model` |
| 2 | Contributor/Contribution API endpoints | 1 | Done | `contributor-api-endpoints` |
| 3 | NemoClaw agent + Unity MCP Extension setup | — | Not started | `nemoclaw-agent-setup` |
| 4 | NemoClaw layout tools (`place_objects_in_scene`, `read_sketch_layout`) | 3 | Not started | `nemoclaw-scene-tools` |
| 4a | NemoClaw subject labeling for uploads (`identify_subject`) | 3 (live path only) | Mock path built; live path waits on 3 | `nemoclaw-subject-labeling` |
| 5 | `connection/compose` endpoint (mock path, then live NemoClaw path) | 1, 2, 4 | Not started | `connection-compose-endpoint` |
| 6 | `stage_immersive_reveal` + immersive scene-craft toolkit | 4, 5 | Not started | `immersive-reveal-staging` |
| 6a | NemoClaw environment objects from web images (`find_object_image`) | 4, 10 | Not started | `nemoclaw-environment-sourcing` |
| 7 | Notability sketch: direct display (flat quad) + SAM3D memory-plaque path | — | Not started | `sketch-image-gen-backends` |
| 8 | Unity: diegetic attribution + bounded per-contributor edit | 5, 6 | Not started | `unity-diegetic-attribution` |
| 9 | Meta hardware polish (passthrough, hand tracking, MRC, Quest identity, Llama Guard) | 8 | Not started | `meta-hardware-polish` |
| 10 | GPU end-to-end verification + cloud backend activation | — | GPU verified (L40S); cloud env vars on the EC2 API not set yet | `gpu-cloud-activation` |
| 11 | Unity offline builder fix + real-PLY splat rendering | — | Partially built | `unity-offline-builder-and-rendering` |
| 12 | Demo video + write-up | 1–11 (as available) | Not started | `demo-video-prep` |

Steps 7, 10, and 11 have no dependency on the social layer and can be built
in parallel with steps 1–6 by a different session. Everything funnels into
12. `meta-track-alignment` is the standing skill that governs *every* step
above — load it whenever judgment calls come up mid-step.

### Collaborative VR + web accounts track (steps 13–29) — gated

The web app with Clerk accounts (uploads, Notability sketches, optional
text), Meta-account sign-in on Quest linked to Clerk, and live
multi-headset rooms. Approved 2026-09-25 as a **post-MVP, gated** track:
it must never break or delay the MVP (steps 1–12), and every step is
blocked until its prerequisites are verifiably done. See "Collaborative VR
+ web accounts track" below and AGENT.md Hard Rule 9.

| # | Step | Depends on | Status | Skill |
|---|------|-----------|--------|-------|
| 13 | Accounts: Clerk app, Meta Horizon app + test users, Unity Meta Quest provider | — | Unity Cloud linked; rest not confirmed | `collab-vr-accounts-and-gates` |
| 14 | Quest Meta identity spike on a real headset | 13 | Not started | `meta-quest-identity` |
| 15 | Backend revision safety (`based_on_revision` 409, conditional DynamoDB writes, LIVE pointer) | — | Done | `backend-revision-concurrency` |
| 16 | Backend auth core: Clerk web sessions + NemoClaw M2M, mock mode, fail-fast config | 15 | Not started | `backend-auth-clerk` |
| 17 | Membership, invite codes, Contributor ↔ Clerk user, ownership, `room_prompt` | 2, 16 | Not started | `room-api-and-ownership` |
| 18 | Meta identity exchange + Quest ↔ Clerk linking (backend, room tokens) | 14, 16 | Not started | `meta-quest-identity` |
| 19 | Web app foundation: `app/` React + Vite + `@clerk/react`, API client, mock mode | 13, 16 | Not started | `web-app-foundation` |
| 20 | Web uploads: person selects each object on a canvas (click/box/name) → SAM 3.1 masks → refine → generate PLYs; several photos at once; Notability sketches; optional text; invites; Link Quest page | 7, 17, 18, 19, 26 | Not started | `web-uploads-and-linking` |
| 21 | Public room API `/v1/rooms/{project_id}/state` + `/edits` | 15, 17, 18 | Not started | `room-api-and-ownership` |
| 22 | Unity networking: Meta sign-in, Multiplayer Services, NGO 2.x, Distributed Authority | 13, 14 | Not started | `unity-cloud-collaborative-vr` |
| 23 | Unity backprop client: room token, save on settle, session-owner polling | 21, 22 | Not started | `vr-edit-cloud-backprop-sync` |
| 24 | NemoClaw room tools (`get_room_state`, `propose_room_edit`; publish approved on the web) | 3, 15, 16, 21 | Not started | `top-tier-nemoclaw-tool-design` |
| 25 | End-to-end verification: web + two or more headsets | 20, 23, 29 | Not started | `collab-vr-device-verification` |
| 26 | Durable jobs (no in-memory dict), uploads in shared storage, upload → selections → refine → generate API, batch job polling | 15 | Not started | `durable-jobs-and-multi-object-upload` |
| 27 | GPU worker: SAM 3.1 masks from the person's selections (interactive points/box, semantic text), per-object Fast-SAM3D, dispatcher with leases, benchmarked concurrency | 26 | Not started | `gpu-multi-object-worker` |
| 28 | Letters: upload + recipients, sealed access, recipient-only open, scene schema, web form | 17, 19, 21, 26 | Not started | `letters-backend-and-web` |
| 29 | Letters in VR: envelope, networked open animation, textured 3D paper page | 22, 28 | Not started | `letters-vr-envelope` |

Every known issue these steps fix, with status, is in
`docs/KNOWN_ISSUES.md`.

**Gate command (mandatory before starting steps 13–29):**
`python3 scripts/check_collab_gates.py <step>`. BLOCKED means stop. Done
means `python3 scripts/check_collab_gates.py --done <step>` **and**
`bash scripts/verify_local.sh` both pass.

---

## Step 1 — Contributor / Contribution / ConnectionInsight data model + storage

**Goal:** persist who contributed what and why, and the AI's connection
output, using the existing storage abstraction — N-ary from day one, never a
fixed pair.

**Files:** `backend/main.py` (new Pydantic models, near `ProjectAsset`),
`backend/storage.py` (new `AuthoringStore` abstract methods + both backend
implementations), `backend/test_storage.py` (new tests).

**Concrete steps:**
1. In `main.py`, add `Contributor`, `Contribution` (with `ContributionSourceType = Literal["photo", "sketch", "letter"]`), and `ConnectionInsight` (with a per-object `placement_rationale` list, a `backend: Literal["mock", "meta", "xai", "nebius"]` field and a `model: str` field — see the `nemoclaw-model-providers` skill) as `BaseModel` subclasses, following the exact field style of `ProjectAsset`/`AssetView` (typed, `Field(min_length=..., max_length=...)`, `datetime` timestamps via `utc_now()`).
2. Extend `ProjectRecord` with `contributor_ids: list[str]`, `contribution_ids: list[str]`, `min_contributors: int = Field(default=2, ge=2)`, `max_contributors: int = Field(default=6, ge=2)` — read the defaults from `SKETCHSCAPE_MIN_CONTRIBUTORS` / `SKETCHSCAPE_MAX_CONTRIBUTORS` at project-creation time, matching how other env-configured defaults are read in `main.py`.
3. Add to `AuthoringStore` (abstract): `list_contributors`, `append_contributor`, `list_contributions`, `append_contribution`, `list_connection_insights`, `append_connection_insight` — mirroring the existing `list_blueprints`/`append_blueprint` naming exactly.
4. Implement in `LocalJsonStore`: same JSON-file, atomic-write pattern already used for blueprints — store each list under the project's JSON record.
5. Implement in `DynamoDbStore`: reuse `_query_children(project_id, sk_prefix)` (already generic) with `sk_prefix="CONTRIBUTOR"`, `"CONTRIBUTION"`, and `"INSIGHT"`. `append_contributor`/`append_contribution` write with `sk = f"CONTRIBUTOR#{contributor.contributor_id}"` / `f"CONTRIBUTION#{contribution.contribution_id}"` (unordered, one per id — no `_seq_key` needed since ids are already unique). `append_connection_insight` writes with `sk = self._seq_key("INSIGHT", insight.revision)` exactly like `append_blueprint`, since insights are revisioned like blueprints. **Do not create a second DynamoDB table** — this is the same table, same partition key, new sort-key families, per `docs/ARCHITECTURE.md`.
6. Write `backend/test_storage.py` tests mirroring the existing blueprint/publication tests: round-trip a contributor and a contribution through both `LocalJsonStore` and (if `boto3`/moto available) `DynamoDbStore`; assert a project with 3+ contributors round-trips correctly (this is the concrete N-ary check, not just 2).

**Definition of done:** `bash scripts/verify_local.sh` passes with new tests covering ≥3 contributors on one project; no field anywhere hard-codes a pair (grep the diff for `contributor_a`/`contributor_b` and reject any hit).

---

## Step 2 — Contributor / Contribution API endpoints

**Goal:** expose step 1's models over HTTP, matching the existing route style exactly.

**Files:** `backend/main.py`, `backend/test_api.py`.

**Concrete steps:**
1. `POST /v1/projects/{project_id}/contributors` (`response_model=Contributor`, `status_code=201`) — body `{display_name: str}`; generate `contributor_id` the same way `create_project_asset` generates `asset_id` (check that function for the id-generation helper already in use); append to `project.contributor_ids` and call `store.append_contributor`.
2. `GET /v1/projects/{project_id}/contributors` (`response_model=list[Contributor]`) — thin wrapper over `store.list_contributors`.
3. `POST /v1/projects/{project_id}/contributions` (`response_model=Contribution`, `status_code=201`) — body `{contributor_id, asset_id, source_type, memory_text}`; validate `contributor_id` exists in the project and `asset_id` is `status == AssetStatus.READY` (reuse the validation pattern from `validate_blueprint_assets`), then `store.append_contribution`.
4. `GET /v1/projects/{project_id}/contributions` (`response_model=list[Contribution]`).
5. Add `test_api.py` tests in the style of `MultiViewProvenanceTests`: register 3 contributors, submit a contribution each, assert all list back correctly and that submitting a contribution for a non-ready asset returns 4xx.

**Definition of done:** `verify_local.sh` green; a project can hold ≥2 contributors and their contributions purely through these endpoints, no direct storage access from a client.

---

## Step 3 — NemoClaw agent + Unity MCP Extension setup

**Goal:** stand up the actual NemoClaw agent runtime this repo has only described so far, wired to Meta's official Unity MCP Extension, before any tool can be built on top of it.

**Files:** `config/nemoclaw/sketchscape-tools.json`, `config/nemoclaw/mcp-servers.example.json`, no production code yet (this is environment/registration work).

**Concrete steps:**
1. Choose the agent runtime per `AGENT.md`'s "NemoClaw integration" section —
   [OpenClaw](https://github.com/openclaw/openclaw), [Hermes Agent](https://github.com/NousResearch/hermes-agent),
   or [LangChain Deep Agents](https://github.com/langchain-ai/deepagents) —
   and follow its current official onboarding. Do not guess a setup flow
   from memory; check current docs.
2. Install and configure Meta's **Unity MCP Extension for Horizon**
   (https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/)
   per that page's *current* instructions. **Requires Unity Editor
   6000.0.66f2 or later.** Register it as NemoClaw's Unity MCP target —
   never a generic/third-party Unity MCP server for this track.
3. Configure NemoClaw's model provider per the `nemoclaw-model-providers`
   skill and `config/nemoclaw/model-providers.example.json`. All three are
   OpenAI-SDK compatible, so one adapter serves them all:
   - `NEMOCLAW_MODEL_PROVIDER=meta` (default for the Meta track): Meta
     Model API, `https://api.meta.ai/v1`, model `muse-spark-1.3` (tool
     calling and image input), key in `META_MODEL_API_KEY`. It's in public
     preview for US developers.
   - `xai`: Grok API, `https://api.x.ai/v1`, `grok-4.7`, `XAI_API_KEY`.
     Use it for the Resilience Commons framing.
   - `nebius`: Nebius Token Factory,
     `https://api.tokenfactory.nebius.com/v1/`, open models such as Llama,
     `NEBIUS_API_KEY`. Choose exact model ids from its catalog.

   `NEMOCLAW_MODEL_BACKEND` is replaced by `NEMOCLAW_MODEL_PROVIDER`,
   `NEMOCLAW_MODEL` and `NEMOCLAW_VISION_MODEL`. Muse Spark is a reasoning
   model and has nothing to do with the rejected "Meta Muse Image"
   image-generation backend. Keys live only in the runtime's credential
   provider.
4. Update `config/nemoclaw/sketchscape-tools.json`: flip `implementation_status`
   from `target` to `implemented` for `gpu.start`-adjacent entries only once
   actually verified; add new `http_operations` entries for
   `contributor.register`, `contribution.submit`, and `connection.compose`
   (mirroring the existing entry shape: `id`, `method`, `path`, `purpose`,
   `approval_required`, `implementation_status`) as steps 2 and 5 land.
5. Confirm the registered Unity MCP target is **local/private only** — never
   expose it publicly, per the existing safety boundary in
   `.agents/skills/sketchscape-infrastructure/SKILL.md`.

**Definition of done:** NemoClaw can reach a local Unity MCP session through the official Horizon extension and echo back a trivial read-only scene inspection — no scene mutation yet. Credentials are never written to any file in this repo.

---

## Step 4 — NemoClaw layout tools

**Goal:** build the two tools that turn a catalog of contributed objects into a spatial layout, generalized to N objects from the start.

**Files:** wherever this repo's NemoClaw tool implementations live once step 3's runtime is chosen (document the actual path here once decided — do not leave tool code un-findable); `config/nemoclaw/sketchscape-tools.json` entries.

**Concrete steps:**
1. `place_objects_in_scene(objects: list[{asset_id, label}], sketch_layout_hint: LayoutHint | None) -> ExperienceBlueprintInput` — reasons about realistic layout for however many objects are passed (test with 2 and with 5), assigns `position`/`rotation`/`scale`/`interactions` per `BlueprintObject`, and returns a blueprint input ready for `POST /v1/projects/{id}/blueprints`. Do not publish automatically here — publication is a separate, explicit step per the existing blueprint contract.
2. `read_sketch_layout(sketch_image) -> LayoutHint` — optional; extracts rough spatial relationships ("lamp is left of chair") as a small structured hint object `place_objects_in_scene` can consume or ignore.
3. Both tools must accept a **list** of objects, never a hard-coded pair — this is the concrete enforcement of `docs/ARCHITECTURE.md`'s N-contributor section at the tool-signature level.
4. Unit-test both tools' pure-reasoning logic outside of any live LLM call where possible (deterministic geometry/bounds checks), and add one integration smoke test that runs `place_objects_in_scene` against `PIPELINE_MODE=mock` fixtures.

**Definition of done:** both tools produce a schema-valid `ExperienceBlueprintInput` (validated against `shared/experience-blueprint.schema.json`) for a 2-object input and a 5-object input in the same test run.

---

## Step 4a — NemoClaw subject labeling for uploads

**Goal:** a contributor uploads a photo without typing anything; NemoClaw
looks at it, decides which object is the subject, and passes a short,
specific noun phrase to SAM 3.1 as `subject_hint`.

**Decisions already made (do not re-litigate):**
- **Several subjects per upload** (updated 2026-09-25). `identify_subject`
  returns a list of labels, capped by `SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD`
  (default 8). They're used only for the optional "Suggest objects"
  helper and for naming. The person chooses which objects to mask and
  generate by clicking, boxing, or naming them on the website (steps 20,
  26–27). The single-object
  path still works for existing callers.
- A contributor-typed `subject_hint` always wins; NemoClaw only labels when
  it is empty.
- The worker's `mask_review` stays: if SAM 3.1 finds no clear match for
  NemoClaw's label, the job goes to review with that label shown for
  correction. NemoClaw's label is a reading of the photo, not the generic
  guessed prompt the worker forbids.
- Labels are noun phrases SAM 3.1 handles ("wicker armchair"), never
  relational sentences ("the chair left of the table").

**Files:** `backend/subject_labeler.py` (new, uses the same
`mock | …`-selector pattern as the other pluggable backends in this repo,
e.g. `backend/storage.py`'s `create_store`), `backend/main.py` (hook in
`create_reconstruction` / `create_project_asset`), `backend/test_subject_labeler.py`,
`config/nemoclaw/sketchscape-tools.json`.

**Concrete steps:**
1. `identify_subject(image) -> SubjectLabel {label, alternatives, backend}`.
   `SKETCHSCAPE_SUBJECT_LABELER=mock|nemoclaw`, default `mock`.
2. Mock path: deterministic, offline, no model call; labelled `backend="mock"`.
3. Record provenance on the job: `subject_hint_source: "user" | "nemoclaw"`.
4. Live path (after step 3): the tool runs inside NemoClaw on the
   configured vision model (`NEMOCLAW_VISION_MODEL`; Muse Spark on the
   default `meta` provider) — never a standalone model call bypassing NemoClaw. Tests
   mock it; no live call without explicit user approval (Hard Rule 3).

**Definition of done:** an upload with no `subject_hint` produces a labelled
job in mock mode; a user-typed hint is never overwritten; `verify_local.sh`
green.

---

## Step 5 — `connection/compose` endpoint

**Goal:** the single most important missing piece — produces `ConnectionInsight` and a blueprint proposal by invoking NemoClaw's own tools, never a standalone model-API call that bypasses them.

**Files:** `backend/main.py`, `backend/test_api.py`.

**Concrete steps:**
1. `POST /v1/projects/{project_id}/connection/compose` (`response_model` — define a `ConnectionComposeResponse` wrapping `ConnectionInsight` + `ExperienceBlueprintInput`).
2. Guard clause: `len(store.list_contributions(project_id)) >= project.min_contributors`, else `409`. This is the concrete enforcement point for `SKETCHSCAPE_MIN_CONTRIBUTORS`.
3. **Mock path** (`PIPELINE_MODE=mock`, build this first): a deterministic function over the contributions' labels/memory text — no network call, no NemoClaw runtime required. Reuse a simple deterministic technique already proven in this codebase's mock philosophy (e.g. keyword-overlap or a fixed small lookup table keyed by label pairs/sets) so the same inputs always produce the same theme. Label the result `backend="mock"` on the `ConnectionInsight`.
4. **Live path**: invoke NemoClaw's `place_objects_in_scene` (step 4) to get the blueprint, and derive `ConnectionInsight.theme`/`explanation`/`object_rationales` from the same reasoning pass — do not make two independent calls that could disagree. Record `backend=NEMOCLAW_MODEL_PROVIDER` (`"meta"`, `"xai"` or `"nebius"`) and `model` = the exact model id used.
5. Persist via `store.append_connection_insight`; the caller separately calls the existing `POST /v1/projects/{project_id}/blueprints` with the returned `ExperienceBlueprintInput` to save it as a revision (reuse, don't duplicate, the existing blueprint creation path).
6. Tests: one asserting the mock path is deterministic (call twice, same theme), one asserting `409` below `min_contributors`, one asserting the response references only `READY` assets (reuse `validate_blueprint_assets`' checking pattern).

**Definition of done:** two (and separately, in another test, four) contributions compose into a valid `ConnectionInsight` + blueprint proposal in mock mode with zero external calls; `verify_local.sh` green.

---

## Step 6 — `stage_immersive_reveal` + immersive scene-craft toolkit

**Goal:** the emotional-staging tool and the open-source toolkit it's built from — additive on top of steps 4–5, never a dependency the core story needs.

**Files:** NemoClaw tool code (same location as step 4), Unity project (`../HackGTUnity`, outside this repo) for the actual staging components.

**Concrete steps (backend/tool side):**
1. `stage_immersive_reveal(connection_insight: ConnectionInsight, objects: list[BlueprintObject]) -> StagingPlan` — a new structured output (define its schema) describing reveal order, a lighting/mood preset keyed to the theme, a connecting-motif spec (e.g. a light-path curve between object positions), narration audio reference or text-to-synthesize, and per-object haptic/sound signature ids. This must accept the same N-length object list as step 4.
2. `StagingPlan` is consumed by the Unity side, not rendered here — keep this tool's output plain data, no Unity-specific types.

**Concrete steps (Unity side, per `AGENT.md`'s "Immersive scene craft"):**
3. Guided sequencing: adopt [VR Builder](https://github.com/MindPort-GmbH/VR-Builder)'s step/transition authoring model (or a minimal subset) to drive the reveal order from `StagingPlan`.
4. Animation: pick **one** of [PrimeTween](https://github.com/KyryloKuzyk/PrimeTween) or [TweenPlayables](https://github.com/AnnulusGames/TweenPlayables) — document the choice in `docs/INTEGRATION_GUIDE.md` once made, don't leave both half-integrated.
5. Mood lighting: integrate one open-source URP volumetric light/fog shader ([CristianQiu/Unity-URP-Volumetric-Light](https://github.com/CristianQiu/Unity-URP-Volumetric-Light) or [ramalingamthangamani/URP-Volumetric-Fog](https://github.com/ramalingamthangamani/URP-Volumetric-Fog)), parameterized by `StagingPlan`'s lighting preset.
6. Atmosphere: restrained ambient particles from Unity's own [VisualEffectGraph-Samples](https://github.com/Unity-Technologies/VisualEffectGraph-Samples).
7. Spatial audio + narration: [Resonance Audio](https://github.com/resonance-audio/resonance-audio) for 3D sound, plus spoken narration of `ConnectionInsight.explanation` — a recorded voice is safest for the demo; if synthesizing, Meta's own open-source [MMS TTS](https://github.com/facebookresearch/fairseq/tree/main/examples/mms) is on-brand (CC-BY-NC 4.0 — fine for a hackathon demo, flag if this ever ships commercially). This narration is what replaces on-screen text.
8. Per-object haptics/sound: Unity XR Interaction Toolkit's haptic API (`SendHapticImpulse`) driven by `StagingPlan`'s per-object signature ids, paired with each object's animation sound cue.
9. Verify graceful degradation: with none of steps 3–8 installed, the room must still load and read correctly (plain lighting, no sound) — write this as an explicit manual check before calling the step done, since it's not something `verify_local.sh` can test.

**Definition of done:** a recorded run-through shows the reveal choreography working end to end for a 2-object mock composition, and a second run with all of steps 3–8 stubbed out still shows a correct (if plain) room.

---

## Step 6a — NemoClaw environment objects from web images

**Goal:** when NemoClaw builds the immersive room around the contributed
objects, it can add set-dressing objects on its own (a rug, a lamp, shelving
that suits the theme) by finding a clean single-object photo on the web and
sending it through the same SAM 3.1 → Fast-SAM3D pipeline.

**Decisions already made:**
- Web images only for NemoClaw's own environment objects — never to replace
  or split contributors' uploads, and no generated images for this.
- Contributed objects stay the heroes; environment objects are staged as
  supporting set dressing by `stage_immersive_reveal` (step 6).

**Concrete steps:**
1. `find_object_image(description) -> {image_url, source, license, attribution}`
   searching reuse-friendly sources only (Openverse, Wikimedia Commons).
   Record source/license on the resulting asset so every published object
   has clear rights.
2. Guardrails: per-scene cap on environment objects (default 6, env
   configurable) because each one is an autonomously started GPU job, plus
   an on/off flag. Mock mode uses a fixed fixture set: no web, no GPU.
3. Feed the resulting assets into `place_objects_in_scene` alongside the
   contributed ones, marked as environment objects.

**Definition of done:** mock composition includes environment objects from
fixtures with source/license metadata; cap and off switch are tested.

---

## Step 7 — Notability sketch: direct display + SAM3D memory-plaque path

**Goal:** replace the retired sketch → image-generation → reconstruction
pipeline with two paths that use a Notability sketch/page for what it
actually is, instead of trying to hallucinate a fake photorealistic photo
out of a line drawing.

**The old pipeline is gone.** `POST /v1/sketches`, `backend/image_gen.py`
(`mock`/`azure`/`hf` backends), and `backend/test_image_gen.py` have been
deleted. Converting a sketch into a fabricated "photorealistic" object via
DALL-E/SDXL added a paid backend, an extra network hop, and a visibly fake
result, for a use case a direct photo upload to the existing
`POST /v1/reconstructions` already serves better: if a contributor has a
real object, they photograph it. **Do not reintroduce `image_gen.py`, the
`azure`/`hf`/`grok` image backends, or `/v1/sketches`.** If a Meta Muse
Image reference turns up anywhere, that's doubly stale — it was already
rejected before this pipeline was removed entirely.

**What a Notability sketch is for now:** the ideas below, not a stand-in
photo.
- **Drawings:** Path 1, a flat card.
- **Letters** (a handwritten Notability page addressed to someone): the
  textured 3D paper page inside an envelope, built in steps 28–29.
  Recipient-only opening with a live animation, no GPU, handwriting stays
  legible. This replaces Path 2 for letters.
- **Path 2** (SAM3D memory plaque) stays optional for non-letter pages.

**Files:** `backend/main.py` (new endpoint(s)), Unity project for the
render/mesh side, `shared/scene.schema.json` only if a genuinely new runtime
field is required (per `AGENT.md`'s rule — don't add a "caption" field for
this).

### Path 1 — Direct display (flat quad, fast/cheap)

A Notability export is placed into the room as a textured plane/card, no
SAM 3.1 or Fast-SAM3D involved. This is the default, always-available path:

1. New endpoint (e.g. `POST /v1/projects/{project_id}/sketch-assets`) that
   stores the uploaded sketch image and registers it as a catalog asset with
   a source type distinguishing it from a reconstructed `.ply` (a flat
   quad/card asset, not a mesh) — reuse the existing asset/catalog contract,
   don't fork a parallel one.
2. `place_objects_in_scene` (step 4) treats this asset type as a
   billboard/card placement (position + rotation + scale, facing outward or
   toward the viewer) rather than a 3D object placement.
3. No image-gen backend, no GPU, no paid API — this path is free and works
   offline exactly like `PIPELINE_MODE=mock`.

### Path 2 — SAM3D memory plaque (diegetic text, no floating UI)

The better use of Notability: run the **actual page** — sketch plus the
contributor's handwritten/typed memory note — through the existing
SAM 3.1 → Fast-SAM3D pipeline like any other photo, producing a real 3D
plaque/page object with the memory text physically part of its
geometry/texture. This is a concrete instance of AGENT.md's "the connection
must be felt, not read" rule and Step 8's need for a physically-modeled
in-world text object instead of a floating UI card — treat this as the
mechanism Step 8 uses for per-contributor memory text, not a separate
display gimmick:

1. The Notability page image is uploaded to `POST /v1/reconstructions`
   exactly like a photo (no new reconstruction code needed) — the "object"
   being reconstructed is the physical page/plaque itself.
2. NemoClaw's staging (`stage_immersive_reveal`, step 6) places the
   resulting plaque mesh near its contributor's other object, per Step 8's
   attribution manifest.
3. Confirm Fast-SAM3D's real output quality on a flat page with text before
   committing to this as the primary path (it was verified in the GPU pass
   for object geometry, not specifically for a flat textured plane with
   legible text) — if text doesn't survive reconstruction legibly, keep
   Path 1 as the fallback for that contribution rather than shipping an
   illegible plaque.

**Definition of done:** a contributor can submit a Notability sketch and see
it appear in the room either as a flat card (Path 1, always works) or as a
reconstructed 3D plaque with legible embedded text (Path 2, GPU-dependent,
verified per point 3 above). `mock` mode exercises Path 1 end to end with no
GPU or paid API. No `image_gen.py`, no `azure`/`hf`/`grok` image backends, no
`/v1/sketches` anywhere in the repo.

---

## Step 8 — Unity: diegetic attribution + bounded per-contributor edit

**Goal:** make the AI's output and each contributor's ownership perceivable in Unity without a UI text panel, and let each contributor edit only their own object(s) — generalized to N. Where a contributor's memory text needs to be physically legible in-world, prefer step 7's SAM3D memory-plaque path (a real reconstructed page/plaque object) over inventing a new text-rendering mechanism.

**Files:** Unity project (`../HackGTUnity`), plus a small sidecar social-manifest schema in this repo if Unity needs one (per `AGENT.md`: keep it in the authoring blueprint or a versioned sidecar, not `shared/scene.schema.json`, unless a genuinely new runtime field is required).

**Concrete steps:**
1. Define the sidecar manifest shape carrying, per object: `contributor_id`, `contributor_display_name`, and a reference into the `StagingPlan` (step 6) for that object's attribution cue (marker/material tint/spoken intro) — write this as a small JSON schema next to `shared/scene.schema.json` if it doesn't already have a home.
2. Compile this manifest alongside the compiled scene in the existing `compile_blueprint` path (`backend/main.py`) — don't invent a second compile step.
3. In Unity, extend `SceneInteractionController`'s existing bounded-action registry (see `docs/INTEGRATION_GUIDE.md` §3) so a given contributor's session can only submit `scale_by`/`translate_by`/`rotate_by` for object ids the manifest attributes to them — this is the N-safe version of "one bounded edit per contributor."
4. Wire attribution cues (marker/material/spoken intro) and the staging plan from step 6 into the actual scene at build time via the existing offline experience builder, not a new separate builder.

**Definition of done:** a 3-contributor mock composition, once compiled, shows each object correctly attributed in Unity, and each contributor's edit is rejected for objects they didn't contribute (test via the desktop simulator, no headset required).

---

## Step 9 — Meta hardware polish

**Goal:** the small, mostly-optional, Meta-specific additions from `AGENT.md`'s "Hardware and production ideas" — build in this priority order, stop wherever time runs out.

**Files:** Unity project; `backend/main.py` for the Llama Guard hook.

**Concrete steps, in priority order:**
0. Use **Meta XR Building Blocks** (Meta > Tools > Building Blocks in the
   Unity menu, requires Meta XR Core SDK) to drag-and-drop the Passthrough
   and Hand Tracking blocks below instead of assembling them by hand.
1. Passthrough closing beat via the [Meta XR SDK's Passthrough API](https://developers.meta.com/horizon/documentation/unity/unity-passthrough/)
   (`OVRManager` → Quest Features → Passthrough Support, or the Building
   Blocks shortcut above).
2. Hand tracking for the bounded edit (step 8) via the [Meta XR Interaction SDK](https://developers.meta.com/horizon/documentation/unity/unity-handtracking-overview/)
   — pinch-to-grab as an alternate input path alongside the existing
   controller path, not a replacement. Use its built-in grab/poke gestures
   rather than custom hand-pose detection.
3. Contributor identity from the logged-in Quest account via the Meta
   Platform SDK — `Oculus.Platform.Users.GetLoggedInUser().OnComplete(...)`
   returns a `User` with `.DisplayName` — falling back to the typed display
   name from step 2's endpoint. This is display-only. For **verified**
   identity (accounts, permissions), use the Meta user-proof flow and
   Clerk linking from steps 14 and 18 (`meta-quest-identity`), never the
   client-reported user id alone.
4. [Llama Guard](https://github.com/meta-llama/PurpleLlama) moderation (Meta's
   open-source PurpleLlama project, Llama Guard 3 in 1B/8B variants): in
   `POST /v1/projects/{project_id}/contributions` (step 2), pass
   `memory_text` through Llama Guard before persisting; reject or flag per
   its response — define the exact rejection contract (4xx with reason, or
   store a moderation flag) before wiring it in.
5. Mixed Reality Capture recording is a *recording-time* choice, not a build step — see step 12.

**Definition of done:** each item built is independently toggleable/optional; none blocks the core connection flow if skipped, per `AGENT.md`'s explicit rule.

---

## Step 10 — GPU end-to-end verification + cloud backend activation

**Goal:** the already-documented infra work in `AGENT.md` items 2–3 — included here only for sequencing completeness; the concrete steps live in `infra/aws/SMOKE_TEST_GUIDE.md`.

**Status:** the GPU half is done — verified end-to-end on an NVIDIA L40S (g6e.xlarge, us-east-2): 70 s total, a 53 MB / 814,432-vertex PLY (see `docs/PROJECT_STATUS.md`). What's left is setting the cloud backend env vars on the EC2 API process. Re-run the GPU part only if something changed, and only with approval.

**Concrete steps:** follow `infra/aws/SMOKE_TEST_GUIDE.md` exactly — start EC2 → SSM + `nvidia-smi` → publish bundle → bootstrap with HF token (one-time, unset immediately) → SAM 3.1 smoke test → Fast-SAM3D smoke test → full API callback → stop instance. Then set `SKETCHSCAPE_STORAGE_BACKEND=dynamodb`, `SKETCHSCAPE_DYNAMODB_TABLE`, `SKETCHSCAPE_ARTIFACTS_BACKEND=s3`, `SKETCHSCAPE_ARTIFACTS_BUCKET` on the running API process (Step 5 of the same guide). **Never run any of this without explicit user approval** — it costs money.

**Definition of done:** matches `infra/aws/SMOKE_TEST_GUIDE.md`'s own success criteria.

---

## Step 11 — Unity offline builder fix + real-PLY splat rendering

**Goal:** the already-documented Unity work in `AGENT.md` items 5–7 — included here for sequencing; concrete steps live there.

**Concrete steps:** in `SketchScapeOfflineExperienceBuilder`, create a `GsplatRenderer` when a `.ply` exists and skip the object entirely (no primitive) when it doesn't; then load one real Fast-SAM3D `.ply` in Unity with UnitySplats and confirm render + acceptable Quest framerate; then build the baseline room environment (walls/floor/lighting/colliders/locomotion) that step 6's immersive layer sits on top of.

**If UnitySplats hits a blocker:** [aras-p/UnityGaussianSplatting](https://github.com/aras-p/UnityGaussianSplatting)
is the other well-known Unity Gaussian-splat renderer and reportedly runs on
Quest 3/Quest Pro — but its author has flagged no significant further
development since December 2023, so treat it as a fallback reference for
comparison/debugging, not a primary dependency to adopt fresh.

**Definition of done:** matches the acceptance checks already in `AGENT.md` items 5–7.

---

## Step 12 — Demo video + write-up

**Goal:** ship the artifact judges actually see.

**Concrete steps:** load the `demo-video-prep` skill; walk `features.txt` line by line against whatever subset of steps 1–11 actually landed; record in `PIPELINE_MODE=mock`; write up both tracks per `docs/PROJECT_STATUS.md`'s write-up structure.

**Definition of done:** matches `docs/PROJECT_STATUS.md`'s "Social-product definition of done" and the checklist in `features.txt`.

---

## Collaborative VR + web accounts track (steps 13–29)

**Goal:** people sign up on the SketchScape website and upload their photos,
Notability sketches, and optional text there. In their Quest headsets they
share one live Shared Room: one person's move/rotate/scale shows on every
headset immediately and is saved, so the room looks the same after
everyone leaves.

**Architecture (decided 2026-09-25, don't re-litigate):**

- **Accounts: Clerk.** Every person is a Clerk user, created on the
  website.
  - The website (`app/`, React + Vite + `@clerk/react`, replacing the old
    Electron plan) sends Clerk session tokens.
  - The backend verifies them with `clerk-backend-api`
    (`session_token`, `authorized_parties` = web origins).
- **Headset identity: the Meta account.** Clerk has no Meta Quest login
  provider, so the headset never holds a Clerk token.
  - The Quest proves the user with Meta Platform SDK `GetUserProof()`
    nonces.
  - Unity Cloud signs in with `SignInWithOculusAsync(nonce, userId)`.
  - The backend validates a second nonce at
    `graph.oculus.com/user_nonce_validate`, looks up the Clerk user linked
    to that Meta ID, and issues a 1-hour **room token**.
  - Linking happens once: the headset shows a code, and the person enters
    it on the website's Link Quest page.
  - `GetUserProof` needs Meta's Data Use Checkup. Until it's approved,
    only Meta test users work.
- **NemoClaw identity:** a Clerk M2M token (`kind="service"`).
- **Live layer:** Unity Multiplayer Services **Distributed Authority** +
  Netcode for GameObjects 2.x. Client-hosted Relay can't migrate the host,
  so the room would close when the host left.
- **Durable layer:** blueprint revisions stay the source of truth (Hard
  Rule 6).
  - Headsets save through the **public** room API (`/v1/rooms/*`, Hard
    Rule 4), which checks ownership, allowed interactions, bounds, and
    revision, then publishes server-side in one request.
  - No Unity Cloud Save.
- **NemoClaw** changes a live room only by drafting a revision; a person
  approves the publish on the website. It never changes a live room
  through the Editor-only Unity MCP Extension.
- **Uploads:** photos and sketches go through the existing asset routes
  and step 7 sketch routes.
  - Optional text: object label / `subject_hint` (NemoClaw labels the
    photo if it's blank), memory text per contribution, and a project
    `room_prompt`, all treated as untrusted data.
  - **Cost decision (user): no per-user upload limits.** Every cloud
    upload may start a GPU job, which means uncapped spend.

**Rejected alternatives (documented so nobody rebuilds them):**
- Clerk OAuth + PKCE browser login on the headset federated via Unity
  OIDC. The browser redirect back into an immersive app was the riskiest
  step, and it's unnecessary with Meta sign-in.
- Electron desktop app, because Clerk's Electron support is unofficial.
- Next.js, because AGENT.md rules it out and it would add a Node server.
- Unity Cloud Save, because its shared data is server-write-only and would
  be a second source of truth.

**Gate system:**
- `scripts/check_collab_gates.py` checks evidence in code and config for
  each step and all its prerequisites.
- Facts no script can see are manual gates in
  `config/collab-vr/gates.json`, which only the user may confirm.
- Every run also scans the repo, `app/.env*`, and the Unity project for
  leaked secrets:
  - Clerk `sk_` keys
  - Meta `OC|app_id|app_secret` tokens
  - `VITE_*SECRET*` variables, which Vite would ship in the public bundle
- `verify_local.sh` runs the status check, so a leak fails verification.

**Config and secrets:** one matrix for local, dev, and prod lives in the
`collab-vr-accounts-and-gates` skill. Secrets (`CLERK_SECRET_KEY`,
`SKETCHSCAPE_META_APP_SECRET`, `SKETCHSCAPE_ROOM_TOKEN_SECRET`) live only
in backend secret storage (and the Meta secret in the Unity dashboard).
The backend refuses to start when misconfigured:
- `clerk` mode without a secret key, or with `*` origins.
- `mock` mode against DynamoDB or a non-mock pipeline.
- Meta enabled without its secrets.

**Per-step detail lives in the skills** (table above). What each step
delivers:

- **13** — Clerk app, Meta app with test users, Unity Meta provider; the
  config matrix.
- **14** — proves Meta identity on a real Quest first: entitlement check,
  two nonces, `SignInWithOculusAsync`, server validation.
  *Results (fill in):* sign-in OK: ___ · nonce is_valid: ___ · test users
  set up: ___
- **15** — fixes three concurrency bugs:
  - silent lost edits (no base-revision check)
  - the DynamoDB overwrite race (unconditional `put_item`, per-process
    lock)
  - the live room going backwards (publish compare-and-set on a `LIVE`
    pointer)
- **16** — Clerk session/M2M verification, authors on revisions, CORS
  locked to web origins, fail-fast startup.
- **17** — invite codes, membership checks on every project route, Clerk
  binding for contributors, ownership, `room_prompt`.
- **18** — `/v1/auth/meta/session`, `/link-code`, `/link`: nonce
  validation, unique Meta↔Clerk links, hashed single-use codes with
  attempt limits, room tokens.
- **19** — the web app shell with Clerk, an authenticated API client, and
  a mock mode that works offline.
- **20** — photo upload with progress; Notability flat card or 3D plaque
  (PDF → PNG in the browser if needed; HEIC converted or rejected);
  optional label, memory text, and room prompt; invites; Link Quest page.
- **21** — `/v1/rooms/*` with idempotent, owner-checked, bounded,
  revision-checked edits built on the live revision.
- **22** — Meta sign-in plus Distributed Authority networking from the VR
  Multiplayer Template 2.1, ported with matching package versions; an
  in-headset link-code screen.
- **23** — save on release (debounced); 409 → rebase; retries with the
  same `client_edit_id`; room-token refresh; session-owner polling.
- **24** — NemoClaw drafts room edits; a person approves the publish on
  the website.
- **25** — end-to-end verification on real hardware.
  *Results (fill in):* fps with N people: ___ · session survives owner
  leaving: ___ · DUC status: ___ · quotas checked: ___

**Added 2026-09-25:**

- **Any number of people.** Rooms, invites, uploads, letters (many
  recipients), and live sessions all take lists. The Unity session's
  `MaxPlayers` comes from the project's `max_contributors`
  (`SKETCHSCAPE_MAX_CONTRIBUTORS`, default 6). Tests use 3+ people, never
  just 2. The demo can still show two.
- **Data architecture:** `docs/DATA_ARCHITECTURE.md` is the single
  reference. It covers every DynamoDB item and index, the S3 layout for
  uploads, masks, PLYs and letters, the optional user text fields and
  limits, the accounts data, and the job lifecycle. Adding GSI1, GSI2 and
  TTL is a Terraform change that needs approval.
- **Polling contract** (in DATA_ARCHITECTURE.md): one project-level jobs
  endpoint with ETag/304 for the web app, `since_revision` for the
  headset, and a nonce-free link-status poll. Backoff, jitter, polling
  pauses when the tab is hidden, and a separate rate-limit bucket.
- **26** — fixes three bugs that break multi-object and multi-user
  uploads: in-memory jobs, uploads on one API host's disk, and
  `asset_ids` appended inside the whole-project blob. Adds the
  **person-chosen** flow:
  1. Upload.
  2. On the website, mark every wanted object: click (include/exclude),
     box, or typed name.
  3. SAM 3.1 masks exactly those objects.
  4. Refine any one.
  5. Generate one PLY per object.

  Also adds batch polling. Auto-detect only suggests selections.
- **27** — SAM 3.1 turns the person's selections into masks in one pass
  per photo: points and boxes use the interactive predictor (one mask
  each), and typed names use the semantic predictor (best instance plus
  alternatives). Then one Fast-SAM3D job runs per chosen object through a
  leased queue.
  `SKETCHSCAPE_GPU_CONCURRENCY` defaults to 1 and is raised only after an
  approved VRAM benchmark (a T4 stays at 1).
  *Results (fill in):* instance: ___ · peak VRAM 1 job: ___ · 2 jobs: ___
  · concurrency chosen: ___
- **28–29** — letters. The Notability page becomes a textured 3D paper
  mesh (legible, no GPU) sealed in an envelope. Only the addressed
  recipients can open it; everyone in the room sees the open animation
  live, and the opened state is saved. A sealed page is never served to
  non-recipients.
- **NemoClaw models:** Meta Model API (Muse Spark, the default), Grok API,
  or Nebius Token Factory through one OpenAI-compatible adapter (step 3,
  `nemoclaw-model-providers`).

**Never do in this track:**
- Put a secret in the repo, `app/`, or the Unity project.
- Let a headset call authoring routes.
- Publish a NemoClaw draft without a person's approval.
- Use anonymous Unity sign-in outside the offline fallback.
- Start a step whose gate is BLOCKED.
- Serve a sealed letter's page to anyone other than its author and
  recipients.
- Raise GPU concurrency without a recorded benchmark.
- Hard-code two people anywhere.

---

## If time runs out

Priority order if the full plan can't land before the deadline: **5 (compose endpoint, mock path only) → 1–2 (data model/API it depends on) → 8 (diegetic attribution, even a minimal version) → 11 (real splat rendering) → 12 (video)**. Steps 3–4 and 6 (NemoClaw agent + immersive staging) are what make the story *strong*, but 5's mock path alone is enough to demo the connection insight without a live agent — the mock output is judging-safe by design. Steps 7, 9, 10 are genuinely optional polish; skip them first. The
Collaborative VR + web accounts track (13–29) is post-MVP: never pull time from steps
1–12 for it before the demo is safe.
