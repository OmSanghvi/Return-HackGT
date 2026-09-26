"""Guide runtime routes (Build Plan step 32): `/v1/rooms/{project_id}/guide/*`.

Kept in its own ``APIRouter`` module and registered with a single
``app.include_router(router)`` line at the very end of ``main.py``, the same
pattern ``letter_routes.py`` and ``tour_routes.py`` already use -- see
``tour_routes.py``'s module docstring for why the top-level ``from main
import ...`` below is safe despite the mutual reference.

All three routes use the same identity header and membership check as
``/v1/rooms/*`` (``require_project_read``); they work before the room API's
own edits route matters here because they only need step 17's membership.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from guide import GuideEngine, GuideTurnRequestBody, GuideTurnResponse, stale_element_ids

from main import (  # noqa: E402 - see module docstring
    check_room_edit_rate_limit,
    get_blueprint,
    get_project,
    require_project_read,
    store,
)

router = APIRouter(tags=["guide"])


class GuideTourStepView(BaseModel):
    step_id: str
    stop_anchor_element_id: str
    stop_offset_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    focus_element_ids: list[str] = Field(default_factory=list)
    reveal_element_ids: list[str] = Field(default_factory=list)


class GuideTourElementView(BaseModel):
    element_id: str
    object_id: str = ""
    staging_cue_id: str = ""
    initially_visible: bool = True


class GuideTourResponse(BaseModel):
    tour_available: bool
    tour_version: int = 0
    persona: dict = Field(default_factory=dict)
    steps: list[GuideTourStepView] = Field(default_factory=list)
    elements: list[GuideTourElementView] = Field(default_factory=list)
    stale_element_ids: list[str] = Field(default_factory=list)


class GuideSessionResponse(BaseModel):
    session_id: str
    tour_version: int
    turn: GuideTurnResponse


async def _active_tour_and_live_objects(project_id: str) -> tuple[Any, set[str]]:
    """The active tour plus the live blueprint's object ids, or 404.

    Both routes that run a turn need this; `GET /guide/tour` computes the
    same pair to report `stale_element_ids` (tolerating a missing live
    blueprint there instead of 404ing, since Unity should still see the
    tour shape at scene load even if publishing hasn't happened yet).
    """
    active_version = store.get_active_tour_version(project_id)
    if active_version is None:
        raise HTTPException(404, "This project has no active guide tour.")
    tour = store.get_tour(project_id, active_version)
    if tour is None:
        raise HTTPException(404, "This project has no active guide tour.")
    live_revision = store.get_live_revision(project_id)
    if live_revision is None:
        raise HTTPException(404, "This project has no published blueprint.")
    blueprint = await get_blueprint(project_id, live_revision)
    return tour, {obj.id for obj in blueprint.objects}


@router.get(
    "/v1/rooms/{project_id}/guide/tour",
    response_model=GuideTourResponse,
    dependencies=[Depends(require_project_read)],
)
async def get_guide_tour(project_id: str) -> GuideTourResponse:
    get_project(project_id)
    active_version = store.get_active_tour_version(project_id)
    if active_version is None:
        return GuideTourResponse(tour_available=False)
    tour = store.get_tour(project_id, active_version)
    if tour is None:
        return GuideTourResponse(tour_available=False)

    live_object_ids: set[str] = set()
    live_revision = store.get_live_revision(project_id)
    if live_revision is not None:
        blueprint = await get_blueprint(project_id, live_revision)
        live_object_ids = {obj.id for obj in blueprint.objects}

    return GuideTourResponse(
        tour_available=True,
        tour_version=tour.tour_version,
        persona=tour.persona.model_dump(mode="json"),
        steps=[
            GuideTourStepView(
                step_id=step.step_id,
                stop_anchor_element_id=step.stop.anchor_element_id,
                stop_offset_m=list(step.stop.offset_m),
                focus_element_ids=list(step.focus_element_ids),
                reveal_element_ids=list(step.reveal_element_ids),
            )
            for step in tour.steps
        ],
        elements=[
            GuideTourElementView(
                element_id=element.element_id,
                object_id=element.object_id or "",
                staging_cue_id=element.staging_cue_id or "",
                initially_visible=element.initially_visible,
            )
            for element in tour.elements
        ],
        stale_element_ids=stale_element_ids(tour, live_object_ids),
    )


@router.post(
    "/v1/rooms/{project_id}/guide/sessions",
    response_model=GuideSessionResponse,
    status_code=201,
)
async def create_guide_session(project_id: str, identity=Depends(require_project_read)) -> GuideSessionResponse:
    get_project(project_id)
    tour, _live_object_ids = await _active_tour_and_live_objects(project_id)
    engine = GuideEngine(store)
    session, turn = await engine.start_session(project_id, identity.user_id, tour)
    return GuideSessionResponse(session_id=session.session_id, tour_version=tour.tour_version, turn=turn)


@router.post(
    "/v1/rooms/{project_id}/guide/sessions/{session_id}/turns",
    response_model=GuideTurnResponse,
)
async def post_guide_turn(
    project_id: str,
    session_id: str,
    request: GuideTurnRequestBody,
    identity=Depends(require_project_read),
) -> GuideTurnResponse:
    # Turns share the room API's write rate-limit bucket (Build Plan 32.6).
    check_room_edit_rate_limit(identity.user_id)
    get_project(project_id)
    tour, live_object_ids = await _active_tour_and_live_objects(project_id)
    engine = GuideEngine(store)
    return await engine.handle_turn(project_id, session_id, tour, live_object_ids, request)
