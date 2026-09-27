"""GPU vision-language server for SketchScape (loopback :8003).

Contract: docs/IMMERSIVE_SCENE_PIPELINE.md section 3 (and 1b for analysis.json).

    GET  /health                                  -> {"status": "ok", "model": "..."}
    POST /v1/detect  {"image_b64", "max_objects"} -> {"objects": [{"name", "box", "salient"}]}
    POST /v1/analyze {"image_b64"}                -> analysis.json document

The model (default Qwen/Qwen3-VL-4B-Instruct, bf16, ~9 GB VRAM) is loaded once
and kept resident. Everything above the ``# --- model ---`` line is pure
Python (stdlib only) so ``test_vlm_server.py`` can exercise the JSON
extraction and normalization without torch, PIL or a GPU.

CLI:
    python vlm_server.py --serve [--port 8003] [--model /path/or/hf-id]
    python vlm_server.py --once detect|analyze --image photo.jpg   # one-shot, prints JSON
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
from typing import Any

DEFAULT_MODEL = os.environ.get(
    "VLM_MODEL", "/opt/sketchscape/runtime/vlm/models/Qwen3-VL-4B-Instruct"
)
DEFAULT_PORT = int(os.environ.get("VLM_PORT", "8003"))
MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_OBJECTS = 12
HARD_MAX_OBJECTS = 40
# Prompts per batched generation. 4 fits the <= 10 GB VRAM budget at a
# 1280 px model view (peak ~9.6 GB with Qwen3-VL-4B bf16).
MAX_BATCH = max(1, int(os.environ.get("VLM_MAX_BATCH", "4")))
CACHE_SIZE = 64  # recent photos (sha1 of the bytes) -> objects / analysis

# ---------------------------------------------------------------- prompts --

INVENTORY_PROMPT = """List the kinds of physical objects in this photo. Scan the WHOLE image: the foreground (including objects cut off by the frame edges, like a table or chair right in front of the camera), the middle and the background, from left to right.

Include every object that could be cut out and rebuilt as its own 3D model: furniture, animals, people, appliances, electronics, lamps, fireplaces, stoves, plants, framed pictures, decor, textiles lying on things (blankets, rugs, pillows, curtains), doors, windows, and small items (remote controls, cups, books, bowls, trays).
Never list walls, floor, ceiling, sky, ground, shadows, reflections, or parts of an object (legs, armrests, seat cushions, handles, knobs).

Each label is 1-3 lowercase words: a concrete noun with at most ONE color or material word ("golden retriever", "white mug", "leather armchair", "brick fireplace", "glass coffee table"). List each kind ONCE even when there are several of it, and give different labels to things that look different ("green armchair" and "wooden chair", not "chair" twice).

Answer with ONLY a JSON array of strings, most important first, at most {max_objects} entries."""

GROUND_PROMPT = """Locate every instance of these objects in the image: {names}.

Output one entry per separate object (two chairs -> two entries, each with its own box), labelled with exactly one of the given labels; skip a label you cannot see. Boxes tightly enclose the visible part of the object.

Answer with ONLY a JSON array, no prose:
[{{"bbox_2d": [x1, y1, x2, y2], "label": "..."}}]"""

# Single-pass fallback when the inventory step fails.
DETECT_PROMPT = """Detect every distinct physical object in this photo that could be cut out and rebuilt as its own 3D model: furniture, animals, people, appliances, electronics, lamps, fireplaces, plants, decor, framed pictures, textiles lying on things (blankets, rugs, pillows, curtains) and small items (remote controls, cups, books, bowls). Scan the whole image including the foreground and objects cut off by the frame edges.

Rules:
- Do NOT include walls, floor, ceiling, sky, ground, background, shadows, reflections, light beams, or parts of an object (legs, armrests, cushions of a sofa, handles, knobs).
- Label = a short concrete noun phrase of 1-3 words, lowercase, optionally with ONE color or material word: "golden retriever", "white mug", "leather armchair", "wool throw", "glass coffee table". No sentences, no counts, no plurals.
- Every separate instance is its own entry (two chairs -> two entries, each with its own box).
- Order by importance, most important first. At most {max_objects} entries.

