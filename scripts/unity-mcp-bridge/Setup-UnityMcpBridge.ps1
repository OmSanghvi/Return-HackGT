<#
.SYNOPSIS
  Connects a NemoClaw sandbox (WSL2/Docker) to the Unity Editor's MCP server
  on this Windows machine. Idempotent: rerun it after a reboot, or whenever
  Unity was restarted.

.DESCRIPTION
  Chain: NemoClaw sandbox -> OpenShell L7 proxy -> https://<wsl-gw>:9443
  (tls_proxy.py) -> http://127.0.0.1:19443 (mcp-proxy) -> relay_win.exe --mcp
  -> Unity Editor.

  1. Creates a venv with mcp-proxy (per-machine state in
     %LOCALAPPDATA%\SketchScape\unity-mcp-bridge; nothing in the repo).
  2. Detects the Windows-side WSL address (it can change across reboots).
  3. In WSL: ensures a private CA and a leaf cert for that address (pki.sh).
     The CA key never leaves WSL.
  4. (Re)starts mcp-proxy and the TLS proxy, bound to the WSL address only.
  5. Verifies an MCP initialize from WSL with strict TLS verification.
  6. Registers the bridge with the NemoClaw sandbox (nemoclaw-register.sh).
     With -Onboard it first creates the sandbox with the CA baked in.

  Prerequisites: Windows + WSL2 distro with NemoClaw installed, Docker
  Desktop, Unity Editor open on HackGTUnity with Unity MCP enabled (Project
  Settings > AI > Unity MCP), and Python 3.10+ on Windows.

.EXAMPLE
  # First time on a new laptop (creates the 'sketchscape' sandbox):
  .\Setup-UnityMcpBridge.ps1 -Onboard -AcceptThirdPartySoftware

.EXAMPLE
  # Every later session / after a reboot:
  .\Setup-UnityMcpBridge.ps1
#>
[CmdletBinding()]
param(
  [string]$Sandbox = "sketchscape",
  [string]$Distro = "Ubuntu",
  [int]$Port = 9443,
  [int]$BackendPort = 19443,
  [switch]$Onboard,
  [switch]$AcceptThirdPartySoftware,
  [switch]$SkipNemoClaw,
  [switch]$Stop
)

# Not "Stop": Windows PowerShell 5.1 turns any stderr line from a native
# command (wsl.exe, pip) into a terminating error. Exit codes are checked
# explicitly instead.
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = Join-Path $env:LOCALAPPDATA "SketchScape\unity-mcp-bridge"
$CertDir = Join-Path $StateDir "certs"
$VenvDir = Join-Path $StateDir "venv"
$McpProxyVersion = "0.9.0"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

function ConvertTo-WslPath([string]$winPath) {
  $p = $winPath -replace '\\', '/'
  if ($p -match '^([A-Za-z]):(.*)$') { return "/mnt/$($Matches[1].ToLower())$($Matches[2])" }
  return $p
}

function Invoke-Wsl([string]$script) {
  # Run a bash snippet in a login shell (so nemoclaw/openshell are on PATH).
  # It goes through a temp file because PowerShell 5.1 mangles embedded double
  # quotes in native-command arguments.
  $tmp = Join-Path $StateDir "wsl-step.sh"
  [IO.File]::WriteAllText($tmp, ($script -replace "`r`n", "`n") + "`n", (New-Object Text.UTF8Encoding $false))
  $out = & wsl.exe -d $Distro -- bash -l (ConvertTo-WslPath $tmp) 2>&1
  $code = $LASTEXITCODE
  return @{ Output = ($out | ForEach-Object { "$_" }); Code = $code }
}

function Stop-PortOwner([int]$port) {
  # Only stop our own bridge processes (python / mcp-proxy), never Unity.
  $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($null -eq $proc) { continue }
    if ($proc.ProcessName -match '^(python|python3|python3\.\d+|mcp-proxy)$') {
      & taskkill.exe /T /F /PID $proc.Id | Out-Null
      Write-Host "    stopped $($proc.ProcessName) (PID $($proc.Id)) on port $port"
    } else {
      Fail "port $port is owned by '$($proc.ProcessName)' (PID $($proc.Id)); pick another -Port/-BackendPort."
    }
  }
}

function Find-Uv {
  $cmd = Get-Command uv.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $local = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
  if (Test-Path $local) { return $local }
  return $null
}

