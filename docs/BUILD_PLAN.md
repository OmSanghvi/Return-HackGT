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
| 3 | NemoClaw agent + Unity MCP Extension setup | — | **Done: NemoClaw ↔ Unity MCP verified directly** (2026-09-26). Runtime: NVIDIA NemoClaw CLI in WSL, OpenClaw agent, sandbox **`sketchscape`** (onboarded with a per-machine private CA baked in), local Ollama `qwen3.5:9b` for dev. A live agent turn made a real `tools/call` to `meta_get_config_information` and got Editor data back, through OpenShell's `mcp_bridge_unity_mcp` policy. The bridge is scripted and idempotent: `scripts/unity-mcp-bridge/Setup-UnityMcpBridge.ps1` (TLS proxy on the WSL gateway IP → mcp-proxy → Unity's `relay_win.exe --mcp`). Rerun it after a reboot; on a new laptop, run it with `-Onboard`. `../HackGTUnity` is on Unity 6000.6.3f1, with `com.unity.ai.assistant@2.20.0-pre.1` and `com.meta.xr.unity-mcp.extension` (pinned to commit `ac3dd9cdb2675cb0eee98655acb0731349fc6f9e`). Claude Code's own `unity-mcp` stdio connection also still works. **Meta Horizon tools live** (2026-09-26): Meta XR SDK `com.meta.xr.sdk.all` 207.0.0 installed. Meta's MCP extension is embedded in `HackGTUnity/Packages/` with a Unity 6.5+ compile fix (`scripts/unity-mcp-bridge/patches/`; upstream `GetInstanceID()` is a hard error). Unity MCP now lists 17 tools (9 `meta_*`), and NemoClaw's agent made a real `tools/call` to `meta_get_interactors_state`. Still open: (a) the scene has no camera rig yet, so no `meta_add_*` tool has run and the patched line is unexercised. (b) `Unity_RunCommand`, the 7 `meta_add_*` tools and `meta_update_android_manifest` are exposed but not yet approval-gated. (c) `qwen3.5:9b` is unreliable at tool calling; switch provider to `meta`/`xai`/`nebius` with `nemoclaw inference set` (don't rebuild without the CA). (d) The old `my-assistant` sandbox was destroyed (2026-09-26), so `sketchscape` is the only sandbox | `nemoclaw-agent-setup` |
| 4 | NemoClaw layout tools (`place_objects_in_scene`, `read_sketch_layout`) | 3 | Implemented and unit-tested (`backend/scene_tools.py`, `backend/scene_tools_cli.py`, 21 tests green); confirmed working via direct exec inside the sandbox; installed into the sandbox as the `sketchscape-scene-tools` OpenClaw skill (shows `✓ ready`); **Live agent tool-calling now verified** (2026-09-26, session `scene-verify-1`): with a sufficiently directive prompt and `--session-id` for a multi-turn conversation, `qwen3.5:9b` genuinely invoked `exec` running the real `scene_tools_cli.py place_objects_in_scene` command (confirmed in the raw `.jsonl` session transcript, not just self-reported) and got back the real, correct, schema-valid blueprint. The first attempt to have it summarize that result came back with empty content (a small-model reliability quirk after a large tool-result blob enters context, not a correctness problem) — a second turn in the same session recovered cleanly and correctly reported the real first object's position (`x=-1.938, y=0.175, z=1.807`) pulled from the actual tool output, not fabricated. Two earlier one-shot (non-session) attempts had failed to clearly invoke the tool at all — the fix was `--session-id` plus an explicit "use your shell/execute tool, do not simulate" instruction. **Blueprint → Unity write bridge is now a real, reusable, input-driven tool** (2026-09-26): `backend/blueprint_to_unity.py` (`blueprint_to_unity_command(blueprint)`) takes any schema-valid `ExperienceBlueprintInput` — validated against `shared/experience-blueprint.schema.json` before codegen — and deterministically generates a Unity Editor `IRunCommand` C# script that recreates it as real GameObjects (placeholder cubes + floor plane). `backend/blueprint_to_unity_cli.py` exposes it the same way `scene_tools_cli.py` does (JSON in via arg or stdin, C# source out), for an agent with shell access. 7 new unit tests in `backend/test_blueprint_to_unity.py` (28 total across both files) cover object counts 1–8, floor on/off, and string escaping. **Verified twice against the live Editor with two different blueprint shapes** (a 4-object set, then a differently-sized 3-object set generated purely through the CLI) — both landed in `HackGTUnity` with correct position/rotation/scale on read-back, proving this isn't hardcoded to one demo shape. Note: Unity's `JsonUtility.FromJson` silently fails to populate nested custom classes inside this dynamically-compiled RunCommand context (confirmed with a minimal, null-free repro) — the bridge generates C# object-creation statements directly from the blueprint dict in Python rather than parsing JSON at runtime in Unity; any future bridge code should do the same, not assume `JsonUtility` works here. Verified runs were Claude-Code-mediated (paste generated C# into `Unity_RunCommand`). NemoClaw can now reach Unity MCP directly (step 3), but it shouldn't call `Unity_RunCommand` unattended until that tool has an approval gate. Doesn't touch `interactions`/haptics or real per-asset prefabs (step 6 Part B territory, still placeholder cubes) | `nemoclaw-scene-tools` |
| 4a | NemoClaw subject labeling for uploads (`identify_subject`) | 3 (live path only) | Mock path built; live path waits on 3 | `nemoclaw-subject-labeling` |
| 5 | `connection/compose` endpoint (mock path, then live NemoClaw path) | 1, 2, 4 | Mock path built; live path waits on 4 | `connection-compose-endpoint` |
| 6 | `stage_immersive_reveal` + immersive scene-craft toolkit | 4, 5 | Part A (backend tool, `backend/scene_tools.py`) implemented and unit-tested; Part B (Unity-side toolkit) built, untested (2026-09-26): `unity/Assets/Scripts/Staging/` (StagingPlan DTOs/parser, `ImmersiveStagingDirector`) applies mood lighting (light color/intensity, fog, URP Volume `ColorAdjustments`), a `LineRenderer` connecting motif, ordered per-object reveal with haptics (`UnityEngine.XR.InputDevices` impulses), and narration (clip if packaged, else a caption event, never a UI card), hooked into `SketchScapeOfflineExperienceBuilder` via `meta.staging`; not opened in the Editor yet, no `staging` block in the `compiled-scene.json` fixture to exercise it | `immersive-reveal-staging` |
| 6a | NemoClaw environment objects from web images (`find_object_image`) | 4, 10 | Not started | `nemoclaw-environment-sourcing` |
| 7 | Notability sketch: direct display (flat quad) + SAM3D memory-plaque path | — | Flat card built; plaque wired, legibility unverified on GPU | `sketch-image-gen-backends` |
| 8 | Unity: diegetic attribution + bounded per-contributor edit | 5, 6 | Built (manifest, owner-only edits, base ring); not yet checked in Unity; staging cues wait on 6 | `unity-diegetic-attribution` |
| 9 | Meta hardware polish (passthrough, hand tracking, MRC, Quest identity, Llama Guard) | 8 | Not started | `meta-hardware-polish` |
| 10 | GPU end-to-end verification + cloud backend activation | — | GPU verified (L40S); cloud env vars on the EC2 API not set yet | `gpu-cloud-activation` |
| 11 | Unity offline builder fix + real-PLY splat rendering | — | Core builder rebuilt and verified end-to-end through the real backend API (project → asset → publish → export → build), not just a fixture (2026-09-26, see step detail below); still needs a real Fast-SAM3D `.ply` (in progress separately) and the Quest/room-environment portion | `unity-offline-builder-and-rendering` |
| 12 | Demo video + write-up | 1–11 (as available) | Not started | `demo-video-prep` |

Steps 7, 10, and 11 have no dependency on the social layer and can be built
in parallel with steps 1–6 by a different session. Everything funnels into
12. `meta-track-alignment` is the standing skill that governs *every* step
above — load it whenever judgment calls come up mid-step.

### Collaborative VR + web accounts track (steps 13–29) — gated

The web app (uploads, Notability sketches, optional text) and live
multi-headset rooms, all under **two hardcoded accounts** — no Clerk, no
Meta account linking. Approved 2026-09-25 as a **post-MVP, gated** track:
it must never break or delay the MVP (steps 1–12), and every step is
blocked until its prerequisites are verifiably done. See "Collaborative VR
+ web accounts track" below and AGENT.md Hard Rule 9.

**Identity decision (revised 2026-09-26, supersedes the 2026-09-25 Clerk/Meta
plan):** the two hardcoded accounts (`SKETCHSCAPE_AUTH_MODE=demo`,
`SKETCHSCAPE_DEMO_USERS`) are the **real, permanent identity model** for
this track, not a temporary stand-in. There is no Clerk sign-in, no Meta
account linking, and no room-token exchange anywhere in this plan. See
`collab-vr-accounts-and-gates` for the full identity model and rationale,
and `docs/KNOWN_ISSUES.md` R13 for what this changed and why.

