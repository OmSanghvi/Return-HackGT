"""SketchScape's Unity-facing reconstruction API.

This process deliberately does *not* load CUDA, SAM, or SAM 3D. It owns
uploads, job state, scene JSON, and artifacts. A separate GPU worker receives
one job at a time and writes the result manifest in ``worker_contract.json``.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import secrets
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import upload_pipeline
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
from letters import LetterSceneRef, RoomLetterView, room_letter_views


DATA_ROOT = Path(os.environ.get("SKETCHSCAPE_DATA_DIR", "./data")).resolve()
ARTIFACT_ROOT = DATA_ROOT / "artifacts"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
# Scope used for standalone (no-project) `/v1/reconstructions` uploads, so
# their input bytes still land under ArtifactStore's uploads/<scope>/<job_id>/
# shared-storage layout instead of a host-local path (Build Plan step 26).
STANDALONE_UPLOAD_SCOPE = "_standalone_"
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)


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
    source: Literal["placeholder", "sam3d", "sketch_card", "letter"] = "placeholder"
    actions: list[Literal["scale_by", "translate_by", "rotate_by"]] = Field(
        default_factory=lambda: ["scale_by", "translate_by", "rotate_by"]
    )
    # Anyone in the room may pick this up to look at it; it returns to its
    # place when released (local only; nothing is saved).
    grabbable: bool = False
    # Step 28: runtime fields for a letter object. The texture URL is never
    # here -- it depends on who's asking (sealed vs. opened), so Unity reads
    # it from room state instead.
    letter: LetterSceneRef | None = None


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
    image_key: str = Field(description="ArtifactStore uploads/ key of the uploaded source image.")
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
    # Step 26: reconstruction | sketch_card | letter (letter arrives in step 28).
    kind: Literal["reconstruction", "sketch_card", "letter"] = "reconstruction"
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
    # Bound to the caller's verified identity when they join (a Clerk `sub`
    # in clerk mode, a fixed demo account id in demo mode, or the mock
    # `X-SketchScape-Dev-User` value). None for unbound personas created in
    # mock mode after the creator.
    clerk_user_id: str | None = None


class ContributorCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    # Required outside mock mode (clerk, demo); optional in mock so existing
    # local/demo flows keep working (Hard Rule 2).
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
    interactions: list[Literal["highlight", "inspect", "scale", "translate", "rotate", "activate", "grab"]] = Field(
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
    # Set from the caller's verified identity outside mock mode (clerk,
    # demo -- step 16); unset for mock-mode/manual authoring, matching that
    # mode's behavior before step 16 (Hard Rule 2).
    author: str | None = None
    # Step 21: the room API's idempotency key. Set only on revisions created
    # through POST /v1/rooms/{project_id}/edits, so a retried edit call (same
    # author + client_edit_id) can be recognized and replayed instead of
    # double-applied. None for every other authoring path.
    client_edit_id: str | None = Field(default=None, max_length=100)


class PublicationRecord(BaseModel):
    """An immutable record of one blueprint publication.

    Publication history is append-only. Each publish appends a record so the
    log always shows which revision was live at a given time; earlier records
    are never rewritten.
    """

    project_id: str
    revision: int
    published_at: datetime
    # Set from the caller's verified identity outside mock mode (clerk,
    # demo -- step 16); unset for mock-mode/manual publishing, matching
    # create_blueprint above.
    author: str | None = None


class ReconstructionResponse(BaseModel):
    job_id: str
    status: JobStatus
    poll_url: str
    scene_url: str = "/v1/scene"


JobKind = Literal["segment", "reconstruct"]


class ReconstructionJob(ReconstructionResponse):
    """Durable reconstruction / segmentation job (Build Plan step 26).

    Persisted in the AuthoringStore so any API instance can answer a poll.
    ``kind=segment`` runs SAM 3.1 over person-chosen selections; ``kind=
    reconstruct`` runs Fast-SAM3D for one selection's mask.
    """

    created_at: datetime
    updated_at: datetime
    original_filename: str = ""
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
    # Step 26 durable-job fields.
    kind: JobKind = "reconstruct"
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    upload_id: str | None = None
    selection_ids: list[str] = Field(default_factory=list)
    # Shared-storage keys (ArtifactStore uploads/ prefix), not host-local paths.
    image_key: str | None = None
    mask_key: str | None = None


SelectionStatus = Literal["pending", "segmented", "failed", "generated"]
SelectionOrigin = Literal["person", "suggested"]


class SelectionPrompt(BaseModel):
    """A typed name for the object SAM 3.1 should find (validated in the route)."""

    text: str = Field(min_length=1, max_length=100)


class UploadSelection(BaseModel):
    selection_id: str = Field(min_length=1, max_length=80)
    prompt: SelectionPrompt
    label: str | None = Field(default=None, max_length=100)
    memory_text: str = Field(default="", max_length=1000)
    status: SelectionStatus = "pending"
    mask_key: str | None = None
    preview_key: str | None = None
    score: float | None = None
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    origin: SelectionOrigin = "person"
    mask_preview_url: str | None = None
    # Set on a `failed` selection (Build Plan step 27): why SAM 3.1 found
    # nothing usable for this typed name, shown so the person can refine it.
    error: str | None = Field(default=None, max_length=200)


class UploadRecord(BaseModel):
    upload_id: str
    project_id: str
    uploader_user_id: str
    image_key: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    created_at: datetime
    original_filename: str = ""
    selections: list[UploadSelection] = Field(default_factory=list)


class SelectionsRequest(BaseModel):
    selections: list[UploadSelection] = Field(min_length=1)


class RefineSelectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100)


class GenerateRequest(BaseModel):
    selection_ids: list[str] = Field(min_length=1)


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


class SelectionWorkerResult(BaseModel):
    """Per-selection SAM 3.1 outcome (Build Plan step 27).

    One `segment` job masks every selection the person typed in a single
    SAM 3.1 pass over the photo, so the worker reports back once per
    selection rather than once per job (see
    ``POST /v1/internal/reconstructions/{job_id}/selections/{selection_id}/result``).
    A `failed` selection never blocks the others (Hard Rule 7).
    """

    status: Literal["segmented", "failed"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = Field(default=None, max_length=200)


def placeholder_scene(uploaded_filename: str = "sketch.png") -> SceneDocument:
    return SceneDocument(
        objects=[
            SceneObject(id="tree_1", type="tree", position=[-2.1, 0, 7], scale=[1, 1, 1]),
            SceneObject(id="house_1", type="house", position=[2.1, 0, 7.7], scale=[1.4, 1.4, 1.4]),
        ],
        meta={"source": "upload", "mode": "placeholder", "uploaded_filename": uploaded_filename},
    )


current_scene = placeholder_scene()
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

def cors_settings(mode: str | None = None) -> tuple[list[str], list[str]]:
    """CORS (origins, headers) for ``mode`` (default: the current env var).

    Extracted as a pure function so its exact logic is independently
    testable: ``app.add_middleware(CORSMiddleware, ...)`` below runs exactly
    once, at import time, so a test that later patches
    ``SKETCHSCAPE_AUTH_MODE``/``SKETCHSCAPE_WEB_ORIGINS`` and replays a
    request through this same ``app`` can never observe a different live
    CORS configuration -- unlike identity/membership checks, which do read
    the environment per-request. A test instead calls this function directly
    with the origins it wants to verify and drives a real preflight against a
    fresh ``CORSMiddleware`` built from its result (see
    ``test_auth.CorsPreflightTests``).

    In `clerk` and `demo` mode, only the configured web origin(s) may call
    this API, and bearer/header auth (not cookies) carries identity, so
    credentialed CORS isn't needed. `mock` mode keeps today's
    SKETCHSCAPE_ALLOWED_ORIGINS behavior unchanged (default "*") -- no
    behavior change for local/offline use (Hard Rule 2).
    """
    resolved_mode = (mode if mode is not None else os.environ.get("SKETCHSCAPE_AUTH_MODE", "mock")).strip().lower()
    if resolved_mode in ("clerk", "demo"):
        return web_origins(), ["Authorization", "Content-Type", "If-None-Match", "X-SketchScape-Dev-User"]
    return os.environ.get("SKETCHSCAPE_ALLOWED_ORIGINS", "*").split(","), ["*"]


# PATCH: project room_prompt (step 17). DELETE: remove a selection (step 26).
CORS_METHODS = ["GET", "POST", "PATCH", "DELETE"]
# Job and room-state polling read these; a cross-origin browser hides them
# from JavaScript unless they're exposed.
CORS_EXPOSE_HEADERS = ["ETag", "Retry-After"]

_cors_origins, _cors_headers = cors_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=CORS_METHODS,
    allow_headers=_cors_headers,
    expose_headers=CORS_EXPOSE_HEADERS,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


async def read_upload_bytes(upload: UploadFile, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """Read a bounded upload fully into memory (needed for EXIF/PIL handling)."""
    data = bytearray()
    while chunk := await upload.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(413, f"File is larger than the {limit // 1024 // 1024} MB limit.")
    if not data:
        raise HTTPException(400, "The uploaded image is empty.")
    return bytes(data)


def safe_exif_transpose(raw: bytes) -> tuple[bytes, int, int, str]:
    """Apply EXIF orientation for a real photo; pass non-image bytes through.

    Mock-mode/tests routinely post placeholder bytes that aren't a decodable
    image (Hard Rule 2: mock stays fully offline and doesn't need real
    images). A real upload from the web app's selection canvas is always a
    genuine JPEG/PNG/WebP, so only that path exercises the actual transpose.
    """
    try:
        return upload_pipeline.apply_exif_transpose(raw)
    except Exception:
        return raw, 1, 1, ".png"


def _bytes_upload_file(data: bytes, filename: str) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(data))


def get_job_or_404(job_id: str) -> ReconstructionJob:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown reconstruction job.")
    return job


def get_upload_or_404(project_id: str, upload_id: str) -> UploadRecord:
    upload = store.get_upload_record(project_id, upload_id)
    if upload is None:
        raise HTTPException(404, "Unknown upload.")
    return upload


def project_asset_ids(project: ProjectRecord) -> set[str]:
    """Every asset attached to a project.

    Union of the legacy list-in-a-blob (`ProjectRecord.asset_ids`, read-only
    for old snapshots) and the new child-item links written by
    `store.link_asset` (Build Plan step 26) -- the fix for two concurrent
    uploads racing on `project.asset_ids.append(...)` and dropping one.
    """
    return set(project.asset_ids) | set(store.list_linked_asset_ids(project.project_id))


def require_upload_owner(upload: UploadRecord, identity: Identity) -> None:
    """Only the uploader may edit their upload's selections (mock mode: no-op, Hard Rule 2)."""
    if _auth_mode() == "mock" or identity.kind == "service":
        return
    if upload.uploader_user_id != identity.user_id:
        raise HTTPException(403, "Only the uploader can edit this upload's selections.")


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
    keep working (Hard Rule 2). In ``clerk`` and ``demo`` mode:

    - ``read`` / ``draft``: a project member, or a service (NemoClaw).
    - ``write``: a project member only (never a service) — uploads,
      contributions, invite rotation, room_prompt, publish.
    """
    if _auth_mode() == "mock":
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
        letter = store.get_letter(blueprint.project_id, asset.asset_id) if asset.kind == "letter" else None
        scene_objects.append(
            SceneObject(
                id=item.id,
                type=asset.label,
                position=item.position.copy(),
                rotation=item.rotation.copy(),
                scale=item.scale.copy(),
                # A letter's texture is access-gated per-caller, so it never
                # goes in the (cached, shared) compiled scene -- Unity reads
                # it from room state instead.
                asset_url=None if asset.kind == "letter" else asset.artifact_url,
                source=(
                    "letter"
                    if asset.kind == "letter"
                    else "sketch_card"
                    if asset.kind == "sketch_card"
                    else "sam3d" if asset.artifact_url else "placeholder"
                ),
                actions=[
                    action
                    for action in ("scale_by", "translate_by", "rotate_by")
                    if action.removesuffix("_by") in item.interactions
                ],
                grabbable="grab" in item.interactions,
                letter=(
                    LetterSceneRef(
                        letter_id=letter.letter_id,
                        recipient_contributor_ids=letter.recipient_contributor_ids,
                        aspect_ratio=letter.aspect_ratio,
                        envelope_style=letter.envelope_style,
                    )
                    if letter is not None
                    else None
                ),
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
    subject_hint: str | None, image_bytes: bytes, image_suffix: str, original_filename: str, has_mask: bool
) -> tuple[str | None, SubjectHintSource | None, str | None]:
    """Return (hint, source, label backend); a typed hint always wins.

    NemoClaw labels only when SAM 3.1 will need a prompt: no typed hint and no
    uploaded mask. No label leaves the worker's mask_review path unchanged.
    `identify_subject` takes a path, so the (already shared-storage-durable)
    image bytes are spilled to a throwaway temp file just for this call.
    """
    if subject_hint and subject_hint.strip():
        return subject_hint.strip(), "user", None
    if has_mask:
        return None, None, None
    with tempfile.NamedTemporaryFile(suffix=image_suffix) as tmp:
        tmp.write(image_bytes)
        tmp.flush()
        try:
            label = await asyncio.to_thread(
                subject_labeler.identify_subject, Path(tmp.name), original_filename
            )
        except SubjectLabelError as exc:
            print(f"identify_subject unavailable: {exc}", file=sys.stderr)
            return None, None, None
    if label is None:
        return None, None, None
    return label.label, "nemoclaw", label.backend


def dispatch_job(job: ReconstructionJob, background_tasks: BackgroundTasks) -> None:
    """Route a freshly queued job to the configured pipeline backend."""
    pipeline_mode = os.environ.get("PIPELINE_MODE", "mock")
    if pipeline_mode == "mock":
        if job.kind == "segment":
            background_tasks.add_task(run_mock_segment_job, job.job_id)
        else:
            background_tasks.add_task(run_mock_reconstruct_job, job.job_id)
        return
    if pipeline_mode == "aws-local":
        if job.kind == "segment":
            # Build Plan step 27: left `queued`. The GPU-host dispatcher
            # (worker/gpu_dispatcher.py) claims it via POST
            # /v1/internal/jobs/claim, batches every pending selection's
            # typed name into one SAM 3.1 pass, and reports back per
            # selection through /selections/{selection_id}/result -- unlike
            # the legacy single-object `reconstruct` push path below, which
            # is unchanged.
            return
        background_tasks.add_task(run_local_gpu_job, job.job_id)
        return
    job.status = JobStatus.FAILED
    job.error = "No GPU-worker adapter is configured. Use PIPELINE_MODE=mock or aws-local."
    job.updated_at = utc_now()
    store.save_job(job)


async def run_mock_reconstruct_job(job_id: str) -> None:
    """Demo-safe fallback; it never pretends to have run SAM 3D."""
    global current_scene
    job = store.get_job(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    job.updated_at = utc_now()
    store.save_job(job)
    await asyncio.sleep(0.15)
    job.scene = placeholder_scene(job.original_filename or "sketch.png")
    job.scene.meta.update(
        {
            "pipeline": "mock",
            "mask_provided": job.mask_key is not None,
            "next_real_worker": "automatic mask -> SAM 3D Objects -> Gaussian-splat PLY",
        }
    )
    current_scene = job.scene
    job.status = JobStatus.COMPLETE
    job.updated_at = utc_now()
    store.save_job(job)
    sync_project_asset(job)


async def run_mock_segment_job(job_id: str) -> None:
    """Mock SAM 3.1: a fixed centered ellipse per text-prompt selection
    (upload_pipeline.render_mock_mask) -- no GPU, no network (Build Plan
    step 26/27's mock-mode contract).
    """
    job = store.get_job(job_id)
    if job is None:
        return
    job.status = JobStatus.RUNNING
    job.updated_at = utc_now()
    store.save_job(job)
    await asyncio.sleep(0.05)

    upload = store.get_upload_record(job.project_id, job.upload_id) if job.project_id and job.upload_id else None
    if upload is None:
        job.status = JobStatus.FAILED
        job.error = "Upload record not found for this segmentation job."
        job.updated_at = utc_now()
        store.save_job(job)
        return

    for selection in upload.selections:
        if selection.selection_id not in job.selection_ids:
            continue
        mask_image = upload_pipeline.render_mock_mask(upload.width, upload.height, selection.prompt)
        buffer = io.BytesIO()
        mask_image.save(buffer, format="PNG")
        mask_key = await artifact_store.put_upload(
            upload.project_id,
            upload.upload_id,
            f"selections/{selection.selection_id}-mask.png",
            _bytes_upload_file(buffer.getvalue(), "mask.png"),
            size_limit=MAX_UPLOAD_BYTES,
        )
        selection.mask_key = mask_key
        selection.preview_key = mask_key
        selection.mask_preview_url = (
            f"/v1/projects/{upload.project_id}/uploads/{upload.upload_id}"
            f"/selections/{selection.selection_id}/mask"
        )
        selection.score = 0.92
        selection.status = "segmented"
    store.save_upload_record(upload)

    job.status = JobStatus.COMPLETE
    job.updated_at = utc_now()
    store.save_job(job)


async def run_local_gpu_job(job_id: str) -> None:
    """Submit a job to the persistent worker server on loopback.

    The worker server (worker/worker_server.py) keeps all models loaded in
    memory between jobs, eliminating the 2–3 minute cold-start penalty from
    loading large checkpoints on every request.  It must be running before
    the first job is submitted; it starts automatically via the
    sketchscape-worker systemd service.
    """
    async with local_worker_lock:
        job = store.get_job(job_id)
        if job is None or job.status != JobStatus.QUEUED:
            return
        job.updated_at = utc_now()
        store.save_job(job)

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
                store.save_job(job)
                return
            except Exception as error:
                from urllib.error import HTTPError

                if isinstance(error, HTTPError) and error.code == 503:
                    if asyncio.get_running_loop().time() < deadline:
                        job.updated_at = utc_now()
                        store.save_job(job)
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
                store.save_job(job)
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
    return [store.get_asset(asset_id) for asset_id in project_asset_ids(project) if store.get_asset(asset_id)]


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
    if mode != "mock":
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
    if request.asset_id not in project_asset_ids(project):
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
    """Queue a reconstruction and optionally register it in a project catalog.

    A thin wrapper around the shared-storage job pipeline (Build Plan step
    26): the upload plus one automatic selection covering the whole image,
    with no UploadRecord/selection-canvas step, so the Unity desktop panel and
    existing single-object tests keep working unchanged.
    """
    if project_id:
        enforce_project_access(project_id, identity, capability="write")
    project = get_project(project_id) if project_id else None

    image_extension(image)  # 415 on an unsupported content type
    raw_image = await read_upload_bytes(image)
    oriented_image, _, _, image_suffix = safe_exif_transpose(raw_image)

    job_id = uuid.uuid4().hex
    upload_scope = project_id or STANDALONE_UPLOAD_SCOPE
    image_key = await artifact_store.put_upload(
        upload_scope, job_id, f"image{image_suffix}",
        _bytes_upload_file(oriented_image, f"image{image_suffix}"),
        size_limit=MAX_UPLOAD_BYTES,
    )
    mask_key: str | None = None
    if mask is not None:
        mask_suffix = image_extension(mask)
        raw_mask = await read_upload_bytes(mask)
        mask_key = await artifact_store.put_upload(
            upload_scope, job_id, f"mask{mask_suffix}",
            _bytes_upload_file(raw_mask, f"mask{mask_suffix}"),
            size_limit=MAX_UPLOAD_BYTES,
        )
    subject_hint, hint_source, label_backend = await resolve_subject_hint(
        subject_hint, oriented_image, image_suffix, image.filename or "", mask_key is not None
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
        kind="reconstruct",
        image_key=image_key,
        mask_key=mask_key,
    )
    if project is not None:
        asset_id = uuid.uuid4().hex
        job.asset_id = asset_id
        label = (subject_hint or Path(image.filename or "object").stem or "object")[:80]
        first_view = AssetView(
            view_index=0,
            image_key=image_key,
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
        # Child link item, not a `project.asset_ids.append` -- see
        # `project_asset_ids`'s docstring for the concurrent-write bug this
        # replaces.
        store.link_asset(project.project_id, asset_id)
        project.updated_at = now
        store.save_project(project)
    store.save_job(job)
    dispatch_job(job, background_tasks)
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
    job = get_job_or_404(response.job_id)
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
    return get_job_or_404(job_id)


@app.get("/v1/internal/reconstructions/{job_id}/input/{kind}")
async def get_worker_input(
    job_id: str,
    kind: Literal["image", "mask"],
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> Response:
    """Private pull endpoint used by a Camber job; never call this from Unity.

    Reads from ArtifactStore's uploads/ prefix (Build Plan step 26) rather
    than a host-local path, so any API instance's upload is fetchable by the
    worker regardless of which instance originally wrote it.
    """
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = get_job_or_404(job_id)
    key = job.image_key if kind == "image" else job.mask_key
    if key is None:
        raise HTTPException(404, f"This job has no {kind} input.")
    data = artifact_store.open_upload(key)
    media_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)


@app.get("/v1/internal/reconstructions/{job_id}/task")
async def get_worker_task(
    job_id: str,
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> dict[str, str | None]:
    """Return the worker-only text concept for local SAM 3.1 segmentation."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = get_job_or_404(job_id)
    return {"job_id": job_id, "subject_hint": job.subject_hint}


@app.post("/v1/internal/reconstructions/{job_id}/result", response_model=ReconstructionJob)
async def receive_worker_result(
    job_id: str,
    result: Annotated[str, Form(description="JSON WorkerResult payload")],
    worker_token: Annotated[str | None, Form()] = None,
    worker_id: Annotated[str | None, Form(description="Lease owner from /v1/internal/jobs/claim")] = None,
    ply: UploadFile | None = File(default=None, description="SAM 3D Gaussian-splat PLY"),
    mask: UploadFile | None = File(default=None, description="Aligned binary object mask"),
    preview: UploadFile | None = File(default=None, description="Mask-preview PNG"),
) -> ReconstructionJob:
    """Private callback for the GPU worker; it is not a Unity endpoint."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = get_job_or_404(job_id)
    # Jobs claimed through the durable lease queue (step 26/27) are only
    # completable by their current lease owner; a legacy push-submitted job
    # (aws-local's direct-submit path) never has a lease, so it's unaffected.
    if job.lease_owner is not None and job.lease_owner != worker_id:
        raise HTTPException(401, "This job's lease is held by a different worker.")
    try:
        payload = WorkerResult.model_validate_json(result)
    except ValueError as error:
        raise HTTPException(422, "`result` must be valid WorkerResult JSON.") from error

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
    job.lease_owner = None
    job.lease_expires_at = None
    store.save_job(job)
    sync_project_asset(job)
    return job


class SegmentTaskSelection(BaseModel):
    selection_id: str
    text: str


class SegmentTaskResponse(BaseModel):
    job_id: str
    image_key: str | None = None
    selections: list[SegmentTaskSelection]


@app.get("/v1/internal/reconstructions/{job_id}/selections", response_model=SegmentTaskResponse)
async def get_worker_selections(
    job_id: str,
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> SegmentTaskResponse:
    """Worker-only (Build Plan step 27): the typed names for a `segment`
    job's pending selections, so the dispatcher can batch every one of them
    into a single SAM 3.1 predictor call (skill item 1) -- unlike
    `/task` above, which only carries one legacy `subject_hint`.
    """
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = get_job_or_404(job_id)
    if job.kind != "segment":
        raise HTTPException(404, "This job has no selections; it is not a segment job.")
    if job.project_id is None or job.upload_id is None:
        raise HTTPException(404, "This segment job has no upload to read selections from.")
    upload = get_upload_or_404(job.project_id, job.upload_id)
    by_id = {item.selection_id: item for item in upload.selections}
    selections = [
        SegmentTaskSelection(selection_id=sid, text=by_id[sid].prompt.text)
        for sid in job.selection_ids
        if sid in by_id
    ]
    return SegmentTaskResponse(job_id=job_id, image_key=job.image_key, selections=selections)


@app.post(
    "/v1/internal/reconstructions/{job_id}/selections/{selection_id}/result",
    response_model=UploadSelection,
)
async def receive_selection_result(
    job_id: str,
    selection_id: str,
    result: Annotated[str, Form(description="JSON SelectionWorkerResult payload")],
    worker_token: Annotated[str | None, Form()] = None,
    worker_id: Annotated[str | None, Form(description="Lease owner from /v1/internal/jobs/claim")] = None,
    mask: UploadFile | None = File(default=None, description="Binary object mask, white is the object"),
    preview: UploadFile | None = File(default=None, description="Optional mask-preview PNG"),
) -> UploadSelection:
    """Worker-only (Build Plan step 27): one call per selection from the
    single SAM 3.1 pass over a `segment` job's typed names. The job
    completes once every selection has a terminal outcome; a selection with
    no usable mask is `failed` with a reason and never blocks the others
    (Hard Rule 7)."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    job = get_job_or_404(job_id)
    if job.kind != "segment":
        raise HTTPException(422, "This job is not a segment job.")
    if job.lease_owner is not None and job.lease_owner != worker_id:
        raise HTTPException(401, "This job's lease is held by a different worker.")
    if selection_id not in job.selection_ids:
        raise HTTPException(404, "Unknown selection for this job.")
    if job.project_id is None or job.upload_id is None:
        raise HTTPException(404, "This segment job has no upload.")
    upload = get_upload_or_404(job.project_id, job.upload_id)
    selection = next((item for item in upload.selections if item.selection_id == selection_id), None)
    if selection is None:
        raise HTTPException(404, "Unknown selection for this upload.")

    try:
        payload = SelectionWorkerResult.model_validate_json(result)
    except ValueError as error:
        raise HTTPException(422, "`result` must be valid SelectionWorkerResult JSON.") from error

    if payload.status == "segmented":
        if mask is None:
            raise HTTPException(422, "A segmented selection must include a `mask` file.")
        mask_key = await artifact_store.put_upload(
            job.project_id,
            job.upload_id,
            f"selections/{selection_id}-mask.png",
            mask,
            size_limit=MAX_UPLOAD_BYTES,
        )
        preview_key = mask_key
        if preview is not None:
            preview_key = await artifact_store.put_upload(
                job.project_id,
                job.upload_id,
                f"selections/{selection_id}-preview.png",
                preview,
                size_limit=MAX_UPLOAD_BYTES,
            )
        selection.mask_key = mask_key
        selection.preview_key = preview_key
        selection.mask_preview_url = (
            f"/v1/projects/{job.project_id}/uploads/{job.upload_id}"
            f"/selections/{selection_id}/mask"
        )
        selection.score = payload.score
        selection.alternatives = payload.alternatives
        selection.status = "segmented"
        selection.error = None
    else:
        selection.status = "failed"
        selection.score = None
        selection.error = payload.reason or "Nothing found matching that name; try being more specific."

    store.save_upload_record(upload)

    resolved = {item.selection_id for item in upload.selections if item.status in ("segmented", "failed")}
    if set(job.selection_ids) <= resolved:
        job.status = JobStatus.COMPLETE
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = utc_now()
        store.save_job(job)

    return selection


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
    if not store.get_job(job_id) or Path(filename).name != filename:
        raise HTTPException(404, "Unknown artifact.")
    return await artifact_store.serve(job_id, filename)


def validate_blueprint_assets(project: ProjectRecord, request: ExperienceBlueprintInput) -> None:
    object_ids = [item.id for item in request.objects]
    if len(object_ids) != len(set(object_ids)):
        raise HTTPException(422, "Blueprint object IDs must be unique.")
    known_assets = project_asset_ids(project)
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


# -- the room API (Build Plan step 21) ----------------------------------------
#
# The only backend surface a shipped Unity player may call for collaborative
# edits (AGENT.md Hard Rule 4). Headsets authenticate the same way the website
# does -- the X-SketchScape-Dev-User account header, no room token, no Clerk
# session (decision 2026-09-26; see collab-vr-accounts-and-gates and
# room-api-and-ownership). require_project_read/require_project_write already
# give this route the exact access rule the skill specifies: a project member
# or a service may GET /state; only a member (never a service) may POST
# /edits.


class RoomObjectView(BaseModel):
    """One object in a room's live state, from a headset's point of view."""

    id: str
    asset_id: str
    position: list[float]
    rotation: list[float]
    scale: list[float]
    interactions: list[str]
    owner_contributor_id: str | None = None
    editable_by_me: bool = False


class RoomStateResponse(BaseModel):
    project_id: str
    live_revision: int
    objects: list[RoomObjectView]
    # asset_id -> artifact URL (e.g. "/v1/artifacts/{job_id}/{filename}"), so a
    # headset can fetch every object's PLY with the exact same account header
    # or service token it used for this request -- no separate credential.
    artifact_urls: dict[str, str] = Field(default_factory=dict)
    experience: ExperienceSettings
    environment: EnvironmentSettings
    navigation: NavigationSettings
    # Step 28: sealed/opened state + a texture URL only when the caller may
    # see it (the author, a recipient, or -- once opened -- anyone).
    letters: list[RoomLetterView] = Field(default_factory=list)


class RoomEdit(BaseModel):
    """One object's absolute new transform. Only the fields that are set are
    applied and interaction-checked; omitted fields leave that axis alone."""

    object_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    position: list[float] | None = Field(default=None, min_length=3, max_length=3)
    rotation: list[float] | None = Field(default=None, min_length=3, max_length=3)
    scale: list[float] | None = Field(default=None, min_length=3, max_length=3)


class RoomEditRequest(BaseModel):
    base_revision: int = Field(ge=0)
    client_edit_id: str = Field(min_length=1, max_length=100)
    edits: list[RoomEdit] = Field(min_length=1, max_length=20)


# Sliding-window, in-process rate limiters (Build Plan step 21). Keyed by
# identity.user_id, separate buckets for the cheap polling read vs. the
# heavier, revision-checked write, per the room-api-and-ownership skill. A
# multi-instance deployment will need a shared limiter (e.g. Redis/DynamoDB);
# noted here rather than built, since this API still runs as one process.
_ROOM_EDIT_RATE_LIMIT_WINDOW_SECONDS = 1.0
_ROOM_EDIT_RATE_LIMIT_MAX_CALLS = 5
_room_edit_call_times: dict[str, list[float]] = {}
_ROOM_STATE_RATE_LIMIT_WINDOW_SECONDS = 1.0
_ROOM_STATE_RATE_LIMIT_MAX_CALLS = 20
_room_state_call_times: dict[str, list[float]] = {}


def _check_rate_limit(
    buckets: dict[str, list[float]], key: str, window_seconds: float, max_calls: int, detail: str
) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds
    calls = buckets.setdefault(key, [])
    while calls and calls[0] < cutoff:
        calls.pop(0)
    if len(calls) >= max_calls:
        raise HTTPException(429, detail)
    calls.append(now)


def check_room_edit_rate_limit(user_id: str) -> None:
    _check_rate_limit(
        _room_edit_call_times,
        user_id,
        _ROOM_EDIT_RATE_LIMIT_WINDOW_SECONDS,
        _ROOM_EDIT_RATE_LIMIT_MAX_CALLS,
        "Too many room edits; slow down and retry shortly.",
    )


def check_room_state_rate_limit(user_id: str) -> None:
    _check_rate_limit(
        _room_state_call_times,
        user_id,
        _ROOM_STATE_RATE_LIMIT_WINDOW_SECONDS,
        _ROOM_STATE_RATE_LIMIT_MAX_CALLS,
        "Too many room-state polls; slow down and retry shortly.",
    )


def _room_object_views(project_id: str, blueprint: ExperienceBlueprint, owned: set[str]) -> list[RoomObjectView]:
    contributions = {c.contribution_id: c for c in store.list_contributions(project_id)}
    views: list[RoomObjectView] = []
    for obj in blueprint.objects:
        contribution = contributions.get(obj.contribution_id or "")
        views.append(
            RoomObjectView(
                id=obj.id,
                asset_id=obj.asset_id,
                position=list(obj.position),
                rotation=list(obj.rotation),
                scale=list(obj.scale),
                interactions=list(obj.interactions),
                owner_contributor_id=contribution.contributor_id if contribution else None,
                editable_by_me=obj.id in owned,
            )
        )
    return views


@app.get("/v1/rooms/{project_id}/state")
async def get_room_state(
    project_id: str,
    request: Request,
    since_revision: Annotated[int | None, Query(ge=0)] = None,
    identity: Identity = Depends(require_project_read),
) -> Response:
    """A headset's (or the website's, or NemoClaw's) view of the live room.

    404 if nothing is published yet. Supports cheap polling: an ETag over the
    live revision, and ?since_revision=<N> as an equivalent alternative for a
    client that can't easily read response headers -- either one short-
    circuits to 304 when the room hasn't changed. Step 28 folds a
    letter-state version (a monotonic count of every open recorded for this
    project) into the ETag too, so a new open shows up in the next poll.
    """
    check_room_state_rate_limit(identity.user_id)
    project = get_project(project_id)
    live_revision = store.get_live_revision(project_id)
    if live_revision is None:
        live_revision = project.published_revision
    if live_revision is None:
        raise HTTPException(404, "This project has no published blueprint.")
    letters_version = store.letters_version(project_id)

    # The body is per-caller (editable_by_me, letter texture visibility), so
    # the ETag must be too: one headset switching Account 1 -> Account 2
    # resends its old If-None-Match, and a revision-only tag would 304 it
    # into keeping the other account's edit rights / letter visibility.
    # ?since_revision has no identity in it, so a client must drop it after
    # an account switch (documented in room-api-and-ownership).
    etag = f'"{project_id}:{live_revision}:{identity.user_id}:{letters_version}"'
    if request.headers.get("if-none-match") == etag or since_revision == live_revision:
        return Response(status_code=304, headers={"ETag": etag})

    blueprint = await get_blueprint(project_id, live_revision)
    owned = owned_object_ids(project_id, identity.user_id, blueprint)
    objects = _room_object_views(project_id, blueprint, owned)
    artifact_urls = {
        obj.asset_id: store.get_asset(obj.asset_id).artifact_url
        for obj in blueprint.objects
        if store.get_asset(obj.asset_id) and store.get_asset(obj.asset_id).artifact_url
    }
    letters = store.list_letters(project_id)
    viewer_contributor = (
        find_contributor_by_clerk_user(project_id, identity.user_id) if identity.kind != "service" else None
    )
    letter_views = room_letter_views(
        letters,
        {letter.letter_id: _opened_by(project_id, letter.letter_id) for letter in letters},
        {obj.asset_id: obj.id for obj in blueprint.objects},
        viewer_contributor_id=viewer_contributor.contributor_id if viewer_contributor else None,
        texture_url_for=lambda letter_id: f"/v1/projects/{project_id}/letters/{letter_id}/texture",
    )
    body = RoomStateResponse(
        project_id=project_id,
        live_revision=live_revision,
        objects=objects,
        artifact_urls=artifact_urls,
        experience=blueprint.experience,
        environment=blueprint.environment,
        navigation=blueprint.navigation,
        letters=letter_views,
    )
    return JSONResponse(content=body.model_dump(mode="json"), headers={"ETag": etag})


def _opened_by(project_id: str, letter_id: str) -> list[str]:
    """Contributor ids who have opened this letter (step 28)."""
    return [record.contributor_id for record in store.list_letter_opens(project_id, letter_id)]


def _validate_finite_vector(values: list[float], label: str) -> None:
    for value in values:
        if not math.isfinite(value):
            raise HTTPException(422, f"{label} must contain finite numbers.")


def _validate_bounded_vector(values: list[float], low: float, high: float, label: str) -> None:
    _validate_finite_vector(values, label)
    if any(v < low or v > high for v in values):
        raise HTTPException(422, f"{label} must be within [{low}, {high}] on every axis.")


@app.post("/v1/rooms/{project_id}/edits", status_code=201)
async def submit_room_edits(
    project_id: str,
    request: RoomEditRequest,
    identity: Identity = Depends(require_project_write),
) -> Response:
    """Apply a bounded, ownership-checked set of absolute transforms.

    ``require_project_write`` already rejects a service identity with 403
    (NemoClaw never calls this -- it drafts through the authoring API and a
    person approves the publish; see top-tier-nemoclaw-tool-design), so by the
    time this body runs, ``identity`` is always a person's account header.

    Server order (room-api-and-ownership): idempotency, ownership, allowed
    interactions, bounds, staleness, then one conditional append + LIVE
    pointer compare-and-set. Values are absolute, so a retried call with the
    same ``client_edit_id`` is harmless either way.
    """
    check_room_edit_rate_limit(identity.user_id)
    get_project(project_id)
    author = author_from_identity(identity)

    # 1. Idempotency: a previous call with this author + client_edit_id already
    # landed a revision -- replay it rather than re-applying (or 409ing on) it.
    for existing in store.list_blueprints(project_id):
        if existing.client_edit_id == request.client_edit_id and existing.author == author:
            live_now = store.get_live_revision(project_id) or 0
            return JSONResponse(
                status_code=200, content={"revision": existing.revision, "live_revision": live_now}
            )

    live_revision = store.get_live_revision(project_id)
    if live_revision is None:
        raise HTTPException(404, "This project has no published blueprint.")
    live_blueprint = await get_blueprint(project_id, live_revision)

    # 2. Ownership.
    owned = owned_object_ids(project_id, identity.user_id, live_blueprint)
    object_map = {obj.id: obj for obj in live_blueprint.objects}
    unknown_ids = sorted({edit.object_id for edit in request.edits} - set(object_map))
    if unknown_ids:
        raise HTTPException(422, f"Unknown object id(s): {', '.join(unknown_ids)}")
    not_owned = sorted({edit.object_id for edit in request.edits} - owned)
    if not_owned:
        raise HTTPException(403, f"Not editable by you: {', '.join(not_owned)}")

    # 3-4. Interaction allowlist + bounds, applied to copies of the live objects.
    updated_objects = {obj_id: obj.model_copy(deep=True) for obj_id, obj in object_map.items()}
    for edit in request.edits:
        if edit.position is None and edit.rotation is None and edit.scale is None:
            raise HTTPException(422, f"{edit.object_id}: set at least one of position/rotation/scale.")
        target = updated_objects[edit.object_id]
        if edit.position is not None:
            if "translate" not in target.interactions:
                raise HTTPException(422, f"{edit.object_id} does not allow translate.")
            _validate_bounded_vector(edit.position, -100.0, 100.0, f"{edit.object_id}.position")
            target.position = list(edit.position)
        if edit.rotation is not None:
            if "rotate" not in target.interactions:
                raise HTTPException(422, f"{edit.object_id} does not allow rotate.")
            _validate_finite_vector(edit.rotation, f"{edit.object_id}.rotation")
            target.rotation = [value % 360.0 for value in edit.rotation]
        if edit.scale is not None:
            if "scale" not in target.interactions:
                raise HTTPException(422, f"{edit.object_id} does not allow scale.")
            _validate_bounded_vector(edit.scale, 0.05, 20.0, f"{edit.object_id}.scale")
            target.scale = list(edit.scale)

    # 5. Staleness.
    if request.base_revision != live_revision:
        return JSONResponse(status_code=409, content={"live_revision": live_revision})

    # 6. Copy the LIVE blueprint (never the latest draft) with only these
    # transforms applied, validate, and append with a conditional write.
    new_input = ExperienceBlueprintInput(
        experience=live_blueprint.experience,
        environment=live_blueprint.environment,
        objects=list(updated_objects.values()),
        portals=live_blueprint.portals,
        navigation=live_blueprint.navigation,
    )
    project = get_project(project_id)
    validate_blueprint_assets(project, new_input)

    new_revision: ExperienceBlueprint | None = None
    last_error: RevisionConflict | None = None
    for _ in range(_MAX_BLUEPRINT_APPEND_ATTEMPTS):
        revisions = store.list_blueprints(project_id)
        candidate = ExperienceBlueprint(
            **new_input.model_dump(),
            project_id=project_id,
            revision=len(revisions) + 1,
            created_at=utc_now(),
            based_on_revision=request.base_revision,
            author=author,
            client_edit_id=request.client_edit_id,
        )
        try:
            store.append_blueprint(candidate)
        except RevisionConflict as error:
            last_error = error
            continue
        new_revision = candidate
        break
    if new_revision is None:
        raise HTTPException(
            409,
            f"Could not append a room-edit revision after {_MAX_BLUEPRINT_APPEND_ATTEMPTS} "
            f"attempts (too many concurrent writers); retry. Last conflict: {last_error}",
        )
    project.blueprint_revisions.append(new_revision.revision)
    project.updated_at = utc_now()
    store.save_project(project)

    # 7. LIVE pointer compare-and-set -- 409 if someone else published between
    # our staleness check above and this append.
    if not store.set_live_revision(project_id, request.base_revision, new_revision.revision):
        latest = store.get_live_revision(project_id)
        return JSONResponse(status_code=409, content={"live_revision": latest if latest is not None else 0})

    # Keep the legacy last-write-wins cache in sync, matching publish_blueprint.
    project.published_revision = new_revision.revision
    project.updated_at = utc_now()
    store.save_project(project)

    store.append_publication(
        PublicationRecord(
            project_id=project_id, revision=new_revision.revision, published_at=utc_now(), author=author
        )
    )
    global current_scene
    current_scene = compile_blueprint(new_revision)

    return JSONResponse(
        status_code=201, content={"revision": new_revision.revision, "live_revision": new_revision.revision}
    )


@app.get(
    "/v1/projects/{project_id}/assets/{asset_id}",
    response_model=ProjectAsset,
    dependencies=[Depends(require_project_read)],
)
async def get_project_asset(project_id: str, asset_id: str) -> ProjectAsset:
    """Return a single catalog asset with its full view provenance."""
    project = get_project(project_id)
    if asset_id not in project_asset_ids(project):
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
    if asset_id not in project_asset_ids(project):
        raise HTTPException(404, "Unknown asset for this project.")
    asset = store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(404, "Asset record not found.")
    if asset.status == AssetStatus.READY:
        # Adding more views to a READY asset is valid — additional angles may
        # improve the reconstruction or enable future fusion. The asset stays
        # READY from its first successful view.
        pass

    image_extension(image)
    raw_image = await read_upload_bytes(image)
    oriented_image, _, _, image_suffix = safe_exif_transpose(raw_image)
    job_id = uuid.uuid4().hex
    image_key = await artifact_store.put_upload(
        project_id, job_id, f"image{image_suffix}",
        _bytes_upload_file(oriented_image, f"image{image_suffix}"),
        size_limit=MAX_UPLOAD_BYTES,
    )
    mask_key: str | None = None
    if mask is not None:
        mask_suffix = image_extension(mask)
        raw_mask = await read_upload_bytes(mask)
        mask_key = await artifact_store.put_upload(
            project_id, job_id, f"mask{mask_suffix}",
            _bytes_upload_file(raw_mask, f"mask{mask_suffix}"),
            size_limit=MAX_UPLOAD_BYTES,
        )
    subject_hint, hint_source, label_backend = await resolve_subject_hint(
        subject_hint, oriented_image, image_suffix, image.filename or "", mask_key is not None
    )

    now = utc_now()
    view_index = len(asset.views)
    new_view = AssetView(
        view_index=view_index,
        image_key=image_key,
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
        kind="reconstruct",
        image_key=image_key,
        mask_key=mask_key,
    )
    store.save_job(job)
    dispatch_job(job, background_tasks)

    return new_view


# -- multi-object upload: person-chosen selections -> SAM 3.1 -> generate -----
#
# Build Plan step 26. The person picks which objects in a photo become 3D on
# the website; those choices are the SAM 3.1 prompts. Auto-detect only ever
# creates *suggested* selections -- nothing is generated without the person
# choosing. See docs/DATA_ARCHITECTURE.md's "Object selection flow".


class UploadCreateResponse(BaseModel):
    upload_id: str
    image_url: str
    width: int
    height: int


class JobIdResponse(BaseModel):
    job_id: str | None = None


class GenerateResponse(BaseModel):
    assets: list[ProjectAsset]
    jobs: list[ReconstructionJob]


def upload_image_url(project_id: str, upload_id: str) -> str:
    return f"/v1/projects/{project_id}/uploads/{upload_id}/image"


@app.post(
    "/v1/projects/{project_id}/uploads",
    response_model=UploadCreateResponse,
    status_code=201,
)
async def create_upload(
    project_id: str,
    image: Annotated[UploadFile, File(description="Photo or Notability sketch page")],
    identity: Identity = Depends(require_project_write),
) -> UploadCreateResponse:
    get_project(project_id)
    image_extension(image)  # 415 on an unsupported content type
    raw = await read_upload_bytes(image)
    oriented, width, height, suffix = safe_exif_transpose(raw)

    upload_id = uuid.uuid4().hex
    image_key = await artifact_store.put_upload(
        project_id, upload_id, f"source{suffix}",
        _bytes_upload_file(oriented, f"source{suffix}"),
        size_limit=MAX_UPLOAD_BYTES,
    )
    upload = UploadRecord(
        upload_id=upload_id,
        project_id=project_id,
        uploader_user_id=identity.user_id,
        image_key=image_key,
        width=width,
        height=height,
        created_at=utc_now(),
        original_filename=image.filename or "image",
    )
    store.save_upload_record(upload)
    return UploadCreateResponse(
        upload_id=upload_id,
        image_url=upload_image_url(project_id, upload_id),
        width=width,
        height=height,
    )


@app.get(
    "/v1/projects/{project_id}/uploads/{upload_id}",
    response_model=UploadRecord,
    dependencies=[Depends(require_project_read)],
)
async def get_upload(project_id: str, upload_id: str) -> UploadRecord:
    return get_upload_or_404(project_id, upload_id)


@app.get(
    "/v1/projects/{project_id}/uploads/{upload_id}/image",
    dependencies=[Depends(require_project_read)],
)
async def get_upload_image(project_id: str, upload_id: str) -> Response:
    upload = get_upload_or_404(project_id, upload_id)
    data = artifact_store.open_upload(upload.image_key)
    media_type = mimetypes.guess_type(upload.image_key)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)