Answer with ONLY a JSON array, no prose:
[{{"bbox_2d": [x1, y1, x2, y2], "label": "..."}}]"""

# The analysis is split in two prompts that run as one batch (half the
# output tokens each, so about half the latency of one long answer).
ANALYZE_SCENE_PROMPT = """You are a lighting designer who must rebuild this photo as an immersive VR room. Study the photo, then answer with ONLY this JSON object, keeping every value short:
{
  "caption": "one factual sentence describing the photo",
  "room_type": "the kind of place in 1-3 words, e.g. living room, bedroom, kitchen, cabin living room, office, garden",
  "setting": "indoor" or "outdoor",
  "camera_view": "eye-level" or "top-down" or "low-angle" or "close-up",
  "time_of_day": "morning" or "midday" or "afternoon" or "evening" or "night" or "unknown",
  "mood": "2-4 comma-separated adjectives",
  "lighting": {
    "key_direction": where the MAIN light comes FROM, relative to the camera: "left", "right", "above", "camera" (from the photographer's side, like a flash), "backlight" (from beyond the subject, shining toward the camera), "camera-left", "camera-right", "backlight-left" or "backlight-right"; judge from which sides of objects are brightest and which way shadows fall,
    "key_source": "what the main light is, e.g. window, ceiling lamp, table lamp, camera flash, sun, overcast sky",
    "color_temperature_k": integer Kelvin of the dominant light (candle 1900, incandescent 2700, warm LED 3000, halogen 3200, fluorescent 4000, direct sun 5500, overcast daylight 6500, open shade 7500),
    "sources": ["each visible or clearly implied light source with its position"],
    "brightness": "dim" or "medium" or "bright",
    "shadows": "soft" or "hard" or "none"
  }
}"""

ANALYZE_DESIGN_PROMPT = """You are a set designer who must rebuild this photo as an immersive VR room. Study the photo, then answer with ONLY this JSON object, keeping every value short:
{
  "materials": {
    "floor": "the floor material with color and finish, e.g. polished walnut planks, grey ceramic tile, beige carpet; if no floor is visible, the floor this kind of room most likely has",
    "floor_visible": true or false,
    "walls": "the wall material with color, e.g. white painted plaster, exposed red brick; if no wall is visible, the most likely walls",
    "other": ["up to 5 other prominent materials with color, e.g. blue velvet, brushed steel"]
  },
  "search_terms": {
    "hdri": ["2-4 queries of 1-3 words for a 360 HDRI library like Poly Haven, naming the kind of place and light, e.g. living room, cabin interior, warm indoor, sunset, forest, studio"],
    "sounds": ["2-4 short queries for looping ambient sounds that belong in this scene, e.g. room tone, fireplace crackling, rain on window, birds outside"],
    "images": ["2-4 short queries for pictures that would suit the walls of this room"]
  }
}"""

RETRY_SUFFIX = (
    "\n\nYour previous answer was not valid JSON in the required shape. "
    "Reply again with ONLY the JSON, no prose and no markdown."
)

# ------------------------------------------------------ JSON extraction --

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1)
    # An unterminated fence (generation cut off) still starts with ```json.
    return re.sub(r"^\s*```(?:json|JSON)?\s*", "", text)


def _balanced_span(text: str, start: int) -> tuple[int, bool]:
    """End index (exclusive) of the JSON value opening at ``start``.

    Returns (end, complete). When the text ends before the value closes,
    returns (len(text), False).
    """
    stack: list[str] = []
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append("]" if ch == "[" else "}")
        elif ch in "]}":
            if not stack or stack[-1] != ch:
                return i, False
            stack.pop()
            if not stack:
                return i + 1, True
    return len(text), False


def _loads_lenient(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    fixed = re.sub(r",\s*([\]}])", r"\1", candidate)  # trailing commas
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    fixed = re.sub(r"\bNone\b", "null", fixed)
    return json.loads(fixed)


def _repair_truncated_array(fragment: str) -> Any:
    """Salvage a JSON array cut off mid-generation: keep complete elements."""
    last = fragment.rfind("}")
    while last > 0:
        try:
            return _loads_lenient(fragment[: last + 1] + "]")
        except json.JSONDecodeError:
            last = fragment.rfind("}", 0, last)
    raise ValueError("truncated array has no complete element")


def extract_json(text: str, want: type | None = None) -> Any:
    """First JSON value (object or array) in model output.

    Tolerates markdown fences, leading/trailing prose, trailing commas,
    Python literals and an array truncated by max_new_tokens. ``want`` (dict
    or list) prefers a value of that type. Raises ValueError when nothing
    usable is found.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty model output")
    body = _strip_fences(text)
    openers = "{[" if want is None else ("{" if want is dict else "[")
    errors: list[str] = []
    for i, ch in enumerate(body):
        if ch not in openers:
            continue
        end, complete = _balanced_span(body, i)
        fragment = body[i:end]
        try:
            if complete:
                value = _loads_lenient(fragment)
            elif ch == "[":
                value = _repair_truncated_array(fragment)
            else:
                continue
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        if want is None or isinstance(value, want):
            return value
    if want is list:
        # Some models wrap the array: {"objects": [...]}.
        try:
            obj = extract_json(text, dict)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            for key in ("objects", "detections", "items", "results"):
                if isinstance(obj.get(key), list):
                    return obj[key]
    raise ValueError("no JSON %s in model output%s" % (
        "value" if want is None else want.__name__,
        (": " + errors[-1]) if errors else ""))


# --------------------------------------------------------- normalization --

# Surfaces / non-objects never sent to SAM as an object (matched on head noun).
EXCLUDED_HEADS = {
    "wall", "walls", "floor", "floors", "flooring", "ceiling", "background",
    "ground", "sky", "shadow", "shadows", "reflection", "reflections", "light",
    "lighting", "sunlight", "room", "scene", "image", "photo", "picture frame edge",
    "wallpaper", "baseboard", "grass", "air", "surface", "area", "corner",
    "space", "interior", "view",
}
# Fixed parts of the building: kept, but never salient.
STRUCTURAL_HEADS = {"window", "door", "doorway", "stairs", "staircase", "column",
                    "beam", "archway", "railing", "outlet", "switch"}
# Object parts the model sometimes lists despite the prompt.
PART_HEADS = {"leg", "legs", "armrest", "armrests", "handle", "knob", "cushion seam",
              "paw", "paws", "tail", "ear", "ears", "whiskers", "button", "buttons",
              "seat", "backrest", "shelf edge"}
_ARTICLES = {"a", "an", "the", "some", "one", "two", "three", "several", "many"}
_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_IRREGULAR_PLURALS = {"people": "person", "men": "man", "women": "woman",
                      "children": "child", "mice": "mouse", "geese": "goose",
                      "feet": "foot", "teeth": "tooth", "knives": "knife",
                      "shelves": "shelf", "leaves": "leaf", "loaves": "loaf"}
_KEEP_S = ("ss", "us", "is", "as", "ics", "news", "glasses", "pants", "jeans", "scissors",
           "shorts", "stairs", "blinds", "drapes", "curtains", "headphones")


def singularize(word: str) -> str:
    if word in _IRREGULAR_PLURALS:
        return _IRREGULAR_PLURALS[word]
    for plural, single in _IRREGULAR_PLURALS.items():  # bookshelves, tablecloths...
        if len(plural) > 4 and word.endswith(plural):
            return word[: -len(plural)] + single
    if len(word) <= 3 or word.endswith(_KEEP_S):
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "xes", "sses", "zzes")):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize_name(raw: Any) -> str:
    """Short, lowercase, SAM-promptable noun phrase; '' when unusable."""
    if not isinstance(raw, str):
        return ""
    text = raw.lower().replace("_", " ")
    text = re.sub(r"\(.*?\)", " ", text)          # drop parentheticals
    text = re.split(r"[,;:/]| with | on | in | of the | near | next to ", text)[0]
    words = _WORD_RE.findall(text)
    while words and words[0] in _ARTICLES:
        words = words[1:]
    words = [w for w in words if not w.isdigit()]
    if not words:
        return ""
    words = words[-4:]  # the head noun is last in English noun phrases
    words[-1] = singularize(words[-1])
    name = " ".join(words)
    return name[:40].strip()


