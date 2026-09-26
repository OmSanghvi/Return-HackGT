"""NemoClaw scene-layout and immersive-staging tools (Build Plan steps 4 and 6).

``place_objects_in_scene`` and ``stage_immersive_reveal`` are pure, offline
reasoning functions -- not a standalone model-API call. Per AGENT.md, the
tools *are* the composition mechanism: NemoClaw's own agent loop supplies
the creative judgment by choosing when and how to call these tools; the
tools themselves stay deterministic so they're unit-testable without a live
LLM (design rule 10 in the ``top-tier-nemoclaw-tool-design`` skill) and so
``PIPELINE_MODE=mock`` never needs a network call to produce a valid scene.

``read_sketch_layout`` is different: reading a Notability sketch genuinely
requires vision perception, so it follows the same mock/nemoclaw backend
split as ``subject_labeler.py`` (``SKETCHSCAPE_SCENE_TOOLS=mock|nemoclaw``).

Both scene tools accept a **list** of objects, never a hard-coded pair --
the concrete, tool-signature-level enforcement of docs/ARCHITECTURE.md's
N-contributor section.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "shared" / "experience-blueprint.schema.json"
_SCHEMA_CACHE: dict | None = None

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
ALLOWED_INTERACTIONS = ("highlight", "inspect", "scale", "translate", "rotate", "activate")
_DEFAULT_SIZE = (0.6, 0.6, 0.6)


class SceneToolError(RuntimeError):
    """Raised when a scene tool is misconfigured, fed bad input, or would
    return a schema-invalid result."""


@dataclass(frozen=True)
class SceneObjectInput:
    """One contributed object, as passed to ``place_objects_in_scene``."""

    asset_id: str
    label: str = ""


@dataclass(frozen=True)
class LayoutHint:
    """Rough spatial relationships read from a Notability sketch.

    ``relations`` are free-text strings of the form
    ``"<label phrase> <relation> <label phrase>"`` where relation is one of
    left_of, right_of, behind, in_front_of, next_to, above, below.
    ``place_objects_in_scene`` may use these or ignore them entirely --
    they're a hint, never a hard dependency.
    """

    relations: list[str] = field(default_factory=list)
    backend: str = "mock"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def _load_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(_SCHEMA_PATH.read_text())
    return _SCHEMA_CACHE


def _validate_blueprint_input(blueprint_input: dict, *, project_id: str) -> None:
    """Validate against shared/experience-blueprint.schema.json.

    That schema describes the persisted ``ExperienceBlueprint`` record, which
    adds ``project_id``/``revision``/``created_at`` on top of the
    ``ExperienceBlueprintInput`` shape this tool returns -- those three are
    assigned by the backend at `POST /v1/projects/{id}/blueprints` time, so
    we wrap a throwaway envelope here purely to validate the object/transform
    shapes before returning the input-only payload to the caller.
    """
    envelope = {
        "project_id": project_id,
        "revision": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **blueprint_input,
    }
    try:
        jsonschema.validate(envelope, _load_schema())
    except jsonschema.ValidationError as exc:
        raise SceneToolError(f"produced a schema-invalid blueprint: {exc.message}") from exc


# ---------------------------------------------------------------------------
# place_objects_in_scene
# ---------------------------------------------------------------------------

_SIZE_CATALOG: list[tuple[re.Pattern, tuple[float, float, float]]] = [
    (re.compile(r"lamp|candle|vase|mug|cup|plant|photo|frame|book|small", re.I), (0.25, 0.35, 0.25)),
    (re.compile(r"chair|stool|backpack|box|suitcase|guitar", re.I), (0.55, 0.85, 0.55)),
    (re.compile(r"table|desk|shelf|dresser|bike|bicycle|bookcase", re.I), (1.1, 0.9, 0.6)),
    (re.compile(r"sofa|couch|bed|piano|car|wardrobe", re.I), (2.0, 0.9, 0.9)),
]

_RELATION_WORDS = ("left_of", "right_of", "in_front_of", "behind", "next_to", "above", "below")
_RELATION_PATTERN = re.compile(
    r"(?P<a>.+?)\s+(?P<rel>" + "|".join(_RELATION_WORDS) + r")\s+(?P<b>.+)", re.IGNORECASE
)


def _footprint_for_label(label: str) -> tuple[float, float, float]:
    for pattern, size in _SIZE_CATALOG:
        if pattern.search(label):
            return size
    return _DEFAULT_SIZE


def _slugify(label: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", label.strip()).strip("_")
    return slug[:60] or "object"


def _get(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _normalize_object(raw: Any, index: int) -> dict:
    asset_id = _get(raw, "asset_id")
    label = _get(raw, "label") or ""
    if not asset_id or not isinstance(asset_id, str) or not ID_PATTERN.match(asset_id):
        raise SceneToolError(f"object at index {index} has an invalid or missing asset_id: {asset_id!r}")
    label = (label or asset_id).strip()
    object_id = f"{_slugify(label)}_{index}"
    if not ID_PATTERN.match(object_id):
        object_id = f"object_{index}"
    return {"asset_id": asset_id, "label": label, "id": object_id}


def _parse_relation(text: str) -> Optional[tuple[str, str, str]]:
    match = _RELATION_PATTERN.match(text.strip())
    if not match:
        return None
    return match.group("a").strip().lower(), match.group("rel").lower(), match.group("b").strip().lower()


def _find_index(norm: list[dict], phrase: str) -> Optional[int]:
    phrase = phrase.lower()
    for i, obj in enumerate(norm):
        label = obj["label"].lower()
        if phrase in label or label in phrase:
            return i
    return None


def _ordering_from_hint(norm: list[dict], hint: Optional[LayoutHint]) -> list[int]:
    order = list(range(len(norm)))
    if not hint:
        return order
    for relation in hint.relations:
        parsed = _parse_relation(relation)
        if not parsed:
            continue
        a_phrase, rel, b_phrase = parsed
        if rel not in ("left_of", "right_of"):
            continue
        a_idx = _find_index(norm, a_phrase)
        b_idx = _find_index(norm, b_phrase)
        if a_idx is None or b_idx is None or a_idx == b_idx:
            continue
        if rel == "right_of":
            a_idx, b_idx = b_idx, a_idx
        pos_a, pos_b = order.index(a_idx), order.index(b_idx)
        if pos_a > pos_b:
            order[pos_a], order[pos_b] = order[pos_b], order[pos_a]
    return order


def _depth_bias_from_hint(norm: list[dict], hint: Optional[LayoutHint]) -> dict[int, float]:
    bias = {i: 0.0 for i in range(len(norm))}
    if not hint:
        return bias
    for relation in hint.relations:
        parsed = _parse_relation(relation)
        if not parsed:
            continue
        a_phrase, rel, _b_phrase = parsed
        if rel not in ("behind", "in_front_of"):
            continue
        idx = _find_index(norm, a_phrase)
        if idx is None:
            continue
        bias[idx] += 0.4 if rel == "behind" else -0.4
    return bias


def _lay_out_objects(norm: list[dict], hint: Optional[LayoutHint]) -> list[dict]:
    count = len(norm)
    order = _ordering_from_hint(norm, hint)
    depth_bias = _depth_bias_from_hint(norm, hint)
    base_radius = 1.6 + 0.35 * count
    arc_span = min(150.0, 40.0 + 18.0 * count)
    start_angle = -arc_span / 2.0
    step = arc_span / (count - 1) if count > 1 else 0.0

    placed: list[Optional[dict]] = [None] * count
    for slot, idx in enumerate(order):
        obj = norm[idx]
        angle_deg = start_angle + step * slot
        angle = math.radians(angle_deg)
        depth = base_radius + (0.35 if slot % 2 == 1 else 0.0) + depth_bias.get(idx, 0.0)
        depth = max(depth, 0.6)
        x = depth * math.sin(angle)
        z = depth * math.cos(angle)
        footprint = _footprint_for_label(obj["label"])
        y = footprint[1] / 2.0
        facing_deg = (math.degrees(angle) + 180.0) % 360.0
        scale = tuple(round(footprint[i] / _DEFAULT_SIZE[i], 3) for i in range(3))
        placed[idx] = {
            "id": obj["id"],
            "asset_id": obj["asset_id"],
            "position": [round(x, 3), round(y, 3), round(z, 3)],
            "rotation": [0.0, round(facing_deg, 2), 0.0],
            "scale": list(scale),
            "interactions": ["highlight", "inspect"],
        }
    return placed  # type: ignore[return-value]


def place_objects_in_scene(
    objects: Sequence[Any],
    sketch_layout_hint: Optional[LayoutHint] = None,
    *,
    project_id: str = "preview",
    theme: str = "Shared Room",
) -> dict:
    """Turn a list of contributed objects into a schema-valid blueprint proposal.

    ``objects`` is a list of ``{asset_id, label}`` (dicts, ``SceneObjectInput``,
    or anything with those attributes) -- never a fixed pair. Reasons about
    realistic layout (an arc facing the room's entry point, varied depth for
    an immersive, non-flat feel, and label-driven relative scale) and returns
    an ``ExperienceBlueprintInput``-shaped dict ready for
    ``POST /v1/projects/{id}/blueprints``. Never publishes -- that stays a
    separate, explicit, approval-gated step.
    """
    if not objects:
        raise SceneToolError("place_objects_in_scene needs at least one object")
    norm = [_normalize_object(raw, i) for i, raw in enumerate(objects)]
    ids = [o["id"] for o in norm]
    if len(ids) != len(set(ids)):
        raise SceneToolError(f"place_objects_in_scene produced duplicate object ids: {ids}")

    placed = _lay_out_objects(norm, sketch_layout_hint)
    blueprint_input = {
        "experience": {"mode": "ar_vr", "theme": theme[:200] or "Shared Room", "units": "meters"},
        "environment": {
            "lighting_preset": "neutral",
            "skybox": None,
            "floor": True,
            "ambient_audio": None,
        },
        "objects": placed,
        "portals": [],
        "navigation": {"vr": "teleport", "ar": "surface-placement"},
    }
    _validate_blueprint_input(blueprint_input, project_id=project_id)
    return blueprint_input


# ---------------------------------------------------------------------------
# read_sketch_layout
# ---------------------------------------------------------------------------


def read_sketch_layout(sketch_image: Any = None, *, backend: Optional[str] = None) -> LayoutHint:  # noqa: ARG001
    """Extract rough spatial relationships from a Notability sketch.

    Optional -- ``place_objects_in_scene`` works fine with ``None``. The
    mock backend is honest about having no real vision signal: it always
    returns an empty hint rather than guessing. The live path needs
    NemoClaw's configured vision model (Build Plan step 3); until that's
    wired up, selecting it raises rather than silently falling back to a
    standalone model call.
    """
    selected = (backend or os.environ.get("SKETCHSCAPE_SCENE_TOOLS", "mock")).strip().lower()
    if selected in {"", "mock", "test", "demo"}:
        return LayoutHint(relations=[], backend="mock")
    if selected == "nemoclaw":
        raise SceneToolError(
            "read_sketch_layout's live path runs inside the NemoClaw agent's configured "
            "vision model (Build Plan step 3). Use SKETCHSCAPE_SCENE_TOOLS=mock until "
            "that vision path is wired up and verified."
        )
    raise SceneToolError(f"Unknown SKETCHSCAPE_SCENE_TOOLS backend '{selected}'. Use 'mock' or 'nemoclaw'.")


# ---------------------------------------------------------------------------
# stage_immersive_reveal (Build Plan step 6)
# ---------------------------------------------------------------------------

_MOOD_PALETTE: list[tuple[re.Pattern, dict]] = [
    (re.compile(r"warm|home|comfort|family|nostalg", re.I), {"preset": "warm-amber", "color": [1.0, 0.72, 0.42]}),
    (re.compile(r"cool|calm|ocean|water|winter", re.I), {"preset": "cool-teal", "color": [0.35, 0.75, 0.85]}),
    (re.compile(r"myster|dream|memory|night", re.I), {"preset": "dusk-violet", "color": [0.55, 0.4, 0.85]}),
    (re.compile(r"joy|celebrat|bright|adventure", re.I), {"preset": "sunrise-gold", "color": [1.0, 0.85, 0.5]}),
]
_DEFAULT_MOOD = {"preset": "neutral-glow", "color": [0.9, 0.9, 0.95]}
_HAPTIC_PALETTE = ("pulse_soft", "pulse_sharp", "pulse_warm", "pulse_cool", "pulse_deep")


def _mood_for_theme(theme: str) -> dict:
    for pattern, mood in _MOOD_PALETTE:
        if pattern.search(theme or ""):
            return mood
    return _DEFAULT_MOOD


def _distance(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _shared_center(objects: Sequence[Any]) -> list[float]:
    positions = [_get(o, "position") for o in objects]
    return [sum(p[i] for p in positions) / len(positions) for i in range(3)]


def stage_immersive_reveal(connection_insight: Any, objects: Sequence[Any]) -> dict:
    """Choreograph the moment contributions are experienced together.

    Accepts the same N-length object list as ``place_objects_in_scene``.
    Never puts ``theme``/``explanation`` on a floating UI card -- the
    narration text is the primary channel, expressed as spoken narration in
    Unity, alongside lighting, a connecting light-path motif, and per-object
    haptic/sound signatures (AGENT.md: "the connection must be felt, not
    read"). Degrades gracefully: every field here is plain data a Unity
    scene can ignore entirely and still load correctly with plain lighting
    and no effects.
    """
    if not objects:
        raise SceneToolError("stage_immersive_reveal needs at least one object")

    ordered = sorted(objects, key=lambda o: _distance(_get(o, "position"), _shared_center(objects)))
    reveal_order = [_get(o, "id") for o in ordered]
    theme = _get(connection_insight, "theme", "") or ""
    explanation = _get(connection_insight, "explanation", "") or ""
    mood = _mood_for_theme(theme)

    center = _shared_center(objects)
    motif = {
        "type": "light_path",
        "curve": "catmull_rom",
        "color": mood["color"],
        "control_points": [_get(o, "position") for o in ordered] + [center],
    }
    narration = {
        # Always present so the room can speak the connection even before
        # any TTS engine or recorded voice is wired up (Part B, Unity side).
        "text": explanation or theme or "A shared moment, brought together.",
        "voice": "narrator_default",
        "tts_engine": None,
    }
    haptic_signatures = {
        _get(o, "id"): _HAPTIC_PALETTE[i % len(_HAPTIC_PALETTE)] for i, o in enumerate(ordered)
    }

    return {
        "reveal_order": reveal_order,
        "lighting_preset": mood["preset"],
        "connecting_motif": motif,
        "narration": narration,
        "haptic_signatures": haptic_signatures,
        "summary": (
            f"Reveal order: {', '.join(reveal_order)}; "
            f"lighting={mood['preset']}; {len(haptic_signatures)} haptic signature(s) assigned."
        ),
    }