@app.get(
    "/v1/projects/{project_id}/uploads/{upload_id}/selections/{selection_id}/mask",
    dependencies=[Depends(require_project_read)],
)
async def get_selection_mask(project_id: str, upload_id: str, selection_id: str) -> Response:
    upload = get_upload_or_404(project_id, upload_id)
    selection = next((item for item in upload.selections if item.selection_id == selection_id), None)
    if selection is None or selection.mask_key is None:
        raise HTTPException(404, "No mask for this selection.")
    return Response(content=artifact_store.open_upload(selection.mask_key), media_type="image/png")


@app.post(
    "/v1/projects/{project_id}/uploads/{upload_id}/selections",
    response_model=JobIdResponse,
    status_code=202,
)
async def create_selections(
    project_id: str,
    upload_id: str,
    request: SelectionsRequest,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(require_project_write),
) -> JobIdResponse:
    upload = get_upload_or_404(project_id, upload_id)
    require_upload_owner(upload, identity)
    for selection in request.selections:
        upload_pipeline.validate_selection_prompt(selection.prompt)

    existing_ids = {item.selection_id for item in upload.selections}
    # Idempotent resend: a selection_id we've already seen creates nothing new.
    new_selections = [item for item in request.selections if item.selection_id not in existing_ids]

    max_objects = upload_pipeline.max_objects_per_upload()
    if len(upload.selections) + len(new_selections) > max_objects:
        raise HTTPException(422, f"A photo may have at most {max_objects} selected objects.")

    if not new_selections:
        return JobIdResponse(job_id=None)

    upload.selections.extend(new_selections)
    store.save_upload_record(upload)

    job_id = uuid.uuid4().hex
    now = utc_now()
    job = ReconstructionJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=job_url(job_id),
        created_at=now,
        updated_at=now,
        project_id=project_id,
        kind="segment",
        upload_id=upload_id,
        selection_ids=[item.selection_id for item in new_selections],
        image_key=upload.image_key,
    )
    store.save_job(job)
    dispatch_job(job, background_tasks)
    return JobIdResponse(job_id=job_id)


