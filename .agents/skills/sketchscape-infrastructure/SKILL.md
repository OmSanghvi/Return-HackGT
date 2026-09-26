---
name: sketchscape-infrastructure
description: Plan, configure, validate, or operate SketchScape AWS GPU inference, SAM 3.1/Fast-SAM3D workers, NemoClaw, Unity MCP, and Unity scene integration. Use for infrastructure changes, deployment checks, model pipeline work, or scene automation in this repository.
---

# SketchScape infrastructure

Treat the repository documentation and contracts as authoritative. Read `docs/ARCHITECTURE.md`, `docs/INTEGRATION_GUIDE.md`, and `docs/INFRASTRUCTURE_ROADMAP.md` before changing infrastructure. Published experience blueprints and their referenced project assets are the authoring source of truth; generated Unity scene state is reproducible output.

## Safety boundaries

- Never run `terraform apply`, start an EC2 instance, download model weights, install NemoClaw, or change a Unity scene without explicit user approval.
- Never put AWS, Hugging Face, worker, Unity Cloud, or MCP credentials in source control, scene assets, command arguments, or chat output.
- Preserve `PIPELINE_MODE=mock` as the default and as an offline fallback.
- Keep NemoClaw and Unity MCP in the development control plane. The Unity client must call only the public backend API and must never invoke agent/MCP tools at runtime.
- Keep SAM 3.1 and Fast-SAM3D in separate environments. On a 16 GiB T4, run them sequentially and release segmentation memory before reconstruction.

## AWS workflow

1. Run `./scripts/aws_preflight.sh` before Terraform planning.
2. Inspect `infra/aws/terraform.tfvars` without printing secrets.
3. Run `terraform fmt -check`, `terraform validate`, and `terraform plan`; explain cost-impacting changes.
4. Require explicit approval before `terraform apply`, instance start, bundle publication, or bootstrap.
5. Verify SSM and `nvidia-smi` before model bootstrap.
6. Stop the GPU immediately after bounded smoke tests.

## Unity and MCP workflow

- The Unity project is separate from this repository. Confirm its project root before changing it.
- Use `config/unity/sketchscape-scene.profile.json` as desired state; discover actual GameObject names and component IDs through read-only MCP inspection before writes.
- Route authored experiences through project assets, validated blueprint revisions, publication, and the editor-time `SketchScapeOfflineExperienceBuilder`; do not make opaque MCP scene edits the source of truth.
- Treat `SketchScapeExperienceCompiler` as preview-only. Final builds must use saved generated scenes and packaged assets, with no NemoClaw/MCP/authoring-backend runtime dependency.
- For Meta Quest, require Android Build Support, SDK/NDK Tools, OpenJDK, OpenXR validation, and a successful no-device APK build; never claim hardware validation without a headset.
- Make a scene checkpoint/save before mutation, configure one scene at a time, compile, inspect console errors, then run EditMode tests.
- Do not expose a local Unity MCP endpoint publicly. When NemoClaw is used, register only a trusted local/private endpoint and use the sandbox's credential and network-policy mechanisms.

## Validation

Run `./scripts/verify_local.sh` after repository changes. For Terraform changes, also run `terraform fmt -check -recursive` and `terraform validate` from `infra/aws` when Terraform is installed. Report skipped GPU, AWS, NemoClaw, and Unity validation explicitly.
