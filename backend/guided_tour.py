"""Guided tour contract (Build Plan step 30): shared/guided-tour.schema.json.

A guide bot inside the VR room (step 32) may say and do **only** what a
``GuidedTour`` document contains, so this module has two jobs:

1. Define the JSON shape (mirrored in ``shared/guided-tour.schema.json``).
2. ``validate_guided_tour``: prove a candidate document is closed (every id
   it can reference exists in the document) and true (every fact traces back
   to something a person wrote, NemoClaw's recorded insight, or a fixed set
   of connective words for sealed letters).

This module is deliberately standalone -- it takes plain data (a blueprint's
objects, the social manifest, the project's contributions) as arguments
instead of importing ``main`` or touching the store, the same way
``scene_tools.py`` keeps its layout reasoning free of a live LLM or a live
store. ``backend/tour_routes.py`` does the wiring: it loads the blueprint and
contributions from the store and calls the pure functions here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from guide_validator import grounding_violations

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$"

MAX_STEPS = 30
MAX_FACTS = 400
MAX_ELEMENTS = 200
MAX_SERIALIZED_BYTES = 256 * 1024

# Words a `letter_envelope` fact may use beyond the tour's own vocabulary
# (contributor names, element labels, the theme title, the persona name).
_LETTER_ENVELOPE_EXTRA_WORDS = frozenset(
    {"letter", "from", "for", "to", "sealed", "a", "an", "the", "is", "this", "and"}
)

# Common short words never treated as "sealed content" when checking that a
# letter's private text hasn't leaked into a fact -- keeps the leak check
# from flagging incidental overlap on filler words.
_SEALED_CONTENT_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "this", "and", "to", "for", "from", "of", "in", "on",
        "at", "me", "my", "we", "our", "it", "its", "i", "you", "your", "was", "were",
        "be", "been", "am", "are", "that", "with", "as", "by",
    }
)

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")


class TourFactSource(BaseModel):
    kind: Literal[
        "connection_insight",
        "placement_rationale",
        "contribution_memory",
        "attribution",
        "room_prompt",
        "letter_envelope",
        "authored",
    ]
    ref_id: str | None = Field(default=None, max_length=120)


class TourFact(BaseModel):
    fact_id: str = Field(pattern=ID_PATTERN)
    text: str = Field(min_length=1, max_length=500)
    source: TourFactSource
    derived_from: list[str] = Field(default_factory=list, max_length=20)


class TourElement(BaseModel):
    element_id: str = Field(pattern=ID_PATTERN)
    kind: Literal["contribution", "environment", "letter", "motif"]
    object_id: str | None = Field(default=None, pattern=ID_PATTERN)
    contributor_id: str | None = Field(default=None, max_length=80)
    contributor_display_name: str | None = Field(default=None, max_length=100)
    label: str = Field(default="", max_length=200)
    fact_ids: list[str] = Field(default_factory=list, max_length=50)
    staging_cue_id: str | None = Field(default=None, max_length=80)
    initially_visible: bool = True


class TourStop(BaseModel):
    anchor_element_id: str = Field(pattern=ID_PATTERN)
    offset_m: list[float] = Field(min_length=3, max_length=3)


class TourNarration(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    fact_ids: list[str] = Field(default_factory=list, max_length=50)


class TourStep(BaseModel):
    step_id: str = Field(pattern=ID_PATTERN)
    title: str = Field(default="", max_length=100)
    stop: TourStop
    focus_element_ids: list[str] = Field(default_factory=list, max_length=50)
    reveal_element_ids: list[str] = Field(default_factory=list, max_length=50)
    fact_ids: list[str] = Field(default_factory=list, max_length=50)
    narration: TourNarration
    next_step_ids: list[str] = Field(default_factory=list, max_length=10)
    min_dwell_s: float = Field(default=3.0, ge=0, le=30)


class TourGuardrails(BaseModel):
    off_topic_reply: str = Field(min_length=1, max_length=300)
    max_lines_per_turn: int = Field(default=3, ge=1, le=10)


class TourPersona(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    voice: Literal["mms-tts-eng"] = "mms-tts-eng"
    style: Literal["warm", "playful", "calm"] = "warm"


class TourTheme(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    fact_ids: list[str] = Field(default_factory=list, max_length=20)


class TourAuthoredBy(BaseModel):
    backend: Literal["mock", "meta", "xai", "nebius"]
    model: str = Field(min_length=1, max_length=120)
    tool: str = Field(min_length=1, max_length=80)
    prompt_version: str | None = Field(default=None, max_length=40)


class GuidedTourInput(BaseModel):
    """The document `POST /v1/projects/{id}/tours` accepts and validates."""

    schema_version: Literal[1] = 1
    based_on_revision: int = Field(ge=1)
    persona: TourPersona
    theme: TourTheme
    facts: list[TourFact] = Field(max_length=MAX_FACTS)
    elements: list[TourElement] = Field(max_length=MAX_ELEMENTS)
    steps: list[TourStep] = Field(min_length=1, max_length=MAX_STEPS)
    start_step_id: str = Field(pattern=ID_PATTERN)
    end_step_ids: list[str] = Field(min_length=1, max_length=MAX_STEPS)
    guardrails: TourGuardrails
    authored_by: TourAuthoredBy


class GuidedTour(GuidedTourInput):
    project_id: str
    tour_version: int = Field(ge=1)
    status: Literal["draft", "active", "retired"] = "draft"
    created_at: datetime
    # Caller identity that created this draft, matching ExperienceBlueprint.author.
    author: str | None = None


# ---------------------------------------------------------------------------
# validate_guided_tour
# ---------------------------------------------------------------------------


def _fail(rule: str, detail: str) -> None:
    raise HTTPException(422, f"{rule}: {detail}")


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT_PATTERN.split(text.strip()) if part.strip()]


def _content_words(text: str) -> set[str]:
    """Lower-cased tokens of `text` that carry meaning, for the sealed-letter leak check."""
    return {
        token.lower()
        for token in _WORD_PATTERN.findall(text or "")
        if len(token) >= 3 and token.lower() not in _SEALED_CONTENT_STOPWORDS
    }


def validate_guided_tour(
    tour_input: GuidedTourInput,
    *,
    blueprint: Any,
    social_manifest: dict,
    contributions: list[Any],
) -> None:
    """Raise ``HTTPException(422, "<rule>: <detail>")`` on the first violation.

    ``blueprint`` is an ``ExperienceBlueprint`` (duck-typed: needs
    ``.objects``, each with ``.id``/``.contribution_id``).
    ``social_manifest`` is ``compile_social_manifest(blueprint)``'s output.
    ``contributions`` is ``store.list_contributions(project_id)`` -- every
    contribution in the project, needed both to check ``contribution_memory``
    facts verbatim and to keep every letter's private text out of the tour.
    """
    # -- 1. size and counts -------------------------------------------------
    serialized = json.dumps(tour_input.model_dump(mode="json"))
    if len(serialized.encode("utf-8")) > MAX_SERIALIZED_BYTES:
        _fail("size", f"serialized tour is over {MAX_SERIALIZED_BYTES} bytes.")
    if len(tour_input.steps) > MAX_STEPS:
        _fail("size", f"at most {MAX_STEPS} steps are allowed.")
    if len(tour_input.facts) > MAX_FACTS:
        _fail("size", f"at most {MAX_FACTS} facts are allowed.")
    if len(tour_input.elements) > MAX_ELEMENTS:
        _fail("size", f"at most {MAX_ELEMENTS} elements are allowed.")

    # -- 2. uniqueness + reference resolution --------------------------------
    fact_ids = [fact.fact_id for fact in tour_input.facts]
    if len(fact_ids) != len(set(fact_ids)):
        _fail("duplicate_id", "fact_id is not unique.")
    element_ids = [element.element_id for element in tour_input.elements]
    if len(element_ids) != len(set(element_ids)):
        _fail("duplicate_id", "element_id is not unique.")
    step_ids = [step.step_id for step in tour_input.steps]
    if len(step_ids) != len(set(step_ids)):
        _fail("duplicate_id", "step_id is not unique.")

    fact_set, element_set, step_set = set(fact_ids), set(element_ids), set(step_ids)

    def _require_facts(ids: list[str], where: str) -> None:
        unknown = [fid for fid in ids if fid not in fact_set]
        if unknown:
            _fail("unknown_reference", f"{where} references unknown fact id(s): {unknown}")

    def _require_elements(ids: list[str], where: str) -> None:
        unknown = [eid for eid in ids if eid not in element_set]
        if unknown:
            _fail("unknown_reference", f"{where} references unknown element id(s): {unknown}")

    def _require_steps(ids: list[str], where: str) -> None:
        unknown = [sid for sid in ids if sid not in step_set]
        if unknown:
            _fail("unknown_reference", f"{where} references unknown step id(s): {unknown}")

    _require_facts(tour_input.theme.fact_ids, "theme.fact_ids")
    for element in tour_input.elements:
        _require_facts(element.fact_ids, f"element {element.element_id}.fact_ids")
    for step in tour_input.steps:
        _require_facts(step.fact_ids, f"step {step.step_id}.fact_ids")
        _require_facts(step.narration.fact_ids, f"step {step.step_id}.narration.fact_ids")
        _require_elements(step.focus_element_ids, f"step {step.step_id}.focus_element_ids")
        _require_elements(step.reveal_element_ids, f"step {step.step_id}.reveal_element_ids")
        _require_elements([step.stop.anchor_element_id], f"step {step.step_id}.stop.anchor_element_id")
        _require_steps(step.next_step_ids, f"step {step.step_id}.next_step_ids")
    if tour_input.start_step_id not in step_set:
        _fail("unknown_reference", f"start_step_id references unknown step id: {tour_input.start_step_id}")
    unknown_ends = [sid for sid in tour_input.end_step_ids if sid not in step_set]
    if unknown_ends:
        _fail("unknown_reference", f"end_step_ids references unknown step id(s): {unknown_ends}")

    # -- 3. elements ----------------------------------------------------------
    blueprint_object_ids = {obj.id for obj in blueprint.objects}
    manifest_by_object = {entry["object_id"]: entry for entry in social_manifest.get("objects", [])}
    for element in tour_input.elements:
        if element.kind == "motif":
            if element.object_id is not None:
                _fail("element_motif", f"element {element.element_id}: a motif's object_id must be null.")
            if not element.staging_cue_id:
                _fail(
                    "element_motif",
                    f"element {element.element_id}: a motif needs a non-empty staging_cue_id.",
                )
            continue
        if element.object_id is None or element.object_id not in blueprint_object_ids:
            _fail(
                "element_object",
                f"element {element.element_id}: object_id {element.object_id!r} is not in "
                f"blueprint revision {blueprint.revision}.",
            )
        if element.kind == "contribution":
            manifest_entry = manifest_by_object.get(element.object_id)
            if manifest_entry is None:
                _fail(
                    "element_contributor",
                    f"element {element.element_id}: object {element.object_id} has no contributor "
                    "in the social manifest.",
                )
            if (
                element.contributor_id != manifest_entry["contributor_id"]
                or element.contributor_display_name != manifest_entry["contributor_display_name"]
            ):
                _fail(
                    "element_contributor",
                    f"element {element.element_id}: contributor_id/contributor_display_name must "
                    "match the social manifest.",
                )

    # -- 4. facts ---------------------------------------------------------------
    contributions_by_id = {c.contribution_id: c for c in contributions}
    manifest_by_contribution = {
        entry["contribution_id"]: entry for entry in social_manifest.get("objects", [])
    }
    vocab = _build_vocab(tour_input, social_manifest)
    facts_by_id = {fact.fact_id: fact for fact in tour_input.facts}

    # Every letter-sourced contribution's private text -- never allowed to
    # leak into any fact, even as a substring (step 28 hasn't landed a
    # dedicated Letter model with `note_text` yet, so a letter-sourced
    # Contribution's `memory_text` is the sealed content today).
    sealed_content_words: set[str] = set()
    for contribution in contributions:
        if contribution.source_type == "letter":
            sealed_content_words |= _content_words(contribution.memory_text)

    for fact in tour_input.facts:
        if fact.source.kind == "contribution_memory":
            contribution = contributions_by_id.get(fact.source.ref_id or "")
            if contribution is None:
                _fail(
                    "fact_contribution_memory",
                    f"fact {fact.fact_id}: source.ref_id {fact.source.ref_id!r} is not a known contribution.",
                )
            candidates = {contribution.memory_text.strip()} | set(_sentences(contribution.memory_text))
            if fact.text.strip() not in candidates:
                _fail(
                    "fact_contribution_memory",
                    f"fact {fact.fact_id}: text must equal contribution {contribution.contribution_id}'s "
                    "memory_text verbatim, or one of its sentences.",
                )
        elif fact.source.kind == "attribution":
            contribution = contributions_by_id.get(fact.source.ref_id or "")
            if contribution is None:
                _fail(
                    "fact_attribution",
                    f"fact {fact.fact_id}: source.ref_id {fact.source.ref_id!r} is not a known contribution.",
                )
            manifest_entry = manifest_by_contribution.get(contribution.contribution_id)
            name = manifest_entry["contributor_display_name"] if manifest_entry else None
            if not name or name not in fact.text:
                _fail(
                    "fact_attribution",
                    f"fact {fact.fact_id}: text must contain the contributor's display name.",
                )
            labels = [
                element.label
                for element in tour_input.elements
                if fact.fact_id in element.fact_ids and element.label
            ]
            if labels and not any(label in fact.text for label in labels):
                _fail(
                    "fact_attribution",
                    f"fact {fact.fact_id}: text must contain the element's label.",
                )
        elif fact.source.kind == "authored":
            if not fact.derived_from:
                _fail("fact_authored", f"fact {fact.fact_id}: an authored fact needs at least one derived_from id.")
            unknown = [fid for fid in fact.derived_from if fid not in facts_by_id]
            if unknown:
                _fail("fact_authored", f"fact {fact.fact_id}: derived_from references unknown fact id(s): {unknown}")
            derived_texts = [facts_by_id[fid].text for fid in fact.derived_from]
            violations = grounding_violations(fact.text, derived_texts, vocab)
            if violations:
                _fail(
                    "fact_authored",
                    f"fact {fact.fact_id}: introduces ungrounded token(s) {violations} not present in "
                    "its derived_from facts or the tour vocabulary.",
                )
        elif fact.source.kind == "letter_envelope":
            allowed = _tokenize_all(vocab) | _LETTER_ENVELOPE_EXTRA_WORDS
            disallowed = {token.lower() for token in _WORD_PATTERN.findall(fact.text)} - allowed
            if disallowed:
                _fail(
                    "fact_letter_envelope",
                    f"fact {fact.fact_id}: uses word(s) outside the tour vocabulary: {sorted(disallowed)}",
                )

        if sealed_content_words:
            fact_words = {token.lower() for token in _WORD_PATTERN.findall(fact.text)}
            leaked = fact_words & sealed_content_words
            if leaked:
                _fail(
                    "sealed_letter_leak",
                    f"fact {fact.fact_id}: contains word(s) from a sealed letter's private text: "
                    f"{sorted(leaked)}",
                )

    # -- 5. reveals -------------------------------------------------------------
    hidden_element_ids = {element.element_id for element in tour_input.elements if not element.initially_visible}
    for step in tour_input.steps:
        bad_reveals = [eid for eid in step.reveal_element_ids if eid not in hidden_element_ids]
        if bad_reveals:
            _fail(
                "reveal_hidden_only",
                f"step {step.step_id}: reveal_element_ids names element(s) that aren't "
                f"initially_visible: false: {bad_reveals}",
            )

    # -- 6. step graph ------------------------------------------------------------
    steps_by_id = {step.step_id: step for step in tour_input.steps}
    reachable: set[str] = set()
    queue = [tour_input.start_step_id]
    while queue:
        current = queue.pop()
        if current in reachable or current not in steps_by_id:
            continue
        reachable.add(current)
        queue.extend(steps_by_id[current].next_step_ids)
    unreachable = step_set - reachable
    if unreachable:
        _fail("step_graph_unreachable", f"step id(s) not reachable from start_step_id: {sorted(unreachable)}")
    dead_ends = [
        step.step_id
        for step in tour_input.steps
        if step.step_id not in tour_input.end_step_ids and not step.next_step_ids
    ]
    if dead_ends:
        _fail("step_graph_dead_end", f"non-end step(s) with no next_step_ids: {dead_ends}")

    revealed_by_reachable_steps: set[str] = set()
    for step_id in reachable:
        revealed_by_reachable_steps |= set(steps_by_id[step_id].reveal_element_ids)
    unrevealed_hidden = hidden_element_ids - revealed_by_reachable_steps
    if unrevealed_hidden:
        _fail(
            "reveal_unreachable",
            f"hidden element(s) never revealed by a reachable step: {sorted(unrevealed_hidden)}",
        )

    # -- 7. narration ---------------------------------------------------------------
    for step in tour_input.steps:
        outside = [fid for fid in step.narration.fact_ids if fid not in set(step.fact_ids)]
        if outside:
            _fail(
                "narration_grounding",
                f"step {step.step_id}: narration.fact_ids must be a subset of the step's fact_ids: {outside}",
            )
        narration_facts = [facts_by_id[fid].text for fid in step.narration.fact_ids]
        violations = grounding_violations(step.narration.text, narration_facts, vocab)
        if violations:
            _fail(
                "narration_grounding",
                f"step {step.step_id}: narration introduces ungrounded token(s) {violations}.",
            )


def _tokenize_all(entries: list[str]) -> set[str]:
    tokens: set[str] = set()
    for entry in entries:
        tokens |= {token.lower() for token in _WORD_PATTERN.findall(entry or "")}
    return tokens


def _build_vocab(tour_input: GuidedTourInput, social_manifest: dict) -> list[str]:
    """Contributor display names, element labels, the theme title, the persona name."""
    vocab: list[str] = [tour_input.theme.title, tour_input.persona.name]
    vocab.extend(element.label for element in tour_input.elements if element.label)
    vocab.extend(
        entry["contributor_display_name"]
        for entry in social_manifest.get("objects", [])
        if entry.get("contributor_display_name")
    )
    return vocab


# ---------------------------------------------------------------------------
# compose_tour_mock
# ---------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def compose_tour_mock(
    blueprint: Any,
    insight: Any,
    contributions: list[Any],
    contributors: dict[str, Any],
    social_manifest: dict,
    assets: dict[str, Any],
) -> GuidedTourInput:
    """Deterministic, offline stand-in for NemoClaw's `author_guided_tour` (step 31).

    Same inputs always produce the same tour (aside from `created_at`, which
    the caller assigns). No network, no model call. ``assets`` is
    ``asset_id -> ProjectAsset`` (for ``.label``) -- ``compile_social_manifest``'s
    entries don't carry a label, only attribution.
    """
    manifest_by_object = {entry["object_id"]: entry for entry in social_manifest.get("objects", [])}
    rationale_by_object = {item.object_id: item for item in insight.placement_rationale}
    contributions_by_id = {c.contribution_id: c for c in contributions}

    facts: list[TourFact] = []
    elements: list[TourElement] = []

    f_theme = TourFact(
        fact_id="f_theme",
        text=_clip(f"The room's theme is {insight.theme}.", 500),
        source=TourFactSource(kind="connection_insight", ref_id=f"insight:{insight.revision}"),
    )
    f_explanation = TourFact(
        fact_id="f_explanation",
        text=_clip(insight.explanation, 500),
        source=TourFactSource(kind="connection_insight", ref_id=f"insight:{insight.revision}"),
    )
    facts.extend([f_theme, f_explanation])

    steps: list[TourStep] = []
    contribution_step_ids: list[str] = []
    first_object_id: str | None = None

    for obj in blueprint.objects:
        if not obj.contribution_id:
            # No contribution -- an environment object gets its own element
            # (with an owner-free fact only if it has a label); nothing else
            # is contributed set-dressing worth narrating.
            asset = assets.get(obj.asset_id)
            asset_label = asset.label if asset else ""
            if not asset_label:
                continue
            env_fact = TourFact(
                fact_id=f"f_{obj.id}_env",
                text=_clip(f"There is a {asset_label} in the room.", 500),
                source=TourFactSource(kind="authored"),
                derived_from=["f_theme"],
            )
            facts.append(env_fact)
            elements.append(
                TourElement(
                    element_id=obj.id,
                    kind="environment",
                    object_id=obj.id,
                    label=asset_label,
                    fact_ids=[env_fact.fact_id],
                )
            )
            continue

        contribution = contributions_by_id.get(obj.contribution_id)
        if contribution is None:
            continue
        manifest_entry = manifest_by_object.get(obj.id, {})
        asset = assets.get(obj.asset_id)
        label = (asset.label if asset else "") or ""
        name = manifest_entry.get("contributor_display_name") or "A contributor"

        if first_object_id is None:
            first_object_id = obj.id

        if contribution.source_type == "letter":
            # Letters get an envelope fact only -- who it's from, never the
            # sealed note text (Notability letters land in step 28).
            letter_fact = TourFact(
                fact_id=f"f_{obj.id}_letter",
                text=_clip(f"This is a sealed letter from {name}.", 500),
                source=TourFactSource(kind="letter_envelope", ref_id=contribution.contribution_id),
            )
            facts.append(letter_fact)
            elements.append(
                TourElement(
                    element_id=obj.id,
                    kind="letter",
                    object_id=obj.id,
                    label=label,
                    fact_ids=[letter_fact.fact_id],
                )
            )
            continue

        owner_fact = TourFact(
            fact_id=f"f_{obj.id}_owner",
            text=_clip(f"{name} brought the {label}.", 500),
            source=TourFactSource(kind="attribution", ref_id=contribution.contribution_id),
        )
        facts.append(owner_fact)
        element_fact_ids = [owner_fact.fact_id]
        step_fact_ids = [owner_fact.fact_id]
        narration_fact_ids = [owner_fact.fact_id]
        narration_text = owner_fact.text

        memory_fact_ids: list[str] = []
        first_memory_fact: TourFact | None = None
        if contribution.memory_text.strip():
            for index, sentence in enumerate(_sentences(contribution.memory_text)):
                memory_fact = TourFact(
                    fact_id=f"f_{obj.id}_memory_{index}",
                    text=_clip(sentence, 500),
                    source=TourFactSource(kind="contribution_memory", ref_id=contribution.contribution_id),
                )
                facts.append(memory_fact)
                memory_fact_ids.append(memory_fact.fact_id)
                if first_memory_fact is None:
                    first_memory_fact = memory_fact
            element_fact_ids.extend(memory_fact_ids)
            step_fact_ids.extend(memory_fact_ids)
            narration_fact_ids.append(memory_fact_ids[0])
            narration_text = _clip(f"{owner_fact.text} {first_memory_fact.text}", 600)

        rationale = rationale_by_object.get(obj.id)
        if rationale is not None:
            why_fact = TourFact(
                fact_id=f"f_{obj.id}_why",
                text=_clip(rationale.rationale, 500),
                source=TourFactSource(kind="placement_rationale", ref_id=obj.id),
            )
            facts.append(why_fact)
            element_fact_ids.append(why_fact.fact_id)
            step_fact_ids.append(why_fact.fact_id)

        elements.append(
            TourElement(
                element_id=obj.id,
                kind="contribution",
                object_id=obj.id,
                contributor_id=manifest_entry.get("contributor_id"),
                contributor_display_name=manifest_entry.get("contributor_display_name"),
                label=label,
                fact_ids=element_fact_ids,
            )
        )

        step_id = f"s_{obj.id}"
        steps.append(
            TourStep(
                step_id=step_id,
                title=label or "Stop",
                stop=TourStop(anchor_element_id=obj.id, offset_m=[0.8, 1.4, 0.6]),
                focus_element_ids=[obj.id],
                fact_ids=step_fact_ids,
                narration=TourNarration(text=narration_text, fact_ids=narration_fact_ids),
                min_dwell_s=3.0,
            )
        )
        contribution_step_ids.append(step_id)

    anchor = first_object_id or (blueprint.objects[0].id if blueprint.objects else None)
    if anchor is None:
        raise ValueError("compose_tour_mock needs at least one blueprint object to anchor the welcome step.")

    welcome_step = TourStep(
        step_id="s_welcome",
        title="Welcome",
        stop=TourStop(anchor_element_id=anchor, offset_m=[0.8, 1.4, 0.6]),
        fact_ids=["f_theme"],
        narration=TourNarration(
            text=_clip(f"Welcome. {f_theme.text}", 600), fact_ids=["f_theme"]
        ),
        next_step_ids=[contribution_step_ids[0]] if contribution_step_ids else ["s_together"],
        min_dwell_s=3.0,
    )

    contribution_element_ids = [element.element_id for element in elements if element.kind == "contribution"]
    together_step = TourStep(
        step_id="s_together",
        title="Together",
        stop=TourStop(anchor_element_id=anchor, offset_m=[0.8, 1.4, 0.6]),
        focus_element_ids=contribution_element_ids,
        fact_ids=["f_theme"],
        narration=TourNarration(text=f_theme.text, fact_ids=["f_theme"]),
        min_dwell_s=3.0,
    )

    # Chain each contribution step to the next, and the last one to together.
    for index, step in enumerate(steps):
        if index + 1 < len(steps):
            step.next_step_ids = [steps[index + 1].step_id]
        else:
            step.next_step_ids = ["s_together"]

    all_steps = [welcome_step, *steps, together_step]

    tour_input = GuidedTourInput(
        based_on_revision=blueprint.revision,
        persona=TourPersona(name="Lumen", voice="mms-tts-eng", style="warm"),
        theme=TourTheme(title=insight.theme, fact_ids=["f_theme", "f_explanation"]),
        facts=facts,
        elements=elements,
        steps=all_steps,
        start_step_id="s_welcome",
        end_step_ids=["s_together"],
        guardrails=TourGuardrails(
            off_topic_reply="I can only tell you about this room and what everyone brought to it.",
            max_lines_per_turn=3,
        ),
        authored_by=TourAuthoredBy(
            backend="mock", model="mock-tour-v1", tool="compose_tour_mock", prompt_version=None
        ),
    )
    # A mock tour that fails its own validator is a bug in this function, not
    # a caller error -- fail loudly rather than store a broken draft.
    validate_guided_tour(tour_input, blueprint=blueprint, social_manifest=social_manifest, contributions=contributions)
    return tour_input