@app.post(
    "/v1/projects/{project_id}/uploads/{upload_id}/selections/{selection_id}/refine",
    response_model=JobIdResponse,
    status_code=202,
)
async def refine_selection(
    project_id: str,
    upload_id: str,
    selection_id: str,
    request: RefineSelectionRequest,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(require_project_write),
) -> JobIdResponse:
    upload = get_upload_or_404(project_id, upload_id)
    require_upload_owner(upload, identity)
    selection = next((item for item in upload.selections if item.selection_id == selection_id), None)
    if selection is None:
        raise HTTPException(404, "Unknown selection.")
    selection.prompt = SelectionPrompt(text=request.text)
    upload_pipeline.validate_selection_prompt(selection.prompt)
    selection.status = "pending"
    selection.mask_key = None
    selection.preview_key = None
    selection.mask_preview_url = None
    store.save_upload_record(upload)

    job_id = uuid.uuid4().hex
    now = utc_now()
    job = ReconstructionJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=job_url(job_id),
        created_at=now,
        updated_at=now,
        project_id=project_id,
        kind="segment",
        upload_id=upload_id,
        selection_ids=[selection_id],
        image_key=upload.image_key,
    )
    store.save_job(job)
    dispatch_job(job, background_tasks)
    return JobIdResponse(job_id=job_id)


