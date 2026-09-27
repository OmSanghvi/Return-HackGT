#!/usr/bin/env bash
# Deploy the SketchScape OpenClaw skills (with the backend tools they shell
# out to) into a NemoClaw sandbox. Run inside WSL. Idempotent: rerun after a
# sandbox rebuild or whenever backend/scene_tools.py or backend/unity_room.py
# change, or after scripts/sync_s3_assets_to_unity.py refreshes the asset
# catalog.
#
#   bash scripts/nemoclaw-deploy-skills.sh [sandbox] [--force]   # default: sketchscape
#
# The room-build runner calls this before every build. When the sandbox
# already has exactly this content (same hash of every staged file) it stops
# after one quick check instead of reinstalling (~30 s saved per build);
# --force reinstalls anyway.
set -euo pipefail

SANDBOX="${1:-sketchscape}"
FORCE=0
[[ "${2:-}" == "--force" ]] && FORCE=1
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_ROOT="/sandbox/.openclaw/workspace/skills"
MARK="$SKILLS_ROOT/.sketchscape-deploy-hash"
SKILLS=(sketchscape-scene-tools sketchscape-unity-room sketchscape-subject-labeler sketchscape-room-tools)
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# Each skill gets its own copy of the tools, so a skill directory stays
# self-contained. unity_room needs scene_tools; scene_tools needs the schema
# at ../shared relative to backend/.
BACKEND_FILES=(scene_tools.py scene_tools_cli.py unity_room.py unity_room_cli.py web_media.py scene_layout.py blueprint_to_unity.py blueprint_to_unity_cli.py nemoclaw_vision.py room_tools.py room_tools_cli.py)

for skill in "${SKILLS[@]}"; do
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
done

HASH="$(cd "$STAGE" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)"
if [[ $FORCE -eq 0 ]]; then
  DEPLOYED="$(nemoclaw "$SANDBOX" exec -- sh -c "cat '$MARK' 2>/dev/null || true" 2>/dev/null | tr -d '\r' | tail -n 1)"
  if [[ "$DEPLOYED" == "$HASH" ]]; then
    echo "== skills already deployed (content ${HASH:0:12}); nothing to do (--force reinstalls)"
    exit 0
  fi
fi

for skill in "${SKILLS[@]}"; do
  echo "== installing $skill"
  nemoclaw "$SANDBOX" skill install "$STAGE/$skill"
done

# Read-only Openverse / Poly Haven search for the room tools (web_media.py).
# Without it the tools fall back to their curated offline catalog.
if ! timeout 120 nemoclaw "$SANDBOX" policy list 2>/dev/null | grep -q "sketchscape-web-media"; then
  echo "== adding sandbox policy sketchscape-web-media"
  timeout 180 nemoclaw "$SANDBOX" policy add --from-file "$REPO/config/nemoclaw/policies/sketchscape-web-media.yaml" --yes \
    || echo "WARN: could not add the sketchscape-web-media policy; web searches will use the curated fallback"
fi

echo "== ensuring jsonschema in the sandbox"
nemoclaw "$SANDBOX" exec -- sh -c 'python3 -c "import jsonschema" 2>/dev/null || pip install --user --break-system-packages --quiet jsonschema'

echo "== smoke test inside the sandbox"
nemoclaw "$SANDBOX" exec -- python3 "$SKILLS_ROOT/sketchscape-unity-room/backend/unity_room_cli.py" compose_room \
  '{"objects":[{"asset_id":"a1","label":"lamp"},{"asset_id":"a2","label":"chair"}],"room_name":"Deploy_Check","scene_id":"none"}' \
  | head -c 400; echo
nemoclaw "$SANDBOX" exec -- python3 "$SKILLS_ROOT/sketchscape-unity-room/backend/unity_room_cli.py" search_environment \
  '{"kind":"hdri","query":"cozy living room","count":1}' | head -c 400; echo
nemoclaw "$SANDBOX" skill list

# Remember what is deployed, so the next unchanged deploy is a no-op.
nemoclaw "$SANDBOX" exec -- sh -c "printf '%s\n' '$HASH' > '$MARK'"
echo "== deployed skills content ${HASH:0:12}"
