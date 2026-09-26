"""Guided tour routes (Build Plan steps 30-31): draft -> activate.

Kept in its own ``APIRouter`` module, registered from ``main.py`` with a
single ``app.include_router(router)`` line placed at the very end of that
file, so this file never needs to edit ``main.py``'s body while other Build
Plan tracks are also changing it.

Importing from ``main`` at module scope here is safe even though ``main``
also imports this module: ``main.py`` does that import as the very last line
in the file, after every name this module needs (``store``, ``get_project``,
``require_project_read`` and friends, the Pydantic models) is already
defined. When Python reaches that bottom line, ``main`` is already present
in ``sys.modules`` (currently executing), so ``from main import ...`` here
just reads attributes off the already-populated module -- the same
"import at the bottom to avoid a cycle" trick ``storage.py``'s module
docstring describes.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import Identity, require_user
from guided_tour import GuidedTour, GuidedTourInput, compose_tour_mock, validate_guided_tour
from storage import RevisionConflict

from main import (  # noqa: E402 - see module docstring
    author_from_identity,
    compile_social_manifest,
    enforce_project_access,
    get_blueprint,
    get_project,
    require_project_draft,
    require_project_read,
    store,
    utc_now,
)

router = APIRouter()

_MAX_TOUR_APPEND_ATTEMPTS = 5


class TourSummary(BaseModel):
    """List-view row for `GET /v1/projects/{project_id}/tours`."""

    tour_version: int
    status: Literal["draft", "active", "retired"]
    based_on_revision: int
    authored_by: dict
    created_at: str


class ActivateTourRequest(BaseModel):
    expected_active_version: int | None = None


def _tour_author_backend() -> str:
    return os.environ.get("SKETCHSCAPE_TOUR_AUTHOR", "mock").strip().lower()


def _live_revision(project_id: str) -> int | None:
    project = get_project(project_id)
    live_revision = store.get_live_revision(project_id)
    return live_revision if live_revision is not None else project.published_revision


def _store_tour_draft(project_id: str, tour_input: GuidedTourInput, author: str | None) -> GuidedTour:
    last_error: RevisionConflict | None = None
    for _ in range(_MAX_TOUR_APPEND_ATTEMPTS):
        existing = store.list_tours(project_id)
        tour = GuidedTour(
            **tour_input.model_dump(),
            project_id=project_id,
            tour_version=len(existing) + 1,
            status="draft",
            created_at=utc_now(),
            author=author,
        )
        try:
            store.append_tour(tour)
        except RevisionConflict as error:
            last_error = error
            continue
        return tour
    raise HTTPException(
        409,
        f"Could not create a new tour version after {_MAX_TOUR_APPEND_ATTEMPTS} attempts "
        "(too many concurrent authors).",
    ) from last_error


def _run_nemoclaw_tour_author(project_id: str) -> None:
    """Background task for `SKETCHSCAPE_TOUR_AUTHOR=nemoclaw`'s `/tours/compose`.

    Calls the same `author_guided_tour` tool step 31's CLI/agent wrapper
    uses (`tour_author.py`), so `/tours/compose` and a direct NemoClaw tool
    call go through one mechanism, not two. Runs detached from the request
    that triggered it, so an exception here is logged, not raised.
    """
    import tour_author  # noqa: PLC0415 - optional, only needed on this path

    try:
        tour_author.author_guided_tour(project_id)
    except Exception:  # noqa: BLE001 - see docstring
        logging.getLogger(__name__).exception("author_guided_tour(%s) failed in the background", project_id)


@router.post("/v1/projects/{project_id}/tours/compose", status_code=201)
async def compose_tour(
    project_id: str,
    background_tasks: BackgroundTasks,
    identity: Identity = Depends(require_project_draft),
):
    live_revision = _live_revision(project_id)
    if live_revision is None:
        raise HTTPException(409, "This project has no published (LIVE) blueprint yet.")
    insights = store.list_connection_insights(project_id)
    if not insights:
        raise HTTPException(409, "This project has no ConnectionInsight yet; run connection/compose first.")
    latest_insight = insights[-1]

    composer = _tour_author_backend()
    if composer == "mock":
        blueprint = await get_blueprint(project_id, live_revision)
        contributions = store.list_contributions(project_id)
        contributors = {c.contributor_id: c for c in store.list_contributors(project_id)}
        social_manifest = compile_social_manifest(blueprint)
        assets = {obj.asset_id: store.get_asset(obj.asset_id) for obj in blueprint.objects}
        tour_input = compose_tour_mock(
            blueprint, latest_insight, contributions, contributors, social_manifest, assets
        )
        return _store_tour_draft(project_id, tour_input, author_from_identity(identity))
    if composer == "nemoclaw":
        background_tasks.add_task(_run_nemoclaw_tour_author, project_id)
        return JSONResponse(status_code=202, content={"status": "authoring"})
    raise HTTPException(500, f"Unknown SKETCHSCAPE_TOUR_AUTHOR '{composer}'. Use 'mock' or 'nemoclaw'.")


@router.post("/v1/projects/{project_id}/tours", response_model=GuidedTour, status_code=201)
async def create_tour(
    project_id: str,
    request: GuidedTourInput,
    identity: Identity = Depends(require_project_draft),
) -> GuidedTour:
    live_revision = _live_revision(project_id)
    if live_revision is None or request.based_on_revision != live_revision:
        raise HTTPException(
            409,
            f"based_on_revision {request.based_on_revision} is not the currently published "
            f"revision ({live_revision}).",
        )
    blueprint = await get_blueprint(project_id, request.based_on_revision)
    contributions = store.list_contributions(project_id)
    social_manifest = compile_social_manifest(blueprint)
    validate_guided_tour(
        request,
        blueprint=blueprint,
        social_manifest=social_manifest,
        contributions=contributions,
        letters=store.list_letters(project_id),
    )
    return _store_tour_draft(project_id, request, author_from_identity(identity))


@router.get(
    "/v1/projects/{project_id}/tours",
    response_model=list[TourSummary],
    dependencies=[Depends(require_project_read)],
)
async def list_tours(project_id: str) -> list[TourSummary]:
    get_project(project_id)
    return [
        TourSummary(
            tour_version=tour.tour_version,
            status=tour.status,
            based_on_revision=tour.based_on_revision,
            authored_by=tour.authored_by.model_dump(),
            created_at=tour.created_at.isoformat(),
        )
        for tour in store.list_tours(project_id)
    ]


@router.get(
    "/v1/projects/{project_id}/tours/{tour_version}",
    response_model=GuidedTour,
    dependencies=[Depends(require_project_read)],
)
async def get_tour(project_id: str, tour_version: int) -> GuidedTour:
    get_project(project_id)
    tour = store.get_tour(project_id, tour_version)
    if tour is None:
        raise HTTPException(404, "Unknown tour version.")
    return tour


@router.post("/v1/projects/{project_id}/tours/{tour_version}/activate", response_model=GuidedTour)
async def activate_tour(
    project_id: str,
    tour_version: int,
    request: ActivateTourRequest,
    identity: Identity = Depends(require_user),
) -> GuidedTour:
    # People only: NemoClaw drafts, a person approves. `require_user` above
    # already turns a service identity into a 403 before this body runs.
    enforce_project_access(project_id, identity, capability="write")
    get_project(project_id)
    tour = store.get_tour(project_id, tour_version)
    if tour is None:
        raise HTTPException(404, "Unknown tour version.")
    current = store.get_active_tour_version(project_id)
    if current != request.expected_active_version:
        raise HTTPException(
            409,
            f"expected_active_version {request.expected_active_version} is stale; the currently "
            f"active tour version is {current}.",
        )
    activated = store.activate_tour(project_id, request.expected_active_version, tour_version)
    if activated is None:
        latest = store.get_active_tour_version(project_id)
        raise HTTPException(
            409,
            f"expected_active_version {request.expected_active_version} is stale; the currently "
            f"active tour version is {latest}.",
        )
    return activated


@router.get(
    "/v1/projects/{project_id}/connection/insights",
    dependencies=[Depends(require_project_read)],
)
async def list_connection_insights_route(project_id: str):
    """Read-only: the project's ConnectionInsight history, in revision order.

    Added in step 31 so NemoClaw's `author_guided_tour` tool can read the
    latest insight without reaching into the store directly.
    """
    get_project(project_id)
    return store.list_connection_insights(project_id)
