# Handoff — NemoClaw + Unity MCP orchestration (Build Plan steps 3, 4, 6)

Written 2026-09-26. Third revision, evening; it supersedes the earlier
versions. Read the **START HERE** section first. The older sections below it
are background and history.

The last session (`65c057b2-388a-42b5-a56f-ed1265d08877`) ran on a different
Claude account, so it can't be resumed from the next one. This file is the
handoff.

## LATEST+2 (2026-09-26, night) — one-command startup, and live auto-labeling

- **`scripts/Start-SketchScape.ps1`** brings the whole stack up after a
  reboot, skipping any step that's already fine:
  1. Docker.
  2. Unity on HackGTUnity; it waits for the MCP relay.
  3. The bridge setup.
  4. A check for the NemoClaw IPv4 patch. It reports a missing patch and
     never applies it.
  5. The Muse Spark route, judged by the adapter being alive *and* having
     registered a route. If that fails, it prompts for the key in the
     console, then restarts the gateway.
  6. The skills.

  `-ForceKey` re-enters the key. It was verified end to end on the running
  stack, where every step correctly skipped. The recovery path after an
  actual reboot hasn't run yet.
- **NemoClaw's `Inference: unhealthy` status line is a false alarm with
  Muse Spark.** Its probe misreads Meta's response. Don't use it as a health
  check.
- **`identify_subject` live path (step 4a)**, turned on with
  `SKETCHSCAPE_SUBJECT_LABELER=nemoclaw`:
  - The backend (`subject_labeler.NemoClawSubjectLabeler`) stages the photo
    in WSL, runs `nemoclaw <sb> upload`, then
    `nemoclaw <sb> exec -- python3 …/sketchscape-subject-labeler/backend/nemoclaw_vision.py`.
  - That script calls `https://inference.local/v1/chat/completions` with the
    image, so NemoClaw injects the key and the backend never holds it.
  - `--mask` names a single masked object, which is how the 11 "object"
    scans can be relabeled. Spot checks were correct: the blanket mask gave
    "pink blanket", and the remote mask gave "white tv remote".
  - "Suggest objects" now adds every object found, deduplicated and capped.
  - Muse Spark reasons for about 1.6k tokens before answering, so
    `max_tokens` is 6000. Each call takes 11–25 s.
  - Tests: `test_nemoclaw_vision.py` (7) and `test_subject_labeler.py` (17).

## LATEST+1 (2026-09-26, night) — rooms now use the real 3D scans from AWS

- **What happened:** the Muse Spark agent built
  `Assets/SketchScape/AgentRooms/Lazy_Sunday.unity` from one prompt (session
  `room-real-1`) using **real Fast-SAM3D Gaussian-splat scans**: cat, TV
  remote control, pink blanket and tomato. Every object is grabbable, and
  there are 4 teleport hotspots. Verified by a hierarchy dump (each object
  has a `GsplatRenderer`) and an Editor screenshot.
- **Getting the assets:** run `python scripts/sync_s3_assets_to_unity.py`
  (after `aws login`; the account is `820672722003`, region `us-east-1`).
  - It reads the catalog assets (`ASSET#…`) from DynamoDB
    `sketchscape-authoring`.
  - It keeps `ready` reconstructions with a real label (not "object"),
    newest per label.
  - It downloads `artifacts/<job>/reconstruction.ply` from
    `sketchscape-artifacts-20260922133334256700000003`.
  - It repairs non-finite opacity (the remote had 90 bad values).
  - It writes the files to `HackGTUnity/Assets/SketchScape/AssetLibrary/`,
    plus `config/nemoclaw/asset-catalog.json`.
  - Then refresh the Unity AssetDatabase, and rerun
    `scripts/nemoclaw-deploy-skills.sh` so the sandbox gets the catalog.
  - 11 more ready scans are labeled only "object". Label them (in the
    backend, or by looking at `uploads/<project>/<upload>/source.jpg`) to
    make them usable.
- **Room builder:** `compose_room` matches each object to the catalog, by
  exact `asset_id` or by label words ("our cat Miso" → "cat"). Matches are
  built as real splats; everything else stays a tinted cube. The plan's
  `visual` field says which each object got. New CLI verb: `list_assets all`.
- **Gotchas found (also in the bridge README Gotchas):**
  - The scans are **Z-up**. With the Gsplat importer's default (RUB) frame,
    the splat child is rotated +90° about X. This was checked with the
    tomato stem, which ends up on top, the blanket, which lies flat, and a
    screenshot.
  - `Unity_RunCommand` can't reference the Gsplat assembly, so the
    generated C# reaches `Gsplat.GsplatRenderer` through reflection.
  - Unity's MCP capture tools and a manual `Camera.Render()` don't draw
    splats. To check visually, frame the Scene View and take a desktop
    screenshot.
  - `GetInstanceID()` is a compile error on Unity 6.6. Use `GetEntityId()`
    or log the object itself.
