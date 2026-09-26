# NemoClaw ↔ Unity MCP bridge (Windows + WSL2)

Lets a NemoClaw agent sandbox call the Unity Editor's MCP tools directly.
The chain is:

```
NemoClaw sandbox (Docker, WSL2)
  -> OpenShell L7 egress proxy (policy mcp_bridge_unity_mcp)
  -> https://<wsl-gateway-ip>:9443/mcp/   tls_proxy.py  (cert from a private CA)
  -> http://127.0.0.1:19443/mcp/           mcp-proxy 0.9.0
  -> ~/.unity/relay/relay_win.exe --mcp    Unity's MCP relay
  -> Unity Editor (HackGTUnity)
```

## Use

From a normal PowerShell window in the repo root:

```powershell
# First time on a laptop: also creates the `sketchscape` sandbox with the CA baked in
.\scripts\unity-mcp-bridge\Setup-UnityMcpBridge.ps1 -Onboard -AcceptThirdPartySoftware

# After every reboot, or after restarting Unity
.\scripts\unity-mcp-bridge\Setup-UnityMcpBridge.ps1

# Stop the bridge
.\scripts\unity-mcp-bridge\Setup-UnityMcpBridge.ps1 -Stop
```

If script execution is blocked, prefix the command with
`powershell -ExecutionPolicy Bypass -File`. Run it directly: don't pipe its
output (e.g. into `Select-String`). The detached proxies keep the pipe open,
so the pipeline never ends.

Options: `-Sandbox <name>` (default `sketchscape`), `-Distro <wsl distro>`
(default `Ubuntu`), `-Port`/`-BackendPort`, `-SkipNemoClaw`. `-Onboard` uses
`NEMOCLAW_PROVIDER`/`NEMOCLAW_MODEL` from your WSL environment, or local
Ollama `qwen3.5:9b` if they're unset. Inside the agent, tool ids look like
`unity-mcp__Unity_GetConsoleLogs`.

## Prerequisites

- Windows with WSL2 (default NAT networking) and Docker Desktop.
- NemoClaw CLI installed in the WSL distro.
- Unity Editor open on `HackGTUnity`, with Unity MCP enabled
  (Project Settings > AI > Unity MCP). That creates
  `%USERPROFILE%\.unity\relay\relay_win.exe`. If Unity lists a pending
  connection there, accept it.
- `uv` (`winget install --id astral-sh.uv`) or a python.org Python 3.10+.
  MSYS2/Cygwin Pythons don't work: they can't install PyPI's Windows wheels.
- One admin action per machine: an inbound firewall rule for TCP 9443 from
  the WSL subnet. The script prints the exact command if the rule is missing.

## Meta Horizon tools (`meta_*`) in HackGTUnity

Without these steps, Unity MCP exposes only `meta_get_config_information`
from Meta's extension. With them, it exposes 17 tools, 9 of them `meta_*`.

1. **Install the Meta XR SDK.** Asset Store: "Meta XR All-in-One SDK"
   (tested with 207.0.0). Click "Open in Unity", then **Install** in
   Package Manager > My Assets. Opening it alone installs nothing. If Unity
   asks to enable the new Input System backends, say yes (Active Input
   Handling = Both) and restart the Editor.
2. **Patch Meta's MCP extension for Unity 6.5+.** Upstream
   (`meta-quest/Unity-MCP-Extensions` @ `ac3dd9c`, still HEAD on 2026-09-26)
   calls `Object.GetInstanceID()` in `Editor/Tools/GetInteractorsState.cs`.
   That's a hard `CS0619` error on Unity 6000.5+, and it only compiles once
   the SDK is installed. It then breaks the whole extension assembly, so no
   `meta_*` tools appear. To fix, embed the package and apply
   `patches/meta-mcp-extension-unity65-entityid.patch` (from `HackGTUnity/`):

   ```bash
   cp -r Library/PackageCache/com.meta.xr.unity-mcp.extension@* Packages/com.meta.xr.unity-mcp.extension
   git apply --ignore-whitespace --directory=Packages/com.meta.xr.unity-mcp.extension \
     ../Return-HackGT/scripts/unity-mcp-bridge/patches/meta-mcp-extension-unity65-entityid.patch
   ```

   Unity uses an embedded package in place of the git dependency in
   `manifest.json`. Delete the folder to revert. The patch uses
   `(long)EntityId.ToULong(go.GetEntityId())`, the same form Unity AI
   Assistant's own `ObjectsHelper` uses to look objects up.
