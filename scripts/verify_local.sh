#!/usr/bin/env bash
# Local-only validation. This never invokes AWS, Terraform, Docker, or a GPU.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m py_compile \
  "$ROOT/backend/main.py" \
  "$ROOT/backend/storage.py" \
  "$ROOT/backend/artifact_store.py" \
  "$ROOT/backend/subject_labeler.py" \
  "$ROOT/backend/scene_tools.py" \
  "$ROOT/backend/blueprint_to_unity.py" \
  "$ROOT/backend/blueprint_to_unity_cli.py" \
  "$ROOT/backend/unity_room.py" \
  "$ROOT/backend/unity_room_cli.py" \
  "$ROOT/backend/auth.py" \
  "$ROOT/backend/upload_pipeline.py" \
  "$ROOT/backend/room_tools.py" \
  "$ROOT/backend/room_tools_cli.py" \
  "$ROOT/backend/tour_author.py" \
  "$ROOT/backend/tour_author_cli.py" \
  "$ROOT/backend/tour_routes.py" \
  "$ROOT/backend/guided_tour.py" \
  "$ROOT/backend/guide.py" \
  "$ROOT/backend/guide_tools.py" \
  "$ROOT/backend/guide_validator.py" \
  "$ROOT/backend/guide_model.py" \
  "$ROOT/backend/guide_tts.py" \
  "$ROOT/backend/test_api.py" \
  "$ROOT/backend/test_storage.py" \
  "$ROOT/backend/test_subject_labeler.py" \
  "$ROOT/backend/test_scene_tools.py" \
  "$ROOT/backend/test_blueprint_to_unity.py" \
  "$ROOT/backend/test_unity_room.py" \
  "$ROOT/backend/test_asset_sync.py" \
  "$ROOT/scripts/sync_s3_assets_to_unity.py" \
  "$ROOT/backend/test_auth.py" \
  "$ROOT/backend/test_jobs.py" \
  "$ROOT/backend/test_gpu_worker.py" \
  "$ROOT/backend/test_room_tools.py" \
  "$ROOT/backend/test_tour_author.py" \
  "$ROOT/backend/test_guided_tour.py" \
  "$ROOT/backend/test_guide.py"   "$ROOT/backend/test_letters.py"   "$ROOT/backend/letters.py"   "$ROOT/backend/letter_routes.py" \
  "$ROOT/scripts/smoke_test_aws_storage.py" \
  "$ROOT/scripts/export_unity_experience.py" \
  "$ROOT/scripts/check_collab_gates.py" \
  "$ROOT/worker/run_job.py" \
  "$ROOT/worker/segment_sam31_local.py" \
  "$ROOT/worker/gpu_dispatcher.py" \
  "$ROOT/worker/benchmark_concurrency.py" \
  "$ROOT/worker/gaussian_ply_safety.py" \
  "$ROOT/worker/run_fastsam3d_staged.py" \
  "$ROOT/worker/worker_server.py" \
  "$ROOT/worker/test_segment_sam31_local.py" \
  "$ROOT/worker/test_gpu_dispatcher.py" \
  "$ROOT/worker/test_gaussian_ply_safety.py"
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
python3 -m json.tool "$ROOT/backend/worker_contract.json" >/dev/null
# Collaborative VR gate status (read-only, offline). Fails only if a secret
# (Clerk/Meta/xAI key, secret env assignment, VITE_*SECRET*) leaks into the
# repo, app/.env*, or the Unity project.
python3 "$ROOT/scripts/check_collab_gates.py" --status

# backend/.venv/bin/python on Linux/macOS, backend/.venv/Scripts/python.exe on Windows.
VENV_PY=""
for candidate in "$ROOT/backend/.venv/bin/python" "$ROOT/backend/.venv/Scripts/python.exe"; do
  if [[ -x "$candidate" ]]; then VENV_PY="$candidate"; break; fi
done

if [[ -n "$VENV_PY" ]]; then
  (
    cd "$ROOT/backend"
    "$VENV_PY" -m unittest test_api.py test_storage.py test_subject_labeler.py test_scene_tools.py test_blueprint_to_unity.py test_unity_room.py test_asset_sync.py test_auth.py test_jobs.py test_gpu_worker.py test_room_tools.py test_tour_author.py test_guided_tour.py test_guide.py test_letters.py
  )
  # worker/segment_sam31_local.py and gpu_dispatcher.py's testable functions
  # only need numpy/Pillow (already in backend/.venv via requirements.txt +
  # a plain `pip install numpy`) -- never torch/ultralytics, which stay
  # lazily imported so these run on any CPU machine (Build Plan step 27).
  (
    cd "$ROOT/worker"
    "$VENV_PY" -m unittest test_segment_sam31_local.py test_gpu_dispatcher.py test_gaussian_ply_safety.py
  )
else
  echo "Python syntax checks passed. Create backend/.venv and install requirements-dev.txt (plus 'pip install numpy' for the worker tests) to run API + worker tests."
fi