@app.delete(
    "/v1/projects/{project_id}/uploads/{upload_id}/selections/{selection_id}",
    status_code=204,
)
async def delete_selection(
    project_id: str,
    upload_id: str,
    selection_id: str,
    identity: Identity = Depends(require_project_write),
) -> Response:
    upload = get_upload_or_404(project_id, upload_id)
    require_upload_owner(upload, identity)
    remaining = [item for item in upload.selections if item.selection_id != selection_id]
    if len(remaining) == len(upload.selections):
        raise HTTPException(404, "Unknown selection.")
    upload.selections = remaining
    store.save_upload_record(upload)
    return Response(status_code=204)


@app.post(
    "/v1/projects/{project_id}/uploads/{upload_id}/detect",
    response_model=JobIdResponse,
    status_code=202,
)
async def detect_upload_objects(
    project_id: str,
    upload_id: str,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(require_project_write),
) -> JobIdResponse:
    """Optional auto-detect helper (skill item 6): NemoClaw's identify_subject
    as a text prompt, added as a *suggested* selection the person can keep or
    delete. Nothing generates without the person choosing."""
    upload = get_upload_or_404(project_id, upload_id)
    image_bytes = artifact_store.open_upload(upload.image_key)
    suffix = Path(upload.image_key).suffix or ".png"
    label = None
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(image_bytes)
        tmp.flush()
        try:
            label = await asyncio.to_thread(
                subject_labeler.identify_subject, Path(tmp.name), upload.original_filename
            )
        except SubjectLabelError:
            label = None
    if label is None:
        return JobIdResponse(job_id=None)

    selection = UploadSelection(
        selection_id=uuid.uuid4().hex,
        prompt=SelectionPrompt(text=label.label),
        label=label.label,
        origin="suggested",
    )
    max_objects = upload_pipeline.max_objects_per_upload()
    if len(upload.selections) >= max_objects:
        return JobIdResponse(job_id=None)
    upload.selections.append(selection)
    store.save_upload_record(upload)

    job_id = uuid.uuid4().hex
    now = utc_now()
    job = ReconstructionJob(
        job_id=job_id,
        status=JobStatus.QUEUED,
        poll_url=job_url(job_id),
        created_at=now,
        updated_at=now,
        project_id=project_id,
        kind="segment",
        upload_id=upload_id,
        selection_ids=[selection.selection_id],
        image_key=upload.image_key,
        subject_label_backend=label.backend,
    )
    store.save_job(job)
    dispatch_job(job, background_tasks)
    return JobIdResponse(job_id=job_id)


