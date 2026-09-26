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
- Plain `curl` inside the sandbox is denied by design: the policy only admits
  the OpenClaw `node` binaries. To test, use an agent turn, not `curl`.
- The OpenShell log shows `DELETE /mcp/ ... DENIED` at session end. It's
  harmless (MCP session close isn't in the method allowlist).
- Not supported yet: WSL mirrored networking, macOS or Linux hosts, or
  running the bridge automatically at login.
