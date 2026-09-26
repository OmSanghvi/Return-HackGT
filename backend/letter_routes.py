"""Letters routes: upload, list, and recipient-only open (Build Plan step 28).

See `letters.py` for the data model and access rules, and the
`letters-backend-and-web` skill for the full route contract. Registered with
a single `app.include_router(letter_router)` line at the very end of
`main.py` -- by the time that import runs, everything imported from `main`
below is already defined on the module, so this top-level `from main import
...` is safe despite the mutual reference.
"""

from __future__ import annotations

import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image

from auth import Identity
from letters import (
    Letter,
    LetterOpenResponse,
    LetterView,
    letter_view,
    may_see_page,
    validate_recipients,
)
from main import (
    MAX_UPLOAD_BYTES,
    AssetStatus,
    Contribution,
    ProjectAsset,
    _bytes_upload_file,
    artifact_store,
    find_contributor_by_clerk_user,
    get_project,
    image_dimensions,
    image_extension,
    read_upload_bytes,
    require_project_read,
    require_project_write,
    store,
    utc_now,
)

router = APIRouter(tags=["letters"])

# Long edge of the Unity-facing texture (Pillow resize, no GPU job -- skill's
# "textured 3D paper mesh ... at full resolution" means no SAM3D
# reconstruction, not "never downscale"; 2048px keeps handwriting legible).
TEXTURE_LONG_EDGE_PX = 2048