- **Oops:** an orientation-check cleanup saved the active scene, which was
  still `Smoke_Test.unity` after the user had deleted its file. That save
  recreated the file. Delete `Assets/SketchScape/AgentRooms/Smoke_Test.unity`
  again (and `Real_Scan_Check.unity`, a manual test room), by hand.

## LATEST (2026-09-26, late evening) — Muse Spark agent builds Quest rooms in Unity end-to-end

This supersedes "What's about to happen" in START HERE below. Items 1–3
there are done or decided.

- **Model:** NemoClaw `sketchscape` runs **Muse Spark** (`compatible-endpoint`,
  `muse-spark-1.3`, `https://api.meta.ai/v1`).
  - To (re)enter the key, run `scripts/nemoclaw-set-muse-spark.sh` in your
    own WSL shell. It reads the key silently, so it never goes through chat
    or a file.
  - Re-run it after anything that restarts NemoClaw's route adapter (such as
    a reboot). The adapter never persists the key.
- **Local NemoClaw patch (re-apply after any NemoClaw update):**
  - The bug: NemoClaw's SSRF preflight sorts resolved addresses as strings,
    so IPv6 `2a03:…` comes before IPv4 `57.144…`. The HTTPS-pin adapter
    connects to `pinnedAddresses[0]`, and WSL has no IPv6 route, so every
    model call got a 502 within about 3–50 ms (`ENETUNREACH`).
  - The patch: in
    `~/.nemoclaw/source/dist/lib/inference/https-pin-runtime-adapter.js`,
    `pinnedAddress:` now prefers the first IPv4 entry. The original is saved
    next to it as `.orig`.
  - After patching, kill the adapter (its pid is in
    `~/.nemoclaw/https-pin-runtime-adapter.pid`), then re-run the key
    script.
  - The symptom if the patch is lost: `nemoclaw sketchscape status` shows
    Inference unhealthy (HTTP 502), and
    `~/.nemoclaw/https-pin-runtime-adapter.log` shows `status:502` with a
    `durationMs` in the single digits.
- **After an inference switch, restart the agent gateway:** run
  `nemoclaw sketchscape gateway restart`. Until then, OpenClaw keeps the old
  model's in-memory settings. Sessions still recorded `qwen3.5:9b`, and the
  agent stopped after one tool call.
- **Approval gates: none, by user decision.** The user's words: "no gates or
  anything are needed". `config/nemoclaw/sketchscape-tools.json` records
  this on each Unity write tool.
- **New job-shaped tool, `compose_room`**
  (`backend/unity_room.py`, `backend/unity_room_cli.py`, 11 tests in
  `backend/test_unity_room.py`):
  - It runs the layout step, then staging.
  - It generates the C# that builds the room in its **own** scene,
    `Assets/SketchScape/AgentRooms/<slug>.unity`. That scene has mood key
    and ambient light, tinted placeholder cubes, a connection glow, and a
    floor light-path motif. The build refuses to run if another scene has
    unsaved changes.
  - It lists the ordered Meta XR calls: camera rig, interaction rig, one
    grabbable per object, and teleport hotspots.
  - A finalize script saves the scene and reports what is really in it.
  - CLI outputs stay small on purpose, because OpenClaw truncates tool
    results at 16k characters. That truncation is why the first version
    stalled.
- **OpenClaw skill `sketchscape-unity-room`**
  (`config/nemoclaw/skills/sketchscape-unity-room/SKILL.md`), plus the
  re-deployed `sketchscape-scene-tools`:
  - The rebuilt sandbox had lost the old deployment.
  - Deploy or redeploy with `bash scripts/nemoclaw-deploy-skills.sh` (in
    WSL). It installs to `/sandbox/.openclaw/workspace/skills/<name>`,
    bundles the backend Python and the schema, and installs `jsonschema`.
- **Verified end to end:** session `room-e2e-3`. A single natural-language
  prompt (4 objects plus a connection) made Muse Spark do everything itself:
  - calls: `compose_room`, `build_code`, then `Unity_RunCommand`, then
    `meta_get_config_information`, `meta_add_camerarig`,
    `meta_add_interactionrig`, 4× `meta_add_grabbable`, 4×
    `meta_add_teleport_hotspot`, then `finalize_code` and
    `Unity_RunCommand`.
  - result: `Assets/SketchScape/AgentRooms/Evenings_at_Home.unity`, saved.
  - An independent hierarchy dump plus a multi-angle capture confirmed it.
  - First real run of the `meta_add_*` tools, and first time the patched
    `GetInteractorsState` line ran.
