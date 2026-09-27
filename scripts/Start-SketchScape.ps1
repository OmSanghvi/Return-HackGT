<#
.SYNOPSIS
  One command to bring the whole SketchScape agent stack up after a reboot:
  Docker -> Unity Editor -> Unity MCP bridge -> Muse Spark route -> agent
  gateway -> skills. Idempotent; every step skips itself when it's already
  fine.

.DESCRIPTION
  1. Starts Docker Desktop and waits until WSL can reach the Docker engine.
  2. Opens HackGTUnity in the Unity Editor (if it isn't open) and waits for
     Unity MCP's relay (relay_win.exe --relay).
  3. Runs unity-mcp-bridge\Setup-UnityMcpBridge.ps1 (proxies, TLS cert for
     the current WSL address, NemoClaw registration).
  4. Checks NemoClaw's local IPv4-pin patch. It never applies it; if a
     NemoClaw update removed it, it prints the fix and stops.
  5. Checks the Muse Spark route. NemoClaw's route adapter keeps the Meta key
     in memory only, so after a reboot the route is gone. If so, it runs
     scripts/nemoclaw-set-muse-spark.sh, which asks for the key in this
     console (hidden input), then restarts the sandbox's agent gateway.
     (NemoClaw's own "Inference: unhealthy" status line is not used: its
     probe misreads Muse Spark responses even when the route works.)
  6. Deploys the OpenClaw skills if the sandbox doesn't have them.
  7. Optional (-Runner): starts scripts/room_build_runner.py in its own
     window, so the web app's "Build room in VR" requests are built here
     (docs/WEB_TO_QUEST_PIPELINE.md section 2). Skipped if one is running.

  Never wraps wsl.exe in a Windows-side timeout (that once orphaned a
  NemoClaw lifecycle lock); long WSL commands carry their own `timeout`.

.EXAMPLE
  .\scripts\Start-SketchScape.ps1

.EXAMPLE
  # Re-enter the Meta key even if the route looks fine (e.g. after rotating it):
  .\scripts\Start-SketchScape.ps1 -ForceKey

.EXAMPLE
  # Bring the stack up and start the room-build runner in its own window:
  .\scripts\Start-SketchScape.ps1 -Runner
  # ...with extra runner flags (e.g. a dry run that skips the agent):
  .\scripts\Start-SketchScape.ps1 -Runner -RunnerArgs "--no-agent"
#>
[CmdletBinding()]
param(
  [string]$Sandbox = "sketchscape",
  [string]$Distro = "Ubuntu",
  [string]$UnityProject = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "HackGTUnity"),
  [string]$UnityExe = "C:\Program Files\Unity\Hub\Editor\6000.6.3f1\Editor\Unity.exe",
  [string]$DockerExe = (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
  [switch]$ForceKey,
  [switch]$SkipUnity,
  [switch]$Runner,
  [string]$RunnerArgs = "",
  [string]$RunnerPython = "C:\msys64\ucrt64\bin\python.exe"
)

$ErrorActionPreference = "Continue"  # native stderr must not become terminating errors (PS 5.1)
$Repo = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $env:LOCALAPPDATA "SketchScape"
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "    $msg" }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function ConvertTo-WslPath([string]$winPath) {
  $p = $winPath -replace '\\', '/'
  if ($p -match '^([A-Za-z]):(.*)$') { return "/mnt/$($Matches[1].ToLower())$($Matches[2])" }
  return $p
}

function Invoke-Wsl([string]$script) {
  # Through a temp file: PowerShell 5.1 mangles embedded quotes in native args.
  $tmp = Join-Path $StateDir "start-step.sh"
  [IO.File]::WriteAllText($tmp, ($script -replace "`r`n", "`n") + "`n", (New-Object Text.UTF8Encoding $false))
  $out = & wsl.exe -d $Distro -- bash -l (ConvertTo-WslPath $tmp) 2>&1
  return @{ Output = ($out | ForEach-Object { "$_" }); Code = $LASTEXITCODE }
}