def _render_texture(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as source:
        image = source.convert("RGB")
        width, height = image.size
        scale = TEXTURE_LONG_EDGE_PX / max(width, height)
        if scale < 1.0:
            image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def _letter_or_404(project_id: str, letter_id: str) -> Letter:
    letter = store.get_letter(project_id, letter_id)
    if letter is None:
        raise HTTPException(404, "Unknown letter.")
    return letter


def _viewer_contributor_id(project_id: str, identity: Identity) -> str | None:
    """The caller's contributor id in this project, or None (service caller,
    or a mock-mode identity never bound to a contributor -- see
    `create_contributor`'s mock-mode binding rule)."""
    if identity.kind == "service":
        return None
    contributor = find_contributor_by_clerk_user(project_id, identity.user_id)
    return contributor.contributor_id if contributor else None


def _opened_by(project_id: str, letter_id: str) -> list[str]:
    return [record.contributor_id for record in store.list_letter_opens(project_id, letter_id)]


def _texture_url(project_id: str, letter_id: str) -> str:
    return f"/v1/projects/{project_id}/letters/{letter_id}/texture"


@router.post("/v1/projects/{project_id}/letters", response_model=Letter, status_code=201)
async def create_letter(
    project_id: str,
    page: Annotated[UploadFile, File(description="Letter page: JPEG, PNG, or WebP")],
    author_contributor_id: Annotated[str, Form()],
    recipient_contributor_ids: Annotated[list[str], Form()],
    note_text: Annotated[str | None, Form(max_length=2000)] = None,
    envelope_style: Annotated[str, Form()] = "classic",
    memory_text: Annotated[str, Form(max_length=1000)] = "",
    identity: Identity = Depends(require_project_write),
) -> Letter:
    """Store a Notability page as a sealed letter addressed to its recipients.

    ``status=ready`` immediately -- no reconstruction job, no GPU, matching
    the sketch-card path this mirrors.
    """
    del identity  # membership already enforced by require_project_write
    project = get_project(project_id)
    if author_contributor_id not in project.contributor_ids:
        raise HTTPException(422, f"Unknown author contributor id: {author_contributor_id}")
    try:
        recipients = validate_recipients(
            recipient_contributor_ids, author_contributor_id, set(project.contributor_ids)
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if envelope_style not in ("classic",):
        raise HTTPException(422, f"Unknown envelope_style: {envelope_style}")

    ext = image_extension(page)  # 415 on an unsupported content type
    raw = await read_upload_bytes(page, limit=MAX_UPLOAD_BYTES)
    width, height = image_dimensions(raw)
    if width <= 0 or height <= 0:
        raise HTTPException(422, "The letter page has no pixels.")
    aspect_ratio = round(width / height, 6)

    letter_id = uuid.uuid4().hex
    page_key = await artifact_store.put(
        letter_id, f"page{ext}", _bytes_upload_file(raw, f"page{ext}"), size_limit=MAX_UPLOAD_BYTES
    )
    texture_bytes = _render_texture(raw)
    texture_key = await artifact_store.put(
        letter_id,
        "texture-2048.png",
        _bytes_upload_file(texture_bytes, "texture-2048.png"),
        size_limit=MAX_UPLOAD_BYTES,
    )

    now = utc_now()
    asset = ProjectAsset(
        asset_id=letter_id,
        project_id=project_id,
        label="Letter",
        status=AssetStatus.READY,
        kind="letter",
        reconstruction_job_id="",
        # Access-gated (sealed/opened); never served from the public/generic
        # artifact route, so no artifact_url/preview_url here.
        artifact_url=None,
        preview_url=None,
        bounds=[1.0, 1.0, 0.02],
        suggested_scale=[1.0, 1.0, 1.0],
    )
    store.save_asset(asset)
    store.link_asset(project_id, asset.asset_id)

    contribution = Contribution(
        contribution_id=uuid.uuid4().hex,
        project_id=project_id,
        contributor_id=author_contributor_id,
        asset_id=asset.asset_id,
        source_type="letter",
        memory_text=memory_text.strip(),
        created_at=now,
    )
    store.append_contribution(contribution)
    project.contribution_ids.append(contribution.contribution_id)
    project.updated_at = now
    store.save_project(project)

    letter = Letter(
        letter_id=letter_id,
        project_id=project_id,
        author_contributor_id=author_contributor_id,
        recipient_contributor_ids=recipients,
        asset_id=asset.asset_id,
        contribution_id=contribution.contribution_id,
        page_key=page_key,
        texture_key=texture_key,
        aspect_ratio=aspect_ratio,
        note_text=(note_text or "").strip(),
        envelope_style=envelope_style,
        created_at=now,
    )
    store.save_letter(letter)
    return letter


@router.get("/v1/projects/{project_id}/letters", response_model=list[LetterView])
async def list_project_letters(
    project_id: str, identity: Identity = Depends(require_project_read)
) -> list[LetterView]:
    get_project(project_id)
    viewer = _viewer_contributor_id(project_id, identity)
    return [
        letter_view(
            letter,
            _opened_by(project_id, letter.letter_id),
            viewer_contributor_id=viewer,
            image_url=_texture_url(project_id, letter.letter_id),
        )
        for letter in store.list_letters(project_id)
    ]


@router.get("/v1/projects/{project_id}/letters/{letter_id}/texture")
async def get_letter_texture(
    project_id: str, letter_id: str, identity: Identity = Depends(require_project_read)
):
    """The 2048px texture Unity renders on the paper mesh -- gated by
    `may_see_page` (sealed: author + recipients only; opened: everyone)."""
    letter = _letter_or_404(project_id, letter_id)
    viewer = _viewer_contributor_id(project_id, identity)
    if not may_see_page(
        author_contributor_id=letter.author_contributor_id,
        recipient_contributor_ids=letter.recipient_contributor_ids,
        opened_by=_opened_by(project_id, letter_id),
        viewer_contributor_id=viewer,
    ):
        raise HTTPException(403, "This letter is sealed.")
    filename = letter.texture_key.rsplit("/", 1)[-1]
    return await artifact_store.serve(letter_id, filename)


@router.post("/v1/rooms/{project_id}/letters/{letter_id}/open", response_model=LetterOpenResponse)
async def open_letter(
    project_id: str, letter_id: str, identity: Identity = Depends(require_project_write)
) -> LetterOpenResponse:
    """Recipient-only open. Idempotent: a repeat open by the same recipient
    (or a different one) still returns 200 with who opened it first."""
    letter = _letter_or_404(project_id, letter_id)
    viewer = _viewer_contributor_id(project_id, identity)
    if viewer is None or viewer not in letter.recipient_contributor_ids:
        raise HTTPException(403, "Only an addressed recipient may open this letter.")
    store.record_letter_open(project_id, letter_id, viewer, utc_now())
    opens = store.list_letter_opens(project_id, letter_id)
    first = min(opens, key=lambda record: record.opened_at)
    return LetterOpenResponse(opened=True, opened_by=first.contributor_id, opened_at=first.opened_at)