async def do_generate(
    project_id: str,
    upload_id: str,
    selection_ids: list[str],
    background_tasks: BackgroundTasks,
    identity: Identity,
    *,
    create_contribution: bool,
) -> tuple[list[ProjectAsset], list[ReconstructionJob]]:
    project = get_project(project_id)
    upload = get_upload_or_404(project_id, upload_id)
    by_id = {item.selection_id: item for item in upload.selections}
    missing = [sid for sid in selection_ids if sid not in by_id]
    if missing:
        raise HTTPException(422, f"Unknown selection id(s): {', '.join(sorted(missing))}")
    not_segmented = [sid for sid in selection_ids if by_id[sid].status != "segmented"]
    if not_segmented:
        raise HTTPException(409, f"Selections are not segmented yet: {', '.join(sorted(not_segmented))}")

    contributor = (
        find_contributor_by_clerk_user(project_id, identity.user_id)
        if identity.kind != "service"
        else None
    )

    now = utc_now()
    assets: list[ProjectAsset] = []
    jobs: list[ReconstructionJob] = []
    for selection_id in selection_ids:
        selection = by_id[selection_id]
        asset_id = uuid.uuid4().hex
        job_id = uuid.uuid4().hex
        label = (selection.label or "object")[:80]
        first_view = AssetView(
            view_index=0,
            image_key=upload.image_key,
            subject_hint=selection.label,
            subject_hint_source="user" if selection.label else None,
            reconstruction_job_id=job_id,
            recorded_at=now,
        )
        asset = ProjectAsset(
            asset_id=asset_id,
            project_id=project_id,
            label=label,
            status=AssetStatus.PROCESSING,
            reconstruction_job_id=job_id,
            views=[first_view],
        )
        store.save_asset(asset)
        store.link_asset(project_id, asset_id)
        assets.append(asset)

        job = ReconstructionJob(
            job_id=job_id,
            status=JobStatus.QUEUED,
            poll_url=job_url(job_id),
            created_at=now,
            updated_at=now,
            project_id=project_id,
            asset_id=asset_id,
            kind="reconstruct",
            upload_id=upload_id,
            selection_ids=[selection_id],
            image_key=upload.image_key,
            mask_key=selection.mask_key,
            subject_hint=selection.label,
        )
        store.save_job(job)
        dispatch_job(job, background_tasks)
        jobs.append(job)

        selection.status = "generated"

        if create_contribution and contributor is not None:
            contribution = Contribution(
                contribution_id=uuid.uuid4().hex,
                project_id=project_id,
                contributor_id=contributor.contributor_id,
                asset_id=asset_id,
                source_type="photo",
                memory_text=selection.memory_text.strip(),
                created_at=now,
            )
            store.append_contribution(contribution)
            project.contribution_ids.append(contribution.contribution_id)

    project.updated_at = now
    store.save_project(project)
    store.save_upload_record(upload)
    return assets, jobs


