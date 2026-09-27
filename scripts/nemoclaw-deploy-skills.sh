#!/usr/bin/env bash
# Deploy the SketchScape OpenClaw skills (with the backend tools they shell
# out to) into a NemoClaw sandbox. Run inside WSL. Idempotent: rerun after a
# sandbox rebuild or whenever backend/scene_tools.py or backend/unity_room.py
# change, or after scripts/sync_s3_assets_to_unity.py refreshes the asset
# catalog.
#
#   bash scripts/nemoclaw-deploy-skills.sh [sandbox]   # default: sketchscape
set -euo pipefail

SANDBOX="${1:-sketchscape}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="/sandbox/.openclaw/workspace/skills"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Each skill gets its own copy of the tools, so a skill directory stays
# self-contained. unity_room needs scene_tools; scene_tools needs the schema
# at ../shared relative to backend/.
BACKEND_FILES=(scene_tools.py scene_tools_cli.py unity_room.py unity_room_cli.py blueprint_to_unity.py blueprint_to_unity_cli.py nemoclaw_vision.py room_tools.py room_tools_cli.py)

for skill in sketchscape-scene-tools sketchscape-unity-room sketchscape-subject-labeler sketchscape-room-tools; do
  dir="$STAGE/$skill"
  mkdir -p "$dir/backend" "$dir/shared"
  sed "s|{baseDir}|$SKILLS_ROOT/$skill|g" "$REPO/config/nemoclaw/skills/$skill/SKILL.md" > "$dir/SKILL.md"
  for f in "${BACKEND_FILES[@]}"; do cp "$REPO/backend/$f" "$dir/backend/"; done
  cp "$REPO/shared/experience-blueprint.schema.json" "$dir/shared/"
  # Real 3D scans available in Unity (scripts/sync_s3_assets_to_unity.py).
  if [[ -f "$REPO/config/nemoclaw/asset-catalog.json" ]]; then
    mkdir -p "$dir/config/nemoclaw"
    cp "$REPO/config/nemoclaw/asset-catalog.json" "$dir/config/nemoclaw/"
  fi
  echo "== installing $skill"
  nemoclaw "$SANDBOX" skill install "$dir"
done

echo "== ensuring jsonschema in the sandbox"
nemoclaw "$SANDBOX" exec -- sh -c 'python3 -c "import jsonschema" 2>/dev/null || pip install --user --break-system-packages --quiet jsonschema'

echo "== smoke test inside the sandbox"
nemoclaw "$SANDBOX" exec -- python3 "$SKILLS_ROOT/sketchscape-unity-room/backend/unity_room_cli.py" compose_room \
  '{"objects":[{"asset_id":"a1","label":"lamp"},{"asset_id":"a2","label":"chair"}],"room_name":"Deploy_Check"}' \
  | head -3
nemoclaw "$SANDBOX" skill list
