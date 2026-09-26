"""Deterministic grounding check, shared by two steps of the guided tour bot:

- Build Plan step 30 (`guided_tour.validate_guided_tour`): checks that an
  `authored` fact and a step's `narration` never introduce a name, number, or
  quote that isn't already in the facts it's derived from, or in the tour's
  own vocabulary.
- Build Plan step 32 (the live guide runtime, not built yet): the same check
  runs against a model turn's spoken lines before they ever reach Unity.

No model call, no network. It never judges paraphrase quality -- it only
guarantees no new name, number, or quoted span appears, so ordinary lowercase
prose is always allowed through.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))


def _tokenize(text: str | None) -> set[str]:
    return {match.group(0).lower() for match in _WORD_PATTERN.finditer(text or "")}


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for open_ch, close_ch in _QUOTE_PAIRS:
        start = 0
        while True:
            open_index = text.find(open_ch, start)
            if open_index == -1:
                break
            close_index = text.find(close_ch, open_index + 1)
            if close_index == -1:
                break
            spans.append((open_index, close_index))
            start = close_index + 1
    return spans


def _sentence_start_positions(text: str) -> set[int]:
    """Character offsets where a new sentence's first word begins."""
    starts: set[int] = set()
    first = _WORD_PATTERN.search(text)
    if first:
        starts.add(first.start())
    for boundary in re.finditer(r"[.!?]\s+", text):
        following = _WORD_PATTERN.search(text, boundary.end())
        if following:
            starts.add(following.start())
    return starts


def grounding_violations(text: str, facts: list[str], vocab: list[str]) -> list[str]:
    """Tokens in `text` that aren't licensed by `facts` or `vocab`.

    The allowed set is the lower-cased word tokens of `facts` (fact text)
    plus `vocab` (contributor display names, element labels, the theme
    title, the persona name). A token in `text` is a violation when it's a
    capitalized word that doesn't start a sentence, a token containing a
    digit, or a token inside a quoted span -- and its lower case isn't in
    the allowed set. Returns the list of violating tokens verbatim (empty
    means grounded).
    """
    allowed: set[str] = set()
    for fact_text in facts:
        allowed |= _tokenize(fact_text)
    for entry in vocab:
        allowed |= _tokenize(entry)

    text = text or ""
    sentence_starts = _sentence_start_positions(text)
    quoted_spans = _quoted_spans(text)

    violations: list[str] = []
    for match in _WORD_PATTERN.finditer(text):
        token = match.group(0)
        if token.lower() in allowed:
            continue
        is_capitalized_mid_sentence = token[:1].isupper() and match.start() not in sentence_starts
        has_digit = any(char.isdigit() for char in token)
        is_quoted = any(start <= match.start() < end for start, end in quoted_spans)
        if is_capitalized_mid_sentence or has_digit or is_quoted:
            violations.append(token)
    return violations


# ---------------------------------------------------------------------------
# validate_turn / scripted_turn (Build Plan step 32, the live guide runtime)
# ---------------------------------------------------------------------------
#
# Deterministic repairs only -- never a second model call. `tour` is a
# `GuidedTour`; `allowed` is a `guide_tools.Allowed`; `event` is the raw
# event dict; `args` is the model's parsed `guide_turn` tool-call arguments
# (or None, on no tool call). `current_step_id` is the session's step to
# fall back to -- kept as an explicit argument (rather than read off a
# `session` object) so this module stays standalone, the same way
# `guided_tour.py` takes plain data instead of importing a store.