@app.post(
    "/v1/projects/{project_id}/uploads/{upload_id}/generate",
    response_model=GenerateResponse,
    status_code=202,
)
async def generate_selected_objects(
    project_id: str,
    upload_id: str,
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(require_project_write),
) -> GenerateResponse:
    upload = get_upload_or_404(project_id, upload_id)
    require_upload_owner(upload, identity)
    assets, reconstruct_jobs = await do_generate(
        project_id, upload_id, request.selection_ids, background_tasks, identity,
        create_contribution=True,
    )
    return GenerateResponse(assets=assets, jobs=reconstruct_jobs)


@app.get("/v1/projects/{project_id}/jobs")
async def list_project_jobs_route(
    project_id: str,
    request: Request,
    active: Annotated[int, Query()] = 0,
    since: Annotated[str | None, Query()] = None,
    identity: Identity = Depends(require_project_read),
) -> Response:
    """Batch job polling (skill item 7): one call covers every job in flight
    for a project. Read-only, store-only, cheap; supports If-None-Match."""
    get_project(project_id)
    matched = store.list_project_jobs(project_id, active_only=bool(active))
    if since:
        try:
            since_at = datetime.fromisoformat(since)
        except ValueError as error:
            raise HTTPException(422, "`since` must be an ISO 8601 timestamp.") from error
        matched = [job for job in matched if job.updated_at > since_at]
    matched.sort(key=lambda job: job.created_at, reverse=True)
    payload = [json.loads(job.model_dump_json()) for job in matched]
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    etag = hashlib.sha256(body).hexdigest()
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return JSONResponse(content=payload, headers={"ETag": etag})


class ClaimJobRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    kinds: list[JobKind] = Field(default_factory=lambda: ["segment", "reconstruct"])


@app.post("/v1/internal/jobs/claim")
async def claim_internal_job(
    request: ClaimJobRequest,
    worker_token: Annotated[str | None, Header(alias="X-SketchScape-Worker-Token")] = None,
) -> Response:
    """Worker-only (skill item 9): claim the oldest queued job of a given kind."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    lease_seconds = int(os.environ.get("SKETCHSCAPE_JOB_LEASE_SECONDS", "900"))
    job = store.claim_next_job(request.worker_id, list(request.kinds), lease_seconds)
    if job is None:
        return Response(status_code=204)
    return JSONResponse(content=json.loads(job.model_dump_json()))


@app.post("/v1/internal/jobs/{job_id}/lease")
async def renew_internal_job_lease(
    job_id: str,
    worker_id: Annotated[str, Form()],
    worker_token: Annotated[str | None, Form()] = None,
) -> dict[str, bool]:
    """Worker-only (skill item 9): renew a claimed job's lease."""
    if not worker_is_authorized(worker_token):
        raise HTTPException(401, "Invalid GPU worker token.")
    lease_seconds = int(os.environ.get("SKETCHSCAPE_JOB_LEASE_SECONDS", "900"))
    renewed = store.renew_lease(job_id, worker_id, lease_seconds)
    return {"renewed": renewed}


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


