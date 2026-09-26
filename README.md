# SketchScape — Shared Room

Two or more people who care about each other each contribute a meaningful
object: a photo, a Notability sketch, or a handwritten letter. AI (NemoClaw)
works out why those objects belong together, and Unity turns that connection
into one room they can walk through on Meta Quest. It's being built for
Meta's "Bringing People Closer Together with AI" challenge.

```text
Photo  -> SAM 3.1 mask -> Fast-SAM3D -> Gaussian-splat PLY -> project catalog
Contributions (2+) -> connection/compose (NemoClaw) -> versioned blueprint
Published blueprint -> compiled scene -> Unity room on Quest
```

The 3D reconstruction pipeline is the plumbing; the product is the
connection the AI surfaces between everyone's contributions.

## Start here

| Read | For |
| --- | --- |
| [`AGENT.md`](AGENT.md) | Rules every agent and contributor follows, what's built, and the skill for each step |
| [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) | Plain-language status, the pitch, and the demo plan |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | The ordered, step-by-step plan (MVP steps 1–12; gated Collaborative VR track 13–29) |
| [`features.txt`](features.txt) | Features to hit in the demo video |

## Repository map

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI API: projects, assets, jobs, blueprints, publication, safe scene edits. |
| `worker/` | GPU-only SAM 3.1 + staged Fast-SAM3D worker. |
| `shared/` | Blueprint (authoring) and scene (runtime) JSON schemas. |
| `config/` | NemoClaw tool/model/MCP inventories, Unity scene profile, Collaborative VR gates. No credentials. |
| `infra/aws/` | Terraform and bootstrap scripts. They do nothing until a person runs Terraform. |
| `scripts/` | Local verification, gate checks, AWS preflight, Unity export. |
| `docs/` | Status, build plan, architecture, data architecture, known issues. |
| `.claude/skills/` | One Claude Code skill per Build Plan step. |
| `../HackGTUnity/` | The Unity 6 project (outside this repo). It's being cleaned up, so check its current contents rather than trusting older docs. |
| `*_kaggle_notebook.ipynb`, `sam3d_hf_*` | Earlier experiments; not the live path. |

## Run it locally (no GPU, no AWS)

```bash
./scripts/start_mock_demo.sh
```

This starts the backend with `PIPELINE_MODE=mock` at
`http://127.0.0.1:8000` (API docs at `/docs`). Mock mode returns
deterministic results labelled `mock` and never claims a model ran. Point
the Unity project's API base URL there to test the client flow.

Real reconstruction runs on an AWS GPU instance and is never started by
local commands. Starting EC2, running a GPU job, `terraform apply`, or
installing NemoClaw always needs explicit approval (AGENT.md Hard Rule 3).
See [`infra/aws/README.md`](infra/aws/README.md).

## Local verification

```bash
./scripts/verify_local.sh
```

Syntax checks, JSON checks, the Collaborative VR gate status and secret
scan, and (with `backend/.venv` set up) the backend tests. No AWS, Docker,
or GPU commands.
