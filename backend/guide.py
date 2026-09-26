"""The guide turn engine (Build Plan step 32): routing, limits, memory, audio.

Owns the request/response and session/turn models used by
`backend/guide_routes.py` and `backend/storage.py`, plus `GuideEngine`, which
turns one `GuideTurnRequestBody` into a validated `GuideTurnResponse`.

Only the backend ever calls Muse (Hard Rule 4); the key lives in the
backend process env only. Mock is the default provider (Hard Rule 2), and
scripted events (`start`, `next`, `repeat`, `end`) never call the model.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

import guide_tts
from guide_model import GuideModel, create_guide_model
from guide_prompts import GUIDE_PROMPT_VERSION
from guide_tools import allowed_sets, build_guide_tool
from guide_validator import TurnPlan, scripted_turn, validate_turn

# Events the router never sends to the model.
_SCRIPTED_EVENT_TYPES = {"start", "next", "repeat", "end"}
_RECENT_EVENTS_KEPT = 20
_RECENT_EVENTS_IN_PROMPT = 8


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Store schema
# ---------------------------------------------------------------------------


class GuideSession(BaseModel):
    """`GUIDESESSION#<session_id>` (docs/DATA_ARCHITECTURE.md)."""

    session_id: str
    project_id: str
    account: str
    tour_version: int
    current_step_id: str
    visited_step_ids: list[str] = Field(default_factory=list)
    said_fact_ids: list[str] = Field(default_factory=list)
    revealed_element_ids: list[str] = Field(default_factory=list)
    recent_events: list[dict] = Field(default_factory=list)
    turn_count: int = 0
    created_at: datetime
    active: bool = True

    def memory_dict(self) -> dict:
        return {
            "current_step_id": self.current_step_id,
            "visited_step_ids": self.visited_step_ids,
            "said_fact_ids": self.said_fact_ids,
            "revealed_element_ids": self.revealed_element_ids,
            "recent_events": self.recent_events[-_RECENT_EVENTS_IN_PROMPT:],
        }


class GuideTurn(BaseModel):
    """`GUIDETURN#<session_id>#<turn_seq padded 4>` -- the audit trail."""

    project_id: str
    session_id: str
    turn_seq: int
    client_turn_id: str
    event: dict
    response: dict
    usage: dict = Field(default_factory=dict)
    latency_ms: int = 0
    created_at: datetime


# ---------------------------------------------------------------------------
# API request/response models (JsonUtility-friendly: no nulls, "" / [] instead)
# ---------------------------------------------------------------------------


class GuideEvent(BaseModel):
    type: Literal["start", "next", "repeat", "end", "more", "ask_about", "linger", "question"]
    element_id: str = ""
    text: str = Field(default="", max_length=300)

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {"type": self.type}
        if self.element_id:
            payload["element_id"] = self.element_id
        if self.text:
            payload["text"] = self.text
        return payload


class GuideTurnRequestBody(BaseModel):
    client_turn_id: str = Field(min_length=1, max_length=100)
    turn_seq: int = Field(ge=0)
    event: GuideEvent


class GuideTurnLine(BaseModel):
    line_id: str
    text: str
    fact_ids: list[str] = Field(default_factory=list)
    audio_url: str = ""
    duration_s: float = 0.0


class GuideMoveTo(BaseModel):
    anchor_element_id: str = ""
    offset_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])


class GuideValidationInfo(BaseModel):
    passed: bool
    repairs: list[str] = Field(default_factory=list)


class GuideTurnResponse(BaseModel):
    turn_seq: int
    step_id: str
    end: bool
    lines: list[GuideTurnLine] = Field(default_factory=list)
    move_to: GuideMoveTo
    highlight_element_ids: list[str] = Field(default_factory=list)
    reveal_element_ids: list[str] = Field(default_factory=list)
    source: Literal["scripted", "model", "repaired", "fallback"]
    backend: str
    model: str
    validation: GuideValidationInfo
    latency_ms: int


class GuideTurnConflict(BaseModel):
    """Body of a 409: the caller's `turn_seq`/`client_turn_id` didn't match,
    so here's the session's actual last turn to resync against."""

    turn_count: int
    last_turn: GuideTurnResponse | None = None


def _guide_max_turns() -> int:
    return int(os.environ.get("SKETCHSCAPE_GUIDE_MAX_TURNS_PER_SESSION", "60"))


def _guide_daily_model_turns() -> int:
    return int(os.environ.get("SKETCHSCAPE_GUIDE_DAILY_MODEL_TURNS", "500"))


def _guide_model_timeout_s() -> float:
    return float(os.environ.get("SKETCHSCAPE_GUIDE_MODEL_TIMEOUT_S", "15"))


def _guide_routing() -> str:
    return os.environ.get("SKETCHSCAPE_GUIDE_ROUTING", "hybrid").strip().lower()


def stale_element_ids(tour: Any, live_object_ids: set[str]) -> list[str]:
    return sorted(
        element.element_id
        for element in tour.elements
        if element.object_id is not None and element.object_id not in live_object_ids
    )


# Repair kinds from `validate_turn` that mean the plan actually used is
# `scripted_turn`'s output, not the model's -- these turns are `"fallback"`,
# never `"repaired"` (a repaired turn still carries the model's own choice
# of step/intent, just with some ids/text corrected).
_FALLBACK_REPAIR_REASONS = {"no_tool_call", "invalid_tool_args", "unknown_step", "no_lines_after_repair"}


class GuideEngine:
    """`handle_turn`/`start_session` are the entry points `guide_routes.py` calls.

    `store` is an `AuthoringStore` (duck-typed here to keep this module
    import-light); `model` defaults to `create_guide_model()`, overridable
    for tests (`FakeGuideModel`).
    """

    def __init__(self, store: Any, *, model: GuideModel | None = None) -> None:
        self.store = store
        self._model_override = model

    def _model(self) -> GuideModel:
        return self._model_override or create_guide_model()

    async def start_session(self, project_id: str, account: str, tour: Any) -> tuple[GuideSession, GuideTurnResponse]:
        """Create (and make active) a new session, and return its deterministic
        `start` turn. One active session per `(project_id, account)` -- the
        store retires any prior one."""
        import uuid

        session = GuideSession(
            session_id=uuid.uuid4().hex,
            project_id=project_id,
            account=account,
            tour_version=tour.tour_version,
            current_step_id=tour.start_step_id,
            created_at=_utc_now(),
        )
        plan = scripted_turn(tour, tour.start_step_id)
        already_revealed = set(session.revealed_element_ids)
        self._apply_memory(session, plan, {"type": "start"})
        session.turn_count = 1
        response = await self._materialize(
            project_id, tour, plan, turn_seq=0, source="scripted", backend="mock", model="scripted",
            latency_ms=0, already_revealed=already_revealed,
        )
        self.store.create_guide_session(session)
        self.store.append_guide_turn(
            project_id,
            GuideTurn(
                project_id=project_id,
                session_id=session.session_id,
                turn_seq=0,
                client_turn_id="__start__",
                event={"type": "start"},
                response=response.model_dump(mode="json"),
                created_at=_utc_now(),
            ),
        )
        return session, response

    async def handle_turn(
        self,
        project_id: str,
        session_id: str,
        tour: Any,
        live_object_ids: set[str],
        request: GuideTurnRequestBody,
    ) -> GuideTurnResponse:
        stored_session = self.store.get_guide_session(project_id, session_id)
        if stored_session is None:
            raise HTTPException(404, "Unknown guide session.")
        # `LocalJsonStore` returns a live reference, not a copy; mutate our
        # own copy so the compare-and-set below still sees the store's
        # unmodified `turn_count` to check against.
        session = stored_session.model_copy(deep=True)

        existing_turn = self.store.get_guide_turn_by_client_id(project_id, session_id, request.client_turn_id)
        if existing_turn is not None:
            return GuideTurnResponse.model_validate(existing_turn.response)

        if request.turn_seq != session.turn_count:
            last_turn = self.store.get_guide_turn_by_seq(project_id, session_id, session.turn_count - 1)
            raise HTTPException(
                409,
                {
                    "turn_count": session.turn_count,
                    "last_turn": last_turn.response if last_turn else None,
                    "detail": f"turn_seq {request.turn_seq} does not match the session's turn_count {session.turn_count}.",
                },
            )
        if session.turn_count >= _guide_max_turns():
            raise HTTPException(429, "This guide session has reached its turn limit.")

        event = request.event.to_dict()
        allowed = allowed_sets(tour, session.memory_dict(), event, live_object_ids)
        old_turn_count = session.turn_count

        already_revealed = set(session.revealed_element_ids)
        if event["type"] == "end":
            plan = TurnPlan(intent="end", step_id=session.current_step_id, say=[], end=True)
            response = await self._materialize(
                project_id, tour, plan, turn_seq=request.turn_seq, source="scripted", backend="mock",
                model="scripted", latency_ms=0, already_revealed=already_revealed,
            )
            self._apply_memory(session, plan, event)
        elif event["type"] in _SCRIPTED_EVENT_TYPES:
            step_id = self._scripted_next_step_id(tour, session, event["type"], allowed.step_ids)
            plan = scripted_turn(tour, step_id)
            response = await self._materialize(
                project_id, tour, plan, turn_seq=request.turn_seq, source="scripted", backend="mock",
                model="scripted", latency_ms=0, already_revealed=already_revealed,
            )
            self._apply_memory(session, plan, event)
        else:
            response = await self._model_turn(project_id, tour, session, allowed, event, request.turn_seq)

        session.turn_count = old_turn_count + 1
        updated = self.store.update_guide_session(project_id, session_id, old_turn_count, session.model_dump(mode="json"))
        if updated is None:
            current = self.store.get_guide_session(project_id, session_id)
            raise HTTPException(
                409,
                {
                    "turn_count": current.turn_count if current else old_turn_count,
                    "last_turn": None,
                    "detail": "Another turn for this session won the race; retry with the current turn_count.",
                },
            )

        self.store.append_guide_turn(
            project_id,
            GuideTurn(
                project_id=project_id,
                session_id=session_id,
                turn_seq=request.turn_seq,
                client_turn_id=request.client_turn_id,
                event=event,
                response=response.model_dump(mode="json"),
                latency_ms=response.latency_ms,
                created_at=_utc_now(),
            ),
        )
        return response

    # -- routing --------------------------------------------------------

    def _scripted_next_step_id(self, tour: Any, session: "GuideSession", event_type: str, allowed_step_ids: list[str]) -> str:
        steps_by_id = {step.step_id: step for step in tour.steps}
        current = steps_by_id.get(session.current_step_id)
        if event_type == "repeat" or current is None:
            return session.current_step_id
        if event_type == "next":
            for next_id in current.next_step_ids:
                if next_id in allowed_step_ids:
                    return next_id
            return session.current_step_id
        return session.current_step_id

    async def _model_turn(
        self, project_id: str, tour: Any, session: "GuideSession", allowed, event: dict, turn_seq: int
    ) -> GuideTurnResponse:
        routing = _guide_routing()
        today = _utc_now().strftime("%Y-%m-%d")
        over_cap = (
            routing != "model_all"
            and self.store.increment_guide_daily_usage(project_id, today) > _guide_daily_model_turns()
        )

        repairs: list[str] = []
        if over_cap:
            plan = scripted_turn(tour, session.current_step_id)
            source, backend, model_name, usage, latency_ms = "fallback", "mock", "mock-guide-v1", {}, 0
        else:
            model = self._model()
            tool = build_guide_tool(tour, allowed)
            try:
                args, usage, latency_ms = await asyncio.wait_for(
                    model.turn(tour, session.memory_dict(), event, tool, _guide_model_timeout_s()),
                    timeout=_guide_model_timeout_s(),
                )
            except Exception:  # noqa: BLE001 - any model failure (timeout, network, bad response) falls back
                args, usage, latency_ms = None, {}, 0
            plan, repairs = validate_turn(tour, allowed, event, args, session.current_step_id)
            if repairs and set(repairs) & _FALLBACK_REPAIR_REASONS:
                source = "fallback"
            elif repairs:
                source = "repaired"
            else:
                source = "model"
            backend, model_name = model.backend, model.model

        already_revealed = set(session.revealed_element_ids)
        self._apply_memory(session, plan, event)
        return await self._materialize(
            project_id, tour, plan, turn_seq=turn_seq, source=source, backend=backend, model=model_name,
            latency_ms=latency_ms, already_revealed=already_revealed, repairs=repairs, usage=usage,
        )

    # -- memory + response assembly --------------------------------------

    def _apply_memory(self, session: "GuideSession", plan: TurnPlan, event: dict) -> "GuideSession":
        session.current_step_id = plan.step_id
        if plan.step_id not in session.visited_step_ids:
            session.visited_step_ids.append(plan.step_id)
        for line in plan.say:
            for fact_id in line.fact_ids:
                if fact_id not in session.said_fact_ids:
                    session.said_fact_ids.append(fact_id)
        for element_id in plan.reveal_element_ids:
            if element_id not in session.revealed_element_ids:
                session.revealed_element_ids.append(element_id)
        session.recent_events.append(event)
        session.recent_events = session.recent_events[-_RECENT_EVENTS_KEPT:]
        return session

    async def _materialize(
        self,
        project_id: str,
        tour: Any,
        plan: TurnPlan,
        *,
        turn_seq: int,
        source: str,
        backend: str,
        model: str,
        latency_ms: int,
        already_revealed: set[str] = frozenset(),
        repairs: list[str] | None = None,
        usage: dict | None = None,
    ) -> GuideTurnResponse:
        lines: list[GuideTurnLine] = []
        for index, line in enumerate(plan.say):
            audio_url, duration_s = await guide_tts.synthesize(project_id, line.text, tour.persona.voice)
            lines.append(
                GuideTurnLine(
                    line_id=f"t{turn_seq}_{index}",
                    text=line.text,
                    fact_ids=line.fact_ids,
                    audio_url=audio_url,
                    duration_s=duration_s,
                )
            )
        reveal_ids = [eid for eid in plan.reveal_element_ids if eid not in already_revealed]
        step = next((s for s in tour.steps if s.step_id == plan.step_id), None)
        offset = list(step.stop.offset_m) if step is not None else [0.0, 0.0, 0.0]
        return GuideTurnResponse(
            turn_seq=turn_seq,
            step_id=plan.step_id,
            end=plan.end,
            lines=lines,
            move_to=GuideMoveTo(anchor_element_id=plan.move_to_element_id, offset_m=offset),
            highlight_element_ids=plan.highlight_element_ids,
            reveal_element_ids=reveal_ids,
            source=source,  # type: ignore[arg-type]
            backend=backend,
            model=model,
            validation=GuideValidationInfo(passed=source in ("scripted", "model"), repairs=repairs or []),
            latency_ms=latency_ms,
        )
