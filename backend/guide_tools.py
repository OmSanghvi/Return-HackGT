"""The per-turn `guide_turn` tool: which ids Muse may reference this turn.

Standalone like `guided_tour.py` -- it takes plain data (the active tour, the
session's memory dict, the raw event dict, and the live blueprint's object
ids) and returns the allowed id sets plus the tool schema built from them. No
model call, no store access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Allowed:
    step_ids: list[str] = field(default_factory=list)
    fact_ids: list[str] = field(default_factory=list)
    element_ids: list[str] = field(default_factory=list)
    reveal_ids: list[str] = field(default_factory=list)
    move_ids: list[str] = field(default_factory=list)


def _live_element_ids(tour: Any, live_object_ids: set[str]) -> set[str]:
    """Elements whose `object_id` is still in the live blueprint (motifs, whose
    `object_id` is always None, are never stale)."""
    return {
        element.element_id
        for element in tour.elements
        if element.object_id is None or element.object_id in live_object_ids
    }


def allowed_sets(tour: Any, session: dict, event: dict, live_object_ids: set[str]) -> Allowed:
    live_element_ids = _live_element_ids(tour, live_object_ids)
    steps_by_id = {step.step_id: step for step in tour.steps}

    # step_ids: every step anchored on a still-live element.
    step_ids = [
        step.step_id for step in tour.steps if step.stop.anchor_element_id in live_element_ids
    ]

    # fact_ids: the theme's facts always; more depends on the event type.
    fact_ids: set[str] = set(tour.theme.fact_ids)
    event_type = event.get("type")
    current_step = steps_by_id.get(session.get("current_step_id"))
    if event_type == "question":
        fact_ids |= {fact.fact_id for fact in tour.facts}
    elif event_type in ("ask_about", "linger"):
        element_id = event.get("element_id")
        element = next((e for e in tour.elements if e.element_id == element_id), None)
        if element is not None:
            fact_ids |= set(element.fact_ids)
        if current_step is not None:
            fact_ids |= set(current_step.fact_ids)
    elif event_type == "more":
        if current_step is not None:
            fact_ids |= set(current_step.fact_ids)
            for focus_id in current_step.focus_element_ids:
                element = next((e for e in tour.elements if e.element_id == focus_id), None)
                if element is not None:
                    fact_ids |= set(element.fact_ids)

    # element_ids (highlight): non-stale elements that are visible, or
    # already revealed, plus any hidden element the chosen step(s) reveal.
    revealed = set(session.get("revealed_element_ids", []))
    visible_or_revealed = {
        element.element_id
        for element in tour.elements
        if element.element_id in live_element_ids
        and (element.initially_visible or element.element_id in revealed)
    }
    reveal_candidates: set[str] = set()
    for step in tour.steps:
        if step.step_id in step_ids:
            reveal_candidates |= set(step.reveal_element_ids)
    element_ids = visible_or_revealed | (reveal_candidates & live_element_ids)

    # reveal_ids: union of reveal_element_ids over allowed steps.
    reveal_ids = reveal_candidates & live_element_ids

    # move_ids: the stop anchors of the allowed steps, plus "".
    move_ids = {steps_by_id[sid].stop.anchor_element_id for sid in step_ids}
    move_ids.add("")

    return Allowed(
        step_ids=sorted(step_ids),
        fact_ids=sorted(fact_ids),
        element_ids=sorted(element_ids),
        reveal_ids=sorted(reveal_ids),
        move_ids=sorted(move_ids),
    )


def build_guide_tool(tour: Any, allowed: Allowed) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "guide_turn",
            "description": (
                "Your only way to respond. Choose what the guide does next "
                "using ONLY ids and facts from the tour JSON."
            ),
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "intent",
                    "step_id",
                    "say",
                    "highlight_element_ids",
                    "reveal_element_ids",
                    "move_to_element_id",
                ],
                "properties": {
                    "intent": {"type": "string", "enum": ["answer", "narrate", "decline", "end"]},
                    "step_id": {"type": "string", "enum": allowed.step_ids or [""]},
                    "say": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": tour.guardrails.max_lines_per_turn,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["text", "fact_ids"],
                            "properties": {
                                "text": {"type": "string", "maxLength": 400},
                                "fact_ids": {
                                    "type": "array",
                                    "minItems": 1,
                                    "items": {"type": "string", "enum": allowed.fact_ids or [""]},
                                },
                            },
                        },
                    },
                    "highlight_element_ids": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string", "enum": allowed.element_ids or [""]},
                    },
                    "reveal_element_ids": {
                        "type": "array",
                        "maxItems": 3,
                        "items": {"type": "string", "enum": allowed.reveal_ids or [""]},
                    },
                    "move_to_element_id": {"type": "string", "enum": allowed.move_ids or [""]},
                },
            },
        },
    }