| # | Step | Depends on | Status | Skill |
|---|------|-----------|--------|-------|
| 13 | Scope approval for this track | — | Done | `collab-vr-accounts-and-gates` |
| 15 | Backend revision safety (`based_on_revision` 409, conditional DynamoDB writes, LIVE pointer) | — | Done | `backend-revision-concurrency` |
| 16 | Backend auth core: hardcoded demo accounts, mock mode, fail-fast config | 15 | Done | `backend-auth-clerk` |
| 17 | Membership, invite codes, Contributor ↔ account binding, ownership, `room_prompt` | 2, 16 | Done | `room-api-and-ownership` |
| 19 | Web app foundation: `web-app/` React + Vite, hardcoded-account picker, API client, mock mode | 16 | Done (built in `web-app/`, the repo's existing React+Vite app, not a new `app/`) | `web-app-foundation` |
| 20 | Web uploads: person types a name for each object → SAM 3.1 semantic masks → refine → generate PLYs; several photos at once; Notability sketches; optional text; invites | 7, 17, 19, 26 | Mostly done: upload/selections/refine/generate/batch polling/invites/room prompt built; Notability sketch upload is flat-card-only (no PDF→PNG, no plaque) from the web UI | `web-uploads-and-linking` |
| 21 | Public room API `/v1/rooms/{project_id}/state` + `/edits`, and the Quest account switcher's backend half | 15, 17 | Done | `room-api-and-ownership` |
| 22 | Unity networking: anonymous Unity sign-in + account switcher, Multiplayer Services, NGO 2.x, Distributed Authority | — | Not started | `unity-cloud-collaborative-vr` |
| 23 | Unity backprop client: save on settle, session-owner polling | 21, 22 | Not started | `vr-edit-cloud-backprop-sync` |
| 24 | NemoClaw room tools (`get_room_state`, `propose_room_edit`; publish approved on the web) | 3, 15, 16, 21 | Built ahead of step 3 gate, untested (2026-09-26) | `top-tier-nemoclaw-tool-design` |
| 25 | End-to-end verification: web + two or more headsets | 20, 23, 29 | Not started | `collab-vr-device-verification` |
| 26 | Durable jobs (no in-memory dict), uploads in shared storage, upload → selections → refine → generate API, batch job polling | 15 | Done | `durable-jobs-and-multi-object-upload` |
| 27 | GPU worker: SAM 3.1 semantic masks from the person's typed names, per-object Fast-SAM3D, dispatcher with leases, benchmarked concurrency | 26 | Built, unit-tested; real-GPU verification pending user approval | `gpu-multi-object-worker` |
| 28 | Letters: upload + recipients, sealed access (author + recipients, cross-visible between the two accounts), recipient-only open, scene schema, web form | 17, 19, 21, 26 | Built, untested (2026-09-26) | `letters-backend-and-web` |
| 29 | Letters in VR: envelope, networked open animation, textured 3D paper page | 22, 28 | Not started | `letters-vr-envelope` |

### Guided tour bot track (steps 30–34) — gated, added 2026-09-26

After NemoClaw builds the room, it also writes a **guided tour JSON**: the
facts, stops, and elements the tour may use. The backend stores it in the
authoring store (DynamoDB in cloud). A guide bot inside the VR room calls the
backend; the backend calls **Muse Spark** with that JSON as the model's only
knowledge, and returns validated actions (speak, move, highlight, reveal).
The model can only reference ids that exist in the JSON, and every spoken
line must cite facts from it. Full design: "Guided tour bot track" below.
Same gate command as steps 13–29.

| # | Step | Depends on | Status | Skill |
|---|------|-----------|--------|-------|
| 30 | Guided tour contract: `GuidedTour` JSON schema, validation, storage, authoring + activation API, mock tour author | 5 (mock), 15, 17 | Built, untested (2026-09-26) | `guided-tour-contract` |
| 31 | NemoClaw `author_guided_tour` tool (live path; drafts a tour after the scene is built) | 3, 30, R14 token | Built, untested (2026-09-26) | `nemoclaw-tour-authoring` |
| 32 | Guide runtime: `/v1/rooms/{id}/guide/*`, Muse Spark `guide_turn` tool call, grounding validator, session memory, MMS TTS audio | 30 | Built, untested (2026-09-26) | `muse-guide-runtime` |
| 33 | Unity guide bot (single headset): client, action executor, input, spatial audio, highlight/reveal | 32 | Built, untested (2026-09-26) | `unity-guide-bot` |
| 34 | Shared guide bot across headsets (one bot per room, session-owner drives it) | 22, 33 | Not started | `unity-guide-bot` |

Steps 14 and 18 (the Quest Meta-identity spike, and the backend Meta
identity exchange + Quest↔Clerk linking) are **retired** — see below. Every
known issue these steps fix, with status, is in `docs/KNOWN_ISSUES.md`.

**No Clerk, no Meta account, no room tokens (decided 2026-09-26).** Every
person is one of the two hardcoded accounts
(`SKETCHSCAPE_AUTH_MODE=demo`, `SKETCHSCAPE_DEMO_USERS`, default
`demo-alice,demo-bob`), selected with the `X-SketchScape-Dev-User` header
(`mock` mode's header, reused). This has **real per-project
membership/ownership enforcement** (unlike `mock`, which no-ops those
checks) — it is not a lightweight stand-in.

- **Website:** no sign-in screen. An account picker (which of the two
  hardcoded accounts is "you" right now) sets the header on every API
  call. Step 19.
- **Quest:** the same idea, as an in-headset "Account 1 / Account 2"
  switcher — one headset, one shared Meta account for the hardware, but
  the app-level identity is the chosen hardcoded account, sent the same
  way the website sends it. Both accounts view the **same** shared
  project/room (one published blueprint, step 15's LIVE pointer); only
  the *view* changes per account — which objects are `editable_by_me`
  (step 17 ownership) and which letters can be opened (step 28's
  author-or-recipient rule, which is what lets one account read a letter
  the other wrote them). Step 21/22.
- **Unity Multiplayer Services session identity:** anonymous Unity
  sign-in (`SignInAnonymouslyAsync`), tagged with a player property
  holding the chosen hardcoded account id. This needs no Meta account and
  no Clerk token; Distributed Authority and NGO 2.x don't care which
  identity provider signed the player in. Step 22.
- **NemoClaw's service identity** (`kind="service"`, used by step 24) no
  longer depends on Clerk: `auth.py` now also accepts a shared bearer token
  (`SKETCHSCAPE_NEMOCLAW_TOKEN`), matching the existing
  `SKETCHSCAPE_WORKER_TOKEN` pattern, checked before the
  `SKETCHSCAPE_AUTH_MODE` dispatch so it works in `demo` mode. Built as part
  of step 21 (ahead of when the skill originally scheduled it, since the
  room API needed a service-callable `GET /state` too). NemoClaw itself
  (step 3) still hasn't started, so nothing calls this token in production
  yet. See `docs/KNOWN_ISSUES.md` R14.
- The `clerk` value of `SKETCHSCAPE_AUTH_MODE` and its code in
  `backend/auth.py` are **left in place but off this plan** — nothing
  here depends on it, tests still cover it, and it costs nothing to keep
  as a possible future upgrade if this ever needs real accounts. Don't
  build new work against it.

**Retired: step 13's old scope (Clerk/Meta dashboards), step 14 (Quest Meta
identity spike), step 18 (Meta identity exchange + Quest↔Clerk linking).**
None of these are needed by anything else in this plan any more. Their
research (Meta `GetUserProof`/`user_nonce_validate`, `SignInWithOculusAsync`,
Clerk `authenticate_request`) stays recorded in `meta-quest-identity` and
`backend-auth-clerk` for reference, in case a real multi-user product is
built later, but it is not on the critical path and no step depends on it.

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

**Files:** `backend/scene_tools.py` (pure reasoning logic + schema validation), `backend/scene_tools_cli.py` (CLI entry point the agent shells out to), `backend/test_scene_tools.py`; deployed into the NemoClaw sandbox as the `sketchscape-scene-tools` OpenClaw skill at `config/nemoclaw/skills/sketchscape-scene-tools/SKILL.md`; `config/nemoclaw/sketchscape-tools.json` entries under `nemoclaw_agent_tools`.

**Concrete steps:**
1. `place_objects_in_scene(objects: list[{asset_id, label}], sketch_layout_hint: LayoutHint | None) -> ExperienceBlueprintInput` — reasons about realistic layout for however many objects are passed (test with 2 and with 5), assigns `position`/`rotation`/`scale`/`interactions` per `BlueprintObject`, and returns a blueprint input ready for `POST /v1/projects/{id}/blueprints`. Do not publish automatically here — publication is a separate, explicit step per the existing blueprint contract.
2. `read_sketch_layout(sketch_image) -> LayoutHint` — optional; extracts rough spatial relationships ("lamp is left of chair") as a small structured hint object `place_objects_in_scene` can consume or ignore.
3. Both tools must accept a **list** of objects, never a hard-coded pair — this is the concrete enforcement of `docs/ARCHITECTURE.md`'s N-contributor section at the tool-signature level.
4. Unit-test both tools' pure-reasoning logic outside of any live LLM call where possible (deterministic geometry/bounds checks), and add one integration smoke test that runs `place_objects_in_scene` against `PIPELINE_MODE=mock` fixtures.

**Definition of done:** both tools produce a schema-valid `ExperienceBlueprintInput` (validated against `shared/experience-blueprint.schema.json`) for a 2-object input and a 5-object input in the same test run.

**NemoClaw note — object pickup (added 2026-09-26).** A simple pickup
interface already exists without NemoClaw: the `grab` interaction on a
`BlueprintObject` compiles to `grabbable: true` on the scene object, and Unity
(`SketchScapePickup`) lets anyone pick it up with a controller (or left-click in
the Editor) and floats it back to its place on release. Nothing is saved.
Today the mock composer decides `grab` with a fixed rule (`is_pickup_sized` in
`backend/main.py`: a reconstruction ≤ 0.6 m, or a known hand-held label such as
"mug"; sketch cards never). When this step lands:
- `place_objects_in_scene` should decide `grab` per object as part of the same
  layout pass (it knows what the object is and how big it is), instead of the
  fixed rule. Keep `is_pickup_sized` as the mock/fallback path.
- Picking up someone's object is a natural moment for step 6's
  `stage_immersive_reveal` (e.g. a cue that plays that contributor's memory
  when their object is lifted). That needs a `staging_cue_id` per object
  (already in the social manifest) and a Unity hook in
  `SketchScapePickup.BeginHold`; don't let NemoClaw run anything live at
  pickup time.
- Moving an object *and keeping it moved* is not pickup: it goes through the
  owner-checked room API (steps 21/23), and live replication of a held object
  to other headsets is step 22.

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
  generate by typing (or accepting the suggested) name for them on the
  website (steps 20, 26–27). The single-object
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

**Progress (2026-09-26):** the core builder is rebuilt from scratch (the
Unity project was wiped and recreated fresh two sessions ago, so nothing
survived to "fix" — this is a genuine rebuild) and verified against a real
compiled-scene.json + a real (if minimal) binary Gaussian-splat PLY, not just
unit-tested in isolation:

- Installed `com.arloopa.unitysplats` (git `https://github.com/arloopa/UnitySplats.git#v1.2.0`,
  MIT), pinned to the exact tag matching the documented v1.2.0, plus its
  declared dependencies `com.netpyoung.webp` (git, pinned `#0.3.22`) and
  `com.unity.mathematics` (`1.3.2`, resolves from Unity's default registry).
  All three resolve and compile clean in `HackGTUnity` (Unity 6000.6.3f1).
- `Assets/SketchScape/Editor/SketchScapeOfflineExperienceBuilder.cs` — reads
  `Assets/SketchScape/Authoring/compiled-scene.json` (the file
  `scripts/export_unity_experience.py` produces) and, for each object, checks
  whether `Assets/SketchScape/Authoring/Artifacts/{id}.ply` exists **on
  disk** (not just the `source` field — defense in depth against a
  partial/failed export). If it exists: loads it with
  `Gsplat.GsplatRuntimeLoader.LoadFile` and creates a real `GsplatRenderer`.
  If not: the object is skipped entirely — confirmed no GameObject, no
  primitive, nothing stands in for it. Rebuilding twice in a row is
  idempotent (old root is replaced, not duplicated).
- **Verified live** against a hand-built 3-object fixture (not a trivial
  smoke test): one object with a real, valid, minimal binary
  `format binary_little_endian 1.0` Gaussian-splat PLY (the exact 14 required
  vertex properties `PlayCanvasPlyReader` checks for) — confirmed built with
  a real loaded `GsplatAsset` and correct transform; one object with
  `source: "placeholder"` and no `asset_url` — confirmed skipped; one object
  with `source: "sam3d"` and an `asset_url` but a **deliberately missing**
  `.ply` file, simulating a partial export — confirmed the file-existence
  check catches this and skips it too, not just the naive "source" check.
- **Scope deferred** (per explicit decision this session, since there's no
  Quest hardware or Android SDK on this machine to verify it anyway): the
  `Tools > SketchScape` menu commands, generating a dedicated
  `Experience.unity` scene asset and registering it in Build Settings, and
  the whole Quest/Android build pipeline (items 3–4 of the concrete steps
  above, and the baseline VR room environment). The builder currently
  builds directly into whichever scene is open, which is what was tested.
- **Not yet done**: loading an actual real Fast-SAM3D `.ply` from the GPU
  pipeline (none exists locally on this machine — the one ever produced was
  on a since-stopped EC2 instance). The fixture PLY above is genuinely valid
  per the reader's own required-property check, but it's a synthetic
  8-vertex stand-in, not real reconstructed geometry, so Quest-scale splat
  count and visual quality remain unverified.

**Real end-to-end pipeline verified (2026-09-26), separate from the fixture
test above.** Everything from `POST /v1/projects` through the Unity builder
was exercised through the actual backend and actual scripts — not a
hand-built JSON file this time:

1. Stood up the backend locally (`PIPELINE_MODE=mock`, a throwaway data dir).
   This machine's only Python (MSYS2 ucrt64) can't build `pydantic-core` via
   pip (`Unsupported platform: 312`, no Rust) — worked around by installing
   `fastapi`/`uvicorn`/`python-multipart` as prebuilt MSYS2 packages
   (`pacman -S mingw-w64-ucrt-x86_64-python-fastapi mingw-w64-ucrt-x86_64-uvicorn
   mingw-w64-ucrt-x86_64-python-python-multipart`) instead of fighting pip;
   future backend work on this machine should do the same rather than
   retrying a venv + pip install.
2. Created a real project, uploaded two real assets through
   `POST /v1/projects/{id}/assets`.
3. For one asset, called `POST /v1/internal/reconstructions/{job_id}/result`
   — the real private endpoint an actual GPU worker calls — with a synthetic
   but genuinely valid splat PLY, standing in for real Fast-SAM3D output
   (which the user is producing separately on AWS). This is legitimate: the
   endpoint doesn't care who calls it, only that the payload is valid. The
   other asset was left as a genuine mock-mode placeholder (no artifact).
4. Ran `place_objects_in_scene` against the two real catalog `asset_id`s,
   validated and published the resulting blueprint through the real
   `POST /v1/projects/{id}/blueprints` → `.../publish` endpoints, and
   confirmed `GET /v1/projects/{id}/compiled-scene` correctly reported
   `source: "sam3d"` with a real `asset_url` for the completed object and
   `source: "placeholder"` with `asset_url: null` for the other.
5. Ran the real `scripts/export_unity_experience.py` (unmodified, no test
   hooks) against the live local backend — it downloaded exactly one real
   `.ply` (the completed object) and correctly fetched none for the
   placeholder, then wrote a real `compiled-scene.json`.
6. Ran `SketchScapeOfflineExperienceBuilder.Build()` against that real
   export: built 1 object with a real `GsplatRenderer` + loaded asset,
   skipped the placeholder — confirmed via scene inspection, not just the
   returned counts.

This closes the loop the fixture test above couldn't: the full chain from
API upload through publish, export, and Unity build now has one real,
non-mocked pass through every hop except actual GPU inference, which is
exactly the piece the user is handling separately on AWS.

**Real GPU verification (2026-09-26): first genuine Fast-SAM3D pass through
the whole chain, on the actual `sketchscape-gpu-worker` EC2 instance
(`i-05f7fe9fc8d8da00a`, L40S, `us-east-1c`) — not synthetic, not mocked.**

- Started the existing (previously bootstrapped, then stopped) instance —
  first `StartInstances` attempt hit `InsufficientInstanceCapacity`, second
  attempt ~15 minutes later succeeded. All three systemd services
  (`sketchscape.service`, `-worker.service`, `-sam31.service`) came back
  healthy automatically on boot, no re-bootstrap needed — confirms the EBS
  volume genuinely retains a working environment across stop/start.
- Uploaded a real image through the real `POST /v1/projects/{id}/assets`
  endpoint (`PIPELINE_MODE=aws-local` on that host — a real SAM 3.1 +
  Fast-SAM3D run, not the mock path), polled to completion, and got back a
  **real 44.9 MB, 660,224-vertex Gaussian-splat PLY** with a real S3-backed
  `artifact_url` — the same order of magnitude as the "53 MB, 814,432 point"
  reference run in `AGENT.md`.
- Published a real blueprint through the instance's own live API, confirmed
  `compiled-scene` reported `source: "sam3d"` with the real `asset_url`.
- **Found and fixed a real binary-transport bug in the process**: passing
  raw `bytes` through the aws-mcp `call_boto3` tool (either as an S3
  `PutObject` `Body` param, or reading an S3 `GetObject` body back) silently
  corrupts the data — bytes that aren't valid UTF-8 get replaced with the
  U+FFFD replacement character (`EF BF BD`), inflating and corrupting the
  payload. Confirmed by decoding the same hex string locally (byte-perfect)
  vs. round-tripping it through that tool (corrupted, reproducibly, at the
  same offsets). **Workaround, applicable to any future binary transfer
  through this tool: never pass raw bytes through `call_boto3`. Either (a)
  keep the payload as a hex string (pure ASCII, safe through any text
  channel) and decode it with `xxd -r -p` in the actual shell command that
  writes the file, or (b) use `get_presigned_url` and fetch/put the bytes
  with a real HTTP client (`curl`) outside the sandboxed tool entirely.**
  Small files (~400 bytes) went through the hex/`xxd` route directly inside
  an SSM command; the 44.9 MB PLY came back via a presigned URL + local
  `curl`, which has no size concerns at all.
- **Found a real data-quality issue, not a code bug**: the offline builder
  correctly *refused* to render this real PLY — `GsplatRuntimeLoader` failed
  at vertex 9211 of 660,224 with `opacity is not finite` (a NaN/Inf value),
  and the hard rule correctly skipped the object entirely rather than
  showing anything broken or falling back to a primitive. Initial hypothesis
  (wrong, see below): blamed the trivial synthetic test photo as
  out-of-distribution input.
- Instance stopped again immediately after (cost control).

**Root cause found, and fixed (2026-09-26, same day).** Before spending more
GPU time, checked S3 for artifacts already produced by *real* prior sessions
(`ListObjectsV2` on the artifacts bucket) instead of generating another
synthetic test photo — found an older real reconstruction
(`artifacts/a4ade02181dc448680df8ee863da28e8/reconstruction.ply`, 16.4 MB,
240,768 vertices, from an actual 2026-09-24 session, its catalog/job metadata
long gone from process memory but the S3 object still intact) and fetched it
directly via a presigned URL — no new GPU job, no new photo needed. It hit
the **exact same failure**, ruling out the synthetic-photo theory entirely.
Quantified precisely with a standalone binary-PLY parse (not just "it
crashed"): **68,184 of 240,768 vertices (28.32%) had non-finite opacity.**
Root cause: `/etc/sketchscape.env` had `FASTSAM3D_FP16=1` (half-precision
inference) — the "opacity" field is a raw pre-sigmoid logit, and FP16's
limited range overflows to Inf/NaN for enough low-confidence/background
splats to break nearly a third of every real reconstruction.

**Fix applied and live-verified, not just theorized:**
1. Changed `infra/aws/bootstrap_instance.sh` (both the fresh-install heredoc
   and the `upsert_env` reconciliation line) from `FASTSAM3D_FP16=1` to `0`,
   so any future bootstrap or rebuild gets this by default.
2. Started the instance again, hand-patched the one line in the *live*
   `/etc/sketchscape.env` (`sed`, not a full bootstrap re-run — full
   bootstrap redoes apt installs and dependency compilation, unnecessary for
   a one-line config change) and restarted `sketchscape-worker.service`.
3. Re-ran the identical reconstruction (same test photo, same subject hint)
   through the real API and downloaded the result.
4. **Re-ran the same standalone opacity-finiteness check: 0 of 660,160
   vertices non-finite (0.0%).** Sampled all 17 float properties across the
   file for good measure — clean.
5. Ran `SketchScapeOfflineExperienceBuilder.Build()` against this FP32
   output: **Built: 1, Skipped: 0** — the real reconstruction now loads and
   renders with a genuine `GsplatRenderer` + loaded asset, zero failures.
6. Instance stopped again immediately after.

**Trade-off accepted, not yet separately measured**: FP32 roughly doubles
Fast-SAM3D's VRAM/compute footprint per job versus FP16. Not a problem for
this L40S (~46 GiB usable, single-object jobs) but worth knowing if job
concurrency or a smaller GPU is considered later. Wall-clock time for this
one small test job was comparable to the FP16 run (~10s each, both trivially
fast on this hardware for a 64×64 input) — real-world timing on a normal-size
photo is unverified either way.

**Bottom line**: the infrastructure, API, and Unity-side chain are now
proven against a genuine GPU reconstruction, including the failure path
(the hard rule holds even under real, messy model output). The one
remaining unknown is reconstruction *quality* on real photographic input,
which needs an actual photo to test, not a synthetic one.

---

## Step 12 — Demo video + write-up

**Goal:** ship the artifact judges actually see.

**Concrete steps:** load the `demo-video-prep` skill; walk `features.txt` line by line against whatever subset of steps 1–11 actually landed; record in `PIPELINE_MODE=mock`; write up both tracks per `docs/PROJECT_STATUS.md`'s write-up structure.

**Definition of done:** matches `docs/PROJECT_STATUS.md`'s "Social-product definition of done" and the checklist in `features.txt`.

---

## Collaborative VR + web accounts track (steps 13–29)

**Goal:** people use the SketchScape website and upload their photos,
Notability sketches, and optional text there. In their Quest headsets they
share one live Shared Room: one person's move/rotate/scale shows on every
headset immediately and is saved, so the room looks the same after
everyone leaves.

**Architecture (revised 2026-09-26 — replaces the 2026-09-25 Clerk/Meta
plan below; don't re-litigate the revision without a new decision):**

- **Accounts: two hardcoded accounts, not Clerk.** Every person is one of
  the accounts named in `SKETCHSCAPE_DEMO_USERS` (default
  `demo-alice,demo-bob`), verified server-side by
  `SKETCHSCAPE_AUTH_MODE=demo` (`backend/auth.py`) with real per-project
  membership/ownership enforcement.
  - The website (`app/`, React + Vite, no `@clerk/react`) has an account
    picker instead of a sign-in screen; it sends
    `X-SketchScape-Dev-User` on every API call.
- **Headset identity: the same hardcoded accounts, no Meta account
  linking.** One headset, one shared Meta account for the hardware — the
  app-level identity is an in-headset "Account 1 / Account 2" switcher
  sending the same header, and Unity's Multiplayer Services session uses
  **anonymous Unity sign-in** (`SignInAnonymouslyAsync`) tagged with a
  player property holding the chosen account id. No `GetUserProof`, no
  Data Use Checkup, no linking flow, no room token.
- **NemoClaw identity:** a shared bearer token
  (`SKETCHSCAPE_NEMOCLAW_TOKEN`), matching the existing
  `SKETCHSCAPE_WORKER_TOKEN` pattern — not yet added to `auth.py` (small
  step-16 follow-up, needed before step 24; NemoClaw/step 3 hasn't
  started). See `docs/KNOWN_ISSUES.md` R14.
- **Live layer:** Unity Multiplayer Services **Distributed Authority** +
  Netcode for GameObjects 2.x. Client-hosted Relay can't migrate the host,
  so the room would close when the host left. Unaffected by the identity
  change above — DA doesn't care which auth provider signed a player in.
- **Durable layer:** blueprint revisions stay the source of truth (Hard
  Rule 6).
  - Headsets save through the **public** room API (`/v1/rooms/*`, Hard
    Rule 4), authenticated with the hardcoded-account header, which
    checks ownership, allowed interactions, bounds, and revision, then
    publishes server-side in one request.
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

**Superseded 2026-09-25 plan (kept for reference only — not built, not on
the critical path; see `meta-quest-identity` and `backend-auth-clerk`):**
Clerk as the account system, Meta Platform SDK `GetUserProof()` +
`SignInWithOculusAsync` + a backend-issued room token for Quest identity,
linked once to a Clerk user via a website code. Retired because the
project is using two hardcoded accounts as the real identity model instead
of standing up Clerk and a Meta Horizon app. `SKETCHSCAPE_AUTH_MODE=clerk`
and its code in `backend/auth.py` still exist and are still tested, in
case a real multi-user product is built later — nothing in this plan
depends on them.

**Rejected alternatives (documented so nobody rebuilds them):**
- Clerk OAuth + PKCE browser login on the headset federated via Unity
  OIDC. The browser redirect back into an immersive app was the riskiest
  step.
- Meta account sign-in + linking (see "Superseded" above) — more setup
  (Meta Horizon app, test users, Data Use Checkup) than two hardcoded
  accounts need.
- Electron desktop app, because Clerk's Electron support is unofficial
  (moot now, but keeps this app/ a plain web app either way).
- Next.js, because AGENT.md rules it out and it would add a Node server.
- Unity Cloud Save, because its shared data is server-write-only and would
  be a second source of truth.

**Gate system:**
- `scripts/check_collab_gates.py` checks evidence in code and config for
  each step and all its prerequisites.
- Facts no script can see are manual gates in
  `config/collab-vr/gates.json`, which only the user may confirm.
- Every run also scans the repo, `app/.env*`, and the Unity project for
  leaked secrets (Clerk `sk_` keys and `VITE_*SECRET*` variables are still
  scanned for, since the `clerk` code path still exists).
- `verify_local.sh` runs the status check, so a leak fails verification.

**Config and secrets:** one matrix for local, dev, and prod lives in the
`collab-vr-accounts-and-gates` skill. The backend refuses to start when
misconfigured:
- `demo` mode without `SKETCHSCAPE_WEB_ORIGINS`, or without exactly two
  `SKETCHSCAPE_DEMO_USERS`.
- `mock` mode against DynamoDB or a non-mock pipeline.

**Per-step detail lives in the skills** (table above). What each step
delivers:

- **13** — scope approval only (recorded, done).
- **15** — fixes three concurrency bugs:
  - silent lost edits (no base-revision check)
  - the DynamoDB overwrite race (unconditional `put_item`, per-process
    lock)
  - the live room going backwards (publish compare-and-set on a `LIVE`
    pointer)
- **16** — hardcoded-account verification, authors on revisions, CORS
  locked to web origins, fail-fast startup.
- **17** — invite codes, membership checks on every project route,
  account binding for contributors, ownership, `room_prompt`.
- **19** — done. Built directly in the existing `web-app/` (not a new `app/`):
  a build-time switch (`VITE_SKETCHSCAPE_API_URL`, `src/config.ts`) so mock
  mode (unset) behaves exactly as before, and real mode (set) swaps in an
  account picker (`src/real/RealShell.tsx`) and a typed API client
  (`src/api/client.ts`) instead of the fake sign-in. See `web-app/hardcode.MD`
  section 0.
- **20** — mostly done, same real-mode branch: photo upload with progress,
  typed per-object names → selections → refine → generate, batch job polling
  (ETag + backoff), room prompt, and project create/join by invite code
  (`src/real/RealProjectPage.tsx`, `src/api/polling.ts`). Not yet from the web
  UI: PDF → PNG for Notability exports and the 3D memory-plaque option (flat
  card works); letters (step 28, out of scope here on purpose).
- **21** — `/v1/rooms/*` with idempotent, owner-checked, bounded,
  revision-checked edits built on the live revision, authenticated with
  the hardcoded-account header.
- **22** — anonymous Unity sign-in, the account switcher, and Distributed
  Authority networking from the VR Multiplayer Template 2.1, ported with
  matching package versions.
- **23** — save on release (debounced); 409 → rebase; retries with the
  same `client_edit_id`; session-owner polling.
- **24** — NemoClaw drafts room edits; a person approves the publish on
  the website.
- **25** — end-to-end verification on real hardware.
  *Results (fill in):* fps with N people: ___ · session survives owner
  leaving: ___ · quotas checked: ___

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
  headset. Backoff, jitter, polling pauses when the tab is hidden, and a
  separate rate-limit bucket.
- **26** — fixes three bugs that break multi-object and multi-user
  uploads: in-memory jobs, uploads on one API host's disk, and
  `asset_ids` appended inside the whole-project blob. Adds the
  **person-chosen** flow:
  1. Upload.
  2. On the website, type a name for every wanted object (a SAM 3.1
     semantic text prompt).
  3. SAM 3.1 masks exactly those objects.
  4. Refine any one.
  5. Generate one PLY per object.

  Also adds batch polling. Auto-detect only suggests selections.
- **27** — SAM 3.1's semantic predictor turns the person's typed names
  into masks in one pass per photo (best instance plus alternatives).
  Then one Fast-SAM3D job runs per chosen object through a leased queue.
  `SKETCHSCAPE_GPU_CONCURRENCY` defaults to 1 and is raised only after an
  approved VRAM benchmark (a T4 stays at 1). **Built and unit-tested (this
  pass), GPU-unverified:** `segment_selections`/`segment_many` in
  `worker/segment_sam31_local.py` (torch/ultralytics imports are now lazy,
  so this runs on CPU); the claim/lease dispatcher
  `worker/gpu_dispatcher.py`; the backend's
  `GET .../reconstructions/{job_id}/selections` and
  `POST .../selections/{selection_id}/result` routes so one segment job's
  several selections report back independently (Hard Rule 7); `aws-local`
  now leaves a `segment` job `queued` for the dispatcher instead of
  auto-failing; `worker_server.py` reads `SKETCHSCAPE_GPU_CONCURRENCY` and
  `SKETCHSCAPE_WORKER_ID`; a `sketchscape-dispatcher` systemd unit in
  `infra/aws/bootstrap_instance.sh`. 164 backend + 33 worker unit tests
  pass (mocks/fakes only, no GPU, no AWS). **Still needed for `--done 27`:**
  the user's approved real-GPU run (`gpu_multi_object_verified` in
  `config/collab-vr/gates.json`) confirming one photo with 3 typed names
  produces 3 correct masks and 3 PLYs, and two uploads submitted together
  both completing.
  *Results (fill in):* instance: ___ · peak VRAM 1 job: ___ · 2 jobs: ___
  · concurrency chosen: 1 (kept at 1 pending an approved benchmark; the
  worker's shared Fast-SAM3D pipeline state isn't concurrency-safe yet —
  see `worker/worker_server.py`'s `main()` and `worker/benchmark_concurrency.py`)
- **28–29** — letters. The Notability page becomes a textured 3D paper
  mesh (legible, no GPU) sealed in an envelope. Only the addressed
  recipients can open it; everyone in the room sees the open animation
  live, and the opened state is saved. A sealed page is never served to
  non-recipients. This is also what lets one hardcoded account read a
  letter the other wrote them.
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

## Guided tour bot track (steps 30–34)

**Goal:** a guide bot inside the VR room walks visitors through what
NemoClaw built. It speaks, moves between objects, highlights them, and
reveals elements NemoClaw staged for the tour. It answers visitors'
questions. Every word and every action comes **only** from a structured tour
JSON that NemoClaw wrote after it built the scene. The model behind the bot
is **Muse Spark** (`muse-spark-1.3`) on the Meta Model API.

**Decision (user, 2026-09-26).** Recorded in AGENT.md under "Guided tour bot":
- NemoClaw **authors** the tour, which covers what exists, what may be said,
  and in what order. That is scene understanding, so it stays in NemoClaw.
- At runtime a **backend-proxied** Muse Spark call **performs** the tour.
  It's a read-only, grounded performer. It never composes, edits, or
  publishes anything, so it doesn't conflict with "NemoClaw builds the
  scene" (AGENT.md). It's the one approved runtime model call.
- The headset never calls Muse directly (Hard Rule 4) and never holds
  `META_MODEL_API_KEY`. It calls `/v1/rooms/{project_id}/guide/*` with the
  same `X-SketchScape-Dev-User` header as every other room route.

### Architecture

```
NemoClaw (after place_objects_in_scene + stage_immersive_reveal)
  └─ author_guided_tour ──POST /v1/projects/{id}/tours──▶ backend validates ──▶ TOUR#<v> (draft)
                                                            person activates on web ──▶ TOURLIVE pointer
Quest guide bot (Unity)
  └─ POST /v1/rooms/{id}/guide/sessions/{sid}/turns {event}
        backend: load TOURLIVE tour + LIVE blueprint + GUIDESESSION memory
          ├─ scripted event (next/repeat/start, no question pending) → deterministic turn, no model call
          └─ model event (question/ask_about/more/linger) → Muse Spark, tool `guide_turn`
                (schema built from this tour: every id is an enum) → grounding validator
                → repair or scripted fallback
        → MMS-TTS audio per line (cached in S3) → GUIDESESSION updated (compare-and-set)
  ◀── {lines[{text, fact_ids, audio_url}], move_to, highlight_element_ids, reveal_element_ids, step_id, end}
```

### How "only the JSON" is enforced (four layers, all required)

1. **The ids are closed sets.** Per request, the `guide_turn` tool schema is
   generated from the active tour. `step_id`, every `fact_id`,
   `highlight_element_ids`, `reveal_element_ids`, and `move_to` are JSON
   Schema `enum`s of the ids in that tour. The model can't name an object,
   step, or fact that isn't in the JSON.
2. **Every spoken line cites facts.** Each `say[]` item needs at least one
   `fact_id`. Cited facts must be in the allowed set for this turn: the
   chosen step's facts, the facts of that step's focus elements, the theme
   facts, and, for `ask_about`, the facts of that element.
3. **Deterministic grounding check** (`backend/guide_validator.py`, no model):
   - Every capitalized word that doesn't start a sentence, every number, and
     every quoted span in `text` must appear (case-insensitive) in the cited
     facts, the tour vocabulary (contributor names, element labels, theme
     title, persona name), or a fixed small allowlist.
   - A line that fails is **replaced** by its cited facts' own `text`,
     verbatim.
   - A turn that fails schema validation, times out
     (`SKETCHSCAPE_GUIDE_MODEL_TIMEOUT_S`, default 8), or has no tool call
     becomes the **scripted fallback**: the current step's `narration`,
     verbatim.
   - Unity never receives an unvalidated id or line.
4. **Prompt and data separation.** The system prompt
   (`backend/guide_prompts.py`, `GUIDE_PROMPT_VERSION = "guide-v1"`) says to
   use only the tour JSON and to decline anything else with
   `guardrails.off_topic_reply`. The tour JSON and the visitor's question go
   in separate delimited blocks, marked as data. Contributor memory text in
   the tour is data, never instructions: an injection inside `memory_text`
   can only produce lines that still pass layers 1–3.

Target, measured by step 32's eval: ≥ 95% of live turns pass layer 3
without repair, and **100%** of turns delivered to Unity pass (repair
guarantees this).

### The tour JSON (the contract; `shared/guided-tour.schema.json`, step 30)

```json
{
  "schema_version": 1,
  "project_id": "p_123",
  "tour_version": 3,
  "based_on_revision": 7,
  "status": "draft",
  "authored_by": {"backend": "mock", "model": "mock-tour-v1", "tool": "compose_tour_mock", "prompt_version": null},
  "created_at": "2026-09-26T18:00:00Z",
  "persona": {"name": "Lumen", "voice": "mms-tts-eng", "style": "warm"},
  "theme": {"title": "Home, carried with us", "fact_ids": ["f_theme", "f_explanation"]},
  "facts": [
    {"fact_id": "f_theme", "text": "The room's theme is Home, carried with us.", "source": {"kind": "connection_insight", "ref_id": "insight:4"}, "derived_from": []},
    {"fact_id": "f_teapot_memory", "text": "My grandmother poured tea from this every Sunday.", "source": {"kind": "contribution_memory", "ref_id": "c_1"}, "derived_from": []},
    {"fact_id": "f_teapot_owner", "text": "Maya brought the teapot.", "source": {"kind": "attribution", "ref_id": "c_1"}, "derived_from": []},
    {"fact_id": "f_teapot_link", "text": "Maya's teapot and Sam's mug sit on one table because both are about Sunday mornings.", "source": {"kind": "authored", "ref_id": null}, "derived_from": ["f_teapot_memory", "f_mug_memory"]}
  ],
  "elements": [
    {"element_id": "obj_teapot", "kind": "contribution", "object_id": "obj_teapot", "label": "teapot",
     "contributor_id": "k_maya", "contributor_display_name": "Maya", "fact_ids": ["f_teapot_memory", "f_teapot_owner"], "initially_visible": true},
    {"element_id": "motif_light_path", "kind": "motif", "object_id": null, "staging_cue_id": "cue_path_1", "label": "light path",
     "contributor_id": null, "contributor_display_name": null, "fact_ids": ["f_teapot_link"], "initially_visible": false}
  ],
  "steps": [
    {"step_id": "s_welcome", "title": "Welcome",
     "stop": {"anchor_element_id": "obj_teapot", "offset_m": [0.8, 1.4, 0.6]},
     "focus_element_ids": [], "reveal_element_ids": [],
     "fact_ids": ["f_theme"],
     "narration": {"text": "Welcome. The room's theme is Home, carried with us.", "fact_ids": ["f_theme"]},
     "next_step_ids": ["s_teapot"], "min_dwell_s": 3}
  ],
  "start_step_id": "s_welcome",
  "end_step_ids": ["s_together"],
  "guardrails": {"off_topic_reply": "I can only tell you about this room and what everyone brought to it.", "max_lines_per_turn": 3}
}
```

Rules that step 30's `validate_guided_tour` enforces. A violation is a 422
naming the rule:
- **Ids.** Every id matches `^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$` and is
  unique within its kind. Every referenced id exists.
- **Elements.**
  - `kind` is `contribution`, `environment`, `letter`, or `motif`.
  - For `contribution`, `environment`, and `letter`, `object_id` must be an
    object in blueprint `based_on_revision`.
  - For `contribution`, `contributor_id` must match that object's entry in
    the social manifest (`compile_social_manifest`).
  - For `motif`, `object_id` is null and `staging_cue_id` refers to step 6's
    `StagingPlan`. The ref is only checked once step 6 exists.
- **Reveals ("which elements to add").**
  - An element with `initially_visible: false` is placed in the published
    blueprint, but Unity hides it until a step reveals it.
  - `reveal_element_ids` may only name `initially_visible: false`
    elements.
  - Every hidden element must be revealed by at least one step reachable
    from the start.
  - The guide never spawns anything that isn't in the blueprint or the
    staging plan.
- **Facts.**
  - `text` is 1–500 chars.
  - `source.kind` is one of `connection_insight`, `placement_rationale`,
    `contribution_memory`, `attribution`, `room_prompt`, `letter_envelope`,
    or `authored`.
  - `contribution_memory` text must equal that contribution's `memory_text`
    **verbatim**, or be a verbatim sentence from it.
  - `authored` facts must list at least one `derived_from` fact, and pass
    the same lexical grounding check against those facts. This makes
    NemoClaw's own prose traceable back to what people actually wrote.
- **Sealed letters.**
  - `letter_envelope` facts may only say who a letter is from and who it is
    for.
  - A letter's `note_text` or page content is **never** a fact, because the
    guide speaks to everyone in the room (step 28's sealed-access rule).
- **Steps.**
  - At most 30 steps, 400 facts, and 200 elements.
  - `narration.text` is ≤ 600 chars, and its `fact_ids` are within the
    step's facts.
  - The step graph from `start_step_id` reaches every step, and every
    non-end step has at least one `next_step_ids` entry.
  - `stop.offset_m` components are within ±5 m.
- **Size.** The serialized size is ≤ 256 KB. The DynamoDB item limit is
  400 KB; the headroom covers metadata. Beyond that, reject: don't split,
  and don't move it to S3.
- **Language.** English only in v1, because MMS voice `mms-tts-eng` is
  English.

### Step 30 — Guided tour contract, storage, authoring API, mock author

**Files:**
- `shared/guided-tour.schema.json` (new)
- `backend/main.py`: `GuidedTour` models, routes, `validate_guided_tour`,
  `compose_tour_mock`
- `backend/storage.py`: `AuthoringStore` methods in both stores
- `backend/test_guided_tour.py` (new)

1. Add Pydantic models that mirror the schema: `TourFact`, `TourElement`,
   `TourStop`, `TourNarration`, `TourStep`, `TourGuardrails`, `TourPersona`,
   `GuidedTourInput`, and `GuidedTour`. `GuidedTour` adds `project_id`,
   `tour_version`, `status: draft|active|retired`, `created_at`, and
   `author`. Add a test asserting that `GuidedTour.model_json_schema()` and
   `shared/guided-tour.schema.json` accept and reject the same fixtures.
2. Add storage to `AuthoringStore`, `LocalJsonStore`, and `DynamoDbStore`
   (layout in `docs/DATA_ARCHITECTURE.md`):
   - `append_tour(tour) -> GuidedTour`: conditional put on
     `TOUR#<version padded 6>`.
   - `get_tour`, `list_tours`.
   - `get_active_tour_version`, and
     `set_active_tour_version(project_id, expected, new)`: compare-and-set
     on `TOURLIVE`, the same pattern as step 15's `set_live_revision`.
3. Routes:
   - `POST /v1/projects/{project_id}/tours/compose`
     (`require_project_draft`):
     - `SKETCHSCAPE_TOUR_AUTHOR=mock` (default) runs `compose_tour_mock`
       over the LIVE blueprint, the latest `ConnectionInsight`, the
       contributions, and the contributors, then stores a **draft**.
     - `nemoclaw` returns 501 until step 31.
     - Returns 409 if there's no LIVE revision or no insight.
   - `POST /v1/projects/{project_id}/tours` (`require_project_draft`, or
     NemoClaw's service identity once R14 lands): takes a
     `GuidedTourInput`, runs `validate_guided_tour` against blueprint
     `based_on_revision`, and stores a draft. Returns 201.
   - `GET /v1/projects/{project_id}/tours` and
     `GET /v1/projects/{project_id}/tours/{tour_version}`
     (`require_project_read`).
   - `POST /v1/projects/{project_id}/tours/{tour_version}/activate`:
     person identities only (`require_user`, project write). A service
     identity gets 403: NemoClaw drafts and a person approves, the same
     rule as room edits. Compare-and-set on `TOURLIVE`. The previous active
     tour becomes `retired`.
4. `compose_tour_mock` is deterministic: same inputs, same tour. It uses no
   network and no model.
   - Step `s_welcome`: theme and explanation facts.
   - One step per contributed object, in blueprint order: attribution,
     `memory_text`, and placement-rationale facts. Its stop is anchored on
     that object with offset `[0.8, 1.4, 0.6]`, rotated to face the room
     centre.
   - Step `s_together`: focuses every contribution and reveals every
     `initially_visible: false` element.
   - Environment objects (step 6a) and letters (step 28) become elements;
     letters get `letter_envelope` facts only.
   - `authored_by.backend = "mock"`.
   - Works with 3+ contributors. Tests never use exactly two.
5. **Staleness, not invalidation.** Room edits (step 21/23) create new
   blueprint revisions that move objects but keep their ids. A tour stays
   valid across edits because stops are relative to anchor elements.
   `GET /v1/rooms/{id}/guide/tour` (step 32) computes `stale_element_ids`:
   element `object_id`s that are no longer in the LIVE blueprint. Steps
   anchored on a stale element are skipped. If more than half the steps are
   skipped, the room reports `tour_available: false`.

**Tests** (`backend/test_guided_tour.py`):
- The mock tour is deterministic and valid for 3 and for 4 contributors.
- One 422 test per validator rule:
  - unknown object
  - wrong contributor
  - `memory_text` not verbatim
  - an authored fact without `derived_from`
  - an authored fact that adds a name
  - a letter `note_text` used as a fact
  - an unreachable step
  - a hidden element never revealed
  - more than 256 KB
- A service identity can't activate (403). Compare-and-set activation
  returns 409 on a stale `expected` version.
- The DynamoDB store round-trips a tour against the in-memory fake table
  that `backend/test_storage.py` already uses.

**Definition of done:** `--done 30` and `verify_local.sh` pass. In mock
mode, compose → activate works with zero external calls.

### Step 31 — NemoClaw `author_guided_tour` (live path)

**Files:** NemoClaw tool code (next to step 4/6 tools; coordinate with
the Track 3 owner, see `docs/TEAM_TASK_SPLIT.md`),
`config/nemoclaw/sketchscape-tools.json` (`tour.draft`, `tour.activate`).

0. Add `GET /v1/projects/{project_id}/connection/insights`
   (`require_project_read`). NemoClaw needs to read the latest insight,
   and no read route exists today.
1. The tool is `author_guided_tour(project_id) -> GuidedTourInput`. It runs
   after `stage_immersive_reveal` and in the same NemoClaw session, so the
   tour order follows the staging's reveal order. NemoClaw's inputs:
   - `GET /v1/projects/{id}/compiled-scene`: LIVE objects plus the social
     manifest.
   - The latest `ConnectionInsight`.
   - The contributions: `memory_text` as delimited data.
   - The `StagingPlan`, if step 6 exists.
2. NemoClaw writes the JSON with its configured provider (`meta` → Muse
   Spark by default). Structured output goes through a tool call whose
   parameters are the schema. On a 422, NemoClaw gets the rule that failed
   and retries at most 2 times; after that it fails loudly. The live author
   still records `authored_by` = {`backend`, `model`, `tool`,
   `prompt_version`}.
3. It posts to `POST /v1/projects/{id}/tours` using the service identity
   (`SKETCHSCAPE_NEMOCLAW_TOKEN`, R14). It **never** activates. The
   registry has `tour.activate` with `approval_required: true`, so a person
   clicks Activate on the website (step 19/20 web app: one "Guided tour"
   panel listing drafts with Activate).
4. `SKETCHSCAPE_TOUR_AUTHOR=nemoclaw` makes `/tours/compose` return 202 and
   start the NemoClaw run. The web app polls `GET /tours` for the new draft.

**Definition of done:** one approved live run (Hard Rule 3: explicit user
approval, spend logged) produces a draft that validates on the first or a
retried attempt. The draft is activated by a person. `tour.draft` shows as
`implemented` in the registry.

### Step 32 — Guide runtime: backend + Muse Spark + validator + memory + TTS

**Files:**
- `backend/guide.py` (new): the turn engine
- `backend/guide_model.py` (new): OpenAI-compatible client
- `backend/guide_tools.py` (new): per-tour `guide_turn` schema
- `backend/guide_validator.py` (new)
- `backend/guide_prompts.py` (new)
- `backend/guide_tts.py` (new)
- `backend/requirements-tts.txt` (new)
- `backend/main.py` (routes)
- `backend/storage.py` (session items)
- `backend/test_guide.py` (new)
- `scripts/guide_cli.py` (new)
- `scripts/eval_guide_live.py` (new)

**32.0 — Muse Spark compatibility spike (first, needs approval, about $0.10).**
Make 10 live calls with a fixture tour and record the results in the table
below before building 32.3:
- Is `tools` accepted?
- Is `tool_choice="required"` honored? If not, use `"auto"`; the missing
  tool call becomes the scripted fallback.
- Is `enum` inside tool parameters honored?
- Is `temperature` accepted? Reasoning models sometimes reject it. Only
  send it if it's accepted.
- p50 and p95 latency.
- Input and output tokens per turn.

*Results (fill in):* tools: ___ · tool_choice required: ___ · enum
honored: ___ · temperature accepted: ___ · p50/p95 latency: ___ / ___ ·
tokens in/out per turn: ___ / ___

**32.1 — Routes.** All use the same identity header and membership check as
`/v1/rooms/*` (step 21's `require_project_read`). They work before step 21
lands because they only need step 17's membership.

- `GET /v1/rooms/{project_id}/guide/tour` returns
  `{tour_available, tour_version, persona, steps[{step_id, stop,
  focus_element_ids, reveal_element_ids}], elements[{element_id, object_id,
  staging_cue_id, initially_visible}], stale_element_ids}`, with an ETag.
  Unity uses it at scene load to hide `initially_visible: false` objects
  and to know the stops. Fact text is not sent, because Unity doesn't need
  it.
- `POST /v1/rooms/{project_id}/guide/sessions` returns `201 {session_id,
  tour_version, turn}`. `turn` is the deterministic `start` turn.
  - One active session per `(project_id, account)`. A new POST retires the
    old one.
  - Step 34 makes this one session per room, owned by the Unity session
    owner.
- `POST /v1/rooms/{project_id}/guide/sessions/{session_id}/turns`, body
  `{client_turn_id, turn_seq, event}`. `event.type` is one of:
  - `start`, `next`, `repeat`, `end`
  - `more`: tell me more about the current step
  - `ask_about` with `element_id`: the visitor pointed at an object and
    pressed Ask
  - `linger` with `element_id`: head gaze on an element not yet discussed
    for 6 s. Sent at most once per element per session.
  - `question` with `text` (≤ 300 chars, untrusted): the optional voice
    path in step 33.

  Response `GuideTurnResponse`. It's JsonUtility-friendly: no
  dictionaries, and "absent" is an empty string or array, never null.

  ```json
  {"turn_seq": 5, "step_id": "s_teapot", "end": false,
   "lines": [{"line_id": "t5_0", "text": "...", "fact_ids": ["f_teapot_memory"], "audio_url": "https://...", "duration_s": 3.4}],
   "move_to": {"anchor_element_id": "obj_teapot", "offset_m": [0.8, 1.4, 0.6]},
   "highlight_element_ids": ["obj_teapot"], "reveal_element_ids": [],
   "source": "model", "backend": "meta", "model": "muse-spark-1.3",
   "validation": {"passed": true, "repairs": []}, "latency_ms": 2410}
  ```
  `source` is `scripted`, `model`, `repaired`, or `fallback`.
  `move_to.anchor_element_id` is `""` when the bot stays put.
- Concurrency:
  - `turn_seq` must equal the session's `turn_count`, else 409 with the
    current turn. This is a compare-and-set on the session item.
  - Repeating a `client_turn_id` returns the stored response with no new
    model call.
  - One turn in flight per session.

**32.2 — Routing (`SKETCHSCAPE_GUIDE_ROUTING`, default `hybrid`).**
- `start`, `next`, `repeat`, and `end` are **scripted**: the step's
  `narration`, verbatim, with its pre-synthesized audio. There's no model
  call, so latency is the store read plus a cached audio URL.
- `more`, `ask_about`, `linger`, and `question` go to the **model**. These
  are where Muse adds something: it picks facts the visitor hasn't heard,
  answers questions from the JSON, and chooses whether to steer toward a
  step.
- `model_all` sends every event to the model, for evaluation only.

**32.3 — The model call** (`guide_model.py`).
- One OpenAI-SDK client. The provider comes from
  `SKETCHSCAPE_GUIDE_MODEL_PROVIDER`: `mock` (default), `meta`, `xai`, or
  `nebius`.
  - The base URL and default model come from a small dict that mirrors
    `config/nemoclaw/model-providers.example.json`. A test asserts that the
    two match.
  - The key comes from `META_MODEL_API_KEY`, `XAI_API_KEY`, or
    `NEBIUS_API_KEY`, set only in the backend process environment.
  - `SKETCHSCAPE_GUIDE_MODEL` overrides the model id; the default is
    `muse-spark-1.3`.
- Messages, in order:
  1. `system`: the `guide-v1` prompt.
  2. `user`: a `<tour_json>` block holding the active tour, then a
     `<session_memory>` block holding structured memory, not a transcript:
     `current_step_id`, `visited_step_ids`, `said_fact_ids`,
     `revealed_element_ids`, and the last 8 events as `{type, element_id,
     question}`.
  3. `user`: the current event, with any visitor text inside `<visitor>`
     tags, labelled untrusted.

  The static tour block comes first, so a provider prefix cache can hit if
  one exists. Don't claim caching savings unless 32.0 measured them.
- `tools = [build_guide_tool(tour, allowed)]`. The tool is `guide_turn`
  with parameters:
  - `intent`: `answer|narrate|decline|end`
  - `step_id`: enum of step ids
  - `say`: 1–3 items of `{text ≤ 400 chars, fact_ids: enum[] minItems 1}`
  - `highlight_element_ids`: enum[], ≤ 4
  - `reveal_element_ids`: enum[] of hidden elements allowed at the chosen
    step, ≤ 3
  - `move_to_element_id`: enum of stop anchors, plus `""`
- Muse's output is validated by `guide_validator.validate_turn(tour,
  session, event, args)`, which returns `(turn, repairs)`. Its rules are
  layers 1–3 above. It also enforces:
  - A `decline` intent uses `guardrails.off_topic_reply`, verbatim.
  - `reveal_element_ids` must be in the chosen step's `reveal_element_ids`.
  - `move_to` must equal the chosen step's `stop.anchor_element_id`.
- Mock provider (`SKETCHSCAPE_GUIDE_MODEL_PROVIDER=mock`), deterministic:
  - `ask_about` or `linger` → the first unsaid fact of that element.
  - `more` → the next unsaid fact of the current step.
  - `question` → the fact with the highest keyword overlap (the same
    tokenizer as `compose_connection_mock`), or `off_topic_reply` if the
    overlap is 0.

  It's labelled `backend="mock"`, `model="mock-guide-v1"`.

**32.4 — Session memory** (the "memory" the model has between turns).
- Item `GUIDESESSION#<session_id>`: `document` = `{tour_version, account,
  current_step_id, visited_step_ids, said_fact_ids, revealed_element_ids,
  events (last 20), turn_count, created_at}`.
- Top-level `turn_count` for the compare-and-set, and `ttl` = now + 24 h.
- Each turn also writes `GUIDETURN#<session_id>#<turn_seq padded 4>` with
  the request, response, validation, token usage, and latency. `ttl` is
  7 days. This is the audit trail for "did the model stay on the JSON?"

**32.5 — Voice** (`guide_tts.py`, `SKETCHSCAPE_GUIDE_TTS=none|mms`,
default `none` in tests and `mms` in the demo).
- Meta MMS-TTS: `transformers.VitsModel` plus
  `AutoTokenizer.from_pretrained("facebook/mms-tts-eng")`. It runs on the
  API host's CPU, 16 kHz mono, and is encoded as 16-bit WAV.
- The license is CC-BY-NC 4.0, already accepted for the demo in step 6.
  Flag it before any commercial use.
- Output goes to the artifact store at
  `guide-audio/<project_id>/<sha256(voice + text)>.wav`, so the same line
  is never synthesized twice.
- `audio_url` uses the existing `/v1/artifacts/...` presigned-redirect
  path, with membership checked.
- Activating a tour (step 30) pre-synthesizes every step's `narration`, so
  scripted turns never wait on TTS.
- `torch` (CPU) and `transformers` live in `backend/requirements-tts.txt`.
  They aren't in the base requirements, so `verify_local.sh` stays light.
- Measure synthesis time per line in 32.0. If p95 is over 1.5 s, lines
  stream as separate requests: Unity starts line 1 while line 2
  synthesizes.
- `none` returns `audio_url: ""`. Unity then plays the bot's "chime" cue
  and moves on.

**32.6 — Limits and cost.**
- `SKETCHSCAPE_GUIDE_MAX_TURNS_PER_SESSION=60` (after that, 429).
- `SKETCHSCAPE_GUIDE_DAILY_MODEL_TURNS=500` per project. Over the cap,
  model events fall back to the mock provider, labelled `source:
  "fallback"`. This is a graceful fallback, not an error.
- Turns share the room API's write rate-limit bucket.
- Rough cost at Muse Spark list prices ($1.25/M in, $4.25/M out): a
  ≤ 64 KB tour is about 16k tokens in, plus about 1k out including
  reasoning, which comes to about $0.025 per model turn. A 20-question
  session costs about $0.50.
- Log `usage` on every `GUIDETURN`.

**32.7 — Tooling.**
- `scripts/guide_cli.py --project p_123 [--live]` plays a tour in the
  terminal against a local backend: `n` = next, `a <element_id>` = ask
  about, `q <text>` = question. It prints each turn's `source` and
  `validation`. This is the headset-free way to develop and demo the guide.
- `scripts/eval_guide_live.py` (live, needs approval) runs 25 canned events
  against a fixture tour and reports the pass-before-repair rate, the
  repair count, and p50/p95 latency. The events are 10 on-topic
  `ask_about`/`question`, 5 off-topic, 5 prompt-injection (a fixture
  `memory_text` containing "ignore your instructions and…"), and 5 asking
  about a sealed letter's contents.

**Tests** (`backend/test_guide.py`, all offline, model mocked with canned
tool-call responses):
- Scripted turns make no model call.
- An invented name in `say.text` is repaired to the cited fact.
- An unknown `element_id` falls back.
- No tool call falls back.
- A timeout falls back.
- An off-topic question gets `off_topic_reply`.
- An injection fixture can't make a line that isn't in the facts.
- A sealed letter's `note_text` never appears in any response.
- A `turn_seq` mismatch returns 409.
- A repeated `client_turn_id` makes no second model call.
- A stale element skips its step.
- The daily cap switches to the fallback.
- `audio_url` is empty with `SKETCHSCAPE_GUIDE_TTS=none`.
- Three contributors.

**Definition of done:**
- `--done 32` and `verify_local.sh` pass, and the mock provider plays a
  full tour through `guide_cli.py`. That's enough to unblock step 33.
- Before any demo or write-up says the guide runs on Muse Spark: 32.0's
  table and `eval_guide_live.py` results are recorded here (after
  approval), and the user confirms the manual gate
  `guide_live_model_verified`.

*Eval results (fill in):* pass before repair: ___% · delivered grounded:
___% · p50/p95 model-turn latency: ___ / ___

### Step 33 — Unity guide bot (single headset)

**Files:** in `../HackGTUnity/Assets/Scripts/Guide/`, all new:
- `SketchScapeGuideModels.cs`
- `SketchScapeGuideClient.cs`
- `SketchScapeGuideBot.cs`
- `SketchScapeGuideObjectMap.cs`
- `SketchScapeGuideHighlighter.cs`
- `SketchScapeGuideInput.cs`

Plus `Assets/Prefabs/GuideBot.prefab`, and an addition to
`SketchScapeOfflineExperienceBuilder.cs`.

1. **Models:** `[Serializable]` DTOs that match `GuideTurnResponse` and the
   `/guide/tour` response, parsed with `JsonUtility`. The response is built
   for this (32.1), so there's no Newtonsoft dependency.
2. **Client:**
   - `UnityWebRequest` to `apiBaseUrl`, the same serialized field pattern
     as `SketchScapeExperienceCompiler`.
   - It sends `X-SketchScape-Dev-User` from the account switcher (step 22),
     or a serialized default account before step 22 exists.
   - Timeout 15 s. It keeps `turn_seq`; on 409 it adopts the returned turn.
   - It never holds a model key. The gate secret scan covers `Assets/`.
3. **Object map:** `element_id` → GameObject through the existing
   `NamedSceneInteractive` id (the builder names objects `item.id`).
   `motif` elements map through a `staging_cue_id` → component registry,
   which step 6 fills. Without step 6, motif elements are ignored.
4. **At scene load** (`BuiltExperienceController` start):
   `GET /guide/tour` → hide every `initially_visible: false` object →
   spawn `GuideBot` at the start step's stop.
   - If the tour is unavailable, no bot spawns. The room still works
     (graceful degradation).
5. **Bot** (a small floating light-orb companion, not a humanoid: cheap,
   readable, fits the "light path" motif language). State machine: `Idle →
   Thinking → Moving → Speaking → Idle`. Executing a turn:
   1. Move: a tween to `anchor.position + anchor.rotation * offset_m`, at
      ≤ 1.2 m/s, facing the anchor. Use step 6's chosen tween library, or
      `Vector3.SmoothDamp` if step 6 isn't done.
   2. Reveal: `SetActive(true)` plus a 0.6 s scale-in and a soft chime.
   3. Highlight: `SketchScapeGuideHighlighter` shows an emissive rim, or a
      spotlight cone from the bot for splats, where a rim shader doesn't
      apply. It clears when the next turn starts.
   4. Speak: download each `audio_url` with
      `UnityWebRequestMultimedia.GetAudioClip(url, AudioType.WAV)` and play
      it on an `AudioSource` on the bot (`spatialBlend = 1`, Resonance
      Audio if step 6 installed it). Lines play in order.

   While `Thinking` (a model turn, 2–6 s), the orb pulses slowly and a
   soft loop plays, so there's never silent dead air. **No text panel and
   no captions** (AGENT.md: felt, not read).
6. **Input** (`SketchScapeGuideInput`, XRI 3.0.11 input actions):
   - A (right) = `next`, B (right) = `repeat`.
   - Right trigger while the ray hovers a mapped element = `ask_about`.
   - Grip on the bot = `more`.
   - Head-gaze raycast dwell of 6 s on an undiscussed element = `linger`.
   - Input is ignored while a turn is in flight.
   - **Optional voice (off by default):** Meta Voice SDK dictation →
     `question`. The Wit.ai client token stays out of git: an ignored
     `WitConfiguration` asset, injected at build. Only build this after
     everything else in this step works.
7. **Builder:** `SketchScapeOfflineExperienceBuilder` adds the
   `GuideBot` prefab and `SketchScapeGuideInput` to the generated scene.
   That's all; the tour itself is fetched at runtime.
8. **Editor tooling:** the `Tools/SketchScape/Guide/Simulate Tour` menu
   drives the bot in Play mode with keyboard keys (N/R/M, click-to-ask)
   against the mock backend. No headset needed.

**Definition of done:** `--done 33` passes. In the desktop simulator
against a mock backend with 3 contributors, the bot walks every step,
reveals the hidden element, and answers `ask_about` on each object. On one
real Quest, the full tour plays with audio at 72 Hz and no frame drops
while the bot moves. The user confirms the manual gate
`guide_bot_verified`.

### Step 34 — Shared guide across headsets

**Files:** in `../HackGTUnity/Assets/Scripts/Guide/`: `SketchScapeGuideNetwork.cs` (new),
changes to `SketchScapeGuideBot.cs`.

1. **One guide per room.** The bot is a `NetworkObject` owned by the
   Distributed Authority **session owner** (step 22). When the owner leaves,
   ownership migrates, and the new owner reuses the same `session_id`,
   stored in a session property.
2. Only the owner calls `/turns`. Other players send their events to the
   owner through `[Rpc(SendTo.Owner)] SubmitGuideEventRpc(type,
   element_id)`. The owner queues them FIFO, one in flight.
3. Replicated state, as `NetworkVariable`s:
   - `currentStepId`
   - `highlightedIds` (a fixed-size string array or a CSV string)
   - `revealedIds`
   - `speakingLineId`
   - `speakingAudioUrl`
   - `speakingStartServerTime`

   Each client downloads and plays the audio itself, starting at
   `speakingStartServerTime`, so everyone hears the line in sync. The bot's
   transform uses `NetworkTransform`.
4. Late joiners read the replicated state: hidden elements already revealed
   are shown, and the current line isn't replayed.
5. The backend `/guide/sessions` route gains `?scope=room` (one active
   session per project rather than per account). The owner's account header
   is recorded on each turn.

**Definition of done:** `--done 34` passes. On two headsets, either person
can ask about an object and both hear the answer from the same bot at the
same time. The owner leaves mid-tour, and the tour continues on the other
headset from the same step. The user confirms the manual gate
`shared_guide_verified`, recorded in step 25's results.

**Never do in this track:**
- Call Muse (or any model) from Unity.
- Put `META_MODEL_API_KEY` anywhere but the backend process environment.
- Deliver a line to Unity that didn't pass the grounding validator.
- Let the guide create objects that aren't in the blueprint or staging plan.
- Include a sealed letter's contents in a tour.
- Let NemoClaw activate a tour.
- Show guide text on a floating panel.
- Make scripted events call the model.

---

## If time runs out

Priority order if the full plan can't land before the deadline: **5 (compose endpoint, mock path only) → 1–2 (data model/API it depends on) → 8 (diegetic attribution, even a minimal version) → 11 (real splat rendering) → 12 (video)**. Steps 3–4 and 6 (NemoClaw agent + immersive staging) are what make the story *strong*, but 5's mock path alone is enough to demo the connection insight without a live agent — the mock output is judging-safe by design. Steps 7, 9, 10 are genuinely optional polish; skip them first. The
Collaborative VR + web accounts track (13–29) is post-MVP: never pull time from steps
1–12 for it before the demo is safe.
The guided tour bot (30–34) is the same: after 1–12 are safe, the cheapest
valuable slice is **30 → 32 (mock provider) → 33**. That's a bot that tours the
room with zero model spend. Switch `SKETCHSCAPE_GUIDE_MODEL_PROVIDER=meta` only
after 32.0's approved spike. Step 34 needs step 22.
