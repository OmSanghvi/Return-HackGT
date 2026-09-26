# Handoff — NemoClaw + Unity MCP orchestration (Build Plan steps 3, 4, 6)

Written 2026-09-26 (second revision, same day — supersedes the previous
version of this file). Read this before continuing the "nemoclaw agents
orchestrate the Unity scene" work.

**To resume this exact conversation in Claude Code**, use session id:

    9ec49dd6-8e12-456d-a920-fce5aadb110c

(Resume it the normal way for this Claude Code install — e.g. `claude
--resume 9ec49dd6-8e12-456d-a920-fce5aadb110c` or whatever the client's
session-resume flow is. If that doesn't apply to your setup, this file is
the fallback: everything below should be enough for a fresh session to pick
up where this one left off.)

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
- Live sandbox: `my-assistant` (default), agent = **OpenClaw**, model = **local
  Ollama `qwen3.5:9b`**. Healthy per `nemoclaw my-assistant doctor`.
- **User decision (already made, don't re-litigate):** keep `qwen3.5:9b` for
  dev/iteration now; switch `NEMOCLAW_MODEL_PROVIDER` to one of `meta`/`xai`/
  `nebius` before the real demo/submission. Config-only swap.
- Useful commands: `nemoclaw list`, `nemoclaw my-assistant doctor`, `nemoclaw
  my-assistant exec -- <cmd>`, `nemoclaw my-assistant upload <host-path>
  <sandbox-dir>` (uploads **into** a directory — don't repeat the filename in
  the destination), `nemoclaw my-assistant agent --agent main -m "<prompt>"`.

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
  - **Tool surface:** Unity exposes only 8 tools (base AI Assistant package):
    `Unity_RunCommand`, `Unity_GetConsoleLogs`, scene/camera captures, asset
    generation, `meta_get_config_information`. **None of the Meta Horizon
    extension's GameObject/grabbable/teleport tools appear.** This is
    probably because the Meta XR SDK isn't installed yet (unverified).
  - `my-assistant` keeps a stale, non-working `unity-mcp` registration.
    Use `sketchscape` for Unity work.
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
