---
name: sketchscape-infrastructure
description: Plan, configure, validate, or operate SketchScape AWS GPU inference, SAM 3.1/Fast-SAM3D workers, NemoClaw, Unity MCP, and Unity scene integration. Use for infrastructure changes, deployment checks, model pipeline work, or scene automation in this repository.
---

# SketchScape infrastructure

Treat the repository documentation and contracts as authoritative. Read `AGENT.md` (hard rules), `docs/BUILD_PLAN.md` (which step this is), `docs/ARCHITECTURE.md`, `docs/DATA_ARCHITECTURE.md`, `docs/INTEGRATION_GUIDE.md`, and `docs/INFRASTRUCTURE_ROADMAP.md` before changing infrastructure. Build Plan steps 13–29 are gated: run `python3 scripts/check_collab_gates.py <step>` first. Published experience blueprints and their referenced project assets are the authoring source of truth; generated Unity scene state is reproducible output.

## Safety boundaries

- Never run `terraform apply`, start an EC2 instance, download model weights, install NemoClaw, or change a Unity scene without explicit user approval.
- Never put AWS, Hugging Face, worker, Unity Cloud, or MCP credentials in source control, scene assets, command arguments, or chat output.
- Preserve `PIPELINE_MODE=mock` as the default and as an offline fallback.
- Keep NemoClaw and Unity MCP in the development control plane. The Unity client must call only the public backend API and must never invoke agent/MCP tools at runtime.
- Keep SAM 3.1 and Fast-SAM3D in separate environments. Within a job, run them sequentially and release segmentation memory before reconstruction. Keep `SKETCHSCAPE_GPU_CONCURRENCY=1` until an approved VRAM benchmark on that instance type (a 16 GiB T4 always stays at 1). The pipeline is verified on an L40S (g6e.xlarge).
- Never apply the DynamoDB GSI/TTL Terraform change (needed by steps 18 and 26) without explicit approval.

## AWS workflow

1. Run `./scripts/aws_preflight.sh` before Terraform planning.
2. Inspect `infra/aws/terraform.tfvars` without printing secrets.
3. Run `terraform fmt -check`, `terraform validate`, and `terraform plan`; explain cost-impacting changes.
4. Require explicit approval before `terraform apply`, instance start, bundle publication, or bootstrap.
5. Verify SSM and `nvidia-smi` before model bootstrap.
6. Stop the GPU immediately after bounded smoke tests.

## Unity and MCP workflow

- The Unity project (`../HackGTUnity`) is separate from this repository and is being cleaned up. Confirm its project root and current contents before changing it.
- For Unity MCP, use Meta's Unity MCP Extension for Horizon (pinned commit), never a generic third-party Unity MCP server. It edits the Editor only; live rooms change through the backend.
- Use `config/unity/sketchscape-scene.profile.json` as desired state; discover actual GameObject names and component IDs through read-only MCP inspection before writes.
- Route authored experiences through project assets, validated blueprint revisions, publication, and the editor-time `SketchScapeOfflineExperienceBuilder`; do not make opaque MCP scene edits the source of truth.
- Treat `SketchScapeExperienceCompiler` as preview-only. Final builds must use saved generated scenes and packaged assets, with no NemoClaw/MCP/authoring-backend runtime dependency.
- For Meta Quest, require Android Build Support, SDK/NDK Tools, OpenJDK, OpenXR validation, and a successful no-device APK build; never claim hardware validation without a headset.
- Make a scene checkpoint/save before mutation, configure one scene at a time, compile, inspect console errors, then run EditMode tests.
- Do not expose a local Unity MCP endpoint publicly. When NemoClaw is used, register only a trusted local/private endpoint and use the sandbox's credential and network-policy mechanisms.

## Validation

Run `./scripts/verify_local.sh` after repository changes. For Terraform changes, also run `terraform fmt -check -recursive` and `terraform validate` from `infra/aws` when Terraform is installed. Report skipped GPU, AWS, NemoClaw, and Unity validation explicitly.
