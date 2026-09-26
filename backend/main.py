"""SketchScape's Unity-facing reconstruction API.

This process deliberately does *not* load CUDA, SAM, or SAM 3D. It owns
uploads, job state, scene JSON, and artifacts. A separate GPU worker receives
one job at a time and writes the result manifest in ``worker_contract.json``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from auth import (
    Identity,
    author_from_identity,
    require_identity,
    require_mock_mode,
    run_startup_checks,
    web_origins,
)
from storage import RevisionConflict, create_store
from artifact_store import create_artifact_store
from subject_labeler import SubjectLabelError, create_subject_labeler


DATA_ROOT = Path(os.environ.get("SKETCHSCAPE_DATA_DIR", "./data")).resolve()
UPLOAD_ROOT = DATA_ROOT / "uploads"
ARTIFACT_ROOT = DATA_ROOT / "artifacts"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
for directory in (UPLOAD_ROOT, ARTIFACT_ROOT):
    directory.mkdir(parents=True, exist_ok=True)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    MASK_REVIEW = "mask_review"
    COMPLETE = "complete"
    FAILED = "failed"


class AssetStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    MASK_REVIEW = "mask_review"
    FAILED = "failed"


class SceneObject(BaseModel):
    id: str
    type: str = Field(description="Semantic label or `gaussian_splat`.")
    position: list[float] = Field(min_length=3, max_length=3)
    rotation: list[float] = Field(default_factory=lambda: [0, 0, 0], min_length=3, max_length=3)
    scale: list[float] = Field(min_length=3, max_length=3)
    asset_url: str | None = None
    source: Literal["placeholder", "sam3d", "sketch_card"] = "placeholder"
    actions: list[Literal["scale_by", "translate_by", "rotate_by"]] = Field(
        default_factory=lambda: ["scale_by", "translate_by", "rotate_by"]
    )


class SceneDocument(BaseModel):
    objects: list[SceneObject]
    instructions: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class SceneResponse(BaseModel):
    status: Literal["complete"] = "complete"
    scene: SceneDocument


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    # Display name for the auto-registered creator contributor (step 17).
    creator_display_name: str = Field(default="Creator", min_length=1, max_length=100)


class ProjectUpdateRequest(BaseModel):
    """Partial update for project fields contributors may set (step 17)."""

    room_prompt: str | None = Field(default=None, max_length=300)


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime
    asset_ids: list[str] = Field(default_factory=list)
    blueprint_revisions: list[int] = Field(default_factory=list)
    published_revision: int | None = None
    contributor_ids: list[str] = Field(default_factory=list)
    contribution_ids: list[str] = Field(default_factory=list)
    min_contributors: int = Field(default=2, ge=2)
    max_contributors: int = Field(default=6, ge=2)
    # Step 17: membership. Empty string only appears on records loaded from
    # pre-step-17 snapshots; get_project() backfills a real code on read.
    invite_code: str = ""
    room_prompt: str | None = Field(default=None, max_length=300)
    created_by: str | None = None


SubjectHintSource = Literal["user", "nemoclaw"]


class ViewStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    MASK_REVIEW = "mask_review"
    FAILED = "failed"


class AssetView(BaseModel):
    """Provenance record for one image/prompt submitted to SAM 3D.

    A catalog asset may be built from multiple views of the same subject.
    Each view tracks its own reconstruction job, mask, and artifact so the
    authoring pipeline can later fuse them or select the best one.
    """

    view_index: int = Field(ge=0, description="0-based insertion order within the asset.")
    image_key: str = Field(description="Storage key of the uploaded source image (relative to UPLOAD_ROOT).")
    subject_hint: str | None = Field(default=None, max_length=100)
    subject_hint_source: SubjectHintSource | None = None
    reconstruction_job_id: str
    status: ViewStatus = ViewStatus.PROCESSING
    artifact_url: str | None = None
    mask_url: str | None = None
    preview_url: str | None = None
    error: str | None = None
    recorded_at: datetime


AssetKind = Literal["reconstruction", "sketch_card"]


class ProjectAsset(BaseModel):
    asset_id: str
    project_id: str
    label: str
    status: AssetStatus
    # `sketch_card` is a Notability page shown as a flat textured card (Build
    # Plan step 7, Path 1): no reconstruction job, ready on upload, and
    # `artifact_url` is the image itself.
    kind: AssetKind = "reconstruction"
    # Legacy single-job convenience field — mirrors views[0].reconstruction_job_id
    # when the asset was created via the single-view path. Multi-view assets set
    # this to the first view's job ID. Always use `views` for provenance.
    # Empty for sketch cards.
    reconstruction_job_id: str
    artifact_url: str | None = None
    mask_url: str | None = None
    preview_url: str | None = None
    bounds: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    suggested_scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    error: str | None = None
    views: list[AssetView] = Field(
        default_factory=list,
        description="Per-view reconstruction provenance. Empty for pre-provenance assets.",
    )


class AddAssetViewRequest(BaseModel):
    """Register a new view (image + optional mask + subject hint) for an existing asset.

    The view queues its own reconstruction job. The asset stays in PROCESSING
    until at least one view reaches READY status.
    """

    subject_hint: str | None = Field(default=None, max_length=100)


class Contributor(BaseModel):
    """One person participating in a Shared Room project.

    A project holds a **list** of contributors — never a fixed pair of
    fields. See docs/ARCHITECTURE.md's "Scaling Shared Room from two
    contributors to N" before assuming there are exactly two.
    """

    contributor_id: str
    project_id: str
    display_name: str = Field(min_length=1, max_length=100)
    joined_at: datetime
    # Bound to the caller's verified identity when they join (Clerk `sub` in
    # clerk mode, or the mock `X-SketchScape-Dev-User` value). None for
    # unbound demo personas created in mock mode after the creator.
    clerk_user_id: str | None = None


class ContributorCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    # Required in clerk mode; optional in mock so existing local/demo flows
    # keep working (Hard Rule 2).
    invite_code: str | None = Field(default=None, max_length=128)


ContributionSourceType = Literal["photo", "sketch", "letter"]


class Contribution(BaseModel):
    """One person's contributed object plus why it matters.

    A project holds a **list** of contributions; `connection/compose` may
    only run once `len(contributions) >= ProjectRecord.min_contributors`.
    """

    contribution_id: str
    project_id: str
    contributor_id: str
    asset_id: str
    source_type: ContributionSourceType
    memory_text: str = Field(default="", max_length=1000)
    created_at: datetime


class ContributionCreateRequest(BaseModel):
    contributor_id: str
    asset_id: str
    source_type: ContributionSourceType
    memory_text: str = Field(default="", max_length=1000)


class PlacementRationale(BaseModel):
    """Why one contributed object was placed where it was, in NemoClaw's layout."""

    object_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    rationale: str = Field(min_length=1, max_length=500)


class ConnectionInsight(BaseModel):
    """NemoClaw's social-reasoning output for a project's contributions.

    Revisioned like `ExperienceBlueprint`, since a new composition pass
    produces a new insight rather than overwriting the previous one. The
    `placement_rationale` list must reference every contribution passed to
    `connection/compose`, not just two.
    """

    project_id: str
    revision: int
    theme: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=2000)
    placement_rationale: list[PlacementRationale] = Field(default_factory=list, max_length=200)
    backend: Literal["mock", "meta", "xai", "nebius"]
    model: str = Field(min_length=1, max_length=120)
    created_at: datetime


class ExperienceSettings(BaseModel):
    mode: Literal["desktop", "ar", "vr", "ar_vr"] = "desktop"
    theme: str = Field(min_length=1, max_length=200)
    units: Literal["meters"] = "meters"


class EnvironmentSettings(BaseModel):
    lighting_preset: str = Field(default="neutral", max_length=80)
    skybox: str | None = Field(default=None, max_length=200)
    floor: bool = True
    ambient_audio: str | None = Field(default=None, max_length=200)


class BlueprintObject(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    position: list[float] = Field(min_length=3, max_length=3)
    rotation: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)
    interactions: list[Literal["highlight", "inspect", "scale", "translate", "rotate", "activate"]] = Field(
        default_factory=list
    )
    # The contribution this object stands for; compile_blueprint turns it into
    # the social manifest. None for unattributed objects (e.g. set dressing).
    contribution_id: str | None = Field(default=None, max_length=80)