- **Unity-side notes:**
  - The team's `First` scene was not modified. The Editor now has
    `Evenings_at_Home` open.
  - The throwaway `Smoke_Test.unity` was deleted by hand. That's the only
    way: `AssetDatabase.DeleteAsset` over MCP is refused as "requires user
    interaction".
  - All the gotchas found this session are also listed in
    `scripts/unity-mcp-bridge/README.md` → Gotchas: the IPv6 pin, gateway
    restart, 16k tool-result truncation, the skills path, zero-byte
    uploads, and DeleteAsset.
  - After a scene-view reframe, the console shows Editor-internal "Invalid
    sorting group ID" `GUIView` errors. They're harmless.
- **Next:**
  - Real per-object assets instead of cubes (needs the PLY/splat import
    path from step 11).
  - Wire narration and haptics: the staging data is returned to the agent
    but not applied in the Editor, because `ImmersiveStagingDirector` lives
    in the repo's `unity/` project.
  - Agent-driven `read_sketch_layout` vision (Muse Spark takes images).

## START HERE (2026-09-26, evening)

### State right now (all verified before the account switch)

- **NemoClaw talks to Unity directly.** The sandbox is **`sketchscape`**, the
  only one (`my-assistant` was destroyed). A live agent made real
  `tools/call`s to Unity (`meta_get_config_information`,
  `meta_get_interactors_state`) through OpenShell's `mcp_bridge_unity_mcp`
  policy.
- **Unity:** `../HackGTUnity`, Unity 6000.6.3f1, scene "First". Meta XR SDK
  `com.meta.xr.sdk.all` 207.0.0 is installed. Meta's MCP extension is
  embedded and patched for Unity 6.5+ (see `scripts/unity-mcp-bridge/`,
  README section "Meta Horizon tools"). Active Input Handling = Both
  (restart done).
- **Tools NemoClaw sees: 17.** `Unity_RunCommand`, `Unity_GetConsoleLogs`,
  3 capture tools, `Unity_AssetGeneration_GetModels`, and
  `Unity_AssetGeneration_GenerateAsset` (**denied** at registration), plus
  9 Meta tools: `meta_get_config_information`,
  `meta_get_interactors_state` (both read-only), 7 `meta_add_*` scene
  writers, and `meta_update_android_manifest`. Inside the agent they're
  called `unity-mcp__<toolName>`.
- **Bridge:** run `scripts/unity-mcp-bridge/Setup-UnityMcpBridge.ps1`. It's
  idempotent and was last run successfully after the reboot. Its README
  covers everything.
- **Model:** still local Ollama `qwen3.5:9b`, and currently *unhealthy*
  because the Ollama auth proxy on 11435 didn't restart after the reboot.
  That's irrelevant, because it's about to be replaced (next item).

### What's about to happen (in order)