function Find-Python {
  # Standard CPython only: MSYS2/Cygwin builds can't use PyPI's Windows wheels
  # (pydantic-core then tries to compile with Rust and fails).
  $candidates = @()
  $py = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($py) { $candidates += (& $py.Source -3 -c "import sys; print(sys.executable)" 2>$null) }
  foreach ($name in "python.exe", "python3.exe") {
    $cmd = Get-Command $name -All -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
  }
  foreach ($c in $candidates | Where-Object { $_ } | Select-Object -Unique) {
    if (-not (Test-Path $c) -or $c -match 'WindowsApps|msys|cygwin|mingw') { continue }
    $v = & $c -c "import sys, sysconfig; print('%d.%d' % sys.version_info[:2], sysconfig.get_platform())" 2>$null
    if ($LASTEXITCODE -ne 0 -or "$v" -notmatch '^(\d+\.\d+) win-amd64$') { continue }
    if ([version]$Matches[1] -ge [version]"3.10") { return $c }
  }
  return $null
}

# --- stop ------------------------------------------------------------------
if ($Stop) {
  Step "Stopping the bridge"
  Stop-PortOwner $Port
  Stop-PortOwner $BackendPort
  exit 0
}

# --- 1. venv + mcp-proxy ---------------------------------------------------
Step "Preparing $StateDir"
New-Item -ItemType Directory -Force -Path $StateDir, $CertDir | Out-Null
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
$mcpProxy = Join-Path $VenvDir "Scripts\mcp-proxy.exe"
if (-not (Test-Path $mcpProxy)) {
  if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
  $uv = Find-Uv
  if ($uv) {
    # uv fetches a standard CPython if the machine doesn't have one.
    Write-Host "    creating venv with uv"
    & $uv venv --quiet --python 3.12 $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "uv venv failed" }
    & $uv pip install --quiet --python $venvPython "mcp-proxy==$McpProxyVersion"
  } else {
    $py = Find-Python
    if (-not $py) {
      Fail "need uv or a standard (python.org) Python 3.10+. Easiest: 'winget install --id astral-sh.uv', then rerun."
    }
    Write-Host "    creating venv with $py"
    & $py -m venv $VenvDir
    & $venvPython -m pip install --quiet --disable-pip-version-check "mcp-proxy==$McpProxyVersion"
  }
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $mcpProxy)) { Fail "installing mcp-proxy==$McpProxyVersion failed" }
  Write-Host "    installed mcp-proxy==$McpProxyVersion"
}

# Unity's AI Assistant installs this relay when Unity MCP is enabled.
$relay = Join-Path $env:USERPROFILE ".unity\relay\relay_win.exe"
if (-not (Test-Path $relay)) {
  Fail "$relay not found. Open HackGTUnity and enable Unity MCP (Project Settings > AI > Unity MCP), then rerun."
}
if (-not (Get-Process -Name Unity -ErrorAction SilentlyContinue)) {
  Write-Host "    WARNING: Unity Editor isn't running; the bridge will start but tools will fail until it is." -ForegroundColor Yellow
}

# --- 2. WSL-facing address -------------------------------------------------
Step "Detecting the Windows-side WSL address"
$wslIf = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object { $_.InterfaceAlias -like "vEthernet (WSL*" } | Select-Object -First 1
if (-not $wslIf) {
  Fail "no 'vEthernet (WSL...)' adapter found. Start WSL ('wsl -d $Distro') and rerun. (WSL mirrored networking isn't supported by this script.)"
}
$ip = $wslIf.IPAddress
Write-Host "    $($wslIf.InterfaceAlias): $ip/$($wslIf.PrefixLength)"

# Inbound firewall rule for the WSL subnet. Creating it needs admin once.
$ruleName = "WSL to Unity MCP bridge"
$rule = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $rule) {
  $prefix = $wslIf.PrefixLength
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $netAddr = ([ipaddress](([ipaddress]$ip).Address -band ([uint32]::MaxValue -shl (32 - $prefix) -band [uint32]::MaxValue))).ToString()
  $cmd = "New-NetFirewallRule -DisplayName '$ruleName' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress $netAddr/$prefix"
  if ($isAdmin) {
    Invoke-Expression $cmd | Out-Null
    Write-Host "    created firewall rule '$ruleName'"
  } else {
    Write-Host "    WARNING: firewall rule '$ruleName' is missing. Run once in an ADMIN PowerShell:" -ForegroundColor Yellow
    Write-Host "      $cmd" -ForegroundColor Yellow
  }
}