class PortalSettings(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    target_project_id: str = Field(min_length=1, max_length=80)
    target_revision: int | None = Field(default=None, ge=1)
    position: list[float] = Field(min_length=3, max_length=3)
    rotation: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    scale: list[float] = Field(default_factory=lambda: [1.0, 1.0, 1.0], min_length=3, max_length=3)


class NavigationSettings(BaseModel):
    vr: Literal["teleport", "smooth", "none"] = "none"
    ar: Literal["surface-placement", "world-anchor", "none"] = "none"


class ExperienceBlueprintInput(BaseModel):
    experience: ExperienceSettings
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    objects: list[BlueprintObject] = Field(min_length=1, max_length=200)
    portals: list[PortalSettings] = Field(default_factory=list, max_length=20)
    navigation: NavigationSettings = Field(default_factory=NavigationSettings)


class ExperienceBlueprint(ExperienceBlueprintInput):
    project_id: str
    revision: int
    created_at: datetime
    # Which published revision this draft was built on, so publish can refuse
    # a stale draft (compare-and-set). None means legacy/manual authoring —
    # that revision keeps today's unconditional publish behavior, including
    # deliberate rollback to an older revision.
    based_on_revision: int | None = None
    # Set from the caller's verified identity in `clerk` mode (step 16);
    # unset for mock-mode/manual authoring, matching that mode's behavior
    # before step 16 (Hard Rule 2).
    author: str | None = None


class PublicationRecord(BaseModel):
    """An immutable record of one blueprint publication.

    Publication history is append-only. Each publish appends a record so the
    log always shows which revision was live at a given time; earlier records
    are never rewritten.
    """

    project_id: str
    revision: int
    published_at: datetime
    # Set from the caller's verified identity in `clerk` mode (step 16);
    # unset for mock-mode/manual publishing, matching create_blueprint above.
    author: str | None = None


class ReconstructionResponse(BaseModel):
    job_id: str
    status: JobStatus
    poll_url: str
    scene_url: str = "/v1/scene"


class ReconstructionJob(ReconstructionResponse):
    created_at: datetime
    updated_at: datetime
    original_filename: str
    subject_hint: str | None = None
    # "nemoclaw" when identify_subject supplied the SAM 3.1 prompt.
    subject_hint_source: SubjectHintSource | None = None
    subject_label_backend: str | None = None
    project_id: str | None = None
    asset_id: str | None = None
    mask_url: str | None = None
    artifact_url: str | None = None
    error: str | None = None
    scene: SceneDocument | None = None


class SceneModificationRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=160)


class SceneActionRequest(BaseModel):
    """A bounded action shared by Unity runtime and authoring/MCP tools."""

    target_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    action: Literal["scale_by", "translate_by", "rotate_by"]
    value: list[float] = Field(min_length=3, max_length=3)
    # Set by a session tied to one contributor; it may then edit only objects
    # the social manifest attributes to them. Empty/None keeps the authoring
    # (MCP/editor) behavior. Self-asserted until the room API (step 21)
    # replaces it with room tokens.
    contributor_id: str | None = Field(default=None, max_length=80)


class InteractiveObject(BaseModel):
    id: str
    name: str
    type: str
    actions: list[Literal["scale_by", "translate_by", "rotate_by"]]


class InteractiveRegistryResponse(BaseModel):
    interactives: list[InteractiveObject]


class WorkerResult(BaseModel):
    """Metadata sent by the private GPU worker after an inference attempt."""

    status: Literal["complete", "mask_review", "failed"]
    object_label: str = Field(default="gaussian_splat", max_length=80)
    error: str | None = Field(default=None, max_length=500)


def placeholder_scene(uploaded_filename: str = "sketch.png") -> SceneDocument:
    return SceneDocument(
        objects=[
            SceneObject(id="tree_1", type="tree", position=[-2.1, 0, 7], scale=[1, 1, 1]),
            SceneObject(id="house_1", type="house", position=[2.1, 0, 7.7], scale=[1.4, 1.4, 1.4]),
        ],
        meta={"source": "upload", "mode": "placeholder", "uploaded_filename": uploaded_filename},
    )


current_scene = placeholder_scene()
# Reconstruction jobs remain process-local by design: a live inference cannot
# survive an API restart, so persisting job state would be misleading. See
# docs/INFRASTRUCTURE_ROADMAP.md for the S3/SQS durability slice.
jobs: dict[str, ReconstructionJob] = {}
job_inputs: dict[str, tuple[Path, Path | None]] = {}
# Projects, catalog assets, blueprint revisions, and publication records are
# durably persisted so authoring state survives an API restart. The backend is
# selected by SKETCHSCAPE_STORAGE_BACKEND: the default single-process JSON store
# for local/demo use, or DynamoDB for concurrency-safe cloud durability. Both
# implement the same surface, so route handlers below are backend-agnostic.
store = create_store(local_state_path=DATA_ROOT / "authoring-state.json")
# Artifact store: PLY, mask, and preview files written by the GPU worker.
# Defaults to the local filesystem; set SKETCHSCAPE_ARTIFACTS_BACKEND=s3 and
# SKETCHSCAPE_ARTIFACTS_BUCKET=<name> to redirect writes to the provisioned S3
# bucket (terraform output -raw artifacts_bucket).
artifact_store = create_artifact_store(local_artifact_root=ARTIFACT_ROOT)
# NemoClaw identify_subject: labels the object in an upload when the
# contributor typed no subject_hint (Build Plan step 4a).
# SKETCHSCAPE_SUBJECT_LABELER=mock (default offline) | nemoclaw
subject_labeler = create_subject_labeler()
# The first AWS deployment is deliberately one GPU and one reconstruction at a
# time. A queue/DynamoDB design is appropriate for production, but allowing
# concurrent 3D reconstructions on a 16 GB GPU would make both jobs fail.
local_worker_lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 - required by FastAPI's lifespan signature
    # Fail fast: refuse to start under an unsafe or self-contradictory
    # SKETCHSCAPE_AUTH_MODE configuration, rather than serving traffic and
    # discovering the problem later. See auth.run_startup_checks.
    run_startup_checks()
    yield


app = FastAPI(title="SketchScape Reconstruction API", version="0.2.0", lifespan=lifespan)

# In `clerk` mode, only the configured web origin(s) may call this API, and
# bearer tokens (not cookies) carry auth, so credentialed CORS isn't needed.
# `mock` mode keeps today's SKETCHSCAPE_ALLOWED_ORIGINS behavior unchanged
# (default "*") -- no behavior change for local/offline use (Hard Rule 2).
if os.environ.get("SKETCHSCAPE_AUTH_MODE", "mock").strip().lower() == "clerk":
    _cors_origins = web_origins()
    _cors_headers = ["Authorization", "Content-Type"]