3. Let Unity recompile (focus the Editor), then rerun
   `Setup-UnityMcpBridge.ps1`.

Expected console noise after every recompile on Unity 6.6: about 60
`[Tool Permissions] ... Library\ScriptAssemblies\Unity.AI.Assistant.Tools.Editor.dll`
errors. Unity 6.6 builds scripts under `Library/Bee/artifacts/` instead,
and AI Assistant's in-Editor permission check still looks in the old
folder. That check only affects the in-Editor chat; MCP is unaffected.
Also expected: MRUK shader errors (they want URP; this project uses the
built-in pipeline) and "Android SDK not found" (needed only for APK builds).

## What it does, and where state lives

| Thing | Location | Notes |
|---|---|---|
| venv, logs, PIDs, leaf cert copy | `%LOCALAPPDATA%\SketchScape\unity-mcp-bridge` | per machine, not in the repo |
| private CA + keys | WSL `~/.config/sketchscape/unity-mcp-pki` (mode 700) | **never commit or share**; each laptop makes its own |
| sandbox trust | baked into the sandbox image at onboard | via `NEMOCLAW_CORPORATE_CA_BUNDLE` + `onboard --from` |

Each run:
1. Detects the Windows-side WSL address, which can change across reboots.
2. Reissues the leaf cert only if that address changed.
3. Restarts both proxies, bound to that address only (never the LAN).
4. Checks MCP `initialize` from WSL with strict TLS.
5. Re-registers the sandbox's `unity-mcp` server only if the endpoint
   changed.

`Unity_AssetGeneration_GenerateAsset` is always denied to the agent: it
spends Unity AI credits.

## Gotchas

- **`nemoclaw <sandbox> rebuild` does not add the CA.** It reuses NVIDIA's
  prebuilt image. A sandbox without the CA fails upstream TLS (`NET:FAIL` in
  `nemoclaw <sb> logs`). The script detects this and refuses. The fix is a new
  sandbox via `-Onboard -Sandbox <new-name>`. Changing only the model provider
  (`nemoclaw inference set ...`) doesn't touch the image.
- **Every `nemoclaw <sandbox> …` command hangs (stale lifecycle lock).**
  Seen 2026-09-26 after a reboot. A `nemoclaw` process was cut off from
  Windows (a timeout around `wsl.exe`) while it held
  `~/.nemoclaw/state/mcp-lifecycle-locks/<hash>.lock`. WSL then restarted,
  so the lock's `pidNamespaceIdentity` pointed at a namespace that no longer
  exists. NemoClaw can't prove that owner dead, and it has no force-unlock.
  The fix:
  1. Confirm no `nemoclaw`/`openshell` lifecycle command is running.
  2. Check that the lock's `pid` doesn't exist and its namespace differs
     from `readlink /proc/self/ns/pid`.
  3. Back up the `.lock` (and any `.candidate-*`) files, then remove them.

  NemoClaw's docs say not to delete lock files by hand. That's right while
  the owner might be alive, so only do it when these checks show the owner
  is gone. Prevention: never time out `wsl.exe` from Windows. The scripts
  bound `nemoclaw` calls with `timeout` inside WSL (`NC_TIMEOUT`, default
  300s), where NemoClaw can recover the lock itself.
- **Muse Spark (or any HTTPS model endpoint with IPv6 DNS) returns 502 in
  milliseconds.** NemoClaw's endpoint preflight sorts resolved addresses as
  strings, so an IPv6 address (`2a03:…`) sorts first, and its HTTPS-pin
  adapter connects to `pinnedAddresses[0]`. WSL has no IPv6 route, so it
  gets `ENETUNREACH`, which is reported as 502 with a `durationMs` in single
  digits in `~/.nemoclaw/https-pin-runtime-adapter.log`.
  - Local fix (applied 2026-09-26, lost on a NemoClaw update): edit
    `~/.nemoclaw/source/dist/lib/inference/https-pin-runtime-adapter.js`
    so `pinnedAddress:` is
    `route.pinnedAddresses.find((a) => !a.includes(":")) ?? route.pinnedAddresses[0]`.
    The original is kept as `.orig`.
  - Then kill the adapter (`~/.nemoclaw/https-pin-runtime-adapter.pid`) and
    rerun `scripts/nemoclaw-set-muse-spark.sh`. The adapter never persists
    the key.