def image_dimensions(data: bytes) -> tuple[int, int]:
    """Width and height of a PNG or baseline/progressive JPEG, without Pillow."""
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
    raw = await read_upload_bytes(image)
    width, height = image_dimensions(raw)
    if width <= 0 or height <= 0:
        raise HTTPException(422, "The sketch image has no pixels.")
    scale = SKETCH_CARD_LONG_SIDE_METERS / max(width, height)
    card_width, card_height = round(width * scale, 4), round(height * scale, 4)
    await artifact_store.put(
        asset_id, filename, _bytes_upload_file(raw, filename), size_limit=MAX_UPLOAD_BYTES
    )

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
    store.link_asset(project.project_id, asset_id)
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
_MOCK_OBJECT_INTERACTIONS: list[Literal["highlight", "inspect", "scale", "translate", "rotate", "activate", "grab"]] = [
    "highlight",
    "inspect",
    "rotate",
]
# Something one person can comfortably hold, in meters (largest side).
PICKUP_MAX_SIZE_METERS = 0.6
# Hand-held things, for assets whose real size is still unknown (mock mode
# reconstructions report the default 1 m bounds).
_PICKUP_LABEL_WORDS = frozenset(
    {
        "mug", "cup", "teacup", "teapot", "bowl", "plate", "spoon", "jar", "bottle", "candle",
        "book", "notebook", "journal", "letter", "postcard", "photo", "frame", "camera", "phone",
        "shell", "stone", "rock", "ball", "toy", "plush", "doll", "figurine", "kite",
        "ring", "watch", "necklace", "bracelet", "key", "keychain", "glasses", "hat", "box",
    }
)


def is_pickup_sized(asset: ProjectAsset) -> bool:
    """Whether a room object is small enough to pick up (sketch cards stay on their stands)."""
    if asset.kind != "reconstruction":
        return False
    size = max(bound * scale for bound, scale in zip(asset.bounds, asset.suggested_scale))
    return size <= PICKUP_MAX_SIZE_METERS or bool(_mock_tokens(asset.label) & _PICKUP_LABEL_WORDS)


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
                interactions=list(_MOCK_OBJECT_INTERACTIONS) + (["grab"] if is_pickup_sized(asset) else []),
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


# Build Plan step 28: letters routes (backend/letter_routes.py). Imported
# here, at the very end, so its own `from main import ...` (store,
# artifact_store, helper functions) sees a fully-defined module.
from letter_routes import router as letter_router  # noqa: E402

app.include_router(letter_router)