else:
    _cors_origins = os.environ.get("SKETCHSCAPE_ALLOWED_ORIGINS", "*").split(",")
    _cors_headers = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=_cors_headers,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def save_upload(upload: UploadFile, destination: Path, *, limit: int = MAX_UPLOAD_BYTES) -> None:
    """Store a bounded upload without trusting the client filename."""
    size = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than the {limit // 1024 // 1024} MB limit.")
            output.write(chunk)
    if not size:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded image is empty.")


def image_extension(upload: UploadFile) -> str:
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    try:
        return allowed[upload.content_type or ""]
    except KeyError as error:
        raise HTTPException(415, "Use a PNG, JPEG, or WebP image.") from error


def job_url(job_id: str) -> str:
    return f"/v1/reconstructions/{job_id}"


def _auth_mode() -> str:
    return os.environ.get("SKETCHSCAPE_AUTH_MODE", "mock").strip().lower()


def new_invite_code() -> str:
    """URL-safe invite code with at least 16 characters (step 17)."""
    return secrets.token_urlsafe(16)


def get_project(project_id: str) -> ProjectRecord:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(404, "Unknown project.")
    # Pre-step-17 snapshots have an empty invite_code; backfill once on read
    # so membership joins always have something to check against.
    if not project.invite_code:
        project.invite_code = new_invite_code()
        project.updated_at = utc_now()
        store.save_project(project)
    return project


def find_contributor_by_clerk_user(project_id: str, clerk_user_id: str) -> Contributor | None:
    for contributor in store.list_contributors(project_id):
        if contributor.clerk_user_id == clerk_user_id:
            return contributor
    return None


def is_project_member(project_id: str, identity: Identity) -> bool:
    if identity.kind == "service":
        return False
    return find_contributor_by_clerk_user(project_id, identity.user_id) is not None


def visible_project(project: ProjectRecord, identity: Identity) -> ProjectRecord:
    """Return a project view; only members see the invite code."""
    if is_project_member(project.project_id, identity):
        return project
    # Service callers (and anyone else allowed to read) get the project
    # without the invite code.
    return project.model_copy(update={"invite_code": ""})


def enforce_project_access(
    project_id: str,
    identity: Identity,
    *,
    capability: Literal["read", "write", "draft"],
) -> None:
    """Membership gate for project-scoped routes (step 17).

    In ``mock`` mode this is a no-op so local/demo flows and existing tests
    keep working (Hard Rule 2). In ``clerk`` mode:

    - ``read`` / ``draft``: a project member, or a service (NemoClaw).
    - ``write``: a project member only (never a service) — uploads,
      contributions, invite rotation, room_prompt, publish.
    """
    if _auth_mode() != "clerk":
        return
    get_project(project_id)  # 404 if unknown
    if identity.kind == "service":
        if capability == "write":
            raise HTTPException(
                403,
                "Service identities may read and draft, but cannot upload, "
                "publish, or change membership.",
            )
        return
    if not is_project_member(project_id, identity):
        raise HTTPException(403, "Not a member of this project.")


def require_project_read(
    project_id: str, identity: Identity = Depends(require_identity)
) -> Identity:
    enforce_project_access(project_id, identity, capability="read")
    return identity


def require_project_write(
    project_id: str, identity: Identity = Depends(require_identity)
) -> Identity:
    enforce_project_access(project_id, identity, capability="write")
    return identity


def require_project_draft(
    project_id: str, identity: Identity = Depends(require_identity)
) -> Identity:
    enforce_project_access(project_id, identity, capability="draft")
    return identity


def owned_object_ids(project_id: str, clerk_user_id: str, blueprint: ExperienceBlueprint) -> set[str]:
    """Object ids in ``blueprint`` this person contributed (derived, not stored).

    Ownership is ``object.asset_id`` ∈ the caller's contribution asset ids.
    Objects with no matching contribution (e.g. NemoClaw environment set-
    dressing) are not owned by anyone and can't be edited from a headset.
    """
    contributor = find_contributor_by_clerk_user(project_id, clerk_user_id)
    if contributor is None:
        return set()
    owned_assets = {
        item.asset_id
        for item in store.list_contributions(project_id)
        if item.contributor_id == contributor.contributor_id
    }
    return {obj.id for obj in blueprint.objects if obj.asset_id in owned_assets}


def register_creator_contributor(
    project: ProjectRecord, identity: Identity, display_name: str
) -> Contributor:
    """Bind the project creator as the first contributor (step 17)."""
    contributor = Contributor(
        contributor_id=uuid.uuid4().hex,
        project_id=project.project_id,
        display_name=display_name.strip() or "Creator",
        joined_at=utc_now(),
        clerk_user_id=identity.user_id,
    )
    store.append_contributor(contributor)
    project.contributor_ids.append(contributor.contributor_id)
    project.updated_at = utc_now()
    store.save_project(project)
    return contributor


def invite_codes_match(provided: str | None, expected: str) -> bool:
    if provided is None or not expected:
        return False
    # secrets.compare_digest requires equal-length strings.
    if len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def sync_project_asset(job: ReconstructionJob) -> None:
    if not job.asset_id:
        return
    asset = store.get_asset(job.asset_id)
    if asset is None:
        return

    # Sync the matching AssetView first so per-view provenance is always current.
    view = next((v for v in asset.views if v.reconstruction_job_id == job.job_id), None)
    if view is not None:
        view.artifact_url = job.artifact_url
        view.mask_url = job.mask_url
        view.error = job.error
        if job.status == JobStatus.COMPLETE:
            view.status = ViewStatus.READY
        elif job.status == JobStatus.MASK_REVIEW:
            view.status = ViewStatus.MASK_REVIEW
        elif job.status == JobStatus.FAILED:
            view.status = ViewStatus.FAILED
        else:
            view.status = ViewStatus.PROCESSING

    # Promote top-level asset fields from the best available view.
    # READY if any view succeeded; MASK_REVIEW if any view needs it (no success
    # yet); FAILED if all views failed; PROCESSING otherwise.
    if asset.views:
        statuses = {v.status for v in asset.views}
        if ViewStatus.READY in statuses:
            asset.status = AssetStatus.READY
            # Promote top-level artifact/mask from the first READY view so the
            # legacy scene compiler always has a usable artifact_url.
            first_ready = next(v for v in asset.views if v.status == ViewStatus.READY)
            asset.artifact_url = first_ready.artifact_url
            asset.mask_url = first_ready.mask_url
            asset.error = None
        elif ViewStatus.MASK_REVIEW in statuses:
            asset.status = AssetStatus.MASK_REVIEW
        elif all(v.status == ViewStatus.FAILED for v in asset.views):
            asset.status = AssetStatus.FAILED
            asset.error = asset.views[-1].error
        # else: still PROCESSING
    else:
        # Pre-provenance asset (no views) — legacy single-job sync.
        asset.artifact_url = job.artifact_url
        asset.mask_url = job.mask_url
        asset.error = job.error
        if job.status == JobStatus.COMPLETE:
            asset.status = AssetStatus.READY
        elif job.status == JobStatus.MASK_REVIEW:
            asset.status = AssetStatus.MASK_REVIEW
        elif job.status == JobStatus.FAILED:
            asset.status = AssetStatus.FAILED
        else:
            asset.status = AssetStatus.PROCESSING

    store.save_asset(asset)
    project = store.get_project(asset.project_id)
    if project is not None:
        project.updated_at = utc_now()
        store.save_project(project)


# Distinct, colorblind-friendly attribution tints, assigned in join order.
ATTRIBUTION_COLORS = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#999999"]


def compile_social_manifest(blueprint: ExperienceBlueprint) -> dict[str, Any]:
    """Sidecar manifest (shared/social-manifest.schema.json): who each object belongs to."""
    project = get_project(blueprint.project_id)
    contributions = {item.contribution_id: item for item in store.list_contributions(project.project_id)}
    contributors = {item.contributor_id: item for item in store.list_contributors(project.project_id)}
    entries = []
    for item in blueprint.objects:
        contribution = contributions.get(item.contribution_id or "")
        if contribution is None:
            continue
        contributor = contributors.get(contribution.contributor_id)
        order = (
            project.contributor_ids.index(contribution.contributor_id)
            if contribution.contributor_id in project.contributor_ids
            else len(project.contributor_ids)
        )
        entries.append(
            {
                "object_id": item.id,
                "contribution_id": contribution.contribution_id,
                "contributor_id": contribution.contributor_id,
                "contributor_display_name": contributor.display_name if contributor else "",
                "source_type": contribution.source_type,
                "attribution_color": ATTRIBUTION_COLORS[order % len(ATTRIBUTION_COLORS)],
                # Filled by stage_immersive_reveal (step 6).
                "staging_cue_id": None,
            }
        )
    return {"version": 1, "objects": entries}


def compile_blueprint(blueprint: ExperienceBlueprint) -> SceneDocument:
    scene_objects: list[SceneObject] = []
    for item in blueprint.objects:
        asset = store.get_asset(item.asset_id)
        if asset is None:
            raise HTTPException(422, f"Blueprint references unknown asset: {item.asset_id}")
        scene_objects.append(
            SceneObject(
                id=item.id,
                type=asset.label,
                position=item.position.copy(),
                rotation=item.rotation.copy(),
                scale=item.scale.copy(),
                asset_url=asset.artifact_url,
                source=(
                    "sketch_card"
                    if asset.kind == "sketch_card"
                    else "sam3d" if asset.artifact_url else "placeholder"
                ),
                actions=[
                    action
                    for action in ("scale_by", "translate_by", "rotate_by")
                    if action.removesuffix("_by") in item.interactions
                ],
            )
        )
    return SceneDocument(
        objects=scene_objects,
        instructions=[],
        meta={
            "pipeline": "experience-blueprint",
            "project_id": blueprint.project_id,
            "revision": blueprint.revision,
            "experience": blueprint.experience.model_dump(),
            "environment": blueprint.environment.model_dump(),
            "navigation": blueprint.navigation.model_dump(),
            "portals": [portal.model_dump() for portal in blueprint.portals],
            "social": compile_social_manifest(blueprint),
        },
    )


def worker_is_authorized(worker_token: str | None) -> bool:
    """Reject public clients from marking a job complete.

    In local development no worker token is necessary. Production must set
    SKETCHSCAPE_WORKER_TOKEN in the backend and GPU-worker environments.
    """
    expected = os.environ.get("SKETCHSCAPE_WORKER_TOKEN")
    return not expected or (worker_token is not None and secrets.compare_digest(worker_token, expected))


async def resolve_subject_hint(
    subject_hint: str | None, image_path: Path, original_filename: str, has_mask: bool
) -> tuple[str | None, SubjectHintSource | None, str | None]:
    """Return (hint, source, label backend); a typed hint always wins.

    NemoClaw labels only when SAM 3.1 will need a prompt: no typed hint and no
    uploaded mask. No label leaves the worker's mask_review path unchanged.
    """
    if subject_hint and subject_hint.strip():
        return subject_hint.strip(), "user", None
    if has_mask:
        return None, None, None
    try:
        label = await asyncio.to_thread(
            subject_labeler.identify_subject, image_path, original_filename
        )
    except SubjectLabelError as exc:
        print(f"identify_subject unavailable: {exc}", file=sys.stderr)
        return None, None, None
    if label is None:
        return None, None, None
    return label.label, "nemoclaw", label.backend


async def run_mock_job(job_id: str) -> None:
    """Demo-safe fallback; it never pretends to have run SAM 3D."""
    global current_scene
    job = jobs[job_id]
    job.status = JobStatus.RUNNING
    job.updated_at = utc_now()
    await asyncio.sleep(0.15)
    image_path, mask_path = job_inputs[job_id]
    job.scene = placeholder_scene(job.original_filename)
    job.scene.meta.update(
        {
            "pipeline": "mock",
            "mask_provided": mask_path is not None,
            "next_real_worker": "automatic mask -> SAM 3D Objects -> Gaussian-splat PLY",
        }
    )
    current_scene = job.scene
    job.status = JobStatus.COMPLETE
    job.updated_at = utc_now()
    sync_project_asset(job)
    await artifact_store.copy_local(
        job_id, f"input{image_path.suffix}", image_path
    )


async def run_local_gpu_job(job_id: str) -> None:
    """Submit a job to the persistent worker server on loopback.

    The worker server (worker/worker_server.py) keeps all models loaded in
    memory between jobs, eliminating the 2–3 minute cold-start penalty from
    loading large checkpoints on every request.  It must be running before
    the first job is submitted; it starts automatically via the
    sketchscape-worker systemd service.
    """
    async with local_worker_lock:
        job = jobs.get(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return
        job.updated_at = utc_now()

        worker_port = int(os.environ.get("SKETCHSCAPE_WORKER_SERVER_PORT", "8001"))
        worker_url = f"http://127.0.0.1:{worker_port}/worker/jobs"
        startup_timeout = float(os.environ.get("SKETCHSCAPE_WORKER_STARTUP_TIMEOUT", "600"))
        deadline = asyncio.get_running_loop().time() + startup_timeout
        payload = json.dumps({
            "job_id": job_id,
            "subject_hint": job.subject_hint or "",
        }).encode()

        def submit() -> None:
            import urllib.request

            request = urllib.request.Request(
                worker_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()

        while True:
            try:
                await asyncio.to_thread(submit)
                # The worker callback becomes authoritative from this point.
                job.status = JobStatus.RUNNING
                job.updated_at = utc_now()
                return
            except Exception as error:
                from urllib.error import HTTPError

                if isinstance(error, HTTPError) and error.code == 503:
                    if asyncio.get_running_loop().time() < deadline:
                        job.updated_at = utc_now()
                        await asyncio.sleep(5)
                        continue
                    detail = "Persistent GPU worker did not finish loading before the startup timeout."
                elif isinstance(error, HTTPError) and error.code == 429:
                    detail = "Persistent GPU worker queue is full; retry after the active job completes."
                else:
                    detail = f"Could not reach persistent GPU worker: {error}"
                job.status = JobStatus.FAILED
                job.error = detail[:500]
                job.updated_at = utc_now()
                sync_project_asset(job)
                return


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "pipeline_mode": os.environ.get("PIPELINE_MODE", "mock")}


@app.post("/v1/projects", response_model=ProjectRecord, status_code=201)
async def create_project(
    request: ProjectCreateRequest, identity: Identity = Depends(require_identity)
) -> ProjectRecord:
    now = utc_now()
    project_id = uuid.uuid4().hex
    project = ProjectRecord(
        project_id=project_id,
        name=request.name.strip(),
        description=request.description.strip(),
        created_at=now,
        updated_at=now,
        min_contributors=int(os.environ.get("SKETCHSCAPE_MIN_CONTRIBUTORS", "2")),
        max_contributors=int(os.environ.get("SKETCHSCAPE_MAX_CONTRIBUTORS", "6")),
        invite_code=new_invite_code(),
        created_by=identity.user_id,
    )
    store.save_project(project)
    # Creator is the first member; invite_code is only visible to members.
    register_creator_contributor(project, identity, request.creator_display_name)
    return visible_project(project, identity)


@app.get("/v1/projects/{project_id}", response_model=ProjectRecord)
async def read_project(
    project_id: str, identity: Identity = Depends(require_project_read)
) -> ProjectRecord:
    return visible_project(get_project(project_id), identity)


@app.patch("/v1/projects/{project_id}", response_model=ProjectRecord)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    identity: Identity = Depends(require_project_write),
) -> ProjectRecord:
    project = get_project(project_id)
    if request.room_prompt is not None:
        cleaned = request.room_prompt.strip()
        project.room_prompt = cleaned or None
        project.updated_at = utc_now()
        store.save_project(project)
    return visible_project(project, identity)


@app.post("/v1/projects/{project_id}/invite/rotate", response_model=ProjectRecord)
async def rotate_project_invite(
    project_id: str, identity: Identity = Depends(require_project_write)
) -> ProjectRecord:
    project = get_project(project_id)
    project.invite_code = new_invite_code()
    project.updated_at = utc_now()
    store.save_project(project)
    return visible_project(project, identity)


@app.get(
    "/v1/projects/{project_id}/assets",
    response_model=list[ProjectAsset],
    dependencies=[Depends(require_project_read)],
)
async def list_project_assets(project_id: str) -> list[ProjectAsset]:
    project = get_project(project_id)
    return [store.get_asset(asset_id) for asset_id in project.asset_ids if store.get_asset(asset_id)]


@app.post(
    "/v1/projects/{project_id}/contributors",
    response_model=Contributor,
    status_code=201,
)
async def create_contributor(
    project_id: str,
    request: ContributorCreateRequest,
    identity: Identity = Depends(require_identity),
) -> Contributor:
    project = get_project(project_id)
    if identity.kind == "service":
        raise HTTPException(403, "Service identities cannot register as contributors.")
    if len(project.contributor_ids) >= project.max_contributors:
        raise HTTPException(409, "This project already has the maximum number of contributors.")

    mode = _auth_mode()
    existing = find_contributor_by_clerk_user(project_id, identity.user_id)
    if mode == "clerk":
        if not invite_codes_match(request.invite_code, project.invite_code):
            raise HTTPException(403, "Invalid invite code.")
        if existing is not None:
            raise HTTPException(409, "Already a contributor of this project.")
        clerk_user_id: str | None = identity.user_id
    else:
        # Mock: invite optional (must match when provided). The creator is
        # already bound to the default dev user; further demo personas join
        # unbound so local multi-contributor flows keep working.
        if request.invite_code is not None and not invite_codes_match(
            request.invite_code, project.invite_code
        ):
            raise HTTPException(403, "Invalid invite code.")
        clerk_user_id = None if existing is not None else identity.user_id

    contributor = Contributor(
        contributor_id=uuid.uuid4().hex,
        project_id=project.project_id,
        display_name=request.display_name.strip(),
        joined_at=utc_now(),
        clerk_user_id=clerk_user_id,
    )
    store.append_contributor(contributor)
    project.contributor_ids.append(contributor.contributor_id)
    project.updated_at = utc_now()
    store.save_project(project)
    return contributor


@app.get(
    "/v1/projects/{project_id}/contributors",
    response_model=list[Contributor],
    dependencies=[Depends(require_project_read)],
)
async def list_contributors(project_id: str) -> list[Contributor]:
    get_project(project_id)
    return store.list_contributors(project_id)


def validate_contribution_request(project: ProjectRecord, request: ContributionCreateRequest) -> None:
    if request.contributor_id not in project.contributor_ids:
        raise HTTPException(422, f"Unknown contributor for this project: {request.contributor_id}")
    if request.asset_id not in project.asset_ids:
        raise HTTPException(422, f"Blueprint references unknown project assets: {request.asset_id}")
    asset = store.get_asset(request.asset_id)
    if asset is None or asset.status != AssetStatus.READY:
        raise HTTPException(409, f"Blueprint assets are not ready: {request.asset_id}")


@app.post(
    "/v1/projects/{project_id}/contributions",
    response_model=Contribution,
    status_code=201,
    dependencies=[Depends(require_project_write)],
)
async def create_contribution(project_id: str, request: ContributionCreateRequest) -> Contribution:
    project = get_project(project_id)
    validate_contribution_request(project, request)
    contribution = Contribution(
        contribution_id=uuid.uuid4().hex,
        project_id=project.project_id,
        contributor_id=request.contributor_id,
        asset_id=request.asset_id,
        source_type=request.source_type,
        memory_text=request.memory_text.strip(),
        created_at=utc_now(),
    )
    store.append_contribution(contribution)
    project.contribution_ids.append(contribution.contribution_id)
    project.updated_at = utc_now()
    store.save_project(project)
    return contribution


@app.get(
    "/v1/projects/{project_id}/contributions",
    response_model=list[Contribution],
    dependencies=[Depends(require_project_read)],
)
async def list_contributions(project_id: str) -> list[Contribution]:
    get_project(project_id)
    return store.list_contributions(project_id)


@app.post(
    "/v1/reconstructions",
    response_model=ReconstructionResponse,
    status_code=202,
)
async def create_reconstruction(
    background_tasks: BackgroundTasks,
    image: Annotated[UploadFile, File(description="Photo with one prominent object")],
    mask: Annotated[UploadFile | None, File(description="Optional aligned white-on-black mask")] = None,
    subject_hint: Annotated[str | None, Form(max_length=100)] = None,
    project_id: Annotated[str | None, Form(max_length=80)] = None,
    identity: Identity = Depends(require_identity),
) -> ReconstructionResponse:
    """Queue a reconstruction and optionally register it in a project catalog."""
    if project_id:
        enforce_project_access(project_id, identity, capability="write")
    project = get_project(project_id) if project_id else None
    job_id = uuid.uuid4().hex
    image_path = UPLOAD_ROOT / f"{job_id}-image{image_extension(image)}"
    await save_upload(image, image_path)
    mask_path: Path | None = None
    if mask is not None:
        mask_path = UPLOAD_ROOT / f"{job_id}-mask{image_extension(mask)}"
        await save_upload(mask, mask_path)
    subject_hint, hint_source, label_backend = await resolve_subject_hint(
        subject_hint, image_path, image.filename or "", mask_path is not None
    )
    now = utc_now()
    job = ReconstructionJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=job_url(job_id),
        created_at=now,
        updated_at=now,
        original_filename=image.filename or "image",
        subject_hint=subject_hint,
        subject_hint_source=hint_source,
        subject_label_backend=label_backend,
        project_id=project_id,
    )
    if project is not None:
        asset_id = uuid.uuid4().hex
        job.asset_id = asset_id
        label = (subject_hint or Path(image.filename or "object").stem or "object")[:80]
        first_view = AssetView(
            view_index=0,
            image_key=image_path.name,
            subject_hint=subject_hint,
            subject_hint_source=hint_source,
            reconstruction_job_id=job_id,
            recorded_at=now,
        )
        store.save_asset(
            ProjectAsset(
                asset_id=asset_id,
                project_id=project.project_id,
                label=label,
                status=AssetStatus.PROCESSING,
                reconstruction_job_id=job_id,
                views=[first_view],
            )
        )
        project.asset_ids.append(asset_id)
        project.updated_at = now
        store.save_project(project)
    jobs[job_id] = job
    job_inputs[job_id] = (image_path, mask_path)
    pipeline_mode = os.environ.get("PIPELINE_MODE", "mock")
    if pipeline_mode == "aws-local":
        # A text prompt is needed only when no mask was uploaded. The local
        # SAM 3.1 worker rejects an empty prompt as mask_review, never guesses.
        background_tasks.add_task(run_local_gpu_job, job_id)
    elif pipeline_mode != "mock":
        job.status = JobStatus.FAILED
        job.error = "No GPU-worker adapter is configured. Use PIPELINE_MODE=mock or aws-local."
        job.updated_at = utc_now()
    else:
        background_tasks.add_task(run_mock_job, job_id)
    return ReconstructionResponse(
        job_id=job.job_id, status=job.status, poll_url=job.poll_url, scene_url=job.scene_url
    )


