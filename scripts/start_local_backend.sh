#!/usr/bin/env bash
# Run the SketchScape backend locally (in WSL) against the REAL shared data
# (DynamoDB table + S3 artifacts bucket), and connect the NemoClaw sandbox's
# room tools to it. Idempotent; rerun after a reboot.
#
#   bash scripts/start_local_backend.sh [--stop]
#
# 1. Ensures NemoClaw's service token (~/.config/sketchscape/nemoclaw-token,
#    mode 600, generated once). Never in the repo.
# 2. Starts `uvicorn main:app` on this WSL's eth0 address, port 8000, with
#    SKETCHSCAPE_STORAGE_BACKEND=dynamodb, S3 artifacts, demo auth (people act
#    as demo accounts; NemoClaw as the service identity: read + draft only,
#    never publish), and PIPELINE_MODE=aws-local (new jobs queue for the GPU
#    host instead of running mock jobs against the real table).
#    AWS credentials come from `aws login` (needs botocore[crt] in the venv).
# 3. Adds the `sketchscape-backend` policy preset so python3 in the sandbox may
#    call exactly the room-tool routes (config/nemoclaw/policies/).
# 4. Writes the backend URL and token into the sandbox's
#    ~/.config/sketchscape/ (mode 600), where backend/room_tools.py reads them.
#    (OpenShell has no generic env injection for skill shells today; the token
#    only grants read + draft on this local backend.)
set -euo pipefail

SANDBOX="${NEMOCLAW_SANDBOX:-sketchscape}"
PORT="${SKETCHSCAPE_BACKEND_PORT:-8000}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$HOME/.config/sketchscape"
STATE="$HOME/.local/state/sketchscape"
PIDFILE="$STATE/backend.pid"
LOG="$STATE/backend.log"
mkdir -p "$CONF" "$STATE"
chmod 700 "$CONF"

running() { [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

if [[ "${1:-}" == "--stop" ]]; then
  if running; then kill "$(cat "$PIDFILE")" && echo "stopped backend $(cat "$PIDFILE")"; else echo "backend not running"; fi
  rm -f "$PIDFILE"
  exit 0
fi

# --- 1. token ---------------------------------------------------------------
if [[ ! -s "$CONF/nemoclaw-token" ]]; then
  (umask 077; python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$CONF/nemoclaw-token")
  echo "generated NemoClaw service token at $CONF/nemoclaw-token"
fi
TOKEN="$(cat "$CONF/nemoclaw-token")"

# --- 2. backend -------------------------------------------------------------
HOST="$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1)"
[[ -n "$HOST" ]] || { echo "ERROR: no eth0 IPv4 address in WSL" >&2; exit 1; }
URL="http://$HOST:$PORT"

if running && curl -fsS -m 5 "$URL/health" >/dev/null 2>&1; then
  echo "backend already running at $URL (pid $(cat "$PIDFILE"))"
else
  running && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  cd "$REPO/backend"
  SKETCHSCAPE_STORAGE_BACKEND=dynamodb \
  SKETCHSCAPE_DYNAMODB_TABLE="${SKETCHSCAPE_DYNAMODB_TABLE:-sketchscape-authoring}" \
  SKETCHSCAPE_ARTIFACTS_BACKEND=s3 \
  SKETCHSCAPE_ARTIFACTS_BUCKET="${SKETCHSCAPE_ARTIFACTS_BUCKET:-sketchscape-artifacts-20260922133334256700000003}" \
  AWS_REGION="${AWS_REGION:-us-east-1}" AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}" \
  SKETCHSCAPE_AUTH_MODE=demo \
  SKETCHSCAPE_WEB_ORIGINS="${SKETCHSCAPE_WEB_ORIGINS:-http://localhost:5173,https://returnweb-hazel.vercel.app}" \
  SKETCHSCAPE_NEMOCLAW_TOKEN="$TOKEN" \
  PIPELINE_MODE="${PIPELINE_MODE:-aws-local}" \
  SKETCHSCAPE_SUBJECT_LABELER="${SKETCHSCAPE_SUBJECT_LABELER:-nemoclaw}" \
  nohup .venv/bin/python -m uvicorn main:app --host "$HOST" --port "$PORT" >"$LOG" 2>&1 &
  echo $! > "$PIDFILE"
  for _ in $(seq 1 60); do
    curl -fsS -m 3 "$URL/health" >/dev/null 2>&1 && break
    kill -0 "$(cat "$PIDFILE")" 2>/dev/null || { echo "ERROR: backend exited; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }
    sleep 1
  done
  curl -fsS -m 3 "$URL/health" >/dev/null || { echo "ERROR: backend not healthy; see $LOG" >&2; exit 1; }
  echo "backend running at $URL (pid $(cat "$PIDFILE"), log $LOG)"
fi

# --- 3. sandbox egress policy -----------------------------------------------
POLICY="$STATE/sketchscape-backend.yaml"
sed -e "s/__BACKEND_HOST__/$HOST/g" -e "s/__BACKEND_PORT__/$PORT/g" \
  "$REPO/config/nemoclaw/policies/sketchscape-backend.yaml.template" > "$POLICY"
timeout 180 nemoclaw "$SANDBOX" policy add --from-file "$POLICY" --trusted-private-host "$HOST" --yes

# --- 4. sandbox config (URL + token) ----------------------------------------
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/sketchscape"
printf '%s\n' "$URL" > "$STAGE/sketchscape/api-url"
(umask 077; printf '%s\n' "$TOKEN" > "$STAGE/sketchscape/nemoclaw-token")
timeout 120 nemoclaw "$SANDBOX" exec -- mkdir -p /sandbox/.config >/dev/null
timeout 120 nemoclaw "$SANDBOX" upload "$STAGE/sketchscape" /sandbox/.config >/dev/null
timeout 120 nemoclaw "$SANDBOX" exec -- chmod -R go-rwx /sandbox/.config/sketchscape >/dev/null
echo "sandbox '$SANDBOX' room tools -> $URL"