- After `nemoclaw inference set`, run `nemoclaw <sb> gateway restart`. The
  running OpenClaw gateway otherwise keeps the previous model's in-memory
  settings. The symptom: session transcripts
  (`/sandbox/.openclaw/agents/main/sessions/<id>.jsonl`) still show the old
  model name, and the agent ends its turn after one tool call with empty
  content.
- **OpenClaw truncates tool results at 16k characters**, including its own
  wrapper. When that happens the agent silently stops, so skill CLIs must
  keep each output small. `unity_room_cli.py` splits its output into
  `compose_room` (a compact plan), `build_code` and `finalize_code` for this
  reason, and a test enforces a 10k cap.
- **Skills install to `/sandbox/.openclaw/workspace/skills/<name>`**, not
  `/sandbox/.openclaw/skills`. A sandbox rebuild wipes them; rerun
  `scripts/nemoclaw-deploy-skills.sh`.
- **`nemoclaw <sb> upload` of a file freshly written under `/mnt/c` can
  arrive as all zero bytes.** Copy it to the WSL filesystem first (for
  example `~/ss-tmp/`) and upload from there.
- The Unity MCP bridge runs as the `openclaw`/`node` binaries only. The
  sandbox policy doesn't let a skill's Python reach it, so the agent passes
  generated C# to `Unity_RunCommand` itself. Don't work around that
  boundary.
- `AssetDatabase.DeleteAsset` through `Unity_RunCommand` is refused ("User
  interactions are not supported for MCP tool calls"). Delete assets by hand
  in the Editor.
- `nemoclaw <sb> status` shows `Inference: unhealthy … invalid response
  body` with Muse Spark even when the route works, because its probe
  misreads Meta's reply. `scripts/Start-SketchScape.ps1` checks the route
  adapter instead.
- Muse Spark reasons before answering (about 1.6k tokens for a busy photo).
  A small `max_tokens` returns `content: null` with `finish_reason: stop`,
  so give it several thousand.
- **Real splat scans are Z-up.** Fast-SAM3D PLYs synced by
  `scripts/sync_s3_assets_to_unity.py` import with Gsplat's default (RUB)
  frame. Rotate the splat +90° about X to stand them up without mirroring;
  `backend/unity_room.py` does this.
- `Unity_RunCommand` code can't reference the Gsplat assembly (CS0246). Use
  reflection: `System.Type.GetType("Gsplat.GsplatRenderer, Gsplat")`, then
  the `GsplatAsset` and `Bounds` fields. The command sandbox also rejects
  `System.Reflection.BindingFlags`, so stick to public members.
- Unity's MCP capture tools (`Unity_Camera_Capture`,
  `…CaptureMultiAngleSceneView`) and a manual `Camera.Render()` don't draw
  Gaussian splats. To check them visually, frame the Scene View and take a
  desktop screenshot.
- `Object.GetInstanceID()` is a compile error on Unity 6.6. Use
  `GetEntityId()`, or log the object with `result.Log("{0}", obj)`.
- Don't call `EditorSceneManager.SaveScene` on "whatever is active" in a
  cleanup step. It will re-create a scene file the user deleted while that
  scene was still open.
- The `DENIED DELETE …/mcp/` line in `openshell logs` at the end of an
  agent turn is the MCP session teardown, which the policy doesn't allow.
  It's harmless.
- After a reboot, Docker Desktop and the Unity Editor must be running before
  you rerun the setup script. The Ollama auth proxy (port 11435) also
  doesn't come back on its own; `nemoclaw <sb> status` then reports the
  inference route as unhealthy. That only matters while the sandbox uses the
  local Ollama model.
- Plain `curl` inside the sandbox is denied by design: the policy only admits
  the OpenClaw `node` binaries. To test, use an agent turn, not `curl`.
- The OpenShell log shows `DELETE /mcp/ ... DENIED` at session end. It's
  harmless (MCP session close isn't in the method allowlist).
- Not supported yet: WSL mirrored networking, macOS or Linux hosts, or
  running the bridge automatically at login.