@app.post(
    "/v1/projects/{project_id}/assets",
    response_model=ProjectAsset,
    status_code=202,
)
async def create_project_asset(
    project_id: str,
    background_tasks: BackgroundTasks,
    image: Annotated[UploadFile, File(description="Photo with one prominent object")],
    mask: Annotated[UploadFile | None, File(description="Optional aligned white-on-black mask")] = None,
    subject_hint: Annotated[str | None, Form(max_length=100)] = None,
    identity: Identity = Depends(require_project_write),
) -> ProjectAsset:
    response = await create_reconstruction(
        background_tasks=background_tasks,
        image=image,
        mask=mask,
        subject_hint=subject_hint,
        project_id=project_id,
        identity=identity,
    )
    job = jobs[response.job_id]
    asset = store.get_asset(job.asset_id or "")
    if asset is None:
        raise HTTPException(500, "Asset was not registered for this reconstruction.")
    return asset


@app.get(
    "/v1/reconstructions/{job_id}",
    response_model=ReconstructionJob,
    dependencies=[Depends(require_identity)],
)
async def get_reconstruction(job_id: str) -> ReconstructionJob:
    try:
        return jobs[job_id]
    except KeyError as error:
        raise HTTPException(404, "Unknown reconstruction job.") from error


@app.get("/v1/internal/reconstructions/{job_id}/input/{kind}")
async def get_worker_input(
    job_id: str,
    kind: Literal["image", "mask"],
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> FileResponse:
    """Private pull endpoint used by a Camber job; never call this from Unity."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    try:
        image_path, mask_path = job_inputs[job_id]
    except KeyError as error:
        raise HTTPException(404, "Unknown reconstruction job.") from error
    file_path = image_path if kind == "image" else mask_path
    if file_path is None or not file_path.is_file():
        raise HTTPException(404, f"This job has no {kind} input.")
    return FileResponse(file_path, filename=file_path.name)


@app.get("/v1/internal/reconstructions/{job_id}/task")
async def get_worker_task(
    job_id: str,
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> dict[str, str | None]:
    """Return the worker-only text concept for local SAM 3.1 segmentation."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown reconstruction job.")
    return {"job_id": job_id, "subject_hint": job.subject_hint}