1. **The user switches NemoClaw to Muse Spark.** User decision: Muse Spark,
   not OpenAI (an OpenAI key doesn't work for `meta`/`xai`/`nebius`). The
   user runs this **in their own WSL terminal**; the key must never go
   through chat, the repo, or a file:
   ```bash
   read -rsp "Meta Model API key: " COMPATIBLE_API_KEY; echo; export COMPATIBLE_API_KEY
   nemoclaw inference set --provider compatible-endpoint --model muse-spark-1.3 \
     --endpoint-url https://api.meta.ai/v1 --credential-env COMPATIBLE_API_KEY \
     --inference-api openai-completions --sandbox sketchscape
   unset COMPATIBLE_API_KEY
   ```
   - It's a runtime route switch with no rebuild, so the CA and Unity
     registration are untouched.
   - The variable must be named `COMPATIBLE_API_KEY` (canonical for
     `compatible-endpoint`).
   - `my-assistant` was deleted because the shared-gateway rule would refuse
     this switch while another sandbox was recorded on a different route.
   - The model id `muse-spark-1.3` comes from the `nemoclaw-model-providers`
     skill (checked 2026-09-25). If the endpoint rejects it, check
     https://dev.meta.ai/models/muse-spark/ rather than guessing.
2. **Next session verifies the switch:** `nemoclaw sketchscape status`
   should show provider `compatible-endpoint`, model `muse-spark-1.3`, and a
   healthy inference route. Then run one read-only Unity tool test with a
   *normal* (non-scripted) prompt, e.g. "What does the Meta config info in
   Unity say?". The goal is to confirm Muse Spark calls
   `unity-mcp__meta_get_config_information` on its own, which qwen couldn't
   do reliably.
3. **Then the user wants to go straight to setting up the agents.** Before
   any real agent work, **decide and build the approval gate**. Today
   nothing stops the agent calling `Unity_RunCommand` (arbitrary C# in the
   Editor), the 7 `meta_add_*` tools, or `meta_update_android_manifest`.
   - Rules: `top-tier-nemoclaw-tool-design` skill; `config/nemoclaw/
     sketchscape-tools.json` marks these `approval_required: true`,
     "exposed-ungated".
   - Options: re-register with `--deny-tool` for a read-only first run, or
     build a real approval path. Ask the user; don't pick silently.
   - No `meta_add_*` tool has ever run. The first one should be
     `meta_add_camerarig` in a scene the user chooses, and it also exercises
     the patched `GetInteractorsState` line for the first time.

### After a reboot (this happened once already)

In order: start **Docker Desktop**
(`C:\Users\kriva\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe`),
open **Unity** on HackGTUnity (`"C:\Program Files\Unity\Hub\Editor\6000.6.3f1\Editor\Unity.exe" -projectPath C:\Users\kriva\Desktop\HackGTUnity`),
wait for its `relay_win.exe --relay` to appear, then run
`Setup-UnityMcpBridge.ps1`.

**Never put a timeout around `wsl.exe` from Windows** when a `nemoclaw`
command runs inside. It orphaned a process holding NemoClaw's per-sandbox
lifecycle lock; WSL then restarted, and every `nemoclaw sketchscape …`
command hung (fixed by hand with the user's OK; details in the README
Gotchas). Put `timeout` inside WSL instead; `nemoclaw-register.sh` now does.

### Repo state

All of this session's work is pushed to `origin/main`:
- the bridge scripts,
- the Meta extension patch,
- the docs,
- the in-WSL timeouts,
- this handoff.

Nothing is left uncommitted from it. Local-only state that isn't in git,
by design:
- the per-machine CA and keys (WSL `~/.config/sketchscape/unity-mcp-pki/`);
- the bridge venv and logs (`%LOCALAPPDATA%\SketchScape\unity-mcp-bridge`);
- the patched embedded extension inside `../HackGTUnity/Packages/` (that
  project isn't a git repo; the patch file in `scripts/unity-mcp-bridge/
  patches/` reproduces it).

## What this task is

Build Plan steps 3 (`nemoclaw-agent-setup`), 4 (`nemoclaw-scene-tools`), and 6
(`immersive-reveal-staging`) in `docs/BUILD_PLAN.md`. Goal: NemoClaw agents use
Unity MCP to decide object placement, relative scale, depth, and immersive
staging (lighting, motif, narration, haptics) for the Shared Room experience.
Load the three skills above (and `top-tier-nemoclaw-tool-design`) before
continuing — they carry the concrete rules this session followed.

## What's actually done

### 1. NemoClaw runtime (Step 3, partially done — unchanged from before)
- **NVIDIA NemoClaw CLI** (`github.com/NVIDIA/NemoClaw`) is installed in **WSL
  Ubuntu** (not Windows), wrapping OpenClaw inside OpenShell.
- Live sandbox: **`sketchscape`** (the only one; `my-assistant` was destroyed
  2026-09-26, and its workspace backups are in
  `~/.nemoclaw/rebuild-backups/my-assistant/`). Agent = **OpenClaw**.
- **Model (user decision, 2026-09-26):** switch to **Muse Spark**
  (`muse-spark-1.3`, Meta Model API) as a `compatible-endpoint` via
  `nemoclaw inference set` (no rebuild). The user enters the key in their
  own WSL shell as `COMPATIBLE_API_KEY`. Until that runs, the sandbox is on
  local Ollama `qwen3.5:9b`.
- Useful commands: `nemoclaw list`, `nemoclaw sketchscape status`, `nemoclaw
  sketchscape exec -- <cmd>`, `nemoclaw sketchscape upload <host-path>
  <sandbox-dir>` (uploads **into** a directory — don't repeat the filename in
  the destination), `nemoclaw sketchscape agent --agent main -m "<prompt>"`.
  Don't wrap these in a Windows-side timeout around `wsl.exe` (see the
  stale-lock gotcha in `scripts/unity-mcp-bridge/README.md`).

### 2. Scene/staging backend tools (Steps 4 and 6, Python side — done)
- **`backend/scene_tools.py`** — pure, deterministic, offline reasoning:
  `place_objects_in_scene`, `read_sketch_layout`, `stage_immersive_reveal`.
  Accepts N objects (tested 1–8). Validates against
  `shared/experience-blueprint.schema.json`.
- **`backend/scene_tools_cli.py`** — CLI wrapper for shell-only agents.
- **`backend/test_scene_tools.py`** — 21 unit tests, green.
- Deployed into the NemoClaw sandbox as an OpenClaw skill
  (`config/nemoclaw/skills/sketchscape-scene-tools/SKILL.md`); registered in
  `config/nemoclaw/sketchscape-tools.json` and `scripts/verify_local.sh`.
- **Not yet verified**: getting the live `qwen3.5:9b` agent to *itself* call
  the tool in a single non-interactive turn. Still open — see priority list
  below. This is now the single biggest unverified gap in the whole chain.

### 3. Unity MCP connection (Step 3, Unity half — DONE this session)
- `HackGTUnity` (sibling dir, Unity 6000.6.3f1) has `com.unity.ai.assistant`
  and `com.meta.xr.unity-mcp.extension` installed and compiling clean (from
  the prior session).
- **This session confirmed the Claude Code ↔ Unity MCP connection is live**:
  the `unity-mcp` stdio server (registered in `~/.claude.json` by the prior
  session) connected automatically at session start — no manual "Pending
  Connection" approval was needed this time (either it auto-approved, or it
  was already approved from an earlier attempt). Verified with real tool
  calls, not just a connection check:
  - `meta_get_config_information` — succeeded.
  - `Unity_GetConsoleLogs` — succeeded, 0 errors, 3 benign warnings (Input
    Manager deprecation, a cloud-account API timeout, an unsigned-executable
    check on `claude.exe` — none block anything).
  - `Unity_RunCommand` with a hand-rolled scene-hierarchy dump (walks
    `SceneManager` root GameObjects recursively) — this is the actual
    **read-only scene inspection** Step 3's definition of done asked for,
    since Meta's extension itself documents no read/query op. Confirmed the
    scene at that point was just the Unity default (`Main Camera` +
    `Directional Light`, empty/unsaved).
- **Step 3 is now done** for the Claude-Code-mediated path. NemoClaw's own
  direct connection is still blocked (see "Still open" below) — unchanged.

### 4. Blueprint → Unity write bridge (Steps 4/6 — NEW this session, the main work)

This is the actual "craft the scene" capability — turning a
`place_objects_in_scene` blueprint into real Unity GameObjects. It did not
exist before this session; the tools in section 2 only ever produced JSON,
never touched Unity.

- **`backend/blueprint_to_unity.py`** — `blueprint_to_unity_command(blueprint)`.
  Takes any schema-valid `ExperienceBlueprintInput` (validated against
  `shared/experience-blueprint.schema.json` before codegen — reuses
  `scene_tools._validate_blueprint_input`) and deterministically generates a
  self-contained Unity Editor `IRunCommand` C# script: a floor plane (if
  `environment.floor`) plus one placeholder cube per object, positioned,
  rotated, and scaled to match the blueprint exactly (`scale` field ×
  `scene_tools._DEFAULT_SIZE`, since the blueprint's scale is a multiplier of
  that 0.6m reference footprint, not a literal Unity `localScale`).
- **`backend/blueprint_to_unity_cli.py`** — CLI wrapper, same shape as
  `scene_tools_cli.py` (JSON in via arg or `-` for stdin, C# source out).
- **`backend/test_blueprint_to_unity.py`** — 7 new unit tests (object counts
  1–8, floor on/off via the `wantsFloor` runtime bool literal, string
  escaping via `json.dumps` — JSON and C# string-escaping rules agree closely
  enough for this to just work, rejection of empty object lists, brace
  balance). 28 tests total across both scene-tools test files, all green.
- Registered both new files in `scripts/verify_local.sh` (both `py_compile`
  and the `.venv` unittest invocation list). **Remember the CRLF gotcha**
  (see "Environment quirks" below) — already handled this time with
  `sed -i 's/\r$//' scripts/verify_local.sh` after editing it.
- **Verified live against the Editor, twice, with two different blueprint
  shapes** (not just one hardcoded demo):
  1. A 4-object set (lamp/chair/table/photo-frame) generated by calling
     `place_objects_in_scene` directly in Python, then hand-adapted into a
     first-draft `Unity_RunCommand` call (this is where the JsonUtility bug
     below was found and worked around).
  2. A 3-object set (guitar/mug/bookshelf) generated **purely through the new
     CLI tool** (`blueprint_to_unity_cli.py` reading JSON from stdin) to
     prove the tool generalizes rather than being hardcoded to the first
     demo's shape.
  Both landed in the live Unity scene with exactly the expected
  position/rotation/scale, confirmed via a read-only hierarchy dump after
  each. Zero console errors either time.
- **Important bug found and worked around**: Unity's `JsonUtility.FromJson`
  **silently fails to populate nested custom classes** when run inside this
  `Unity_RunCommand` dynamically-compiled execution context. Confirmed with
  a minimal, hand-written, null-literal-free repro — even the simplest
  nested-class JSON came back with every reference-type field `null`, while
  the outer object itself was non-null (so it fails silently, not loudly —
  easy to misdiagnose as a data problem instead of a JsonUtility problem).
  **Consequence**: `blueprint_to_unity_command` does NOT emit a script that
  parses JSON at runtime in Unity. It bakes the blueprint's values directly
  into C# object-creation statements *at Python generation time* instead.
  **Any future Unity-bridge code must do the same — do not reach for
  `JsonUtility` for anything beyond flat/primitive fields inside this
  RunCommand context.**
- **Current scene state in the live (unsaved) Editor**, as of end of this
  session: root GameObject `SharedRoom_Blueprint_Second Proof Room`
  containing a `Floor` plane and three cubes (`guitar_0`, `mug_1`,
  `bookshelf_2`) from proof #2 above. This is **not saved to disk** — normal
  Unity Editor in-memory state. If the Editor gets closed without saving, or
  if a new session finds the scene empty again, that's expected and fine;
  none of this is meant to be permanent content, just proof-of-pipeline
  scratch state. Feel free to clear it before building anything real.
- **Still a Claude-Code-mediated bridge, not an agent-callable tool.**
  `blueprint_to_unity_cli.py` produces the C# text; something with an actual
  Unity MCP connection still has to paste it into `Unity_RunCommand`. Right
  now only this Claude Code session has that connection (see the networking
  note below) — NemoClaw itself cannot invoke this yet.
- **Not yet done**: `interactions` (highlight/inspect/etc.) from the
  blueprint are ignored by the bridge — no XR/interactivity wiring yet, no
  real per-asset prefabs (placeholder cubes only). That's Step 6 Part B
  territory, sequenced after this.

## Immediate next action / priority order for next session

> **Superseded (2026-09-26 evening):** follow **START HERE** at the top
> instead. The list below is from earlier in the day. Item 1 was later
> verified; the Unity items are covered in START HERE.

1. **Verify the live `qwen3.5:9b` agent actually invokes
   `place_objects_in_scene`** in a real turn (not just direct CLI exec or
   unit tests). Two prior one-shot attempts acknowledged the skill existed
   but didn't clearly execute it — try a multi-turn/session-based invocation
   or a more directive prompt. This is the single most important open item:
   without it, "NemoClaw agents craft the scene" is still only proven
   half-way (Unity write path works; agent-driven tool-calling doesn't yet).
2. Once (1) works, decide explicitly how NemoClaw's output reaches the
   Unity bridge — it still can't call Unity MCP directly (see below), so
   either Claude Code stays the permanent executor for this track, or the
   NemoClaw↔Unity MCP networking problem needs revisiting after all.
3. Step 6 Part B (Unity-side scene-craft toolkit — VR Builder, tweening,
   volumetric lighting, VFX Graph, Resonance Audio, XR haptics) — not
   started, builds on top of the now-working write bridge.
4. Meta XR SDK v78+ install — blocked on the user's own Unity/Meta account
   (Asset Store login or an `.upmconfig.toml` token); needed before
   `interactions` (grabbable, teleport hotspots) can mean anything.

## Still open / not started

- Everything in "Immediate next action" above, in that priority order.
- **NemoClaw's own direct Unity MCP connection — WORKING (2026-09-26, 15:58).**
  A live agent turn in the new **`sketchscape`** sandbox made a real
  `tools/call` to `meta_get_config_information` and got real Editor data
  back (OpenShell log: `ALLOWED ... rule_methods=tools/call`).
  **Setup is now scripted:** `scripts/unity-mcp-bridge/Setup-UnityMcpBridge.ps1`
  (see its README). It's idempotent: rerun it after a reboot or a Unity
  restart. On a new laptop, run it with `-Onboard -AcceptThirdPartySoftware`.
  Verified here: fresh venv via uv, takeover of the old hand-started
  proxies, strict-TLS check, endpoint-change re-registration, `-Stop`, and
  an agent `tools/call` through the script-started bridge. **Not run yet:**
  the `-Onboard` path on a clean machine. The old hand-built
  `C:\Users\kriva\unity-mcp-bridge\` folder is now unused. Chain:
  1. `mcp-proxy` 0.9.0 (venv in
     `%LOCALAPPDATA%\SketchScape\unity-mcp-bridge`) wraps
     `~/.unity/relay/relay_win.exe --mcp` as Streamable HTTP on
     `127.0.0.1:19443`.
  2. `scripts/unity-mcp-bridge/tls_proxy.py` serves HTTPS on
     **`172.30.144.1:9443` only** (the Windows side of the WSL switch, never
     `0.0.0.0`/LAN). Its cert is a leaf for `unity-mcp.private` +
     `IP:172.30.144.1`, signed by a private CA.
  3. Private CA + keys: WSL `~/.config/sketchscape/unity-mcp-pki/` (mode 700;
     never commit or share). The CA is baked into the `sketchscape` image via
     `NEMOCLAW_CORPORATE_CA_BUNDLE` + `nemoclaw onboard --from
     ~/.nemoclaw/source/Dockerfile`, so OpenShell's L7 proxy trusts the
     upstream TLS. A plain `nemoclaw <sb> rebuild` reuses NVIDIA's prebuilt
     image and does NOT bake the CA. That's why `my-assistant` couldn't be
     fixed in place: NemoClaw refuses a custom-image recreate of it without
     `NEMOCLAW_RECREATE_WITHOUT_BACKUP=1`.
  4. Registered: `nemoclaw sketchscape mcp add unity-mcp --url
     https://172.30.144.1:9443/mcp/ --env UNITY_MCP_BRIDGE_TOKEN
     --trusted-private-host 172.30.144.1 --deny-tool
     Unity_AssetGeneration_GenerateAsset`. The token is a random placeholder
     (the bridge has no auth). Asset generation is denied because it spends
     Unity AI credits and was half the tool-schema size. To re-register, use
     `mcp remove unity-mcp --force`, then `openshell provider delete
     sketchscape-mcp-unity-mcp` (remove keeps the provider, which blocks a
     re-add).
  - **Not automatic at login:** the proxies don't survive a reboot, and
    `172.30.144.1` can change. Rerunning the setup script handles both.
  - **Model caveat:** `qwen3.5:9b` (16k context, CPU) calls the tools only
    with very directive prompts (`tool_call` id
    `unity-mcp__<toolName>`), then often fails to write a reply. The first
    try overflowed context. Expect this to improve on `meta`/`xai`/`nebius`.
    Swap with `nemoclaw inference set`; don't rebuild without the CA.
  - **Tool surface (updated 2026-09-26, after the Meta XR SDK):** 17 tools.
    The 8 base ones (`Unity_RunCommand`, console logs, scene/camera captures,
    asset generation, `meta_get_config_information`), plus 9 Meta ones:
    `meta_get_interactors_state` (read-only) and the write tools
    `meta_add_camerarig`/`interactionrig`/`grabbable`/`distance_grabbable`/
    `teleport_hotspot`/`canvas_interaction_poke`/`canvas_interaction_ray` and
    `meta_update_android_manifest`. Getting them needed two things:
    - Install `com.meta.xr.sdk.all` 207.0.0 (Asset Store; "Open in Unity"
      alone installs nothing).
    - Patch Meta's extension, embedded in `HackGTUnity/Packages/`: upstream
      `GetInstanceID()` is a hard error on Unity 6.5+. The patch and steps are
      in `scripts/unity-mcp-bridge/` (README "Meta Horizon tools" section).

    NemoClaw verified a real `tools/call` to `meta_get_interactors_state`.
    It answered "add a camera rig first": the scene is empty, so no
    `meta_add_*` tool has run yet. **The write tools are not approval-gated
    yet.** Gate them before a capable model is switched in.
  - Unity 6.6 console noise that's expected: about 60 `[Tool Permissions]`
    errors after each recompile (AI Assistant looks for the old
    `Library/ScriptAssemblies` folder; the in-Editor chat only), MRUK URP
    shader errors, and "Android SDK not found" (APK builds only).
    Active Input Handling was switched to Both via the SDK prompt; it needs
    an Editor restart, then a rerun of the setup script.
  - `my-assistant` was destroyed on 2026-09-26, along with its stale
    `unity-mcp` provider. `sketchscape` is the only sandbox.
- Real per-asset prefabs instead of placeholder cubes in the write bridge
  (needs an actual asset pipeline into Unity — not scoped yet).
- A **leftover zombie `Unity.exe` process** (PID 32404 as of the original
  session, ~27 MB memory) from the very first batchmode project-creation
  run. Harmless so far; kill it if file locks in `HackGTUnity/Library/` act
  weird (`taskkill //F //PID 32404` or check `tasklist` for the current PID
  first — it may have already exited since).
- Model provider swap (`NEMOCLAW_MODEL_PROVIDER` → `meta`/`xai`/`nebius`)
  before the real demo — config-only, already decided, just not done yet.

## Abandoned/deprioritized path (context, don't repeat)

A prior session tried registering a **custom** local MCP server (wrapping
`scene_tools_cli.py` over HTTP) as a NemoClaw MCP target via `nemoclaw
my-assistant mcp add`. That command requires an HTTPS URL, a canonical DNS
hostname (rejects raw IPs, `localhost`, IPv6 literals, and OpenShell v0.0.116
alias shortcuts), a registered `--env KEY` credential placeholder, and
`--trusted-private-host`. Deprioritized in favor of the OpenClaw **skill**
mechanism (teaching the agent to shell out to the CLI directly) — which is
what's deployed now. Don't re-attempt the custom-MCP-server route unless the
skill-based approach proves insufficient.

## Environment quirks worth knowing

- This machine's default `python`/`python3` on PATH is **msys64's** (no pip
  by default). Run backend Python via `/c/msys64/ucrt64/bin/python.exe`
  explicitly (add to PATH per-command). It has `jsonschema` installed.
- **The msys64 `ucrt64` Python is a native Windows build, not MSYS-aware**:
  it does NOT understand Git-Bash-style `/c/...` unix paths for file I/O
  from within a `python -c "..."` snippet (e.g. `open('/c/Users/...')`
  raises `FileNotFoundError`). Use `C:/Users/...` (forward slashes are fine,
  just need the drive-letter form) when passing paths into Python code, even
  though the same `/c/...` path works fine as a *shell* argument in the Bash
  tool itself.
- **WSL Ubuntu** has Python 3.14 but no pip by default either. Inside the
  **NemoClaw sandbox** specifically, `pip install --user
  --break-system-packages <pkg>` works fine (disposable container).
- `scripts/verify_local.sh` gets **CRLF line endings** reintroduced by the
  Edit tool on this machine even though HEAD is LF-only. Run
  `sed -i 's/\r$//' scripts/verify_local.sh` after every edit to it.
- A pre-existing, unrelated CRLF bug already breaks `scripts/
  verify_local.sh`'s `bash -n` check on `worker/bootstrap_fastsam3d.sh`. Not
  caused by this or the prior session; not fixed either.
- `nemoclaw <sandbox> upload <host-path> <sandbox-dest>` treats
  `sandbox-dest` as a directory to upload into, not a full destination path.
- **Unity's `JsonUtility.FromJson` silently no-ops on nested custom classes**
  inside the AI Assistant `Unity_RunCommand` dynamically-compiled execution
  context — see section 4 above. Don't rely on it there; bake values into
  the generated C# instead.
- This machine's backend test env (`msys64/ucrt64` python) does **not** have
  `fastapi` installed, so `test_auth.py` and `test_subject_labeler.py` fail
  to import there (pre-existing gap, unrelated to any session's changes).
  `test_scene_tools.py` and `test_blueprint_to_unity.py` don't need fastapi
  and run fine.

## Files touched this session

- `backend/blueprint_to_unity.py` (new)
- `backend/blueprint_to_unity_cli.py` (new)
- `backend/test_blueprint_to_unity.py` (new)
- `scripts/verify_local.sh` (registered the three new files/tests)
- `docs/BUILD_PLAN.md` (status rows for steps 3 and 4 updated)
- `C:\Users\kriva\Desktop\HackGTUnity` (outside this repo) — live Editor
  scene now has unsaved proof-of-pipeline GameObjects under
  `SharedRoom_Blueprint_Second Proof Room`; nothing saved to disk.

## Files touched by the prior session (for reference, see previous handoff
   content in git history / this file's earlier revision if needed)

- `backend/scene_tools.py`, `backend/scene_tools_cli.py`,
  `backend/test_scene_tools.py`
- `backend/requirements.txt` (added `jsonschema`)
- `config/nemoclaw/sketchscape-tools.json`,
  `config/nemoclaw/skills/sketchscape-scene-tools/SKILL.md`
- `C:\Users\kriva\Desktop\HackGTUnity\Packages\manifest.json` (outside repo)
- `C:\Users\kriva\.claude.json` (outside repo) — the `unity-mcp` stdio MCP
  server entry for this project.