def head_noun(name: str) -> str:
    return name.split()[-1] if name else ""


def is_excluded(name: str) -> bool:
    if not name:
        return True
    head = head_noun(name)
    return name in EXCLUDED_HEADS or head in EXCLUDED_HEADS or head in PART_HEADS


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "1", "y"):
            return True
        if v in ("false", "no", "0", "n"):
            return False
    return default


def convert_box(raw: Any, width: int, height: int, box_format: str) -> list[int] | None:
    """Model box -> [x0, y0, x1, y1] integer pixels of the source image.

    box_format: "rel1000" (Qwen3-VL: 0..1000 on each axis), "abs" (pixels of
    the source image), or "norm" (0..1).
    """
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if any(v != v for v in (x0, y0, x1, y1)):  # NaN
        return None
    if box_format == "rel1000":
        sx, sy = width / 1000.0, height / 1000.0
    elif box_format == "norm":
        sx, sy = float(width), float(height)
    else:
        sx = sy = 1.0
    x0, x1 = sorted((x0 * sx, x1 * sx))
    y0, y1 = sorted((y0 * sy, y1 * sy))
    x0 = max(0, min(width, int(round(x0))))
    x1 = max(0, min(width, int(round(x1))))
    y0 = max(0, min(height, int(round(y0))))
    y1 = max(0, min(height, int(round(y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return [x0, y0, x1, y1]


def box_area(box: list[int] | None) -> int:
    if not box:
        return 0
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def box_iou(a: list[int] | None, b: list[int] | None) -> float:
    if not a or not b:
        return 0.0
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = box_area(a) + box_area(b) - inter
    return inter / union if union > 0 else 0.0


_POSITION_WORDS = {"left", "right", "middle", "center", "top", "bottom", "front",
                   "back", "upper", "lower", "far", "near", "first", "second", "third"}


def _position_labels(boxes: list[list[int] | None], width: int, height: int) -> list[str]:
    """Distinguishing position words for same-name instances."""
    n = len(boxes)
    centers = []
    for i, b in enumerate(boxes):
        if b:
            centers.append(((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0, i))
        else:
            centers.append((None, None, i))
    known = [c for c in centers if c[0] is not None]
    labels = [""] * n
    if len(known) < 2:
        return labels
    xs = [c[0] for c in known]
    ys = [c[1] for c in known]
    horizontal = (max(xs) - min(xs)) / max(1, width) >= (max(ys) - min(ys)) / max(1, height)
    order = sorted(known, key=(lambda c: c[0]) if horizontal else (lambda c: c[1]))
    if horizontal:
        words = ["left", "right"] if len(order) == 2 else (
            ["left", "middle", "right"] if len(order) == 3 else None)
    else:
        words = ["top", "bottom"] if len(order) == 2 else (
            ["top", "middle", "bottom"] if len(order) == 3 else None)
    for rank, c in enumerate(order):
        labels[c[2]] = words[rank] if words else ""
    return labels


def normalize_objects(raw: Any, width: int, height: int, max_objects: int = DEFAULT_MAX_OBJECTS,
                      box_format: str = "rel1000") -> list[dict[str, Any]]:
    """Validate and clean detector output into contract objects.

    Output: [{"name", "box", "salient", "prompt"}], salient first then larger
    first, excluded surfaces removed, near-duplicate boxes merged, same-name
    instances given position words ("left cat", "right cat"), capped.
    ``prompt`` is the base noun phrase (no position word) for SAM.
    """
    if isinstance(raw, dict):
        for key in ("objects", "detections", "items", "results"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise ValueError("detections must be a JSON array")
    max_objects = max(1, min(HARD_MAX_OBJECTS, int(max_objects or DEFAULT_MAX_OBJECTS)))
    image_area = max(1, width * height)
    cleaned: list[dict[str, Any]] = []
    for rank, item in enumerate(raw):
        if isinstance(item, str):
            item = {"label": item}
        if not isinstance(item, dict):
            continue
        name = normalize_name(item.get("label") or item.get("name") or item.get("object"))
        if is_excluded(name):
            continue
        box = convert_box(item.get("bbox_2d", item.get("box", item.get("bbox"))),
                          width, height, box_format)
        area_frac = box_area(box) / image_area
        if box and area_frac > 0.97:
            continue  # the whole frame: a surface, not an object
        salient = _as_bool(item.get("salient"), default=(box is None or area_frac >= 0.005))
        if head_noun(name) in STRUCTURAL_HEADS:
            salient = False
        if box and area_frac < 0.0008:
            salient = False
        cleaned.append({"name": name, "box": box, "salient": salient,
                        "_area": area_frac, "_rank": rank})

    # Merge duplicates: same box listed twice (keep the earlier = more important)
    # or same name with no box.
    kept: list[dict[str, Any]] = []
    for obj in cleaned:
        dup = False
        for other in kept:
            if obj["box"] and other["box"] and box_iou(obj["box"], other["box"]) >= 0.85:
                dup = True
            elif obj["name"] == other["name"] and (not obj["box"] or not other["box"]):
                dup = True
            if dup:
                other["salient"] = other["salient"] or obj["salient"]
                break
        if not dup:
            kept.append(obj)

    kept.sort(key=lambda o: (not o["salient"], -o["_area"], o["_rank"]))
    kept = kept[:max_objects]

    # Distinct instances of one kind: name them by position when the photo
    # separates them, else number them.
    groups: dict[str, list[dict[str, Any]]] = {}
    for obj in kept:
        obj["prompt"] = obj["name"]
        groups.setdefault(obj["name"], []).append(obj)
    for name, members in groups.items():
        if len(members) < 2:
            continue
        if name.split()[0] in _POSITION_WORDS:
            continue
        labels = _position_labels([m["box"] for m in members], width, height)
        for i, m in enumerate(members):
            m["name"] = f"{labels[i]} {name}" if labels[i] else (name if i == 0 else f"{name} {i + 1}")
    seen: set[str] = set()
    out = []
    for obj in kept:
        name = obj["name"]
        n = 2
        while name in seen:
            name = f"{obj['name']} {n}"
            n += 1
        seen.add(name)
        out.append({"name": name, "box": obj["box"], "salient": bool(obj["salient"]),
                    "prompt": obj["prompt"]})
    return out


def names_from_inventory(raw: Any, limit: int = 24) -> list[str]:
    """Unique normalized object names from the inventory step, in order."""
    if isinstance(raw, dict):
        for key in ("objects", "items", "inventory", "labels"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
    if not isinstance(raw, list):
        raise ValueError("inventory must be a JSON array")
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("label") or item.get("name")
        name = normalize_name(item)
        if is_excluded(name) or name in names:
            continue
        names.append(name)
        if len(names) >= limit:
            break
    return names


def cct_from_linear_rgb(r: float, g: float, b: float) -> int:
    """Correlated color temperature (K) of a linear-sRGB color (McCamy)."""
    x_ = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y_ = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z_ = 0.0193 * r + 0.1192 * g + 0.9505 * b
    total = x_ + y_ + z_
    if total <= 1e-9:
        return 6500
    x, y = x_ / total, y_ / total
    if abs(0.1858 - y) < 1e-9:
        return 10000
    n = (x - 0.3320) / (0.1858 - y)
    cct = 449.0 * n ** 3 + 3525.0 * n ** 2 + 6823.3 * n + 5520.33
    return int(max(1800, min(10000, round(cct / 50.0) * 50)))


# Key light: where the main light comes FROM, relative to the photo camera.
# "camera" = from the photographer's side (front lighting, flash-like);
# "backlight" = from beyond the subject, shining toward the camera.
KEY_CODES = ("left", "right", "above", "camera", "camera-left", "camera-right",
             "backlight", "backlight-left", "backlight-right")
DEFAULT_KEY_CODE = "camera-left"  # the classic 3/4 key when the photo gives no clue
# lighting.key_direction is written in words that compose_room
# (backend/unity_room.py _key_direction) parses: "left"/"right" -> side,
# "behind"/"camera" -> light on the camera side, "ahead"/"backlit" -> light on
# the far side of the scene, "window" -> low window-light elevation.
KEY_PHRASES = {"left": "left", "right": "right", "above": "above",
               "camera": "behind camera", "camera-left": "behind camera left",
               "camera-right": "behind camera right", "backlight": "ahead, backlit",
               "backlight-left": "ahead left, backlit", "backlight-right": "ahead right, backlit"}
# Horizontal direction the key light comes FROM, degrees clockwise seen from
# above: 0 = from the camera side, 90 = from the right, 180 = from beyond the
# subject (backlight), 270 = from the left.
KEY_AZIMUTH_DEG = {"camera": 0, "camera-right": 45, "right": 90, "backlight-right": 135,
                   "backlight": 180, "backlight-left": 225, "left": 270, "camera-left": 315,
                   "above": 0}
KEY_ELEVATION_DEG = {"above": 75}
TIMES_OF_DAY = ("morning", "midday", "afternoon", "evening", "night", "unknown")
CAMERA_VIEWS = ("eye-level", "top-down", "low-angle", "close-up")
_HEX_RE = re.compile(r"^(?:#?([0-9a-fA-F]{6})|#([0-9a-fA-F]{3}))$")


def _clean_text(value: Any, limit: int = 200, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] if text else default


def _clean_list(value: Any, limit: int, item_limit: int = 60) -> list[str]:
    if isinstance(value, str):
        value = [v for v in re.split(r"[;,]", value)]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _clean_text(item, item_limit).strip(" .").lower() if isinstance(item, str) else ""
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _pick(value: Any, allowed: tuple[str, ...], default: str) -> str:
    if not isinstance(value, str):
        return default
    v = value.strip().lower().replace("_", "-").replace(" ", "-")
    if v in allowed:
        return v
    v2 = v.replace("-", " ")
    for option in allowed:
        if option.replace("-", " ") == v2:
            return option
    for option in sorted(allowed, key=len, reverse=True):  # "from the left side" -> left
        if re.search(r"\b%s\b" % re.escape(option.replace("-", " ")), v2):
            return option
    return default


def normalize_key_direction(value: Any) -> str:
    """Free-text key light direction -> one of KEY_CODES.

    Accepts the prompt's codes and looser phrases ("window at left",
    "behind the camera", "backlight from window", "ceiling lights"). A bare
    "front" means front lighting (camera side); a bare "behind" means behind
    the subject (backlight).
    """
    if not isinstance(value, str) or not value.strip():
        return DEFAULT_KEY_CODE
    v = re.sub(r"[^a-z]+", " ", value.lower()).strip()
    if re.search(r"\bbehind (the )?(camera|photographer|viewer|you)\b", v):
        depth = "camera"
    elif re.search(r"\b(toward|towards|facing|into) (the )?(camera|lens|viewer)\b", v) or re.search(
            r"\b(backlight\w*|backlit|back light|behind|beyond|ahead|opposite|rim)\b", v):
        depth = "backlight"
    elif re.search(r"\b(camera|flash|photographer|frontal|front)\b", v):
        depth = "camera"
    else:
        depth = ""
    left = bool(re.search(r"\bleft\b", v))
    right = bool(re.search(r"\bright\b", v))
    side = "left" if left and not right else ("right" if right and not left else "")
    if depth and side:
        return f"{depth}-{side}"
    if side or depth:
        return side or depth
    if re.search(r"\b(above|overhead|ceiling|top|zenith|downlight\w*|skylight)\b", v):
        return "above"
    return DEFAULT_KEY_CODE


def key_direction_phrase(code: str, source: str = "") -> str:
    """compose_room-readable key direction, e.g. "left, window light"."""
    phrase = KEY_PHRASES.get(code, KEY_PHRASES[DEFAULT_KEY_CODE])
    if code != "above" and re.search(r"\bwindows?\b", (source or "").lower()):
        phrase += ", window light"
    return phrase


def normalize_hex(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    m = _HEX_RE.match(value.strip())
    if not m:
        return ""
    h = (m.group(1) or m.group(2)).lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def normalize_analysis(raw: Any, objects: list[dict[str, Any]] | None = None,
                       palette: list[str] | None = None,
                       measured: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate/clean the model's analysis into the contract 1b document.

    ``objects`` (from detect) and ``palette`` (measured from pixels) override
    whatever the model wrote for those keys. ``measured`` (pixel statistics,
    see VisionModel.measured_light) is kept under lighting.measured and its
    apparent color temperature replaces the model's guess. Raises ValueError when the model
    output is not an object or is missing the core fields.
    """
    if not isinstance(raw, dict):
        raise ValueError("analysis must be a JSON object")
    required = ("caption", "room_type", "lighting")
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError("analysis missing keys: " + ", ".join(missing))
    lighting = raw.get("lighting") if isinstance(raw.get("lighting"), dict) else {}
    materials = raw.get("materials") if isinstance(raw.get("materials"), dict) else {}
    terms = raw.get("search_terms") if isinstance(raw.get("search_terms"), dict) else {}

    setting = _pick(raw.get("setting"), ("indoor", "outdoor"), "indoor")
    key_source = _clean_text(lighting.get("key_source") or lighting.get("key_description"), 120)
    key_code = normalize_key_direction(lighting.get("key_direction"))
    try:
        kelvin = int(round(float(lighting.get("color_temperature_k"))))
    except (TypeError, ValueError):
        kelvin = 4000
    kelvin = max(1800, min(10000, kelvin))
    model_kelvin = kelvin
    measured = dict(measured or {})
    if isinstance(measured.get("color_temperature_k"), (int, float)):
        kelvin = int(max(1800, min(10000, measured["color_temperature_k"])))
    brightness = _pick(lighting.get("brightness"), ("dim", "medium", "bright"), "medium")
    shadows = _pick(lighting.get("shadows"), ("soft", "hard", "none"), "soft")

    model_palette = [h for h in (normalize_hex(v) for v in (raw.get("palette") or [])
                                 if isinstance(raw.get("palette"), list)) if h]
    out_palette = list(palette) if palette else model_palette[:6]

    floor = _clean_text(materials.get("floor"), 80).lower()
    floor_visible = _as_bool(materials.get("floor_visible"), default=True)
    if _uninformative(floor):
        floor, floor_visible = ("wooden floor" if setting == "indoor" else "grass"), False
    walls = _clean_text(materials.get("walls"), 80).lower()
    if _uninformative(walls):
        walls = "white painted plaster" if setting == "indoor" else ""

    doc: dict[str, Any] = {
        "room_type": _clean_text(raw.get("room_type"), 40, "room").lower(),
        "setting": setting,
        "camera_view": _pick(raw.get("camera_view"), CAMERA_VIEWS, "eye-level"),
        "time_of_day": _pick(raw.get("time_of_day"), TIMES_OF_DAY, "unknown"),
        "mood": _clean_text(raw.get("mood"), 80, "calm").lower(),
        "lighting": {
            "key_direction": key_direction_phrase(key_code, key_source + " " + str(lighting.get("key_direction") or "")),
            "key_direction_code": key_code,
            "key_azimuth_deg": KEY_AZIMUTH_DEG[key_code],
            "key_elevation_deg": KEY_ELEVATION_DEG.get(key_code, 40),
            "key_description": key_source,
            "color_temperature_k": kelvin,
            "sources": _clean_list(lighting.get("sources"), 6, 80),
            "brightness": brightness,
            "shadows": shadows,
            "color_temperature_model_k": model_kelvin,
            "measured": measured,
        },
        "materials": {
            "floor": floor,
            "floor_visible": floor_visible,
            "walls": walls,
            "other": _clean_list(materials.get("other"), 6, 60),
        },
        "palette": out_palette,
        "objects": [{"name": o["name"], "box": o.get("box"), "salient": bool(o.get("salient"))}
                    for o in (objects or [])],
        "search_terms": {
            "hdri": _clean_list(terms.get("hdri"), 4, 50),
            "sounds": _clean_list(terms.get("sounds"), 4, 50),
            "images": _clean_list(terms.get("images"), 4, 50),
        },
        "caption": _clean_text(raw.get("caption"), 300),
    }
    if not doc["caption"]:
        raise ValueError("analysis has an empty caption")
    return doc


def _uninformative(text: str) -> bool:
    t = (text or "").strip().lower()
    return (not t or t in ("none", "n/a", "na", "unknown", "unclear", "not applicable")
            or "not visible" in t or "not shown" in t or "cannot" in t)


def box_format_for(model_id: str) -> str:
    """Qwen3-VL grounds in 0..1000 relative coords; Qwen2.5-VL in input pixels."""
    override = os.environ.get("VLM_BOX_FORMAT", "").strip()
    if override:
        return override
    return "abs" if "qwen2" in model_id.lower() else "rel1000"


def decode_image_b64(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("image_b64 is required")
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    try:
        data = base64.b64decode(value, validate=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("image_b64 is not valid base64") from exc
    if not data:
        raise ValueError("image_b64 decoded to nothing")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    return data


def chunk_names(names: list[str], max_groups: int, per_group: int = 4) -> list[list[str]]:
    """Split names into <= max_groups contiguous groups of about equal size.

    Each group becomes one grounding prompt of a batched generation: the
    batch costs about as much wall time as its longest answer, so N short
    answers are ~N times faster than one long one.
    """
    names = [n for n in names if n]
    if not names:
        return []
    groups = max(1, min(max(1, max_groups), -(-len(names) // max(1, per_group))))
    size = -(-len(names) // groups)
    return [names[i:i + size] for i in range(0, len(names), size)]


def merge_group_outputs(texts: list[str]) -> tuple[list[Any], list[int]]:
    """Concatenate the JSON arrays of batched grounding answers, in order.

    Returns (items, indexes of answers that were not a JSON array).
    """
    items: list[Any] = []
    failed: list[int] = []
    for i, text in enumerate(texts):
        try:
            got = extract_json(text, list)
        except ValueError:
            failed.append(i)
            continue
        if isinstance(got, dict):
            got = next((got[k] for k in ("objects", "detections", "items", "results")
                        if isinstance(got.get(k), list)), None)
        if isinstance(got, list):
            items.extend(got)
        else:
            failed.append(i)
    return items, failed


def merge_analysis_parts(scene: Any, design: Any) -> dict[str, Any]:
    """One raw analysis dict from the scene/lighting and materials/terms answers."""
    out: dict[str, Any] = {}
    if isinstance(design, dict):
        out.update(design)
    if isinstance(scene, dict):
        out.update(scene)
    return out


def fingerprints_match(a: Any, b: Any, mean_tol: float = 3.0, max_tol: int = 40) -> bool:
    """Same photo? a/b = (aspect ratio, 16x16 grayscale bytes).

    The backend sends a re-encoded (maybe downscaled) JPEG to /v1/detect and
    the worker the original bytes to /v1/analyze; both must hit one cache
    entry, so this compares tiny thumbnails instead of the bytes.
    """
    if not a or not b or len(a[1]) != len(b[1]) or not a[1]:
        return False
    if abs(a[0] - b[0]) > 0.01 * max(a[0], b[0]):
        return False
    diffs = [abs(x - y) for x, y in zip(a[1], b[1])]
    return sum(diffs) / len(diffs) <= mean_tol and max(diffs) <= max_tol


def rescale_objects(objects: list[dict[str, Any]], from_size: Any, to_size: Any) -> list[dict[str, Any]]:
    """Copies of objects with boxes mapped from one resolution of the photo to another."""
    try:
        sx = float(to_size[0]) / float(from_size[0])
        sy = float(to_size[1]) / float(from_size[1])
    except (TypeError, ValueError, IndexError, ZeroDivisionError):
        sx = sy = 1.0
    out = []
    for obj in objects:
        obj = dict(obj)
        box = obj.get("box")
        if isinstance(box, list) and len(box) == 4 and (sx != 1.0 or sy != 1.0):
            obj["box"] = [max(0, min(int(to_size[0]), int(round(box[0] * sx)))),
                          max(0, min(int(to_size[1]), int(round(box[1] * sy)))),
                          max(0, min(int(to_size[0]), int(round(box[2] * sx)))),
                          max(0, min(int(to_size[1]), int(round(box[3] * sy))))]
        out.append(obj)
    return out


# --------------------------------------------------------------- model --

class VisionModel:
    """Resident Qwen-VL model with a lock (one generation at a time)."""

    def __init__(self, model_path: str, max_side: int = 1280):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        self.model_path = model_path
        self.model_id = os.environ.get("VLM_MODEL_ID") or os.path.basename(model_path.rstrip("/"))
        self.box_format = box_format_for(self.model_id)
        self.max_side = max_side
        self.lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.cache: "collections.OrderedDict[str, dict[str, Any]]" = collections.OrderedDict()
        self.processor = AutoProcessor.from_pretrained(model_path)
        self.processor.tokenizer.padding_side = "left"
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path, dtype=torch.bfloat16, device_map="cuda",
            attn_implementation=os.environ.get("VLM_ATTN", "sdpa"),
        ).eval()

    # -- image helpers
    def load_image(self, data: bytes):
        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        return img

    def model_view(self, img):
        from PIL import Image

        w, h = img.size
        scale = min(1.0, self.max_side / float(max(w, h)))
        if scale < 1.0:
            img = img.resize((max(32, int(w * scale)), max(32, int(h * scale))), Image.BICUBIC)
        return img

    @staticmethod
    def measured_palette(img, colors: int = 6) -> list[str]:
        """Dominant colors from pixels (median cut on a thumbnail), most common first."""
        from PIL import Image

        thumb = img.copy()
        thumb.thumbnail((160, 160))
        q = thumb.quantize(colors=colors + 2, method=Image.Quantize.MEDIANCUT)
        pal = q.getpalette() or []
        counts = sorted(q.getcolors() or [], reverse=True)
        out: list[str] = []
        for _count, idx in counts:
            r, g, b = pal[idx * 3: idx * 3 + 3]
            hx = "#%02x%02x%02x" % (r, g, b)
            # skip near-duplicates of an already chosen color
            if any(sum(abs(int(hx[i:i + 2], 16) - int(o[i:i + 2], 16)) for i in (1, 3, 5)) < 36
                   for o in out):
                continue
            out.append(hx)
            if len(out) >= colors:
                break
        return out

    def measured_light(self, img) -> dict[str, Any]:
        """Apparent color temperature and exposure of the photo, from pixels.

        Averages the brightest near-neutral pixels (the photo's 'whites') in
        linear sRGB and converts to CCT; that is the tint a matching VR light
        must have for the baked splat colors to look right.
        """
        import numpy as np

        thumb = img.copy()
        thumb.thumbnail((256, 256))
        a = np.asarray(thumb, dtype=np.float32) / 255.0
        lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4).reshape(-1, 3)
        srgb = a.reshape(-1, 3)
        lum = lin @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        mx, mn = srgb.max(axis=1), srgb.min(axis=1)
        sat = (mx - mn) / np.maximum(mx, 1e-6)
        result: dict[str, Any] = {"mean_luminance": round(float(lum.mean()), 3)}
        bright = lum >= np.quantile(lum, 0.80)
        pick = bright & (sat < 0.30) & (mx < 0.985)
        if pick.sum() >= 0.01 * len(lum):
            r, g, b = (float(v) for v in lin[pick].mean(axis=0))
            result["color_temperature_k"] = cct_from_linear_rgb(r, g, b)
            result["neutral_fraction"] = round(float(pick.mean()), 3)
        return result

    def release_memory(self) -> None:
        """Return cached-but-unused VRAM after a request (resident ~9 GB, not the peak)."""
        try:
            self.torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - never fail a request over this
            pass

    # -- cache (detect at upload time, analyze later in the scene job: same photo)
    @staticmethod
    def fingerprint(img) -> tuple[float, bytes]:
        from PIL import Image

        w, h = img.size
        return (w / float(max(1, h)), img.convert("L").resize((16, 16), Image.BOX).tobytes())

    def cache_get(self, key: str | None, img) -> dict[str, Any] | None:
        """Cached results for this photo (same bytes, or the same picture
        re-encoded/resized), with boxes mapped to this image's pixels."""
        fp = self.fingerprint(img)
        with self.cache_lock:
            hit = key if key and key in self.cache else None
            if hit is None:
                hit = next((k for k in reversed(self.cache)
                            if fingerprints_match(self.cache[k].get("fp"), fp)), None)
            if hit is None:
                return None
            self.cache.move_to_end(hit)
            entry = json.loads(json.dumps({k: v for k, v in self.cache[hit].items() if k != "fp"}))
        size = entry.get("size") or list(img.size)
        if entry.get("objects") is not None:
            entry["objects"] = rescale_objects(entry["objects"], size, img.size)
        if entry.get("analysis") is not None:
            entry["analysis"]["objects"] = rescale_objects(entry["analysis"].get("objects") or [],
                                                           size, img.size)
            entry["analysis"]["image_size"] = list(img.size)
        return entry

    def cache_put(self, key: str | None, img, **fields: Any) -> None:
        if not key:
            return
        with self.cache_lock:
            entry = self.cache.setdefault(key, {"fp": self.fingerprint(img), "size": list(img.size)})
            entry.update(json.loads(json.dumps(fields)))
            self.cache.move_to_end(key)
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)

    # -- generation
    def generate(self, img, prompts: list[str], max_new_tokens: int,
                 repetition_penalty: float = 1.05) -> list[str]:
        """Batched greedy generation: the same image with each prompt
        (at most MAX_BATCH prompts per forward batch)."""
        if len(prompts) > MAX_BATCH:
            out: list[str] = []
            for i in range(0, len(prompts), MAX_BATCH):
                out.extend(self.generate(img, prompts[i:i + MAX_BATCH], max_new_tokens,
                                         repetition_penalty))
            return out
        torch = self.torch
        view = self.model_view(img)
        convs = [[{"role": "user", "content": [{"type": "image", "image": view},
                                                {"type": "text", "text": p}]}] for p in prompts]
        with self.lock, torch.inference_mode():
            inputs = self.processor.apply_chat_template(
                convs, tokenize=True, add_generation_prompt=True, return_dict=True,
                return_tensors="pt", processor_kwargs={"padding": True},
            ).to(self.model.device)
            out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                      repetition_penalty=repetition_penalty)
            trimmed = out[:, inputs["input_ids"].shape[1]:]
            texts = self.processor.batch_decode(trimmed, skip_special_tokens=True)
            del inputs, out, trimmed
        return texts

    def _ground(self, img, names: list[str], max_objects: int) -> list[dict[str, Any]]:
        """Boxes for the inventory names: one short grounding prompt per name
        group, all groups in one batch; a malformed answer is retried once."""
        w, h = img.size
        groups = chunk_names(names, MAX_BATCH)
        prompts = [GROUND_PROMPT.format(names=", ".join(g)) for g in groups]
        # repetition_penalty 1.0: a penalty would push coordinates away from
        # repeated digits.
        texts = self.generate(img, prompts, 480, repetition_penalty=1.0)
        raw, failed = merge_group_outputs(texts)
        if failed:
            retry = self.generate(img, [prompts[i] + RETRY_SUFFIX for i in failed], 480,
                                  repetition_penalty=1.0)
            more, _ = merge_group_outputs(retry)
            raw.extend(more)
        if not raw and len(failed) == len(prompts):
            raise ValueError("grounding output unusable after one retry")
        return normalize_objects(raw, w, h, max_objects, self.box_format)

    def _single_pass(self, img, max_objects: int) -> list[dict[str, Any]]:
        prompt = DETECT_PROMPT.format(max_objects=max_objects)
        w, h = img.size
        for attempt in range(2):
            text = self.generate(img, [prompt + (RETRY_SUFFIX if attempt else "")], 1400,
                                 repetition_penalty=1.0)[0]
            try:
                return normalize_objects(extract_json(text, list), w, h, max_objects, self.box_format)
            except ValueError:
                if attempt:
                    raise
        return []

    def _inventory(self, img, max_objects: int, text: str | None = None) -> list[str]:
        """Object kinds from an inventory answer (generated here when text is None);
        one retry on a malformed answer."""
        limit = max_objects
        prompt = INVENTORY_PROMPT.format(max_objects=limit)
        for attempt in range(2):
            if text is None:
                text = self.generate(img, [prompt + (RETRY_SUFFIX if attempt else "")], 220)[0]
            try:
                names = names_from_inventory(extract_json(text, list), limit)
                if names:
                    return names
            except ValueError:
                pass
            text = None
        return []

    def _objects(self, img, max_objects: int, inventory_text: str | None) -> list[dict[str, Any]]:
        """Inventory (names) -> batched grounding (boxes); single-pass detect as fallback."""
        started = time.time()
        names = self._inventory(img, max_objects, inventory_text)
        t_inv = time.time()
        objects: list[dict[str, Any]] = []
        if names:
            try:
                objects = self._ground(img, names, max_objects)
            except ValueError:
                objects = []
        if not objects:
            objects = self._single_pass(img, max_objects)
        sys.stderr.write("[vlm] inventory %.1fs (%d kinds) + grounding %.1fs -> %d objects\n"
                         % (t_inv - started, len(names), time.time() - t_inv, len(objects)))
        return objects

    def detect(self, img, max_objects: int = DEFAULT_MAX_OBJECTS,
               image_key: str | None = None) -> dict[str, Any]:
        cached = self.cache_get(image_key, img) or {}
        objs, cap = cached.get("objects"), cached.get("objects_cap", 0)
        if objs is not None and (cap >= max_objects or len(objs) < cap):
            return {"objects": objs[:max_objects], "model": self.model_id, "cached": True}
        objs = self._objects(img, max_objects, None)
        self.cache_put(image_key, img, objects=objs, objects_cap=max_objects)
        return {"objects": objs, "model": self.model_id}

    def analyze(self, img, max_objects: int = 16, image_key: str | None = None) -> dict[str, Any]:
        cached = self.cache_get(image_key, img) or {}
        if cached.get("analysis") is not None:
            return cached["analysis"]
        objects = cached.get("objects")
        started = time.time()
        prompts = [ANALYZE_SCENE_PROMPT, ANALYZE_DESIGN_PROMPT]
        if objects is None:
            prompts.append(INVENTORY_PROMPT.format(max_objects=max_objects))
        texts = self.generate(img, prompts, 420)
        parts: list[Any] = [None, None]
        for attempt in range(2):
            if attempt:
                todo = [i for i in (0, 1) if parts[i] is None]
                if not todo:
                    break
                again = self.generate(img, [prompts[i] + RETRY_SUFFIX for i in todo], 420)
                for i, t in zip(todo, again):
                    texts[i] = t
            for i in (0, 1):
                if parts[i] is not None:
                    continue
                try:
                    got = extract_json(texts[i], dict)
                    if i == 0:
                        normalize_analysis(got)  # the scene part carries the core keys
                    elif not isinstance(got, dict):
                        raise ValueError("design part is not an object")
                    parts[i] = got
                except ValueError:
                    parts[i] = None
        if parts[0] is None:
            raise ValueError("analysis output unusable after one retry")
        sys.stderr.write("[vlm] analysis text %.1fs\n" % (time.time() - started))
        raw = merge_analysis_parts(parts[0], parts[1] or {})
        if objects is None:
            objects = self._objects(img, max_objects, texts[2] if len(texts) > 2 else None)
            self.cache_put(image_key, img, objects=objects, objects_cap=max_objects)
        measured = self.measured_light(img)
        doc = normalize_analysis(raw, objects, self.measured_palette(img), measured)
        doc["image_size"] = list(img.size)
        doc["model"] = self.model_id
        self.cache_put(image_key, img, analysis=doc)
        return json.loads(json.dumps(doc))


def make_handler(vm: VisionModel):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        server_version = "sketchscape-vlm/1"

        def log_message(self, fmt, *args):
            sys.stderr.write("[vlm] " + (fmt % args) + "\n")

        def _respond(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                free, total = vm.torch.cuda.mem_get_info()
                cuda = vm.torch.cuda
                self._respond(200, {"status": "ok", "model": vm.model_id,
                                    "vram_allocated_mb": int(cuda.memory_allocated() / 2**20),
                                    "vram_reserved_mb": int(cuda.memory_reserved() / 2**20),
                                    "vram_peak_reserved_mb": int(cuda.max_memory_reserved() / 2**20),
                                    "gpu_free_mb": int(free / 2**20),
                                    "max_batch": MAX_BATCH})
            else:
                self._respond(404, {"error": "not found"})

        def do_POST(self):
            if self.path not in ("/v1/detect", "/v1/analyze"):
                self._respond(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_IMAGE_BYTES * 2:
                    raise ValueError("bad request body size")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("body must be a JSON object")
                data = decode_image_b64(body.get("image_b64"))
                img = vm.load_image(data)
                image_key = hashlib.sha1(data).hexdigest()
            except (ValueError, json.JSONDecodeError, OSError) as exc:
                self._respond(400, {"error": str(exc)})
                return
            started = time.time()
            try:
                if self.path == "/v1/detect":
                    max_objects = body.get("max_objects", DEFAULT_MAX_OBJECTS)
                    try:
                        max_objects = max(1, min(HARD_MAX_OBJECTS, int(max_objects)))
                    except (TypeError, ValueError):
                        max_objects = DEFAULT_MAX_OBJECTS
                    result = vm.detect(img, max_objects, image_key)
                else:
                    result = vm.analyze(img, image_key=image_key)
            except ValueError as exc:
                self._respond(502, {"error": "model output unusable: %s" % exc})
                return
            except Exception as exc:  # noqa: BLE001 - keep the server alive
                self._respond(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            finally:
                vm.release_memory()
            sys.stderr.write("[vlm] %s %.1fs\n" % (self.path, time.time() - started))
            self._respond(200, result)

    return Handler


def serve(vm: VisionModel, host: str, port: int) -> None:
    from http.server import ThreadingHTTPServer

    httpd = ThreadingHTTPServer((host, port), make_handler(vm))
    sys.stderr.write("[vlm] serving %s on http://%s:%d\n" % (vm.model_id, host, port))
    httpd.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--host", default=os.environ.get("VLM_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-side", type=int, default=int(os.environ.get("VLM_MAX_SIDE", "1280")))
    parser.add_argument("--once", choices=("detect", "analyze"))
    parser.add_argument("--image")
    parser.add_argument("--max-objects", type=int, default=DEFAULT_MAX_OBJECTS)
    args = parser.parse_args()
    if not args.serve and not args.once:
        parser.error("pass --serve or --once")
    vm = VisionModel(args.model, args.max_side)
    if args.once:
        with open(args.image, "rb") as fh:
            img = vm.load_image(fh.read())
        started = time.time()
        result = vm.detect(img, args.max_objects) if args.once == "detect" else vm.analyze(img)
        result["_seconds"] = round(time.time() - started, 2)
        print(json.dumps(result, indent=1))
        return 0
    serve(vm, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
