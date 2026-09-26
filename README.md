# SketchScape

SketchScape turns a photographed or drawn object into a small interactive 3D
scene. The hackathon demo is deliberately split into reliable layers:

```text
Unity desktop experience
        |
FastAPI job API (local mock mode or one GPU worker)
        |
SAM 3.1 concept mask -> Fast-SAM3D -> Gaussian-splat PLY
```

The portal and scene-edit interaction work today without a GPU in `mock` mode.
Real reconstruction is an opt-in AWS deployment; it is never started by local
commands in this repository.

## Repository map

| Path | Purpose |
| --- | --- |
| `backend/` | Token-free Unity-facing API, jobs, artifacts, scene state. |
| `worker/` | GPU-only SAM 3.1 + staged Fast-SAM3D worker scripts. |
| `shared/` | JSON scene contract owned by the backend. |
| `infra/aws/` | Terraform and bootstrap scripts. These do nothing until a person runs Terraform. |
| `docs/` | Architecture, build plan, infrastructure roadmap, and demo runbook. |
| `../HackGTUnity/` | The existing Unity 6 project. Its integration scripts are installed there. |
| `*_kaggle_notebook.ipynb` | Prior experiment notebooks; not the live demo path. |

## Safest development loop

```bash
./scripts/start_mock_demo.sh
```

Then open the Unity project at `../HackGTUnity`, press Play, and use the
**Reconstruct sketch** panel. It uploads an image, polls the job, and reveals
the portal using placeholder scene objects. This costs nothing and proves the
full client/API flow.

Read [the integration guide](docs/INTEGRATION_GUIDE.md) and
[infrastructure roadmap](docs/INFRASTRUCTURE_ROADMAP.md) before using AWS,
NemoClaw, or Unity MCP. Provisioning and external installations must be invoked
deliberately and manually.

## Local verification

```bash
./scripts/verify_local.sh
```

This performs source checks and mock API tests only. It has no AWS, Docker, or
GPU commands.