function Wait-Until([scriptblock]$check, [int]$seconds, [string]$what) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    if (& $check) { return $true }
    Start-Sleep -Seconds 3
  }
  Fail "timed out after ${seconds}s waiting for $what."
}

# --- 1. Docker ---------------------------------------------------------------
Step "Docker Desktop"
$dockerUp = { (Invoke-Wsl "timeout 15 docker info --format '{{.ServerVersion}}' >/dev/null 2>&1").Code -eq 0 }
if (& $dockerUp) {
  Ok "engine reachable from WSL"
} else {
  if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path $DockerExe)) { Fail "Docker Desktop not found at $DockerExe (pass -DockerExe)." }
    Info "starting Docker Desktop..."
    Start-Process -FilePath $DockerExe | Out-Null
  }
  Wait-Until $dockerUp 240 "the Docker engine" | Out-Null
  Ok "engine reachable from WSL"
}

# --- 2. Unity ----------------------------------------------------------------
Step "Unity Editor on $(Split-Path -Leaf $UnityProject)"
$relayUp = { [bool](Get-CimInstance Win32_Process -Filter "Name='relay_win.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*--relay*" }) }
if ($SkipUnity) {
  Info "skipped (-SkipUnity)"
} elseif (& $relayUp) {
  Ok "Unity MCP relay is running"
} else {
  $open = Get-CimInstance Win32_Process -Filter "Name='Unity.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$(Split-Path -Leaf $UnityProject)*" }
  if (-not $open) {
    if (-not (Test-Path $UnityExe)) { Fail "Unity not found at $UnityExe (pass -UnityExe)." }
    Info "opening the project (first import after a reboot can take a few minutes)..."
    Start-Process -FilePath $UnityExe -ArgumentList @("-projectPath", "`"$UnityProject`"") | Out-Null
  }
  Wait-Until $relayUp 900 "Unity MCP's relay (relay_win.exe --relay)" | Out-Null
  Ok "Unity MCP relay is running"
}

# --- 3. Bridge ---------------------------------------------------------------
Step "Unity MCP bridge"
& (Join-Path $PSScriptRoot "unity-mcp-bridge\Setup-UnityMcpBridge.ps1") -Sandbox $Sandbox -Distro $Distro
if ($LASTEXITCODE -ne 0) { Fail "Setup-UnityMcpBridge.ps1 failed (see above)." }

# --- 4. NemoClaw IPv4-pin patch ----------------------------------------------
Step "NemoClaw IPv4-pin patch"
$patch = Invoke-Wsl "grep -q 'local patch: prefer IPv4' ~/.nemoclaw/source/dist/lib/inference/https-pin-runtime-adapter.js"
if ($patch.Code -ne 0) {
  Write-Host "    The local patch is missing (a NemoClaw update replaces it), so Muse Spark calls will fail with 502." -ForegroundColor Yellow
  Write-Host "    Re-apply it in your WSL shell as described in scripts/unity-mcp-bridge/README.md -> Gotchas" -ForegroundColor Yellow
  Write-Host "    ('Muse Spark ... returns 502 in milliseconds'), then rerun this script." -ForegroundColor Yellow
  exit 1
}
Ok "present"

# --- 5. Muse Spark route + agent gateway ------------------------------------
Step "Muse Spark route (Meta key lives only in NemoClaw's adapter memory)"
$routeCheck = @'
pidfile=~/.nemoclaw/https-pin-runtime-adapter.pid
log=~/.nemoclaw/https-pin-runtime-adapter.log
pid=$(cat "$pidfile" 2>/dev/null) || exit 1
ps -p "$pid" -o args= 2>/dev/null | grep -q https-pin-runtime-adapter.js || exit 1
# A route must have been registered since this adapter process last started.
tail -n 200 "$log" | awk '/"adapter_ready"/{r=0} /"route_registered"/{r=1} END{exit r?0:1}'
'@
if (-not $ForceKey -and (Invoke-Wsl $routeCheck).Code -eq 0) {
  Ok "route registered in the running adapter"
} else {
  Info "The route needs the Meta Model API key. Paste it at the hidden prompt below."
  & wsl.exe -d $Distro -- bash -l (ConvertTo-WslPath (Join-Path $PSScriptRoot "nemoclaw-set-muse-spark.sh")) $Sandbox
  if ($LASTEXITCODE -ne 0) { Fail "setting the Muse Spark route failed (see above)." }
  if ((Invoke-Wsl $routeCheck).Code -ne 0) { Fail "the route still isn't registered after entering the key." }
  Ok "route registered"
  Info "restarting the sandbox agent gateway so it picks up the model settings..."
  $r = Invoke-Wsl "timeout 300 nemoclaw $Sandbox gateway restart"
  if ($r.Code -ne 0) { $r.Output | Select-Object -Last 5 | ForEach-Object { Info $_ }; Fail "gateway restart failed." }
  Ok "gateway restarted"
}

# --- 6. Skills ---------------------------------------------------------------
Step "OpenClaw skills in the sandbox"
$skills = Invoke-Wsl "timeout 120 nemoclaw $Sandbox skill list 2>&1 | grep -o 'sketchscape-[a-z-]*' | sort -u"
$have = @($skills.Output | Where-Object { $_ -like "sketchscape-*" })
$wanted = @("sketchscape-scene-tools", "sketchscape-unity-room", "sketchscape-subject-labeler", "sketchscape-room-tools")
if (@($wanted | Where-Object { $have -notcontains $_ }).Count -eq 0) {
  Ok ($have -join ", ")
} else {
  Info "deploying (the sandbox was rebuilt or never had them)..."
  $r = Invoke-Wsl "cd '$(ConvertTo-WslPath $Repo)' && timeout 600 bash scripts/nemoclaw-deploy-skills.sh $Sandbox"
  if ($r.Code -ne 0) { $r.Output | Select-Object -Last 10 | ForEach-Object { Info $_ }; Fail "skill deploy failed." }
  Ok "deployed"
}

# --- 7. Room build runner (optional) ----------------------------------------
if ($Runner) {
  Step "Room build runner (web 'Build room in VR' -> NemoClaw -> HackGTUnity)"
  $runnerScript = Join-Path $PSScriptRoot "room_build_runner.py"
  $tokenFile = Join-Path $env:USERPROFILE ".config\sketchscape\room-runner-token"
  $running = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*room_build_runner.py*" })
  if ($running.Count -gt 0) {
    Ok "already running (pid $($running[0].ProcessId)); log: $StateDir\room-runner.log"
  } else {
    if (-not (Test-Path $RunnerPython)) { Fail "Python not found at $RunnerPython (pass -RunnerPython)." }
    if (-not $env:SKETCHSCAPE_ROOM_RUNNER_TOKEN -and -not (Test-Path $tokenFile)) {
      Fail "no runner token at $tokenFile (one line: the API host's SKETCHSCAPE_NEMOCLAW_TOKEN)."
    }
    # Through -EncodedCommand: PowerShell 5.1 mangles quotes in native args.
    $q = { param($s) "'" + ($s -replace "'", "''") + "'" }
    $cmd = "`$host.UI.RawUI.WindowTitle = 'SketchScape room runner'; `$env:PYTHONUTF8 = '1'; " +
      "Set-Location $(& $q $Repo); & $(& $q $RunnerPython) -u $(& $q $runnerScript) $RunnerArgs; " +
      "Write-Host `"Room runner exited (code `$LASTEXITCODE). Log: $StateDir\room-runner.log`""
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
    Start-Process -FilePath "powershell.exe" -WorkingDirectory $Repo `
      -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded) | Out-Null
    Ok "started in its own window; log: $StateDir\room-runner.log"
  }
}

Write-Host "`nSketchScape agent stack is up." -ForegroundColor Green
Write-Host "Try: wsl -d $Distro -- bash -lc `"nemoclaw $Sandbox agent --agent main -m 'Build a Shared Room in Unity from: my cat, a pink blanket, a tomato'`""