@app.post("/v1/internal/reconstructions/{job_id}/result", response_model=ReconstructionJob)
async def receive_worker_result(
    job_id: str,
    result: Annotated[str, Form(description="JSON WorkerResult payload")],
    worker_token: Annotated[str | None, Form()] = None,
    ply: UploadFile | None = File(default=None, description="SAM 3D Gaussian-splat PLY"),
    mask: UploadFile | None = File(default=None, description="Aligned binary object mask"),
    preview: UploadFile | None = File(default=None, description="Mask-preview PNG"),
) -> ReconstructionJob:
    """Private callback for the GPU worker; it is not a Unity endpoint."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown reconstruction job.")
    try:
        payload = WorkerResult.model_validate_json(result)
    except ValueError as error:
        raise HTTPException(422, "`result` must be valid WorkerResult JSON.") from error

    artifact_dir = ARTIFACT_ROOT / job_id
    artifact_dir.mkdir(exist_ok=True)
    if payload.status == "complete":
        if ply is None or mask is None:
            raise HTTPException(422, "A completed SAM 3D job must include both `ply` and `mask`.")
        if not (ply.filename or "").lower().endswith(".ply"):
            raise HTTPException(422, "The reconstruction must be a .ply file.")
        ply_name, mask_name = "reconstruction.ply", "mask.png"
        job.artifact_url = await artifact_store.put(
            job_id, ply_name, ply, size_limit=MAX_ARTIFACT_BYTES
        )
        job.mask_url = await artifact_store.put(
            job_id, mask_name, mask, size_limit=MAX_UPLOAD_BYTES
        )
        if preview is not None:
            await artifact_store.put(
                job_id, "mask-preview.png", preview, size_limit=MAX_UPLOAD_BYTES
            )
        job.scene = SceneDocument(
            objects=[
                SceneObject(
                    id="reconstruction_1",
                    type=payload.object_label,
                    position=[0, 0, 6],
                    scale=[1, 1, 1],
                    asset_url=job.artifact_url,
                    source="sam3d",
                )
            ],
            meta={"pipeline": "sam3d", "job_id": job_id, "format": "gaussian-splat-ply"},
        )
        global current_scene
        current_scene = job.scene
        job.status = JobStatus.COMPLETE
    elif payload.status == "mask_review":
        job.status = JobStatus.MASK_REVIEW
    else:
        job.status = JobStatus.FAILED
        job.error = payload.error or "GPU worker reported a failure."
    job.updated_at = utc_now()
    sync_project_asset(job)
    return job


@app.get("/v1/scene", response_model=SceneResponse, dependencies=[Depends(require_mock_mode)])
@app.get(
    "/scene",
    response_model=SceneResponse,
    include_in_schema=False,
    dependencies=[Depends(require_mock_mode)],
)
async def get_scene() -> SceneResponse:
    # /v1/scene and /scene both read the same process-global demo scene, not
    # a project's published blueprint (see /v1/projects/{id}/compiled-scene
    # for that) -- a legacy, unauthenticated demo surface, so it stays
    # mock-mode-only rather than joining the authenticated /v1/projects/**
    # group. See require_mock_mode in auth.py.
    return SceneResponse(scene=current_scene)


@app.get(
    "/v1/artifacts/{job_id}/{filename}",
    dependencies=[Depends(require_identity)],
)
async def get_artifact(job_id: str, filename: str) -> Response:
    if not jobs.get(job_id) or Path(filename).name != filename:
        raise HTTPException(404, "Unknown artifact.")
    return await artifact_store.serve(job_id, filename)


def validate_blueprint_assets(project: ProjectRecord, request: ExperienceBlueprintInput) -> None:
    object_ids = [item.id for item in request.objects]
    if len(object_ids) != len(set(object_ids)):
        raise HTTPException(422, "Blueprint object IDs must be unique.")
    known_assets = set(project.asset_ids)
    missing = sorted({item.asset_id for item in request.objects} - known_assets)
    if missing:
        raise HTTPException(422, f"Blueprint references unknown project assets: {', '.join(missing)}")
    unavailable = sorted(
        {
            item.asset_id
            for item in request.objects
            if (store.get_asset(item.asset_id) is None)
            or store.get_asset(item.asset_id).status != AssetStatus.READY
        }
    )
    if unavailable:
        raise HTTPException(409, f"Blueprint assets are not ready: {', '.join(unavailable)}")
    attributed = [item for item in request.objects if item.contribution_id is not None]
    if attributed:
        contributions = {item.contribution_id: item for item in store.list_contributions(project.project_id)}
        mismatched = sorted(
            item.id
            for item in attributed
            if item.contribution_id not in contributions
            or contributions[item.contribution_id].asset_id != item.asset_id
        )
        if mismatched:
            raise HTTPException(
                422, f"Blueprint objects reference unknown or mismatched contributions: {', '.join(mismatched)}"
            )


@app.post(
    "/v1/projects/{project_id}/blueprints/validate",
    response_model=ExperienceBlueprintInput,
    dependencies=[Depends(require_project_draft)],
)
async def validate_blueprint(project_id: str, request: ExperienceBlueprintInput) -> ExperienceBlueprintInput:
    project = get_project(project_id)
    validate_blueprint_assets(project, request)
    return request


_MAX_BLUEPRINT_APPEND_ATTEMPTS = 5


@app.post("/v1/projects/{project_id}/blueprints", response_model=ExperienceBlueprint, status_code=201)
async def create_blueprint(
    project_id: str,
    request: ExperienceBlueprintInput,
    base_revision: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "The published revision this draft was built on (0 = nothing "
                "published yet). Optional for backward compatibility with "
                "manual authoring; new callers (room API, NemoClaw) should "
                "always send it so a stale draft is rejected instead of "
                "silently erasing newer edits."
            ),
        ),
    ] = None,
    identity: Identity = Depends(require_project_draft),
) -> ExperienceBlueprint:
    project = get_project(project_id)
    validate_blueprint_assets(project, request)

    if base_revision is not None:
        current_published = store.get_live_revision(project_id) or 0
        if base_revision != current_published:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": (
                        f"base_revision {base_revision} is stale; the currently "
                        f"published revision is {current_published}."
                    ),
                    "published_revision": current_published,
                },
            )

    last_error: RevisionConflict | None = None
    for _ in range(_MAX_BLUEPRINT_APPEND_ATTEMPTS):
        revisions = store.list_blueprints(project_id)
        blueprint = ExperienceBlueprint(
            **request.model_dump(),
            project_id=project_id,
            revision=len(revisions) + 1,
            created_at=utc_now(),
            based_on_revision=base_revision,
            author=author_from_identity(identity),
        )
        try:
            store.append_blueprint(blueprint)
        except RevisionConflict as error:
            last_error = error
            continue
        project.blueprint_revisions.append(blueprint.revision)
        project.updated_at = utc_now()
        store.save_project(project)
        return blueprint

    raise HTTPException(
        409,
        f"Could not create a new blueprint revision after "
        f"{_MAX_BLUEPRINT_APPEND_ATTEMPTS} attempts (too many concurrent "
        f"writers); try again. Last conflict: {last_error}",
    )


@app.get(
    "/v1/projects/{project_id}/blueprints/{revision}",
    response_model=ExperienceBlueprint,
    dependencies=[Depends(require_project_read)],
)
async def get_blueprint(project_id: str, revision: int) -> ExperienceBlueprint:
    get_project(project_id)
    revisions = store.list_blueprints(project_id)
    if revision < 1 or revision > len(revisions):
        raise HTTPException(404, "Unknown blueprint revision.")
    return revisions[revision - 1]


_MAX_LIVE_POINTER_ATTEMPTS = 5


@app.post("/v1/projects/{project_id}/blueprints/{revision}/publish", response_model=SceneResponse)
async def publish_blueprint(
    project_id: str, revision: int, identity: Identity = Depends(require_project_write)
) -> SceneResponse:
    global current_scene
    project = get_project(project_id)
    blueprint = await get_blueprint(project_id, revision)
    validate_blueprint_assets(project, blueprint)

    if blueprint.based_on_revision is not None:
        # New-style draft: publish only if it was built on what's currently
        # live (the LIVE pointer, not the last-write-wins ProjectRecord blob).
        # A losing compare-and-set means someone else published in between —
        # that's the same "stale draft" condition as a stale base_revision, so
        # it's reported the same way instead of silently retried.
        current_live = store.get_live_revision(project_id)
        expected_published = current_live if current_live is not None else 0
        if blueprint.based_on_revision != expected_published:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": (
                        f"stale draft: rebase on revision {expected_published} "
                        "and try again."
                    ),
                    "published_revision": expected_published,
                },
            )
        if not store.set_live_revision(project_id, current_live, revision):
            latest = store.get_live_revision(project_id)
            latest_published = latest if latest is not None else 0
            return JSONResponse(
                status_code=409,
                content={
                    "detail": (
                        f"stale draft: rebase on revision {latest_published} "
                        "and try again."
                    ),
                    "published_revision": latest_published,
                },
            )
    else:
        # Legacy/manual authoring: unconditional publish, including a
        # deliberate rollback to an older revision. The compare-and-set still
        # runs (against a freshly read pointer, retried) to keep the LIVE
        # pointer update atomic under concurrent writers — but a true race
        # here is retried rather than rejected, since this path never applies
        # the "stale base" business rule.
        for _ in range(_MAX_LIVE_POINTER_ATTEMPTS):
            current_live = store.get_live_revision(project_id)
            if store.set_live_revision(project_id, current_live, revision):
                break
        else:
            raise HTTPException(
                500, "Could not update the live revision pointer; try again."
            )

    current_scene = compile_blueprint(blueprint)
    # Cached copy only — kept for existing clients/tests that read it, but no
    # longer the source of truth for what's live (see get_live_revision above
    # and get_compiled_project_scene below).
    project.published_revision = revision
    project.updated_at = utc_now()
    store.save_project(project)
    # Append-only: record which revision went live and when. Republishing an
    # earlier revision appends a new record rather than rewriting history.
    store.append_publication(
        PublicationRecord(
            project_id=project_id,
            revision=revision,
            published_at=utc_now(),
            author=author_from_identity(identity),
        )
    )
    return SceneResponse(scene=current_scene)


@app.get(
    "/v1/projects/{project_id}/compiled-scene",
    response_model=SceneResponse,
    dependencies=[Depends(require_project_read)],
)
async def get_compiled_project_scene(project_id: str) -> SceneResponse:
    project = get_project(project_id)
    # The LIVE pointer is authoritative; project.published_revision is only a
    # last-write-wins cached copy, kept for backward-compat reads if the
    # pointer is somehow unset (e.g. a snapshot from before this pointer
    # existed).
    live_revision = store.get_live_revision(project_id)
    if live_revision is None:
        live_revision = project.published_revision
    if live_revision is None:
        raise HTTPException(404, "This project has no published blueprint.")
    blueprint = await get_blueprint(project_id, live_revision)
    return SceneResponse(scene=compile_blueprint(blueprint))


@app.get(
    "/v1/projects/{project_id}/publications",
    response_model=list[PublicationRecord],
    dependencies=[Depends(require_project_read)],
)
async def list_project_publications(project_id: str) -> list[PublicationRecord]:
    """Return the append-only publication history for a project."""
    get_project(project_id)
    return store.list_publications(project_id)


@app.get(
    "/v1/projects/{project_id}/assets/{asset_id}",
    response_model=ProjectAsset,
    dependencies=[Depends(require_project_read)],
)
async def get_project_asset(project_id: str, asset_id: str) -> ProjectAsset:
    """Return a single catalog asset with its full view provenance."""
    project = get_project(project_id)
    if asset_id not in project.asset_ids:
        raise HTTPException(404, "Unknown asset for this project.")
    asset = store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(404, "Asset record not found.")
    return asset


@app.get(
    "/v1/projects/{project_id}/assets/{asset_id}/views",
    response_model=list[AssetView],
    dependencies=[Depends(require_project_read)],
)
async def list_asset_views(project_id: str, asset_id: str) -> list[AssetView]:
    """Return per-view reconstruction provenance for one catalog asset."""
    asset = await get_project_asset(project_id, asset_id)
    return sorted(asset.views, key=lambda v: v.view_index)


@app.post(
    "/v1/projects/{project_id}/assets/{asset_id}/views",
    response_model=AssetView,
    status_code=202,
    dependencies=[Depends(require_project_write)],
)
async def add_asset_view(
    project_id: str,
    asset_id: str,
    background_tasks: BackgroundTasks,
    image: Annotated[UploadFile, File(description="Photo of the same subject from a new angle")],
    mask: Annotated[UploadFile | None, File(description="Optional aligned white-on-black mask")] = None,
    subject_hint: Annotated[str | None, Form(max_length=100)] = None,
) -> AssetView:
    """Add a new view to an existing catalog asset and queue its reconstruction.

    The asset stays in PROCESSING until at least one view completes. This lets
    the authoring pipeline accumulate multiple angles before deciding which view
    (or fusion of views) to use as the final PLY.
    """
    project = get_project(project_id)
    if asset_id not in project.asset_ids:
        raise HTTPException(404, "Unknown asset for this project.")
    asset = store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(404, "Asset record not found.")
    if asset.status == AssetStatus.READY:
        # Adding more views to a READY asset is valid — additional angles may
        # improve the reconstruction or enable future fusion. The asset stays
        # READY from its first successful view.
        pass

    job_id = uuid.uuid4().hex
    image_path = UPLOAD_ROOT / f"{job_id}-image{image_extension(image)}"
    await save_upload(image, image_path)
    mask_path: Path | None = None
    if mask is not None:
        mask_path = UPLOAD_ROOT / f"{job_id}-mask{image_extension(mask)}"
        await save_upload(mask, mask_path)
    subject_hint, hint_source, label_backend = await resolve_subject_hint(
        subject_hint, image_path, image.filename or "", mask_path is not None
    )

    now = utc_now()
    view_index = len(asset.views)
    new_view = AssetView(
        view_index=view_index,
        image_key=image_path.name,
        subject_hint=subject_hint,
        subject_hint_source=hint_source,
        reconstruction_job_id=job_id,
        recorded_at=now,
    )
    asset.views.append(new_view)
    store.save_asset(asset)

    job = ReconstructionJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=job_url(job_id),
        created_at=now,
        updated_at=now,
        original_filename=image.filename or "image",
        subject_hint=subject_hint,
        subject_hint_source=hint_source,
        subject_label_backend=label_backend,
        project_id=project_id,
        asset_id=asset_id,
    )
    jobs[job_id] = job
    job_inputs[job_id] = (image_path, mask_path)

    pipeline_mode = os.environ.get("PIPELINE_MODE", "mock")
    if pipeline_mode == "aws-local":
        background_tasks.add_task(run_local_gpu_job, job_id)
    elif pipeline_mode != "mock":
        job.status = JobStatus.FAILED
        job.error = "No GPU-worker adapter is configured. Use PIPELINE_MODE=mock or aws-local."
        job.updated_at = utc_now()
    else:
        background_tasks.add_task(run_mock_job, job_id)

    return new_view


# -- Notability sketches (Build Plan step 7) -----------------------------------
#
# Path 1 ("card", default): the page is stored as-is and shown as a flat
# textured card. No SAM 3.1, no Fast-SAM3D, no GPU, no paid API.
# Path 2 ("plaque", opt-in): the page goes through the existing reconstruction
# pipeline unchanged. Unverified: check that page text survives Fast-SAM3D
# legibly before relying on it, and fall back to a card if it doesn't.

SKETCH_CARD_LONG_SIDE_METERS = 0.8
SKETCH_CARD_BASE_HEIGHT = 0.9
_SKETCH_CARD_TYPES = {"image/png": "sketch.png", "image/jpeg": "sketch.jpg"}


def image_dimensions(path: Path) -> tuple[int, int]:
    """Width and height of a PNG or baseline/progressive JPEG, without Pillow."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
                index += 1 if marker == 0xFF else 2
                continue
            length = int.from_bytes(data[index + 2 : index + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = int.from_bytes(data[index + 5 : index + 7], "big")
                width = int.from_bytes(data[index + 7 : index + 9], "big")
                return width, height
            index += 2 + length
    raise HTTPException(422, "Could not read the sketch image's dimensions.")


def sketch_card_url(project_id: str, asset_id: str, filename: str) -> str:
    return f"/v1/projects/{project_id}/assets/{asset_id}/sketch/{filename}"


@app.post("/v1/projects/{project_id}/sketch-assets", response_model=ProjectAsset, status_code=201)
async def create_sketch_asset(
    project_id: str,
    background_tasks: BackgroundTasks,
    http_response: Response,
    image: Annotated[UploadFile, File(description="Notability page export (PNG or JPEG)")],
    label: Annotated[str | None, Form(max_length=100)] = None,
    display: Annotated[Literal["card", "plaque"], Form()] = "card",
) -> ProjectAsset:
    """Register a Notability sketch as a flat card, or reconstruct it as a plaque."""
    if display == "plaque":
        response = await create_project_asset(
            project_id=project_id,
            background_tasks=background_tasks,
            image=image,
            mask=None,
            subject_hint=(label or "").strip() or "paper page",
        )
        http_response.status_code = 202  # queued like any photo reconstruction
        return response

    project = get_project(project_id)
    filename = _SKETCH_CARD_TYPES.get(image.content_type or "")
    if filename is None:
        raise HTTPException(415, "Sketch cards must be PNG or JPEG (render PDF pages to PNG first).")
    asset_id = uuid.uuid4().hex
    image_path = UPLOAD_ROOT / f"{asset_id}-{filename}"
    await save_upload(image, image_path)
    width, height = image_dimensions(image_path)
    if width <= 0 or height <= 0:
        raise HTTPException(422, "The sketch image has no pixels.")
    scale = SKETCH_CARD_LONG_SIDE_METERS / max(width, height)
    card_width, card_height = round(width * scale, 4), round(height * scale, 4)
    await artifact_store.copy_local(asset_id, filename, image_path)

    now = utc_now()
    asset = ProjectAsset(
        asset_id=asset_id,
        project_id=project.project_id,
        label=((label or "").strip() or Path(image.filename or "sketch").stem or "sketch")[:80],
        status=AssetStatus.READY,
        kind="sketch_card",
        reconstruction_job_id="",
        artifact_url=sketch_card_url(project.project_id, asset_id, filename),
        preview_url=sketch_card_url(project.project_id, asset_id, filename),
        bounds=[card_width, card_height, 0.02],
        suggested_scale=[card_width, card_height, 1.0],
    )
    store.save_asset(asset)
    project.asset_ids.append(asset_id)
    project.updated_at = now
    store.save_project(project)
    return asset


@app.get("/v1/projects/{project_id}/assets/{asset_id}/sketch/{filename}")
async def get_sketch_card_image(project_id: str, asset_id: str, filename: str) -> Response:
    asset = await get_project_asset(project_id, asset_id)
    if asset.kind != "sketch_card" or filename not in _SKETCH_CARD_TYPES.values():
        raise HTTPException(404, "Unknown sketch image.")
    return await artifact_store.serve(asset_id, filename)


# -- connection/compose (Build Plan step 5) ------------------------------------
#
# The mock composer is deterministic over the contributions' labels and memory
# text and makes no network call. The live composer must derive the insight
# from the same NemoClaw place_objects_in_scene pass that produces the layout
# (never a separate model call); it waits on step 4.


class ConnectionComposeResponse(BaseModel):
    """A persisted `ConnectionInsight` plus the blueprint proposal it explains.

    The caller creates the blueprint revision separately through
    `POST /v1/projects/{project_id}/blueprints`.
    """

    insight: ConnectionInsight
    blueprint: ExperienceBlueprintInput


# (theme, lighting_preset, keywords). Order breaks ties.
_MOCK_THEMES: list[tuple[str, str, frozenset[str]]] = [
    (
        "Home, carried with us",
        "warm_evening",
        frozenset({"home", "house", "family", "grandma", "grandmother", "grandpa", "grandfather", "mom", "mother", "dad", "father", "sister", "brother", "childhood"}),
    ),
    (
        "Around the kitchen table",
        "warm_evening",
        frozenset({"kitchen", "cook", "cooking", "recipe", "bake", "baking", "dinner", "breakfast", "food", "tea", "coffee", "mug", "cup", "table"}),
    ),
    (
        "Songs we carry",
        "stage_glow",
        frozenset({"music", "song", "guitar", "piano", "sing", "singing", "concert", "record", "vinyl", "band", "radio"}),
    ),
    (
        "By the water",
        "golden_hour",
        frozenset({"beach", "ocean", "sea", "lake", "river", "boat", "shell", "summer", "swim", "swimming", "wave"}),
    ),
    (
        "Things we grew",
        "soft_daylight",
        frozenset({"garden", "plant", "flower", "tree", "park", "hike", "hiking", "forest", "seed", "leaf"}),
    ),
    (
        "Places that shaped us",
        "dusk",
        frozenset({"travel", "trip", "train", "flight", "road", "map", "city", "moved", "move", "journey", "postcard"}),
    ),
    (
        "How we played",
        "bright_day",
        frozenset({"game", "play", "played", "toy", "ball", "team", "match", "soccer", "basketball", "puzzle"}),
    ),
]
_MOCK_FALLBACK_THEMES: list[tuple[str, str]] = [
    ("Small things, kept close", "warm_evening"),
    ("What we held onto", "soft_daylight"),
    ("Pieces of the same afternoon", "golden_hour"),
]
_MOCK_OBJECT_INTERACTIONS: list[Literal["highlight", "inspect", "scale", "translate", "rotate", "activate"]] = [
    "highlight",
    "inspect",
    "rotate",
]


def _mock_tokens(text: str) -> set[str]:
    tokens = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        tokens.add(word)
        if len(word) > 3 and word.endswith("s"):
            tokens.add(word[:-1])
    return tokens


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def compose_connection_mock(
    contributions: list[Contribution],
    contributors: dict[str, Contributor],
    assets: dict[str, ProjectAsset],
) -> tuple[str, str, list[PlacementRationale], ExperienceBlueprintInput]:
    """Deterministic stand-in for NemoClaw's layout + connection reasoning."""
    ordered = sorted(contributions, key=lambda item: (item.created_at, item.contribution_id))
    texts = [f"{assets[item.asset_id].label} {item.memory_text}" for item in ordered]

    # Prefer the theme the most contributors touch, then the most keyword hits.
    best_score, best_index = (0, 0), None
    for index, (_, _, keywords) in enumerate(_MOCK_THEMES):
        hits = [len(_mock_tokens(text) & keywords) for text in texts]
        score = (sum(1 for count in hits if count), sum(hits))
        if score > best_score:
            best_score, best_index = score, index
    if best_index is not None:
        theme, lighting, _ = _MOCK_THEMES[best_index]
    else:
        digest = hashlib.sha256("\n".join(sorted(texts)).encode("utf-8")).digest()
        theme, lighting = _MOCK_FALLBACK_THEMES[digest[0] % len(_MOCK_FALLBACK_THEMES)]

    # Everyone's object sits on one ring facing the shared center, so no
    # contribution is placed "behind" another.
    count = len(ordered)
    radius = max(1.2, 0.45 * count)
    objects: list[BlueprintObject] = []
    rationale: list[PlacementRationale] = []
    for index, contribution in enumerate(ordered):
        angle = 2 * math.pi * index / count
        x = round(radius * math.sin(angle), 3)
        z = round(radius * math.cos(angle), 3)
        facing = round((math.degrees(angle) + 180.0) % 360.0, 3)
        asset = assets[contribution.asset_id]
        object_id = f"contribution-{contribution.contribution_id[:24]}"
        # A sketch card stands upright with its lower edge at table height.
        y = round(SKETCH_CARD_BASE_HEIGHT + asset.suggested_scale[1] / 2, 3) if asset.kind == "sketch_card" else 0.0
        objects.append(
            BlueprintObject(
                id=object_id,
                asset_id=asset.asset_id,
                position=[x, y, z],
                rotation=[0.0, facing, 0.0],
                scale=list(asset.suggested_scale),
                interactions=list(_MOCK_OBJECT_INTERACTIONS),
                contribution_id=contribution.contribution_id,
            )
        )
        name = contributors[contribution.contributor_id].display_name if contribution.contributor_id in contributors else "A contributor"
        memory = f' ("{_clip(contribution.memory_text, 200)}")' if contribution.memory_text else ""
        rationale.append(
            PlacementRationale(
                object_id=object_id,
                asset_id=asset.asset_id,
                rationale=_clip(
                    f"{name}'s {asset.label}{memory} faces the center of the circle, "
                    f"level with the others, as one part of \"{theme}\".",
                    500,
                ),
            )
        )

    names = []
    for contribution in ordered:
        contributor = contributors.get(contribution.contributor_id)
        if contributor and contributor.display_name not in names:
            names.append(contributor.display_name)
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
    explanation = _clip(
        f"{joined} each brought something that belongs to \"{theme}\". "
        f"The {count} objects stand in one circle facing a shared center, "
        "so the room reads as one gathering rather than separate exhibits.",
        2000,
    )

    blueprint = ExperienceBlueprintInput(
        experience=ExperienceSettings(mode="vr", theme=theme),
        environment=EnvironmentSettings(lighting_preset=lighting),
        objects=objects,
        navigation=NavigationSettings(vr="teleport"),
    )
    return theme, explanation, rationale, blueprint


@app.post(
    "/v1/projects/{project_id}/connection/compose",
    response_model=ConnectionComposeResponse,
    status_code=201,
    dependencies=[Depends(require_project_draft)],
)
async def compose_connection(project_id: str) -> ConnectionComposeResponse:
    project = get_project(project_id)
    contributions = store.list_contributions(project_id)
    if len(contributions) < project.min_contributors:
        raise HTTPException(
            409,
            f"connection/compose needs at least {project.min_contributors} contributions; "
            f"this project has {len(contributions)}.",
        )

    assets: dict[str, ProjectAsset] = {}
    for contribution in contributions:
        asset = store.get_asset(contribution.asset_id)
        if asset is None or asset.status != AssetStatus.READY:
            raise HTTPException(409, f"Blueprint assets are not ready: {contribution.asset_id}")
        assets[asset.asset_id] = asset
    contributors = {item.contributor_id: item for item in store.list_contributors(project_id)}

    composer = os.environ.get("SKETCHSCAPE_CONNECTION_COMPOSER", "mock")
    if composer != "mock":
        raise HTTPException(
            501,
            "Only SKETCHSCAPE_CONNECTION_COMPOSER=mock is implemented; the live NemoClaw "
            "path waits on Build Plan step 4 (place_objects_in_scene).",
        )
    theme, explanation, rationale, blueprint = compose_connection_mock(contributions, contributors, assets)
    validate_blueprint_assets(project, blueprint)

    insight = ConnectionInsight(
        project_id=project_id,
        revision=len(store.list_connection_insights(project_id)) + 1,
        theme=theme,
        explanation=explanation,
        placement_rationale=rationale,
        backend="mock",
        model="mock-composer-v1",
        created_at=utc_now(),
    )
    store.append_connection_insight(insight)
    return ConnectionComposeResponse(insight=insight, blueprint=blueprint)


SAFE_SCENE_ACTIONS = ["scale_by", "translate_by", "rotate_by"]


def find_scene_object(target_id: str) -> SceneObject:
    target = next((item for item in current_scene.objects if item.id == target_id), None)
    if target is None:
        raise HTTPException(404, f"Unknown interactive object: {target_id}")
    return target


def bounded_vector(values: list[float], *, minimum: float, maximum: float, action: str) -> list[float]:
    if any(value < minimum or value > maximum for value in values):
        raise HTTPException(422, f"{action} values must be between {minimum} and {maximum}.")
    return values


@app.get(
    "/v1/interactives",
    response_model=InteractiveRegistryResponse,
    dependencies=[Depends(require_mock_mode)],
)
async def get_interactives() -> InteractiveRegistryResponse:
    """Expose names and capabilities, never Unity component internals."""
    # Process-global demo scene surface (same as /v1/scene) — mock-mode only.
    return InteractiveRegistryResponse(
        interactives=[
            InteractiveObject(id=item.id, name=item.id, type=item.type, actions=item.actions.copy())
            for item in current_scene.objects
        ]
    )


@app.post(
    "/v1/scene/actions",
    response_model=SceneResponse,
    dependencies=[Depends(require_mock_mode)],
)
async def apply_scene_action(request: SceneActionRequest) -> SceneResponse:
    """Apply an allowlisted, bounded transform action to one named object."""
    target = find_scene_object(request.target_id)
    if request.contributor_id:
        owners = {
            entry["object_id"]: entry["contributor_id"]
            for entry in current_scene.meta.get("social", {}).get("objects", [])
        }
        if owners.get(request.target_id) != request.contributor_id:
            raise HTTPException(403, f"{request.target_id} was not contributed by this contributor.")
    if request.action not in target.actions:
        raise HTTPException(403, f"{request.action} is not enabled for {request.target_id}.")
    if request.action == "scale_by":
        factors = bounded_vector(request.value, minimum=0.25, maximum=4.0, action=request.action)
        result = [target.scale[index] * factors[index] for index in range(3)]
        if any(value < 0.05 or value > 20.0 for value in result):
            raise HTTPException(422, "Resulting scale must remain between 0.05 and 20.0.")
        target.scale = result
    elif request.action == "translate_by":
        offsets = bounded_vector(request.value, minimum=-10.0, maximum=10.0, action=request.action)
        result = [target.position[index] + offsets[index] for index in range(3)]
        if any(value < -100.0 or value > 100.0 for value in result):
            raise HTTPException(422, "Resulting position must remain within the scene bounds.")
        target.position = result
    else:
        offsets = bounded_vector(request.value, minimum=-360.0, maximum=360.0, action=request.action)
        target.rotation = [(target.rotation[index] + offsets[index]) % 360.0 for index in range(3)]

    current_scene.instructions.append(
        {"target": request.target_id, "action": request.action, "value": request.value.copy()}
    )
    return SceneResponse(scene=current_scene)


@app.post(
    "/v1/scene/modify",
    response_model=SceneResponse,
    dependencies=[Depends(require_mock_mode)],
)
@app.post(
    "/modify-scene",
    response_model=SceneResponse,
    include_in_schema=False,
    dependencies=[Depends(require_mock_mode)],
)
async def modify_scene(request: SceneModificationRequest) -> SceneResponse:
    """Legacy phrase adapter; all mutations pass through the structured policy."""
    normalized = " ".join(request.instruction.lower().split())
    if "tree" in normalized and ("twice" in normalized or "2x" in normalized) and (
        "tall" in normalized or "height" in normalized
    ):
        return await apply_scene_action(
            SceneActionRequest(target_id="tree_1", action="scale_by", value=[1.0, 2.0, 1.0])
        )
    raise HTTPException(422, "Demo supports: 'make the tree twice as tall'.")


@app.post(
    "/sketch",
    response_model=SceneResponse,
    include_in_schema=False,
    dependencies=[Depends(require_mock_mode)],
)
async def legacy_sketch(sketch: UploadFile = File(...)) -> SceneResponse:
    """Compatibility endpoint retained while Unity migrates to reconstruction jobs."""
    if not (sketch.content_type or "").startswith("image/"):
        raise HTTPException(415, "Upload a sketch image.")
    global current_scene
    current_scene = placeholder_scene(sketch.filename or "sketch.png")
    return SceneResponse(scene=current_scene)