class TurnLinePlan(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class TurnPlan(BaseModel):
    """The deterministic, fully-validated shape `guide.py` turns into a response."""

    intent: str
    step_id: str
    say: list[TurnLinePlan]
    highlight_element_ids: list[str] = Field(default_factory=list)
    reveal_element_ids: list[str] = Field(default_factory=list)
    move_to_element_id: str = ""
    end: bool = False


class _GuideTurnSayItem(BaseModel):
    text: str = Field(max_length=400)
    fact_ids: list[str] = Field(min_length=1)


class GuideTurnArgs(BaseModel):
    """The `guide_turn` tool call's arguments, exactly as the schema in
    `guide_tools.build_guide_tool` shapes them."""

    intent: Literal["answer", "narrate", "decline", "end"]
    step_id: str
    say: list[_GuideTurnSayItem] = Field(min_length=1)
    highlight_element_ids: list[str] = Field(default_factory=list)
    reveal_element_ids: list[str] = Field(default_factory=list)
    move_to_element_id: str = ""


def _tour_vocab(tour: Any) -> list[str]:
    """Contributor display names, element labels, the theme title, the
    persona name -- built straight from the tour document, no social
    manifest needed (unlike `guided_tour._build_vocab`, which validates a
    draft against one)."""
    vocab: list[str] = [tour.theme.title, tour.persona.name]
    vocab.extend(element.label for element in tour.elements if element.label)
    vocab.extend(
        element.contributor_display_name
        for element in tour.elements
        if element.contributor_display_name
    )
    return vocab


def scripted_turn(tour: Any, step_id: str) -> TurnPlan:
    """The deterministic turn for a step: its narration, verbatim, with its
    focus/reveal/stop. Used for `start`/`repeat`/`next`, and as the fallback
    target whenever a model turn can't be trusted."""
    step = next((candidate for candidate in tour.steps if candidate.step_id == step_id), None)
    if step is None:
        raise ValueError(f"scripted_turn: unknown step_id {step_id!r} for this tour.")
    return TurnPlan(
        intent="narrate",
        step_id=step_id,
        say=[TurnLinePlan(text=step.narration.text, fact_ids=list(step.narration.fact_ids))],
        highlight_element_ids=list(step.focus_element_ids),
        reveal_element_ids=list(step.reveal_element_ids),
        move_to_element_id=step.stop.anchor_element_id,
        end=step_id in tour.end_step_ids,
    )


def validate_turn(
    tour: Any, allowed: "Any", event: dict, args: dict | None, current_step_id: str
) -> tuple[TurnPlan, list[str]]:
    """Deterministically validate/repair a model's `guide_turn` call.

    Returns `(plan, repairs)`. `repairs` is empty when the model's turn was
    used unmodified; otherwise it names each repair kind applied. A turn
    that can't be salvaged (bad schema, unknown step, no lines survive)
    falls back to `scripted_turn(tour, current_step_id)`, with the fallback
    reason appended to `repairs` so callers can label `source: "fallback"`.
    """
    repairs: list[str] = []
    if args is None:
        return scripted_turn(tour, current_step_id), ["no_tool_call"]
    try:
        parsed = GuideTurnArgs.model_validate(args)
    except ValidationError:
        return scripted_turn(tour, current_step_id), ["invalid_tool_args"]

    step_id = parsed.step_id if parsed.step_id in allowed.step_ids else current_step_id
    if parsed.step_id not in allowed.step_ids:
        repairs.append("step_id_out_of_allowed_set")
    step = next((candidate for candidate in tour.steps if candidate.step_id == step_id), None)
    if step is None:
        return scripted_turn(tour, current_step_id), repairs + ["unknown_step"]

    highlight = [eid for eid in parsed.highlight_element_ids if eid in allowed.element_ids]
    if len(highlight) != len(parsed.highlight_element_ids):
        repairs.append("dropped_unknown_highlight_ids")

    reveal_allowed = set(step.reveal_element_ids) & set(allowed.reveal_ids)
    reveal = [eid for eid in parsed.reveal_element_ids if eid in reveal_allowed]
    if len(reveal) != len(parsed.reveal_element_ids):
        repairs.append("dropped_disallowed_reveal_ids")

    move_to = parsed.move_to_element_id
    if move_to not in ("", step.stop.anchor_element_id):
        repairs.append("move_to_reset_to_step_anchor")
        move_to = step.stop.anchor_element_id

    facts_by_id = {fact.fact_id: fact for fact in tour.facts}
    allowed_fact_ids = set(allowed.fact_ids)
    vocab = _tour_vocab(tour)

    say: list[TurnLinePlan] = []
    if parsed.intent == "decline":
        say = [TurnLinePlan(text=tour.guardrails.off_topic_reply, fact_ids=[])]
    else:
        for item in parsed.say:
            cited = [fid for fid in item.fact_ids if fid in allowed_fact_ids and fid in facts_by_id]
            if len(cited) != len(item.fact_ids):
                repairs.append("dropped_ungrounded_fact_ids")
            if not cited:
                repairs.append("dropped_line_with_no_grounded_facts")
                continue
            cited_texts = [facts_by_id[fid].text for fid in cited]
            if grounding_violations(item.text, cited_texts, vocab):
                repairs.append("repaired_ungrounded_text")
                text = " ".join(cited_texts)
            else:
                text = item.text
            say.append(TurnLinePlan(text=text, fact_ids=cited))

    if not say:
        return scripted_turn(tour, step_id), repairs + ["no_lines_after_repair"]

    plan = TurnPlan(
        intent=parsed.intent,
        step_id=step_id,
        say=say,
        highlight_element_ids=highlight,
        reveal_element_ids=reveal,
        move_to_element_id=move_to,
        end=parsed.intent == "end" or step_id in tour.end_step_ids,
    )
    return plan, repairs