# --- 3. certificates -------------------------------------------------------
Step "Ensuring the private CA and leaf certificate (in WSL)"
$pkiSh = ConvertTo-WslPath (Join-Path $ScriptDir "pki.sh")
$certDirWsl = ConvertTo-WslPath $CertDir
$r = Invoke-Wsl "bash '$pkiSh' '$ip' '$certDirWsl'"
if ($r.Code -ne 0) { $r.Output; Fail "pki.sh failed" }
$caWsl = ($r.Output | Where-Object { $_ -like "CA=*" }) -replace '^CA=', ''
$leafState = ($r.Output | Where-Object { $_ -like "LEAF=*" }) -replace '^LEAF=', ''
Write-Host "    CA: $caWsl (leaf $leafState)"

# --- 4. (re)start the proxies ----------------------------------------------
Step "Starting mcp-proxy (127.0.0.1:$BackendPort) and TLS proxy ($ip`:$Port)"
Stop-PortOwner $Port
Stop-PortOwner $BackendPort
$mcp = Start-Process -FilePath $mcpProxy -WindowStyle Hidden -PassThru `
  -ArgumentList "--port $BackendPort --host 127.0.0.1 -- `"$relay`" --mcp" `
  -RedirectStandardOutput (Join-Path $StateDir "mcp-proxy.out.log") `
  -RedirectStandardError (Join-Path $StateDir "mcp-proxy.log")
$tls = Start-Process -FilePath $venvPython -WindowStyle Hidden -PassThru `
  -ArgumentList "`"$(Join-Path $ScriptDir 'tls_proxy.py')`" --listen-host $ip --listen-port $Port --backend-port $BackendPort --cert `"$CertDir\unity-mcp-chain.crt`" --key `"$CertDir\unity-mcp-leaf.key`"" `
  -RedirectStandardOutput (Join-Path $StateDir "tls-proxy.log") `
  -RedirectStandardError (Join-Path $StateDir "tls-proxy.err.log")
Set-Content -Path (Join-Path $StateDir "pids.txt") -Value "mcp-proxy=$($mcp.Id)`ntls-proxy=$($tls.Id)" -Encoding ascii

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
  $up1 = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
  $up2 = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($up1 -and $up2) { break }
  Start-Sleep -Milliseconds 500
}
if (-not ($up1 -and $up2)) { Fail "proxies did not start; see logs in $StateDir" }

# --- 5. verify from WSL with strict TLS ------------------------------------
Step "Verifying MCP initialize from WSL (strict TLS)"
$body = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"setup-check","version":"0"}}}'
$check = "curl -s -m 20 --cacert '$caWsl' -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' https://${ip}:$Port/mcp/ -d '$body'"
$ok = $false
for ($i = 0; $i -lt 5 -and -not $ok; $i++) {
  $r = Invoke-Wsl $check
  if (($r.Output -join "") -match '"serverInfo":\{"name":"([^"]+)","version":"([^"]+)"') {
    Write-Host "    OK: $($Matches[1]) $($Matches[2])"
    $ok = $true
  } else { Start-Sleep -Seconds 2 }
}
if (-not $ok) {
  $r.Output | Select-Object -First 5
  Fail "WSL could not complete an MCP initialize. Check the firewall rule and $StateDir\mcp-proxy.log"
}

# --- 6. NemoClaw ------------------------------------------------------------
if ($SkipNemoClaw) { Step "Skipping NemoClaw registration"; exit 0 }
Step "Registering with NemoClaw sandbox '$Sandbox'"
$regSh = ConvertTo-WslPath (Join-Path $ScriptDir "nemoclaw-register.sh")
$envPrefix = ""
if ($AcceptThirdPartySoftware) { $envPrefix = "NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 " }
$onboardArg = ""
if ($Onboard) { $onboardArg = "--onboard" }
$r = Invoke-Wsl "${envPrefix}bash '$regSh' '$Sandbox' '$ip' '$Port' '$caWsl' $onboardArg"
$r.Output | ForEach-Object { Write-Host "    $_" }
if ($r.Code -ne 0) { Fail "NemoClaw registration failed" }

Step "Done. NemoClaw sandbox '$Sandbox' can reach Unity MCP at https://${ip}:$Port/mcp/"
Write-Host "    Tool ids inside the agent: unity-mcp__<toolName> (e.g. unity-mcp__Unity_GetConsoleLogs)"
