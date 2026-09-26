#!/usr/bin/env bash
# Local-only validation. This never invokes AWS, Terraform, Docker, or a GPU.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m py_compile \
  "$ROOT/backend/main.py" \
  "$ROOT/backend/storage.py" \
  "$ROOT/backend/artifact_store.py" \
  "$ROOT/backend/subject_labeler.py" \
  "$ROOT/backend/auth.py" \
  "$ROOT/backend/test_api.py" \
  "$ROOT/backend/test_storage.py" \
  "$ROOT/backend/test_subject_labeler.py" \
  "$ROOT/backend/test_auth.py" \
  "$ROOT/scripts/smoke_test_aws_storage.py" \
  "$ROOT/scripts/export_unity_experience.py" \
  "$ROOT/scripts/check_collab_gates.py" \
  "$ROOT/worker/run_job.py" \
  "$ROOT/worker/segment_sam31_local.py"
bash -n \
  "$ROOT/worker/bootstrap_fastsam3d.sh" \
  "$ROOT/worker/bootstrap_sam31_local.sh" \
  "$ROOT/infra/aws/bootstrap_instance.sh" \
  "$ROOT/infra/aws/publish_bundle.sh" \
  "$ROOT/scripts/aws_preflight.sh"
python3 -m json.tool "$ROOT/config/nemoclaw/mcp-servers.example.json" >/dev/null
python3 -m json.tool "$ROOT/config/nemoclaw/sketchscape-tools.json" >/dev/null
python3 -m json.tool "$ROOT/shared/experience-blueprint.schema.json" >/dev/null
python3 -m json.tool "$ROOT/shared/social-manifest.schema.json" >/dev/null
python3 -m json.tool "$ROOT/config/unity/sketchscape-scene.profile.json" >/dev/null
python3 -m json.tool "$ROOT/config/unity/sketchscape-scene.profile.schema.json" >/dev/null
python3 -m json.tool "$ROOT/config/collab-vr/gates.json" >/dev/null
python3 -m json.tool "$ROOT/config/nemoclaw/model-providers.example.json" >/dev/null
# Collaborative VR gate status (read-only, offline). Fails only if a secret
# (Clerk/Meta/xAI key, secret env assignment, VITE_*SECRET*) leaks into the
# repo, app/.env*, or the Unity project.
python3 "$ROOT/scripts/check_collab_gates.py" --status

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  (
    cd "$ROOT/backend"
    .venv/bin/python -m unittest test_api.py test_storage.py test_subject_labeler.py test_auth.py
  )
else
  echo "Python syntax checks passed. Create backend/.venv and install requirements-dev.txt to run API tests."
fi
