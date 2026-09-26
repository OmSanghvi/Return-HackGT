#!/usr/bin/env bash
# Runs inside WSL (login shell, so `nemoclaw`/`openshell` are on PATH).
# Makes a NemoClaw sandbox able to reach the Windows Unity MCP bridge:
#
#   nemoclaw-register.sh <sandbox> <wsl-gateway-ip> <port> <ca.pem> [--onboard]
#
# --onboard creates the sandbox from NemoClaw's managed Dockerfile with the
# bridge CA baked in (NEMOCLAW_CORPORATE_CA_BUNDLE). A plain `nemoclaw <sb>
# rebuild` reuses NVIDIA's prebuilt image and silently drops the CA, so an
# existing sandbox without it can't be fixed in place. Provider and model come
# from NEMOCLAW_PROVIDER / NEMOCLAW_MODEL (default: local Ollama qwen3.5:9b).
#
# The MCP registration is idempotent: it's redone only when the endpoint
# changed (e.g. the WSL gateway IP moved after a reboot) or is broken.
set -euo pipefail

SANDBOX="${1:?usage: nemoclaw-register.sh <sandbox> <ip> <port> <ca.pem> [--onboard]}"
IP="${2:?missing ip}"
PORT="${3:?missing port}"
CA="${4:?missing ca.pem}"
ONBOARD="${5:-}"
SERVER=unity-mcp
URL="https://${IP}:${PORT}/mcp/"
# Spends Unity AI credits and is half the tool-schema size; never agent-callable.
DENY_TOOLS=(Unity_AssetGeneration_GenerateAsset)

quiet() { grep -v -E "UNDICI|trace-warnings|Active gateway set" || true; }

sandbox_exists() {
  openshell sandbox list -g nemoclaw 2>/dev/null | awk 'NR>1 {print $1}' \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -qx "$SANDBOX"
}

ca_baked() {
  # Managed images decode the CA to this root-owned file at build time.
  local want got
  want="$(openssl x509 -in "$CA" -noout -fingerprint -sha256 | cut -d= -f2)"
  got="$(nemoclaw "$SANDBOX" exec -- sh -c \
    'openssl x509 -in /usr/local/share/nemoclaw/corporate-ca.pem -noout -fingerprint -sha256 2>/dev/null' \
    2>/dev/null | quiet | grep -i fingerprint | cut -d= -f2 || true)"
  [ -n "$got" ] && [ "$want" = "$got" ]
}

if [ "$ONBOARD" = "--onboard" ]; then
  if sandbox_exists; then
    echo "Sandbox '$SANDBOX' already exists; not re-onboarding it."
  else
    [ -n "${NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE:-}" ] || {
      echo "ERROR: non-interactive onboard needs NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1" \
           "(pass -AcceptThirdPartySoftware to the setup script)." >&2
      exit 2
    }
    echo "Onboarding sandbox '$SANDBOX' with the bridge CA baked in (several minutes)..."
    NEMOCLAW_CORPORATE_CA_BUNDLE="$CA" \
    NEMOCLAW_PROVIDER="${NEMOCLAW_PROVIDER:-ollama}" \
    NEMOCLAW_MODEL="${NEMOCLAW_MODEL:-qwen3.5:9b}" \
    NEMOCLAW_SANDBOX_NAME="$SANDBOX" \
      nemoclaw onboard --fresh --name "$SANDBOX" \
        --from "$HOME/.nemoclaw/source/Dockerfile" \
        --non-interactive --yes 2>&1 | quiet \
        | grep -E "baking corporate proxy CA|\[[0-9]/8\]|✓ Sandbox|ERROR|Error|failed" || true
  fi
fi

if ! sandbox_exists; then
  echo "ERROR: sandbox '$SANDBOX' not found. Rerun with -Onboard to create it." >&2
  exit 1
fi

if ! ca_baked; then
  echo "ERROR: sandbox '$SANDBOX' does not trust this machine's bridge CA," >&2
  echo "so OpenShell will fail the upstream TLS handshake (NET:FAIL)." >&2
  echo "Create a new sandbox with -Onboard -Sandbox <new-name>, or destroy and" >&2
  echo "re-onboard this one. 'nemoclaw $SANDBOX rebuild' will NOT add the CA." >&2
  exit 1
fi
echo "Sandbox '$SANDBOX' trusts the bridge CA."

status="$(nemoclaw "$SANDBOX" mcp status "$SERVER" 2>&1 | quiet || true)"
if grep -q "endpoint: ${URL}\$" <<<"$status" \
   && grep -q "policy: present" <<<"$status" \
   && grep -q "adapter: registered" <<<"$status"; then
  echo "MCP server '$SERVER' already registered at $URL."
  exit 0
fi

if grep -q "endpoint:" <<<"$status"; then
  echo "Re-registering '$SERVER' (endpoint changed or registration incomplete)..."
  nemoclaw "$SANDBOX" mcp remove "$SERVER" --force 2>&1 | quiet | tail -1
fi
# `mcp remove` keeps the OpenShell provider, and a leftover one blocks re-add.
openshell provider delete -g nemoclaw "${SANDBOX}-mcp-${SERVER}" >/dev/null 2>&1 || true

deny_args=()
for t in "${DENY_TOOLS[@]}"; do deny_args+=(--deny-tool "$t"); done

# The bridge has no auth; NemoClaw still requires a credential variable, so
# give it a random placeholder that exists only for this command.
UNITY_MCP_BRIDGE_TOKEN="$(openssl rand -hex 24)" \
  nemoclaw "$SANDBOX" mcp add "$SERVER" --url "$URL" \
    --env UNITY_MCP_BRIDGE_TOKEN --trusted-private-host "$IP" "${deny_args[@]}" \
  2>&1 | quiet | grep -E "added to sandbox|ERROR|Error|recovery|refus" || true

nemoclaw "$SANDBOX" mcp status "$SERVER" 2>&1 | quiet \
  | grep -E "endpoint:|policy:|adapter:" | sed 's/^ */  /'
