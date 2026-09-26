#!/usr/bin/env bash
# Switch the NemoClaw sandbox's inference route to Muse Spark (Meta Model API).
# Run in your own WSL terminal. The key is read silently and never echoed,
# written to disk, or passed on the command line.
set -euo pipefail

SANDBOX="${1:-sketchscape}"
MODEL="${NEMOCLAW_MODEL:-muse-spark-1.3}"

read -rsp "Meta Model API key: " COMPATIBLE_API_KEY; echo
if [ -z "$COMPATIBLE_API_KEY" ]; then
  echo "No key entered; nothing changed." >&2
  exit 1
fi
export COMPATIBLE_API_KEY
trap 'unset COMPATIBLE_API_KEY' EXIT

nemoclaw inference set --provider compatible-endpoint --model "$MODEL" \
  --endpoint-url https://api.meta.ai/v1 --credential-env COMPATIBLE_API_KEY \
  --inference-api openai-completions --sandbox "$SANDBOX"

echo
nemoclaw "$SANDBOX" status
