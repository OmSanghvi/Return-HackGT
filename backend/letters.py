"""Notability letters: data model and pure access rules (Build Plan step 28).

See the `letters-backend-and-web` skill for the full contract. This module
owns only the Pydantic models and the access-control logic both the routes
(`letter_routes.py`) and the room-state code in `main.py` depend on -- no
FastAPI routes and no storage implementation live here (`backend/storage.py`
owns persistence).

A letter's ``asset_id`` is always its own ``letter_id`` -- one id for both,
so a letter is a `ProjectAsset(kind="letter")` like any other contributed
object (attribution, blueprint placement) without a second id to keep in
sync.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Literal

from pydantic import BaseModel, Field

EnvelopeStyle = Literal["classic"]
ENVELOPE_STYLES: tuple[EnvelopeStyle, ...] = ("classic",)
MAX_NOTE_TEXT_LENGTH = 2000


class LetterSceneRef(BaseModel):
    """Runtime fields Unity needs on a letter's compiled scene object.

    The texture URL is deliberately absent here -- it depends on who's
    asking (sealed vs. opened), so Unity reads it from room state, not the
    compiled scene (which is cached and shared across every caller).
    """

    letter_id: str
    recipient_contributor_ids: list[str] = Field(min_length=1)
    aspect_ratio: float = Field(gt=0)
    envelope_style: EnvelopeStyle = "classic"


class Letter(BaseModel):
    letter_id: str
    project_id: str
    author_contributor_id: str
    recipient_contributor_ids: list[str] = Field(min_length=1)
    # Same id as the backing ProjectAsset and Contribution.asset_id.
    asset_id: str
    contribution_id: str
    page_key: str
    texture_key: str
    aspect_ratio: float = Field(gt=0)
    note_text: str = Field(default="", max_length=MAX_NOTE_TEXT_LENGTH)
    envelope_style: EnvelopeStyle = "classic"
    created_at: datetime


class LetterOpenRecord(BaseModel):
    project_id: str
    letter_id: str
    contributor_id: str
    opened_at: datetime


class LetterView(BaseModel):
    """What `GET /v1/projects/{id}/letters` returns for one letter.

    ``note_text``/``image_url`` are only populated when the caller may see
    them (the author, a recipient, or -- once opened -- anyone).
    """

    letter_id: str
    author_contributor_id: str
    recipient_contributor_ids: list[str]
    envelope_style: EnvelopeStyle
    aspect_ratio: float
    sealed: bool
    opened_by: list[str]
    note_text: str | None
    image_url: str | None


class LetterOpenResponse(BaseModel):
    opened: bool
    opened_by: str
    opened_at: datetime


class RoomLetterView(BaseModel):
    """One letter's entry in `GET /v1/rooms/{id}/state`'s `letters` list."""

    letter_id: str
    object_id: str
    recipients: list[str]
    opened: bool
    texture_url: str | None = None


def validate_recipients(
    recipient_contributor_ids: list[str],
    author_contributor_id: str,
    project_contributor_ids: set[str],
) -> list[str]:
    """Dedup + validate recipients. Raises ``ValueError`` (the route turns
    it into a 422) for:

    - no recipients at all
    - a recipient who isn't a contributor of this project
    - the author as the only recipient
    """
    if not recipient_contributor_ids:
        raise ValueError("A letter needs at least one recipient.")
    unique = list(dict.fromkeys(recipient_contributor_ids))  # order-preserving dedup
    unknown = [r for r in unique if r not in project_contributor_ids]
    if unknown:
        raise ValueError(f"Unknown recipient contributor id(s): {', '.join(unknown)}")
    if unique == [author_contributor_id]:
        raise ValueError("A letter can't be addressed only to its own author.")
    return unique


def may_see_page(
    *,
    author_contributor_id: str,
    recipient_contributor_ids: list[str],
    opened_by: list[str],
    viewer_contributor_id: str | None,
) -> bool:
    """Sealed: only the author and its recipients. Opened: everyone, since
    the whole room watched it open live."""
    if opened_by:
        return True
    if viewer_contributor_id is None:
        return False
    return viewer_contributor_id == author_contributor_id or viewer_contributor_id in recipient_contributor_ids


def letter_view(
    letter: Letter,
    opened_by: list[str],
    *,
    viewer_contributor_id: str | None,
    image_url: str | None,
) -> LetterView:
    visible = may_see_page(
        author_contributor_id=letter.author_contributor_id,
        recipient_contributor_ids=letter.recipient_contributor_ids,
        opened_by=opened_by,
        viewer_contributor_id=viewer_contributor_id,
    )
    return LetterView(
        letter_id=letter.letter_id,
        author_contributor_id=letter.author_contributor_id,
        recipient_contributor_ids=letter.recipient_contributor_ids,
        envelope_style=letter.envelope_style,
        aspect_ratio=letter.aspect_ratio,
        sealed=not opened_by,
        opened_by=opened_by,
        note_text=letter.note_text if visible else None,
        image_url=image_url if visible else None,
    )


def room_letter_views(
    letters: list[Letter],
    opens_by_letter: dict[str, list[str]],
    object_id_by_asset_id: dict[str, str],
    *,
    viewer_contributor_id: str | None,
    texture_url_for: Callable[[str], str],
) -> list[RoomLetterView]:
    """Build the `letters` list for `GET /v1/rooms/{id}/state`.

    A letter with no matching blueprint object (not yet placed by
    place_objects_in_scene) is skipped -- room state only describes what's
    actually in the published scene.
    """
    views: list[RoomLetterView] = []
    for letter in letters:
        object_id = object_id_by_asset_id.get(letter.asset_id)
        if object_id is None:
            continue
        opened_by = opens_by_letter.get(letter.letter_id, [])
        visible = may_see_page(
            author_contributor_id=letter.author_contributor_id,
            recipient_contributor_ids=letter.recipient_contributor_ids,
            opened_by=opened_by,
            viewer_contributor_id=viewer_contributor_id,
        )
        views.append(
            RoomLetterView(
                letter_id=letter.letter_id,
                object_id=object_id,
                recipients=letter.recipient_contributor_ids,
                opened=bool(opened_by),
                texture_url=texture_url_for(letter.letter_id) if visible else None,
            )
        )
    return views
