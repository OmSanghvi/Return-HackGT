"""Compose a whole, immersive Shared Room for the Unity Editor (room spec v1 -> RoomKit).

``compose_room`` is the one job-shaped entry point a NemoClaw agent calls
(through ``unity_room_cli.py``). It turns a photo scene and/or contributed
objects into a **room spec** (docs/IMMERSIVE_SCENE_PIPELINE.md section 5),
which the Unity Editor script ``SketchScape.RoomKit.Build(string json)``
builds in its own scene file (``Assets/SketchScape/AgentRooms/<slug>.unity``).

Everything defaults intelligently, so a bare
``{"scene_id": ..., "room_name": ...}`` already produces an immersive room:

- **Layout.** With a photo scene (``scene_id``, from ``list_scenes``), the
  whole photo is a metric Gaussian-splat scene placed by
  ``scene_layout.photo_room_layout`` so the player stands where the camera
  was, at real scale; objects the sync cut out of the scene splat are placed
  as separate, grabbable splats exactly where they were in the photo. Without
  a scene, objects stand upright on an arc facing the entry
  (``scene_tools.place_objects_in_scene``) at their label sizes.
- **Environment** from the scene's vision analysis (catalog
  ``scenes[].analysis``): a CC0 HDRI sky by setting/time of day/mood, a key
  light from ``lighting.key_direction`` with its colour from
  ``color_temperature_k`` and its strength from ``brightness``, fill and rim
  lights, practical point lights on lamps/candles/fireplaces/TVs, fog from
  mood and palette, particles (dust in the light indoors, fireflies at
  night outdoors, ...), a floor texture from ``materials.floor``, ambient
  sound from ``search_terms.sounds``.
- **Web media** the agent found (``web_media.search_*``): images become a
  small gallery at eye height around the periphery, facing the player and
  never in front of the photo scene; sounds become ambience or attach to an
  object. Every web asset is credited.
- **Staging** from ``connection_insight`` (``scene_tools.stage_immersive_reveal``).

Outputs: the spec, a compact plan for the agent, and a few lines of C# for
``Unity_RunCommand`` that call RoomKit through reflection with the spec as a
string literal. Standard library only (runs in the NemoClaw sandbox).
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import scene_tools as st
import web_media as wm
from scene_tools import SceneToolError

try:  # the sync-layout stream's photo layout (contract section 0/5)
    import scene_layout as _scene_layout
except Exception:  # pragma: no cover - sandbox without the file
    _scene_layout = None  # type: ignore[assignment]

__all__ = [
    "AGENT_ROOMS_FOLDER",
    "SPEC_VERSION",
    "ROOMKIT_TYPE",
    "compose_room",
    "room_build_command",
    "room_build_parts",
    "room_finalize_command",
    "room_slug",
    "load_catalog",
    "load_catalog_doc",
    "match_catalog",
    "find_scene",
    "list_scenes",
    "kelvin_to_rgb",
    "shared_block",
]

AGENT_ROOMS_FOLDER = "Assets/SketchScape/AgentRooms"
SPEC_VERSION = 1
ROOMKIT_TYPE = "SketchScape.RoomKit, Assembly-CSharp-Editor"
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
DEFAULT_EYE_HEIGHT = 1.6

_OBJECT_TINTS = (
    (0.85, 0.55, 0.45), (0.45, 0.65, 0.85), (0.60, 0.80, 0.50), (0.90, 0.80, 0.45),
    (0.70, 0.55, 0.85), (0.50, 0.80, 0.78), (0.88, 0.62, 0.70), (0.75, 0.70, 0.60),
)
_WHITE = (1.0, 1.0, 1.0)
_HOTSPOT_STANDOFF = 0.9
_MAX_HOTSPOTS = 8
_MAX_IMAGES = 6
_MAX_SOUNDS = 5

# Shared layer (docs/WEB_TO_QUEST_PIPELINE.md section 3): the headset reads the project's
# /v1/rooms/{p}/shared view through the web app's HTTPS proxy (Android blocks cleartext).
DEFAULT_PUBLIC_API_BASE = "https://returnweb-hazel.vercel.app/api"
_DEFAULT_DEMO_USERS = ("demo-alice", "demo-bob")
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def room_slug(name: str) -> str:
    """A file- and GameObject-safe room slug (``[A-Za-z0-9_-]``, max 60)."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip()).strip("_-")[:60]
    return slug or "SharedRoom"


def _checked_slug(slug: str) -> str:
    if not _SLUG_PATTERN.match(slug or ""):
        raise SceneToolError(f"invalid room slug {slug!r}; use letters, digits, '_' or '-' (max 60)")
    return slug


def _scene_path(slug: str) -> str:
    return f"{AGENT_ROOMS_FOLDER}/{slug}.unity"


def _root_name(slug: str) -> str:
    return f"SharedRoom_{slug}"


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "nemoclaw" / "asset-catalog.json"


def load_catalog_doc(path: Optional[str] = None) -> dict:
    """The whole catalog written by scripts/sync_s3_assets_to_unity.py:
    ``{"assets": [...], "scenes": [...]}``. Missing file -> empty catalog."""
    target = Path(path or os.environ.get("SKETCHSCAPE_ASSET_CATALOG") or _CATALOG_PATH)
    if not target.is_file():
        return {"assets": [], "scenes": []}
    doc = json.loads(target.read_text(encoding="utf-8"))
    return {"assets": list(doc.get("assets") or []), "scenes": list(doc.get("scenes") or [])}


def load_catalog(path: Optional[str] = None) -> list[dict]:
    """Real reconstructed assets imported into Unity (catalog ``assets``)."""
    return load_catalog_doc(path)["assets"]


def _words(text: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", (text or "").lower())}


def match_catalog(objects: Sequence[Any], catalog: Sequence[Mapping[str, Any]]) -> list[Optional[dict]]:
    """For each input object, the catalog asset to render it with, or None.

    An exact ``asset_id`` match wins; otherwise the longest catalog label
    whose words all appear in the object's label ("our cat Miso" -> "cat")."""
    by_id = {a.get("asset_id"): a for a in catalog}
    matches: list[Optional[dict]] = []
    for raw in objects:
        found = by_id.get(st._get(raw, "asset_id"))
        if found is None:
            words = _words(st._get(raw, "label") or "")
            candidates = [a for a in catalog if _words(a.get("label", "")) and _words(a["label"]) <= words]
            found = max(candidates, key=lambda a: len(a["label"]), default=None)
        matches.append(dict(found) if found else None)
    return matches


def find_scene(scene_id: str, doc: Mapping[str, Any]) -> Optional[dict]:
    """A catalog scene by its id (the upload id), or a unique prefix of >= 6 chars."""
    sid = (scene_id or "").strip().lower()
    if not sid:
        return None
    scenes = list(doc.get("scenes") or [])
    for scene in scenes:
        if str(scene.get("scene_id", "")).lower() == sid:
            return dict(scene)
    if len(sid) >= 6:
        hits = [s for s in scenes if str(s.get("scene_id", "")).lower().startswith(sid)]
        if len(hits) == 1:
            return dict(hits[0])
    return None


def _scene_assets(scene: Mapping[str, Any], assets: Sequence[Mapping[str, Any]]) -> list[dict]:
    ids = set(scene.get("asset_ids") or [])
    sid = scene.get("scene_id")
    return [dict(a) for a in assets if a.get("asset_id") in ids or (sid and a.get("upload_id") == sid)]


def list_scenes(doc: Mapping[str, Any]) -> list[dict]:
    """Compact summaries of the photo scenes in the catalog, for the agent."""
    assets = list(doc.get("assets") or [])
    out = []
    for scene in doc.get("scenes") or []:
        analysis = scene.get("analysis") or {}
        cut = set(scene.get("cut_asset_ids") or [])
        members = _scene_assets(scene, assets)
        out.append({
            "scene_id": scene.get("scene_id"),
            "project_id": scene.get("project_id"),
            "has_splat": bool(scene.get("unity_path")),
            "caption": str(analysis.get("caption") or "")[:160],
            "room_type": analysis.get("room_type") or "",
            "setting": analysis.get("setting") or "",
            "time_of_day": analysis.get("time_of_day") or "",
            "mood": analysis.get("mood") or "",
            "objects": [a.get("label") for a in members],
            "separate_objects": [a.get("label") for a in members if a.get("asset_id") in cut],
        })
    return out


# ---------------------------------------------------------------------------
# Small math
# ---------------------------------------------------------------------------


def _r(v: float, nd: int = 3) -> float:
    out = round(float(v), nd)
    return 0.0 if out == 0 else out


def _rv(values: Sequence[float], nd: int = 3) -> list[float]:
    return [_r(v, nd) for v in values]


def _clamp01(values: Sequence[float]) -> list[float]:
    return [_r(max(0.0, min(1.0, float(c)))) for c in values]


def _mix(a: Sequence[float], b: Sequence[float], t: float) -> list[float]:
    return [a[i] * (1.0 - t) + b[i] * t for i in range(3)]


def _quat_yaw(yaw_deg: float) -> list[float]:
    h = math.radians(yaw_deg) / 2.0
    return _rv([0.0, math.sin(h), 0.0, math.cos(h)], 4)


def _quat_euler(pitch_deg: float, yaw_deg: float) -> list[float]:
    """Unity ``Quaternion.Euler(pitch, yaw, 0)`` as [x, y, z, w]."""
    px, py = math.radians(pitch_deg) / 2.0, math.radians(yaw_deg) / 2.0
    sx, cx, sy, cy = math.sin(px), math.cos(px), math.sin(py), math.cos(py)
    return _rv([cy * sx, sy * cx, -sy * sx, cy * cx], 4)


def _look_yaw(dx: float, dz: float) -> float:
    """Yaw (degrees) whose forward (+Z) points along (dx, dz)."""
    return math.degrees(math.atan2(dx, dz))


def kelvin_to_rgb(kelvin: Any) -> list[float]:
    """Blackbody colour for a colour temperature (Tanner Helland's fit), 0..1."""
    try:
        k = float(kelvin)
    except (TypeError, ValueError):
        return [1.0, 0.96, 0.9]
    t = max(1000.0, min(40000.0, k)) / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307
    return _clamp01([r / 255.0, g / 255.0, b / 255.0])


def _hex_rgb(value: Any) -> Optional[list[float]]:
    m = re.match(r"^#?([0-9a-fA-F]{6})$", str(value or "").strip())
    if not m:
        return None
    h = m.group(1)
    return [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]


def _palette(analysis: Mapping[str, Any]) -> list[list[float]]:
    return [c for c in (_hex_rgb(v) for v in (analysis.get("palette") or [])) if c]


def _avg(colors: Sequence[Sequence[float]], default: Sequence[float]) -> list[float]:
    if not colors:
        return list(default)
    return [sum(c[i] for c in colors) / len(colors) for i in range(3)]


def _text(value: Any, limit: int = 160) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _flat_words(*values: Any) -> str:
    parts: list[str] = []
    for v in values:
        if isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
        elif isinstance(v, Mapping):
            parts.extend(str(x) for x in v.values())
        elif v:
            parts.append(str(v))
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Frames: the spawn's local frame (camera looks along +Z at yaw 0)
# ---------------------------------------------------------------------------


class _Frame:
    def __init__(self, spawn: Sequence[float], yaw: float, eye: float):
        self.origin = [float(spawn[0]), 0.0, float(spawn[2])]
        self.yaw = float(yaw)
        self.eye = eye
        y = math.radians(self.yaw)
        self.fwd = (math.sin(y), math.cos(y))  # (x, z)
        self.right = (math.cos(y), -math.sin(y))

    def world(self, lateral: float, forward: float, height: float = 0.0) -> list[float]:
        return [
            self.origin[0] + self.right[0] * lateral + self.fwd[0] * forward,
            height,
            self.origin[2] + self.right[1] * lateral + self.fwd[1] * forward,
        ]

    def local(self, p: Sequence[float]) -> tuple[float, float]:
        dx, dz = float(p[0]) - self.origin[0], float(p[2]) - self.origin[2]
        return dx * self.right[0] + dz * self.right[1], dx * self.fwd[0] + dz * self.fwd[1]

    def bearing(self, p: Sequence[float]) -> float:
        lat, fwd = self.local(p)
        return math.degrees(math.atan2(lat, fwd))


# ---------------------------------------------------------------------------
# Analysis-driven environment
# ---------------------------------------------------------------------------

_BRIGHTNESS = {"dim": 0.65, "low": 0.65, "dark": 0.5, "medium": 1.0, "moderate": 1.0, "bright": 1.3, "high": 1.3}


def _brightness(analysis: Mapping[str, Any]) -> float:
    words = _flat_words((analysis.get("lighting") or {}).get("brightness"))
    for key, value in _BRIGHTNESS.items():
        if key in words:
            return value
    tod = _flat_words(analysis.get("time_of_day"))
    return 0.7 if any(w in tod for w in ("night", "evening", "dusk")) else 1.0


def _default_kelvin(analysis: Mapping[str, Any]) -> float:
    tod = _flat_words(analysis.get("time_of_day"))
    mood = _flat_words(analysis.get("mood"))
    if "night" in tod:
        return 2700.0 if (analysis.get("setting") or "indoor") != "outdoor" else 7500.0
    if any(w in tod for w in ("evening", "sunset", "dusk")) or any(w in mood for w in ("cozy", "warm")):
        return 3200.0
    if "morning" in tod or "sunrise" in tod:
        return 4500.0
    return 5500.0


def _key_direction(text: Any) -> tuple[float, float, str]:
    """(travel yaw relative to the camera, elevation degrees, description) for
    light arriving *from* ``text`` ("from window at left")."""
    words = _flat_words(text)
    from_x, from_z = 0.0, 0.0
    if "left" in words:
        from_x -= 1.0
    if "right" in words:
        from_x += 1.0
    if "behind" in words or "back" in words.split() or "camera" in words:
        from_z -= 1.0
    if "front" in words or "ahead" in words or "backlit" in words or "facing" in words or "opposite" in words:
        from_z += 1.0
    overhead = any(w in words for w in ("above", "overhead", "ceiling", "top"))
    if from_x == 0.0 and from_z == 0.0:
        from_x, from_z = -0.7, -0.5  # classic three-quarter key from the upper left
        desc = "default 3/4 left"
    else:
        desc = _text(text, 60) or "analysis"
    elevation = 70.0 if overhead else (18.0 if "window" in words or "sunset" in words or "low" in words else 42.0)
    # Light travels away from where it comes from.
    return _look_yaw(-from_x, -from_z), elevation, desc


def _fog(setting: str, analysis: Mapping[str, Any], base_color: Sequence[float], sky: Sequence[float]) -> dict:
    mood = _flat_words(analysis.get("mood"), analysis.get("caption"))
    density = 0.012 if setting == "indoor" else 0.006
    if any(w in mood for w in ("dream", "mist", "fog", "haz", "cozy", "nostalg", "mysteri", "magic", "romantic", "soft")):
        density *= 1.8
    if any(w in mood for w in ("crisp", "clear", "bright", "clean", "energetic")):
        density *= 0.6
    color = _mix(base_color, sky, 0.5)
    return {"enabled": True, "color": _clamp01(color), "density": _r(density, 4)}


_PRACTICALS = [
    (re.compile(r"candle", re.I), 1850.0, 0.9, 2.5, "candle"),
    (re.compile(r"fire\s*place|fireplace|hearth|campfire|bonfire|fire\b|stove", re.I), 1900.0, 2.0, 5.0, "fire"),
    (re.compile(r"lantern|lamp|sconce|chandelier|bulb|string lights|fairy lights|light\b", re.I), 2700.0, 1.4, 4.0, "lamp"),
    (re.compile(r"\btv\b|television|monitor|screen|laptop", re.I), 8000.0, 0.8, 3.0, "screen"),
    (re.compile(r"neon", re.I), 0.0, 1.2, 3.5, "neon"),
]


def _practical(label: str) -> Optional[tuple[float, float, float, str]]:
    for pattern, kelvin, intensity, rng, kind in _PRACTICALS:
        if pattern.search(label or ""):
            return kelvin, intensity, rng, kind
    return None


def _particles_for(kind: str, frame: _Frame, center: Sequence[float], analysis: Mapping[str, Any],
                   key_color: Sequence[float], palette_avg: Sequence[float]) -> dict:
    presets = {
        "dust": ([3.0, 2.2, 3.0], _mix(key_color, _WHITE, 0.5), 14),
        "fireflies": ([8.0, 2.5, 8.0], [1.0, 0.85, 0.35], 10),
        "snow": ([12.0, 6.0, 12.0], [0.95, 0.97, 1.0], 60),
        "rain": ([12.0, 6.0, 12.0], [0.7, 0.75, 0.85], 200),
        "embers": ([1.2, 1.5, 1.2], [1.0, 0.5, 0.15], 12),
    }
    size, color, rate = presets.get(kind, presets["dust"])
    if kind in ("snow", "rain", "fireflies"):
        pos = frame.world(0.0, 2.0, size[1] / 2.0)
    elif kind == "embers":
        pos = [center[0], 0.4, center[2]]
    else:  # dust hangs in the air between the player and the scene, in the key light
        c_lat, c_fwd = frame.local(center)
        pos = frame.world(c_lat * 0.6, max(1.2, c_fwd * 0.6), frame.eye * 0.9)
    return {"kind": kind, "position": _rv(pos), "size": _rv(size), "color": _clamp01(color), "rate": rate}


def _auto_particles(setting: str, analysis: Mapping[str, Any], labels: Sequence[str]) -> list[str]:
    text = _flat_words(analysis.get("mood"), analysis.get("caption"), analysis.get("time_of_day"),
                       (analysis.get("search_terms") or {}).get("sounds"), analysis.get("room_type"))
    labels_text = " ".join(labels).lower()
    tod = _flat_words(analysis.get("time_of_day"))
    kinds: list[str] = []
    if "snow" in text or "winter" in text:
        kinds.append("snow")
    elif setting == "outdoor" and "rain" in text:
        kinds.append("rain")
    elif setting == "outdoor" and any(w in tod for w in ("night", "evening", "dusk")):
        kinds.append("fireflies")
    elif setting == "indoor":
        kinds.append("dust")
    if re.search(r"fireplace|campfire|bonfire|hearth", labels_text + " " + text):
        kinds.append("embers")
    return kinds[:2]


# ---------------------------------------------------------------------------
# Environment overrides from the request
# ---------------------------------------------------------------------------


def _resolve_hdri(value: Any) -> Optional[dict]:
    """A curated id, a Poly Haven id, or an https .hdr/.exr URL -> {url, name, attribution}."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in ("none", "off", "false"):
        return {"url": "", "name": "none", "attribution": ""}
    if text.startswith("https://"):
        name = text.rsplit("/", 1)[-1][:60]
        return {"url": text, "name": name, "attribution": f"'{name}' HDRI, CC0, via Poly Haven" if "polyhaven.org" in text else ""}
    curated = wm.hdri_by_id(text)
    if curated:
        return {"url": curated["url_2k"], "name": curated["name"], "attribution": curated["attribution"], "exposure": curated["exposure"]}
    if re.match(r"^[a-z0-9_]+$", text):
        return {"url": wm.polyhaven_hdri_url(text), "name": text, "attribution": f"'{text}' HDRI, CC0, via Poly Haven"}
    # Free text: pick the best curated match.
    pick = wm.pick_hdri(keywords=text, mood=text, time_of_day=text, setting=text)
    return {"url": pick["url_2k"], "name": pick["name"], "attribution": pick["attribution"], "exposure": pick["exposure"]}


def _resolve_texture(value: Any, kind: str, setting: str) -> Optional[dict]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in ("none", "off", "false"):
        return {"url": "", "name": "none", "attribution": "", "tile_m": 2.0, "color": None}
    if text.startswith("https://"):
        name = text.rsplit("/", 1)[-1][:60]
        return {"url": text, "name": name, "attribution": f"'{name}' texture, CC0, via Poly Haven" if "polyhaven.org" in text else "",
                "tile_m": 2.0, "color": None}
    if not wm.texture_by_id(text) and re.match(r"^[a-z0-9]+(_[a-z0-9]+)+$", text):  # a Poly Haven id from search_environment
        return {"url": wm._PH_TEX.format(id=text), "name": text, "attribution": f"'{text}' texture, CC0, via Poly Haven", "tile_m": 2.0, "color": None}
    tex = wm.texture_by_id(text) or wm.pick_texture(kind, text, setting=setting)
    if not tex:
        return None
    return {"url": tex["url"], "name": tex["name"], "attribution": tex["attribution"], "tile_m": tex["tile_m"], "color": tex["color"]}


# ---------------------------------------------------------------------------
# JsonUtility safety
# ---------------------------------------------------------------------------


def _check_jsonutility(value: Any, path: str = "spec") -> None:
    """No nulls, no nested arrays, only finite numbers (contract section 5)."""
    if value is None:
        raise SceneToolError(f"room spec has a null at {path}")
    if isinstance(value, bool) or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise SceneToolError(f"room spec has a non-finite number at {path}")
        return
    if isinstance(value, Mapping):
        for k, v in value.items():
            _check_jsonutility(v, f"{path}.{k}")
        return
    if isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            if isinstance(v, (list, tuple)):
                raise SceneToolError(f"room spec has a nested array at {path}[{i}]")
            _check_jsonutility(v, f"{path}[{i}]")
        return
    raise SceneToolError(f"room spec has an unsupported value at {path}: {type(value).__name__}")


# ---------------------------------------------------------------------------
# Shared layer block (contract docs/WEB_TO_QUEST_PIPELINE.md section 3)
# ---------------------------------------------------------------------------


def _demo_users() -> list[str]:
    """The two demo accounts, as ``backend/auth.py`` reads them (exactly two, else the defaults)."""
    raw = os.environ.get("SKETCHSCAPE_DEMO_USERS", "")
    users = [u.strip() for u in raw.split(",") if u.strip()]
    return users if len(users) == 2 and len(set(users)) == 2 else list(_DEFAULT_DEMO_USERS)


def shared_block(project_id: Any) -> dict:
    """The room spec's ``shared`` block: on for a project, ``enabled: false`` with empty values otherwise."""
    pid = str(project_id or "").strip()
    if not _PROJECT_ID_PATTERN.match(pid):
        return {"enabled": False, "project_id": "", "api_base": "", "accounts": [], "labels": [],
                "default_account": "", "snapshot_resource": ""}
    base = (os.environ.get("SKETCHSCAPE_PUBLIC_API_BASE") or "").strip().rstrip("/") or DEFAULT_PUBLIC_API_BASE
    users = _demo_users()
    return {"enabled": True, "project_id": pid, "api_base": base, "accounts": users,
            "labels": [f"Account {i + 1}" for i in range(len(users))], "default_account": users[0],
            "snapshot_resource": f"SharedSnapshots/{pid}"}


def _room_project_id(request: Mapping[str, Any], scene: Optional[Mapping[str, Any]], matches: Sequence[Optional[Mapping[str, Any]]]) -> str:
    """The project a room belongs to: its photo scene's, else the one project all its matched scans share."""
    flag = request.get("shared")
    if flag is False or (isinstance(flag, str) and flag.strip().lower() in ("off", "none", "false", "no")):
        return ""
    if scene and scene.get("project_id"):
        return str(scene["project_id"])
    projects = {str(m.get("project_id")) for m in matches if m and m.get("project_id")}
    return projects.pop() if len(projects) == 1 else ""


# ---------------------------------------------------------------------------
# compose_room
# ---------------------------------------------------------------------------


def _label_size(label: str) -> float:
    return max(st._footprint_for_label(label or ""))


def _object_id(label: str, index: int, taken: set[str]) -> str:
    base = st._slugify(label or "object")[:40]
    oid = f"{base}_{index}"
    if not st.ID_PATTERN.match(oid):
        oid = f"object_{index}"
    while oid in taken:
        oid += "x"
    taken.add(oid)
    return oid


def _photo_layout(scene: Mapping[str, Any], layout_objects: list[dict], eye: float, notes: list[str]) -> Optional[dict]:
    fn = getattr(_scene_layout, "photo_room_layout", None) if _scene_layout is not None else None
    if fn is None:
        notes.append("scene_layout.photo_room_layout is not available here; photo scene skipped, objects on an arc")
        return None
    try:
        return fn(scene.get("scene") or None, layout_objects, player_eye_height=eye)
    except Exception as exc:  # layout failures degrade to the arc layout
        notes.append(f"photo layout failed ({type(exc).__name__}: {str(exc)[:100]}); objects on an arc")
        return None


_FIRE_RE = re.compile(r"fire\s*place|hearth|wood\s*stove|\bstove\b|campfire|bonfire|fire\s*pit", re.I)
# Curated ambiences that live outside: indoors they come in through the window, never as the room's bed.
_OUTDOOR_AMBIENCE = {"birds_morning", "city_evening", "ocean_waves", "night_crickets", "forest_breeze", "wind_gentle"}
# Requested sounds (by title / attach_to) that belong at the fire, or come in from outside.
_FIRE_SOUND_RE = re.compile(r"fire\s*place|fireplace|\bfire\b|crackl|hearth|campfire|\bembers\b|wood\s*stove", re.I)
_OUTSIDE_SOUND_RE = re.compile(r"rain|bird|wind\b|breeze|street|traffic|\bcity\b|cricket|ocean|waves|forest|thunder|storm", re.I)
_GENERIC_SOUND_WORDS = {"cozy", "home", "house", "room", "calm", "quiet", "indoor", "outdoor", "living", "night", "evening",
                        "morning", "summer", "winter", "spring", "open", "nature", "social", "cabin", "apartment", "bedroom"}
_WINDOW_RE = re.compile(r"\bwindows?\b", re.I)
_CURTAIN_RE = re.compile(r"curtain|drape", re.I)


def _photo_anchors(scene: Optional[Mapping[str, Any]], layout: Optional[Mapping[str, Any]],
                   analysis: Mapping[str, Any]) -> list[dict]:
    """World positions of the things the vision analysis boxed in the photo.

    Each ``analysis.objects[].box`` (pixels of the analysed image) takes the
    median depth of the scene's coarse depth-grid points that project inside
    it (or of its nearest few), is unprojected at the box centre with the
    scene intrinsics, and is mapped with the same camera -> world transform
    ``photo_room_layout`` gives the photo splat (``camera_alignment`` of the
    scene's gravity, then ``camera_world``). So a fire crackles, embers rise
    and a warm light glows where the fireplace really is in the photo, and
    outdoor sounds come in through its window. ``top`` is a point near the
    top of the box (a lampshade). Empty when anything needed is missing."""
    sl = _scene_layout
    align = getattr(sl, "camera_alignment", None) if sl is not None else None
    grid_points = getattr(sl, "_depth_grid_points", None) if sl is not None else None
    if not (scene and layout and align and grid_points and layout.get("camera_world")):
        return []
    doc = scene.get("scene") or {}
    try:
        intr = doc["intrinsics"]
        fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
        width, height = (float(v) for v in doc["image_size"])
        rot = align(doc["gravity_up_cam"])
        cam = [float(v) for v in layout["camera_world"]]
        pts = grid_points(doc)
    except (KeyError, TypeError, ValueError, IndexError):
        return []
    if not pts or fx <= 0 or fy <= 0:
        return []
    proj = [(fx * x / z + cx, fy * y / z + cy, z) for x, y, z in pts]
    try:
        aw, ah = (float(v) for v in (analysis.get("image_size") or [width, height]))
    except (TypeError, ValueError):
        aw, ah = width, height
    sx, sy = width / max(aw, 1.0), height / max(ah, 1.0)
    diag = math.hypot(width, height)

    def world(u: float, v: float, z: float) -> list[float]:
        p = [(u - cx) * z / fx, (v - cy) * z / fy, z]
        w = [sum(rot[i][j] * p[j] for j in range(3)) + cam[i] for i in range(3)]
        return [_r(w[0]), _r(max(0.0, w[1])), _r(w[2])]

    anchors: list[dict] = []
    for obj in analysis.get("objects") or []:
        if not isinstance(obj, Mapping):
            continue
        box, name = obj.get("box"), str(obj.get("name") or "").strip()
        if not name or not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            x0, y0, x1, y1 = float(box[0]) * sx, float(box[1]) * sy, float(box[2]) * sx, float(box[3]) * sy
        except (TypeError, ValueError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        u, v = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        depths = [z for pu, pv, z in proj if x0 <= pu <= x1 and y0 <= pv <= y1]
        if len(depths) < 2:  # a small box between grid points: its nearest neighbours
            near = sorted((math.hypot(pu - u, pv - v), z) for pu, pv, z in proj)[:3]
            depths = [z for d, z in near if d <= 0.15 * diag]
        if not depths:
            continue
        depths.sort()
        z = depths[len(depths) // 2]
        anchors.append({"name": name, "position": world(u, v, z), "top": world(u, y0 + 0.15 * (y1 - y0), z)})
    return anchors


def _toward(p: Sequence[float], target: Sequence[float], dist: float) -> list[float]:
    """``p`` moved ``dist`` metres (at most half the way) toward ``target`` on the ground plane."""
    dx, dz = float(target[0]) - float(p[0]), float(target[2]) - float(p[2])
    d = math.hypot(dx, dz)
    if d < 1e-6:
        return [float(p[0]), float(p[1]), float(p[2])]
    k = min(dist, 0.5 * d) / d
    return [float(p[0]) + dx * k, float(p[1]), float(p[2]) + dz * k]


def _arc_positions(count: int, frame: _Frame, *, radius: float, angles: Sequence[float]) -> list[tuple[list[float], float]]:
    out = []
    for i in range(count):
        ang = angles[i % len(angles)] + (0 if i < len(angles) else 8 * (i // len(angles)))
        r = radius + 0.35 * (i // len(angles))
        a = math.radians(ang)
        pos = frame.world(r * math.sin(a), r * math.cos(a), 0.0)
        facing = _look_yaw(frame.origin[0] - pos[0], frame.origin[2] - pos[2])
        out.append((pos, facing))
    return out


def compose_room(request: Mapping[str, Any], *, catalog: Optional[Mapping[str, Any]] = None) -> dict:
    """Plan a full, immersive Quest room. See the module docstring.

    ``request``: ``{"scene_id"?, "objects"? [{"asset_id"?, "label"}], "room_name",
    "theme"?, "connection_insight"? {"theme", "explanation"}, "player_eye_height"?,
    "environment"? {"hdri"|"hdri_url", "floor_texture", "wall_texture", "fog", "shell"},
    "images"? [{"url", "title", "attribution", "placement"?}],
    "sounds"? [{"url", "title", "attribution", "kind": "ambient"|"object", "attach_to"?}],
    "lights"? [...], "particles"? "auto"|"none"|kind|[kinds], "shared"? false}``.

    A room whose photo scene (or whose scans) belong to a project gets the spec's ``shared`` block
    (account switcher, personal notes, letters, object tags in VR); ``"shared": false`` leaves it off.

    Returns ``{"spec", "plan", "build_code", "finalize_code"}``.
    """
    if not isinstance(request, Mapping):
        raise SceneToolError("compose_room expects a JSON object")
    doc = load_catalog_doc() if catalog is None else {"assets": list(catalog.get("assets") or []), "scenes": list(catalog.get("scenes") or [])}
    notes: list[str] = []
    credits: list[str] = []

    def credit(text: Any) -> None:
        t = _text(text, 240)
        if t and t not in credits:
            credits.append(t)

    try:
        eye = float(request.get("player_eye_height") or DEFAULT_EYE_HEIGHT)
    except (TypeError, ValueError):
        raise SceneToolError("player_eye_height must be a number (metres)") from None
    if not 0.8 <= eye <= 2.2:
        raise SceneToolError("player_eye_height must be between 0.8 and 2.2 metres")

    raw_objects = list(request.get("objects") or [])
    for i, raw in enumerate(raw_objects):
        if not isinstance(raw, Mapping) or not (raw.get("label") or raw.get("asset_id")):
            raise SceneToolError(f"objects[{i}] needs a label (and optionally an asset_id)")
    matches = match_catalog(raw_objects, doc["assets"])

    # ---- which photo scene --------------------------------------------------
    scene_req = request.get("scene_id")
    scene: Optional[dict] = None
    if scene_req and str(scene_req).lower() not in ("none", "off", "false"):
        scene = find_scene(str(scene_req), doc)
        if scene is None:
            known = ", ".join(str(s.get("scene_id"))[:12] for s in doc["scenes"][:8]) or "none synced"
            raise SceneToolError(f"unknown scene_id {scene_req!r}; run list_scenes all (known: {known})")
    elif scene_req is None and doc["scenes"]:
        # Objects from one photo -> bring that whole photo scene along.
        votes: dict[str, int] = {}
        for m in matches:
            if not m:
                continue
            for s in doc["scenes"]:
                if m.get("asset_id") in (s.get("asset_ids") or []) or (m.get("upload_id") and m.get("upload_id") == s.get("scene_id")):
                    votes[s["scene_id"]] = votes.get(s["scene_id"], 0) + 1
        if votes:
            best = max(votes.items(), key=lambda kv: kv[1])[0]
            scene = find_scene(best, doc)
            notes.append(f"photo scene {best[:8]} added automatically (its objects were requested); pass \"scene_id\": \"none\" to leave it out")
    if not raw_objects and scene is None:
        raise SceneToolError("compose_room needs a scene_id (see list_scenes all) and/or objects")

    analysis: dict = dict((scene or {}).get("analysis") or {})
    setting = "outdoor" if "outdoor" in _flat_words(analysis.get("setting")) else "indoor"
    insight = request.get("connection_insight") if isinstance(request.get("connection_insight"), Mapping) else None
    theme = _text(request.get("theme") or (insight or {}).get("theme") or analysis.get("room_type") or "Shared Room", 120)
    slug = _checked_slug(room_slug(request.get("room_name") or theme))
    if not analysis:
        # No vision analysis: derive a little from the theme/insight words.
        text = _flat_words(theme, (insight or {}).get("explanation"))
        analysis = {"setting": setting, "mood": text, "time_of_day": text, "search_terms": {"sounds": [text]}}

    taken: set[str] = set()
    spec_objects: list[dict] = []
    in_photo: list[str] = []
    extras: list[tuple[dict, Optional[dict]]] = []  # (normalized raw, catalog match)

    # ---- photo scene layout ---------------------------------------------------
    layout: Optional[dict] = None
    scene_members: list[dict] = []
    if scene is not None:
        scene_members = _scene_assets(scene, doc["assets"])
        has_splat = bool(scene.get("unity_path"))
        cut = set(scene.get("cut_asset_ids") or [])
        # Without a scene splat nothing is "inside" it: place every member separately.
        separate = [a for a in scene_members if (a.get("asset_id") in cut) or not has_splat]
        for a in scene_members:
            if a not in separate:
                in_photo.append(str(a.get("label") or a.get("asset_id")))
        layout_objects = []
        member_ids: dict[str, dict] = {}
        for a in separate:
            oid = _object_id(str(a.get("label") or "object"), len(taken), taken)
            member_ids[oid] = a
            layout_objects.append({
                "id": oid, "pose": a.get("pose"), "native_extent": a.get("native_extent"),
                "bounds_min": a.get("bounds_min"), "bounds_max": a.get("bounds_max"),
                "label_size_m": _label_size(str(a.get("label") or "")),
            })
        layout = _photo_layout(scene, layout_objects, eye, notes)
        placed = (layout or {}).get("objects") or {}
        for oid, a in member_ids.items():
            p = placed.get(oid)
            if not p:
                extras.append(({"id": oid, "label": a.get("label") or oid, "asset_id": a.get("asset_id")}, a))
                continue
            mode = p.get("mode") if p.get("mode") in ("transform", "upright") else "upright"
            spec_objects.append({
                "id": oid, "label": str(a.get("label") or oid), "asset_id": str(a.get("asset_id") or ""),
                "splat_path": str(a.get("unity_path") or ""), "mode": mode,
                "position": _rv(p.get("position") or [0, 0, 0]), "rotation": _rv(p.get("rotation") or [0, 0, 0, 1], 4),
                "scale": _rv(p.get("scale") or [1, 1, 1], 4), "size_m": _r(p.get("size_m") or _label_size(str(a.get("label") or ""))),
                "_visual": f"real 3D scan, {'placed as in the photo' if mode == 'transform' else 'upright at its photo spot'}",
            })
        for note in (layout or {}).get("notes") or []:
            notes.append(_text(note, 120))

    # ---- requested objects not already covered by the scene -----------------
    scene_asset_ids = {a.get("asset_id") for a in scene_members}
    for i, (raw, m) in enumerate(zip(raw_objects, matches)):
        label = _text(raw.get("label") or raw.get("asset_id"), 80)
        if m and m.get("asset_id") in scene_asset_ids:
            if m.get("label") and str(m.get("label")) in in_photo:
                notes.append(f"'{label}' is already in the photo scene")
            continue  # placed (or inside the splat) with its scene
        extras.append(({"id": _object_id(label, len(taken), taken), "label": label, "asset_id": raw.get("asset_id") or (m or {}).get("asset_id") or ""}, m))

    # ---- spawn frame ------------------------------------------------------------
    if layout:
        spawn_pos = list((layout.get("spawn") or {}).get("position") or [0.0, 0.0, 0.0])
        spawn_yaw = float((layout.get("spawn") or {}).get("yaw") or 0.0)
    else:
        spawn_pos, spawn_yaw = [0.0, 0.0, 0.0], 0.0
    frame = _Frame(spawn_pos, spawn_yaw, eye)

    # ---- things the analysis saw in the photo, located in the room ------------
    anchors = _photo_anchors(scene, layout, analysis)
    fire_anchor = next((a for a in anchors if _FIRE_RE.search(a["name"])), None)
    window_anchor = next((a for a in anchors if _WINDOW_RE.search(a["name"])), None) \
        or next((a for a in anchors if _CURTAIN_RE.search(a["name"])), None)
    window_at: Optional[list[float]] = None
    if window_anchor:
        window_at = _toward(window_anchor["position"], frame.origin, 0.3)
        window_at[1] = max(1.2, window_at[1])
    anchored: list[str] = []

    # ---- extras: arc in front (no scene) or low side arcs (beside the photo) -
    if extras:
        if layout:
            angles = [-62.0, 62.0, -80.0, 80.0, -48.0, 48.0, -95.0, 95.0]
            spots = _arc_positions(len(extras), frame, radius=1.7, angles=angles)
            for (obj, m), (pos, facing) in zip(extras, spots):
                spec_objects.append(_upright(obj, m, pos, facing, len(spec_objects)))
        else:
            blueprint = st.place_objects_in_scene(
                [{"asset_id": f"obj{i}", "label": o["label"]} for i, (o, _) in enumerate(extras)],
                theme=theme,
            )
            for (obj, m), b in zip(extras, blueprint["objects"]):
                pos = [b["position"][0], 0.0, b["position"][2]]
                spec_objects.append(_upright(obj, m, pos, b["rotation"][1], len(spec_objects)))

    # ---- bounds of the whole composition --------------------------------------
    pts: list[list[float]] = [frame.origin]
    if layout and layout.get("bounds"):
        bmin, bmax = layout["bounds"].get("min"), layout["bounds"].get("max")
        if bmin and bmax:
            pts += [[bmin[0], 0, bmin[2]], [bmax[0], 0, bmax[2]], [bmin[0], 0, bmax[2]], [bmax[0], 0, bmin[2]]]
    pts += [o["position"] for o in spec_objects]
    min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
    min_z, max_z = min(p[2] for p in pts), max(p[2] for p in pts)
    center = [(min_x + max_x) / 2.0, 0.0, (min_z + max_z) / 2.0]
    if layout and layout.get("bounds") and layout["bounds"].get("min"):
        bmin, bmax = layout["bounds"]["min"], layout["bounds"]["max"]
        scene_center = [(bmin[0] + bmax[0]) / 2, (bmin[1] + bmax[1]) / 2, (bmin[2] + bmax[2]) / 2]
        scene_half = [(bmax[0] - bmin[0]) / 2, (bmax[1] - bmin[1]) / 2, (bmax[2] - bmin[2]) / 2]
    else:
        scene_center = [center[0], 0.8, center[2]] if spec_objects else frame.world(0, 2.0, 0.8)
        scene_half = [max(0.6, (max_x - min_x) / 2), 0.8, max(0.6, (max_z - min_z) / 2)]

    # ---- environment ------------------------------------------------------------
    env_req = request.get("environment") if isinstance(request.get("environment"), Mapping) else {}
    search_terms = analysis.get("search_terms") or {}
    palette = _palette(analysis)
    palette_avg = _avg(palette, (0.6, 0.55, 0.5))
    brightness = _brightness(analysis)
    lighting = analysis.get("lighting") or {}
    kelvin = lighting.get("color_temperature_k") or _default_kelvin(analysis)
    key_color = kelvin_to_rgb(kelvin)

    hdri = _resolve_hdri(env_req.get("hdri_url") or env_req.get("hdri"))
    if hdri is None:
        pick = wm.pick_hdri(setting, analysis.get("time_of_day"), analysis.get("mood"),
                            [analysis.get("room_type") or "", search_terms.get("hdri") or [], analysis.get("caption") or ""])
        hdri = {"url": pick["url_2k"], "name": pick["name"], "attribution": pick["attribution"], "exposure": pick["exposure"]}
    credit(hdri.get("attribution"))
    sky_tint = _clamp01(_mix(_WHITE, palette_avg, 0.15))
    exposure = _r(float(hdri.get("exposure", 1.0)) * (0.75 + 0.25 * brightness), 3)

    fog_req = env_req.get("fog")
    fog = _fog(setting, analysis, _mix(palette_avg, key_color, 0.5), sky_tint)
    if fog_req is False or (isinstance(fog_req, str) and fog_req.lower() in ("none", "off", "false")):
        fog["enabled"] = False
    elif isinstance(fog_req, (int, float)) and not isinstance(fog_req, bool):
        fog["density"] = _r(max(0.0, min(0.2, float(fog_req))), 4)
    elif isinstance(fog_req, Mapping):
        if "enabled" in fog_req:
            fog["enabled"] = bool(fog_req["enabled"])
        if isinstance(fog_req.get("density"), (int, float)):
            fog["density"] = _r(max(0.0, min(0.2, float(fog_req["density"]))), 4)
        if _hex_rgb(fog_req.get("color")):
            fog["color"] = _clamp01(_hex_rgb(fog_req.get("color")))  # type: ignore[arg-type]

    materials = analysis.get("materials") or {}
    floor_tex = _resolve_texture(env_req.get("floor_texture"), "floor", setting)
    if floor_tex is None:
        t = wm.pick_texture("floor", [materials.get("floor") or "", analysis.get("room_type") or "", analysis.get("caption") or ""] if setting == "outdoor" else [materials.get("floor") or "", analysis.get("room_type") or ""], setting=setting)
        floor_tex = {"url": t["url"], "name": t["name"], "attribution": t["attribution"], "tile_m": t["tile_m"], "color": t["color"]} if t else None
    extent = max(abs(min_x), abs(max_x), abs(min_z), abs(max_z), 3.0)
    floor_side = _r(max(12.0, 2.0 * extent + 6.0), 1)
    support = (layout or {}).get("support") or {}
    floor_height = -0.02 if (layout and scene and scene.get("unity_path") and str(support.get("kind")) == "floor") else 0.0
    floor = {
        "enabled": True, "size": [floor_side, floor_side], "height": floor_height,
        "texture_url": (floor_tex or {}).get("url", ""),
        "color": _clamp01((floor_tex or {}).get("color") or _mix(palette_avg, (0.35, 0.32, 0.3), 0.6)),
        "tiling": _r(floor_side / max(0.3, float((floor_tex or {}).get("tile_m") or 2.0)), 2),
    }
    if floor_tex and floor_tex.get("url"):
        credit(floor_tex.get("attribution"))

    shell_req = env_req.get("shell")
    wall_tex = _resolve_texture(env_req.get("wall_texture"), "wall", setting)
    shell_on = bool(shell_req) if not isinstance(shell_req, Mapping) else bool(shell_req.get("enabled", True))
    if wall_tex and wall_tex.get("url") and shell_req is None:
        shell_on = True
    if shell_on and wall_tex is None:
        t = wm.pick_texture("wall", materials.get("walls") or "plaster wall", setting=setting)
        wall_tex = {"url": t["url"], "name": t["name"], "attribution": t["attribution"], "tile_m": t["tile_m"], "color": t["color"]} if t else None
    shell_size = [_r(max(6.0, (max_x - min_x) + 3.0)), _r(max(3.0, eye + 1.4, scene_center[1] + scene_half[1] + 0.5)), _r(max(6.0, (max_z - min_z) + 3.0))]
    if isinstance(shell_req, Mapping) and isinstance(shell_req.get("size"), list) and len(shell_req["size"]) == 3:
        shell_size = [_r(max(shell_size[i], float(shell_req["size"][i]))) for i in range(3)]
    shell = {
        "enabled": shell_on, "center": _rv([center[0], 0.0, center[2]]), "size": shell_size,
        "wall_texture_url": (wall_tex or {}).get("url", "") if shell_on else "",
        "wall_color": _clamp01((wall_tex or {}).get("color") or _mix(palette_avg, _WHITE, 0.5)),
        "ceiling": setting == "indoor",
    }
    if shell_on and wall_tex and wall_tex.get("url"):
        credit(wall_tex.get("attribution"))

    environment = {
        "hdri_url": hdri.get("url", ""), "hdri_rotation": 0.0, "hdri_exposure": exposure,
        "sky_tint": sky_tint, "ambient_mode": "skybox" if hdri.get("url") else "flat",
        "ambient_color": _clamp01(_mix(palette_avg, key_color, 0.5)),
        "ambient_intensity": _r(0.8 + 0.2 * brightness), "fog": fog, "floor": floor, "shell": shell,
    }

    # ---- lights -------------------------------------------------------------------
    rel_yaw, elevation, key_desc = _key_direction(lighting.get("key_direction"))
    key_yaw = frame.yaw + rel_yaw
    lights = [
        {"type": "directional", "color": key_color, "intensity": _r(1.05 * brightness), "position": _rv(frame.world(0, 0, 3.0)),
         "rotation": _quat_euler(elevation, key_yaw), "range": 10.0, "spot_angle": 60.0, "shadows": "soft", "name": "Key Light"},
        {"type": "directional", "color": _clamp01(_mix(key_color, sky_tint, 0.7)), "intensity": _r(0.35 * brightness),
         "position": _rv(frame.world(0, 0, 3.0)), "rotation": _quat_euler(25.0, key_yaw + 180.0), "range": 10.0, "spot_angle": 60.0,
         "shadows": "none", "name": "Fill Light"},
    ]
    rim_color = _clamp01(_mix(palette[0] if palette else key_color, _WHITE, 0.4))
    s_lat, s_fwd = frame.local(scene_center)
    rim_pos = frame.world(s_lat, s_fwd + scene_half[2] + 1.2, max(1.8, scene_center[1] + scene_half[1] + 0.6))
    lights.append({"type": "point", "color": rim_color, "intensity": _r(0.9 * brightness), "position": _rv(rim_pos),
                   "rotation": [0.0, 0.0, 0.0, 1.0], "range": _r(max(4.0, 2.5 * max(scene_half[0], scene_half[2]) + 2.0)),
                   "spot_angle": 60.0, "shadows": "none", "name": "Rim Light"})
    # Practical lights named by the analysis ("floor lamp right", "candles"): at
    # the lamp / fire the analysis boxed in the photo when there is one, else
    # on the named side of the scene.
    for source in list(lighting.get("sources") or [])[:4]:
        found = _practical(str(source))
        if not found or re.search(r"window|sun|sky|daylight", str(source), re.I):
            continue
        k, inten, rng, kind = found
        at = fire_anchor if kind == "fire" else next((a for a in anchors if (_practical(a["name"]) or (0, 0, 0, ""))[3] == kind), None)
        if at:
            pos = _toward(at["position"] if kind == "fire" else at["top"], frame.origin, 0.35)
            pos[1] = max(pos[1], 0.35)
            anchored.append(f"{kind} light at the {_text(at['name'], 30)}")
        else:
            words = _flat_words(source)
            lat = s_lat + (-0.8 * scene_half[0] if "left" in words else (0.8 * scene_half[0] if "right" in words else 0.0))
            pos = frame.world(lat, s_fwd + (0.5 * scene_half[2] if "back" in words else 0.0), 1.3 if kind == "lamp" else 0.6)
        lights.append({"type": "point", "color": kelvin_to_rgb(k), "intensity": _r(inten * brightness), "position": _rv(pos),
                       "rotation": [0.0, 0.0, 0.0, 1.0], "range": rng, "spot_angle": 60.0, "shadows": "none",
                       "name": f"Practical {_text(source, 30)}"})
    for extra in request.get("lights") or []:
        if isinstance(extra, Mapping):
            lights.append(_normalize_light(extra, len(lights)))

    # Practical lights on objects that emit light (lamp, candle, TV, ...).
    for i, obj in enumerate(spec_objects):
        found = _practical(obj["label"])
        if found:
            k, inten, rng, kind = found
            color = palette[0] if (kind == "neon" and palette) else kelvin_to_rgb(k or 3000.0)
            if kind == "fire":
                # A fire glows low at its front, toward the room (RoomKit adds the offset in world space);
                # a transform-mode position is the scan's centre, an upright one its floor contact point.
                p = obj["position"]
                low = p[1] - 0.25 * obj["size_m"] if obj["mode"] == "transform" else p[1] + 0.3 * obj["size_m"]
                front = _toward(p, frame.origin, 0.35)
                offset = [_r(front[0] - p[0]), _r(max(0.3, low) - p[1]), _r(front[2] - p[2])]
            else:
                offset = [0.0, _r(obj["size_m"] * (0.85 if obj["mode"] == "upright" else 0.4)), 0.0]
            obj["light"] = {"enabled": True, "type": "point", "color": _clamp01(color), "intensity": _r(inten), "range": rng, "offset": offset}
        else:
            obj["light"] = {"enabled": False, "type": "point", "color": [1.0, 0.9, 0.8], "intensity": 1.0, "range": 3.0, "offset": [0.0, 0.5, 0.0]}

    # ---- staging --------------------------------------------------------------------
    staging_objects = [{"id": o["id"], "position": o["position"]} for o in spec_objects] or [{"id": "photo_scene", "position": _rv(scene_center)}]
    staged = st.stage_immersive_reveal(insight or {"theme": _flat_words(analysis.get("mood"), theme)}, staging_objects)
    mood_color = list(staged["connecting_motif"]["color"])
    if not insight and palette:
        mood_color = _mix(palette_avg, key_color, 0.5)
    motif_xz: list[float] = []
    if insight and len(spec_objects) >= 2:
        for p in staged["connecting_motif"]["control_points"]:
            motif_xz += [_r(p[0]), _r(p[2])]
    glow = st._shared_center(staging_objects)
    staging = {
        "enabled": True, "mood_color": _clamp01(mood_color), "glow_position": _rv([glow[0], max(1.2, min(1.6, eye - 0.2)), glow[2]]),
        "motif_xz": motif_xz, "reveal_order": [r for r in staged["reveal_order"] if r != "photo_scene"],
        "reveal_seconds": 1.2, "narration": _text((insight or {}).get("explanation") or (insight or {}).get("theme") or "", 400),
        "narration_audio_url": "",
    }

    # ---- particles ------------------------------------------------------------------
    preq = request.get("particles", "auto")
    labels = [o["label"] for o in spec_objects] + in_photo
    if preq in (None, "auto"):
        kinds = _auto_particles(setting, analysis, labels)
    elif isinstance(preq, str) and preq.lower() in ("none", "off", "false"):
        kinds = []
    elif isinstance(preq, str):
        kinds = [preq.lower()]
    elif isinstance(preq, list):
        kinds = [str(k).lower() for k in preq][:3]
    else:
        kinds = []
    kinds = [k for k in kinds if k in ("dust", "fireflies", "snow", "rain", "embers")]
    fire_obj = next((o for o in spec_objects if re.search(r"fire|hearth|candle", o["label"], re.I)), None)
    # Embers rise in front of a fire object, else in front of the fireplace in the photo.
    ember_at = _toward(fire_obj["position"], frame.origin, 0.3) if fire_obj else (
        _toward(fire_anchor["position"], frame.origin, 0.25) if fire_anchor else scene_center)
    if "embers" in kinds and fire_anchor and not fire_obj:
        anchored.append(f"embers at the {_text(fire_anchor['name'], 30)}")
    particles = [
        _particles_for(k, frame, ember_at if k == "embers" else scene_center, analysis, key_color, palette_avg)
        for k in kinds
    ]

    # ---- images: a small gallery around the periphery ---------------------------------
    blocked: list[tuple[float, float]] = []
    if layout and layout.get("bounds"):
        corners = [(x, z) for x in (layout["bounds"]["min"][0], layout["bounds"]["max"][0]) for z in (layout["bounds"]["min"][2], layout["bounds"]["max"][2])]
        bearings = [frame.bearing([x, 0, z]) for x, z in corners]
        blocked.append((min(bearings) - 15.0, max(bearings) + 15.0))
    for o in spec_objects:
        b = frame.bearing(o["position"])
        blocked.append((b - 14.0, b + 14.0))
    radius = max(2.4, min(4.0, 0.6 + max((math.hypot(*frame.local(o["position"])) for o in spec_objects), default=1.8)))
    images = []
    candidates = [a * s for a in (100.0, 125.0, 150.0, 75.0, 170.0, 55.0, 35.0) for s in (-1.0, 1.0)]
    free = [a for a in candidates if not any(lo <= a <= hi for lo, hi in blocked)]
    for img in list(request.get("images") or [])[:_MAX_IMAGES]:
        if not isinstance(img, Mapping) or not str(img.get("url") or "").startswith("https://"):
            notes.append("skipped an image without an https url")
            continue
        placement = img.get("placement")
        if isinstance(placement, Mapping) and isinstance(placement.get("position"), list) and len(placement["position"]) == 3:
            pos = [float(v) for v in placement["position"]]
        else:
            want = str(placement or "").lower()
            pool = [a for a in free if (want == "left" and a < 0) or (want == "right" and a > 0) or (want == "behind" and abs(a) >= 140) or want not in ("left", "right", "behind")] or free or [180.0]
            ang = pool[0]
            if ang in free:
                free.remove(ang)
            a = math.radians(ang)
            pos = frame.world(radius * math.sin(a), radius * math.cos(a), eye - 0.1)
        # +Z of the frame points away from the player (Unity Quad convention), so it faces spawn.
        yaw = _look_yaw(pos[0] - frame.origin[0], pos[2] - frame.origin[2])
        w, h = img.get("width"), img.get("height")
        portrait = isinstance(w, (int, float)) and isinstance(h, (int, float)) and h > w
        images.append({
            "url": str(img["url"]), "title": _text(img.get("title"), 80), "attribution": _text(img.get("attribution"), 240),
            "position": _rv(pos), "rotation": _quat_yaw(yaw), "width": 0.6 if portrait else 0.85, "frame": True,
            "frame_color": _clamp01(_mix(palette[-1] if palette else (0.25, 0.2, 0.16), (0.1, 0.08, 0.06), 0.5)), "lit": True,
        })
        credit(img.get("attribution") or img.get("title"))

    # ---- audio -----------------------------------------------------------------------
    audio: list[dict] = []
    by_label = {o["label"].lower(): o for o in spec_objects}

    def attach_position(target: Any) -> Optional[list[float]]:
        t = str(target or "").lower().strip()
        if not t:
            return None
        for o in spec_objects:
            if t in (o["id"].lower(), o["label"].lower()) or t in o["label"].lower():
                return [o["position"][0], max(0.3, o["position"][1] + 0.2), o["position"][2]]
        for a in anchors:  # something the analysis boxed in the photo ("the fireplace")
            n = a["name"].lower()
            if t in n or n in t or (t in ("fire", "fireplace", "hearth") and _FIRE_RE.search(n)):
                return [a["position"][0], max(0.3, a["position"][1]), a["position"][2]]
        if any(t in lbl.lower() for lbl in in_photo):
            return _rv(scene_center)
        return None

    for snd in list(request.get("sounds") or [])[:_MAX_SOUNDS]:
        if not isinstance(snd, Mapping) or not str(snd.get("url") or "").startswith("https://"):
            notes.append("skipped a sound without an https url")
            continue
        pos = attach_position(snd.get("attach_to"))
        heard = f"{snd.get('title') or ''} {snd.get('attach_to') or ''}"
        if pos is None and _FIRE_SOUND_RE.search(heard) and (fire_obj or fire_anchor):
            # A fire is a point source even when asked for as "ambient": it crackles at the fire.
            pos = attach_position("fire") if fire_obj else attach_position("fireplace")
            if pos and fire_anchor and not fire_obj:
                anchored.append(f"'{_text(snd.get('title'), 40)}' at the {_text(fire_anchor['name'], 30)}")
        elif pos is None and setting == "indoor" and window_at and _OUTSIDE_SOUND_RE.search(heard):
            pos = _rv(window_at)  # the outdoors comes in through the photo's window
            anchored.append(f"'{_text(snd.get('title'), 40)}' through the {_text(window_anchor['name'], 30)}")  # type: ignore[index]
        spatial = str(snd.get("kind") or "").lower() == "object" or pos is not None
        audio.append({"url": str(snd["url"]), "title": _text(snd.get("title"), 80), "attribution": _text(snd.get("attribution"), 240),
                      "position": _rv(pos or frame.world(0, 0, eye)), "spatial": spatial, "volume": 0.6 if spatial else 0.35,
                      "loop": True, "min_distance": 0.6 if spatial else 1.0, "max_distance": 8.0 if spatial else 30.0})
        credit(snd.get("attribution") or snd.get("title"))
    if not any(not a["spatial"] for a in audio):
        indoor = setting == "indoor"
        # The analysis' own sound choices lead; room type and mood only when it named none
        # (mood words like "cozy" would otherwise pull rain into a sunny room).
        sound_terms = search_terms.get("sounds") or []
        beds = wm.pick_sounds([sound_terms] if sound_terms else [analysis.get("room_type") or "", analysis.get("mood") or "", theme],
                              setting=setting, time_of_day=str(analysis.get("time_of_day") or ""), limit=3 if (indoor and window_at) else 2)
        if indoor and window_at and any(s["kind"] == "ambient" for s in beds) \
                and all(s["id"] in _OUTDOOR_AMBIENCE for s in beds if s["kind"] == "ambient"):
            # Only outdoor ambience picked: it comes in through the window and room tone fills the room.
            beds = [s for s in wm.CURATED_SOUNDS if s["id"] == "room_tone"][:1] + beds
        # The room's bed: the first ambience that belongs inside (indoors), non-spatial.
        bed = next((s for s in beds if s["kind"] == "ambient" and not (indoor and s["id"] in _OUTDOOR_AMBIENCE)), None) \
            or next((s for s in beds if s["kind"] == "ambient"), None)
        key_side = frame.world(-2.5 * math.sin(math.radians(rel_yaw)), -2.5 * math.cos(math.radians(rel_yaw)), 1.5)
        outside_at = window_at or key_side  # the photo's window when the analysis saw one, else where the key light comes from

        def covered(s: Mapping[str, Any]) -> bool:
            """The agent already chose a sound like this one (its fire, its rain)."""
            words = [w for w in (s.get("keywords") or []) if len(w) >= 4 and w not in _GENERIC_SOUND_WORDS]
            words.append(str(s.get("id") or "").split("_")[0])
            return any(w and w in a["title"].lower() for a in audio for w in words)

        for s in beds:
            if s is not bed and covered(s):
                continue
            if s["kind"] == "ambient" and s is not bed:  # more ambience (birdsong, the street) comes in through the window
                audio.append({"url": s["url"], "title": s["title"], "attribution": s["attribution"], "position": _rv(outside_at),
                              "spatial": True, "volume": 0.45, "loop": True, "min_distance": 1.5, "max_distance": 14.0})
                if window_at:
                    anchored.append(f"'{s['title']}' through the {_text(window_anchor['name'], 30)}")  # type: ignore[index]
            elif s["kind"] == "ambient":
                audio.append({"url": s["url"], "title": s["title"], "attribution": s["attribution"], "position": _rv(frame.world(0, 0, eye)),
                              "spatial": False, "volume": 0.35, "loop": True, "min_distance": 1.0, "max_distance": 30.0})
            else:  # a detail sound: fire at the fire (an object, else the fireplace in the photo), anything else (rain) at the window
                pos = None
                if s["id"] == "fireplace":
                    pos = (attach_position("fire") if fire_obj else None) or (attach_position("fireplace") if fire_anchor else None)
                    if pos and fire_anchor and not fire_obj:
                        anchored.append(f"fire crackle at the {_text(fire_anchor['name'], 30)}")
                    pos = pos or attach_position("fire")
                elif window_at:
                    anchored.append(f"'{s['title']}' at the {_text(window_anchor['name'], 30)}")  # type: ignore[index]
                pos = pos or _rv(outside_at)
                audio.append({"url": s["url"], "title": s["title"], "attribution": s["attribution"], "position": _rv(pos),
                              "spatial": True, "volume": 0.5, "loop": True, "min_distance": 0.8, "max_distance": 10.0})
            credit(s["attribution"])
    for o in spec_objects:
        if len(audio) >= _MAX_SOUNDS:
            break
        s = wm.object_sound(o["label"])
        if s and not any(a["url"] == s["url"] for a in audio):
            audio.append({"url": s["url"], "title": s["title"], "attribution": s["attribution"],
                          "position": _rv([o["position"][0], max(0.3, o["position"][1] + 0.1), o["position"][2]]),
                          "spatial": True, "volume": 0.45, "loop": True, "min_distance": 0.4, "max_distance": 4.0})
            credit(s["attribution"])

    # A fire you can hear (or see embers from) also glows: a warm light at the
    # fireplace in the photo, unless the analysis already named it as a light.
    has_fire = "embers" in kinds or any(re.search(r"fire|crackl|hearth", a["title"], re.I) for a in audio)
    if fire_anchor and not fire_obj and has_fire and not any(_FIRE_RE.search(l["name"]) for l in lights):
        glow_at = _toward(fire_anchor["position"], frame.origin, 0.4)
        glow_at[1] = max(0.35, glow_at[1])
        lights.append({"type": "point", "color": kelvin_to_rgb(1900.0), "intensity": _r(1.6 * max(0.6, brightness)),
                       "position": _rv(glow_at), "rotation": [0.0, 0.0, 0.0, 1.0], "range": 4.5, "spot_angle": 60.0,
                       "shadows": "none", "name": f"Hearth glow ({_text(fire_anchor['name'], 24)})"})
        anchored.append(f"hearth glow at the {_text(fire_anchor['name'], 30)}")
    if anchored:
        notes.append("anchored to the photo: " + "; ".join(dict.fromkeys(anchored)))

    # ---- teleport hotspots ------------------------------------------------------------
    hotspots: list[list[float]] = [[frame.origin[0], 0.0, frame.origin[2]]]
    for o in spec_objects:
        lat, fwd = frame.local(o["position"])
        dist = math.hypot(lat, fwd)
        if dist > _HOTSPOT_STANDOFF + 0.4:
            k = (dist - _HOTSPOT_STANDOFF) / dist
            hotspots.append(frame.world(lat * k, fwd * k, 0.0))
    if layout:  # beside the photo scene, to see its depth from an angle
        for side in (-1.0, 1.0):
            hotspots.append(frame.world(s_lat + side * (scene_half[0] + 0.5), max(0.8, s_fwd), 0.0))
    deduped: list[list[float]] = []
    for h in hotspots:
        if all(math.hypot(h[0] - d[0], h[2] - d[2]) >= 0.7 for d in deduped):
            deduped.append(_rv([h[0], 0.0, h[2]]))
    hotspots = deduped[:_MAX_HOTSPOTS]

    for extra_credit in list(request.get("credits") or [])[:12]:
        credit(extra_credit)

    # ---- spec -------------------------------------------------------------------------
    photo_scene = {"enabled": False, "splat_path": "", "position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "scale": [1.0, 1.0, 1.0]}
    if scene and scene.get("unity_path") and layout and layout.get("scene_transform"):
        tr = layout["scene_transform"]
        photo_scene = {"enabled": True, "splat_path": str(scene["unity_path"]), "position": _rv(tr["position"]),
                       "rotation": _rv(tr["rotation"], 4), "scale": _rv(tr["scale"], 4)}
    elif scene and scene.get("unity_path"):
        notes.append("photo scene splat not placed (no layout)")

    visuals = {}
    for i, o in enumerate(spec_objects):
        visuals[o["id"]] = o.pop("_visual")
        o["tint"] = list(_WHITE) if o["splat_path"] else _clamp01(_mix(_OBJECT_TINTS[i % len(_OBJECT_TINTS)], mood_color, 0.3))
        o["grabbable"] = True

    spec = {
        "version": SPEC_VERSION, "slug": slug, "scene_path": _scene_path(slug), "root": _root_name(slug),
        "player": {"eye_height": _r(eye), "spawn": _rv(frame.origin), "yaw": _r(frame.yaw, 2)},
        "photo_scene": photo_scene, "objects": spec_objects, "environment": environment, "lights": lights,
        "images": images, "audio": audio, "particles": particles, "staging": staging,
        "teleport": {"floor_collider": True, "hotspots": [c for h in hotspots for c in h]},
        "credits": credits,
        "shared": shared_block(_room_project_id(request, scene, matches)),
    }
    _check_jsonutility(spec)

    # ---- plan (compact, for the agent) ----------------------------------------------
    build_parts = room_build_parts(spec)
    n_parts = len(build_parts)
    steps: list[dict] = [
        {"tool": "unity-mcp__Unity_RunCommand",
         "args": {"Title": f"Build room {slug}" + (f" (part {k}/{n_parts})" if n_parts > 1 else ""),
                  "Code": f"<BUILD CODE{f' PART {k}/{n_parts}' if n_parts > 1 else ''} from: unity_room_cli.py build_code {slug}>"}}
        for k in range(1, n_parts + 1)
    ] + [
        {"tool": "unity-mcp__meta_get_config_information", "args": {}},
        {"tool": "unity-mcp__meta_add_camerarig", "args": {}},
        {"tool": "unity-mcp__meta_add_interactionrig", "args": {}},
    ]
    steps += [{"tool": "unity-mcp__meta_add_grabbable", "args": {"NameOrID": o["id"]}} for o in spec_objects]
    steps += [{"tool": "unity-mcp__meta_add_teleport_hotspot", "args": {"Position": h, "Snap": "SnapPosition"}} for h in hotspots]
    steps.append({"tool": "unity-mcp__Unity_RunCommand", "args": {"Title": f"Finalize room {slug}", "Code": f"<output of: unity_room_cli.py finalize_code {slug}>"}})

    real = sum(1 for o in spec_objects if o["splat_path"])
    summary = (
        f"Room '{slug}'"
        + (f": photo scene {scene['scene_id'][:8]} ({'splat' if photo_scene['enabled'] else 'no splat'})" if scene else "")
        + f", {len(spec_objects)} separate object(s) ({real} real scans)"
        + (f", {len(in_photo)} inside the photo scene" if in_photo else "")
        + f"; sky '{hdri.get('name')}', {len(lights)} lights, {len(audio)} sound(s), {len(images)} image(s), "
        + f"particles {', '.join(kinds) or 'none'}, {len(hotspots)} hotspots. Scene file {_scene_path(slug)} (new; other scenes untouched)."
        + (f" Shared layer on (project {spec['shared']['project_id'][:8]}): account switcher, personal notes, letters, object tags."
           if spec["shared"]["enabled"] else "")
    )
    plan = {
        "summary": summary,
        "room": {"slug": slug, "scene_path": _scene_path(slug), "root": _root_name(slug), "spawn": spec["player"]["spawn"], "yaw": spec["player"]["yaw"]},
        "photo_scene": None if not scene else {"scene_id": scene.get("scene_id"), "splat": photo_scene["enabled"],
                                               "caption": _text(analysis.get("caption"), 140)},
        "objects": [{"id": o["id"], "label": o["label"], "mode": o["mode"], "size_m": o["size_m"], "position": o["position"],
                     "visual": visuals[o["id"]], "light": o["light"]["enabled"]} for o in spec_objects],
        "in_photo_scene": in_photo,
        "environment": {"hdri": hdri.get("name"), "floor": (floor_tex or {}).get("name", "plain"), "fog": fog["density"] if fog["enabled"] else 0,
                        "shell": shell["enabled"], "key_light": f"{int(float(kelvin))}K, {key_desc}"},
        "lights": [l["name"] for l in lights],
        "audio": [a["title"] + (" (spatial)" if a["spatial"] else " (ambient)") for a in audio],
        "images": [i["title"] or i["url"][-40:] for i in images],
        "particles": kinds,
        "staging": {"lighting_preset": staged["lighting_preset"], "reveal_order": staging["reveal_order"], "narration": staging["narration"]},
        "credits": len(credits),
        "unity_steps": steps,
        "shared": {"enabled": spec["shared"]["enabled"], "project_id": spec["shared"]["project_id"]},
        "notes": notes[:8],
    }
    return {"spec": spec, "plan": plan, "build_code": room_build_command(spec), "build_parts": build_parts,
            "finalize_code": room_finalize_command(slug, spec)}


def _upright(obj: Mapping[str, Any], match: Optional[Mapping[str, Any]], pos: Sequence[float], facing: float, index: int) -> dict:
    label = str(obj.get("label") or obj["id"])
    return {
        "id": obj["id"], "label": label, "asset_id": str(obj.get("asset_id") or (match or {}).get("asset_id") or ""),
        "splat_path": str((match or {}).get("unity_path") or ""), "mode": "upright",
        "position": _rv([pos[0], 0.0, pos[2]]), "rotation": _quat_yaw(facing), "scale": [1.0, 1.0, 1.0],
        "size_m": _r(_label_size(label)),
        "_visual": f"real 3D scan ({match['label']}), upright at label size" if match and match.get("unity_path") else "placeholder cube (no real scan for this label)",
    }


def _normalize_light(raw: Mapping[str, Any], index: int) -> dict:
    def vec(key: str, n: int, default: Sequence[float]) -> list[float]:
        v = raw.get(key)
        return _rv(v) if isinstance(v, list) and len(v) == n and all(isinstance(x, (int, float)) for x in v) else list(default)

    kind = str(raw.get("type") or "point").lower()
    if kind not in ("directional", "point", "spot"):
        kind = "point"
    color = _hex_rgb(raw.get("color")) if isinstance(raw.get("color"), str) else vec("color", 3, [1.0, 0.9, 0.8])
    if raw.get("kelvin"):
        color = kelvin_to_rgb(raw.get("kelvin"))
    shadows = str(raw.get("shadows") or "none").lower()
    return {
        "type": kind, "color": _clamp01(color or [1.0, 0.9, 0.8]), "intensity": _r(float(raw.get("intensity") or 1.0)),
        "position": vec("position", 3, [0.0, 2.0, 1.5]), "rotation": vec("rotation", 4, [0.0, 0.0, 0.0, 1.0]),
        "range": _r(float(raw.get("range") or 5.0)), "spot_angle": _r(float(raw.get("spot_angle") or 60.0)),
        "shadows": shadows if shadows in ("soft", "hard", "none") else "none", "name": _text(raw.get("name") or f"Light {index + 1}", 40),
    }


# ---------------------------------------------------------------------------
# Generated C# (a few lines: RoomKit does the work)
# ---------------------------------------------------------------------------

_MISSING_ROOMKIT = (
    "SketchScape RoomKit is not installed in this Unity project. On the host, run: "
    "python scripts/install_hackgt_roomkit.py  (then let Unity recompile) and rerun this step."
)

_BUILD_TEMPLATE = """using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{{
    const string Spec = @"{spec}";

    public void Execute(ExecutionResult result)
    {{
        var kit = System.Type.GetType("{roomkit}");
        if (kit == null) {{ result.LogError("{missing}"); return; }}
        try
        {{
            var report = (string)kit.GetMethod("Build", new[] {{ typeof(string) }}).Invoke(null, new object[] {{ Spec }});
            report = (report ?? "").Replace("{{", "{{{{").Replace("}}", "}}}}");
            if (report.StartsWith("ERROR")) result.LogError(report); else result.Log(report);
        }}
        catch (System.Reflection.TargetInvocationException e) {{ result.LogError("RoomKit.Build failed: " + e.InnerException); }}
    }}
}}
"""

_FINALIZE_TEMPLATE = """using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{{
    public void Execute(ExecutionResult result)
    {{
        var kit = System.Type.GetType("{roomkit}");
        if (kit == null) {{ result.LogError("{missing}"); return; }}
        try
        {{
            var report = (string)kit.GetMethod("Finalize", new[] {{ typeof(string), typeof(float), typeof(float), typeof(float) }})
                .Invoke(null, new object[] {{ "{slug}", {x}f, {z}f, {yaw}f }});
            report = (report ?? "").Replace("{{", "{{{{").Replace("}}", "}}}}");
            if (report.StartsWith("ERROR")) result.LogError(report); else result.Log(report);
        }}
        catch (System.Reflection.TargetInvocationException e) {{ result.LogError("RoomKit.Finalize failed: " + e.InnerException); }}
    }}
}}
"""


def _cs_verbatim(text: str) -> str:
    return text.replace('"', '""')


# The agent must copy the build C# verbatim into one tool argument. Muse Spark managed a 4.1 KB build live but
# never got an 8.4 KB one to Unity, so bigger specs go in parts: each part stores a slice of the spec in the
# Editor's SessionState (file I/O in a Run Command snippet needs a user prompt, which MCP calls can't answer),
# and the last part reassembles them, checks length + FNV-1a (UTF-16 code units) and builds.
BUILD_SINGLE_MAX_CHARS = 3000
BUILD_PART_CHARS = 2400

_STAGE_TEMPLATE = """using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{{
    const string Part = @"{text}";

    public void Execute(ExecutionResult result)
    {{
        SessionState.SetString("SketchScape.RoomSpec.{slug}.{index}", Part);
        result.Log("stored part {index} of {total} for room {slug} (" + Part.Length + " chars); next: part {next}");
    }}
}}
"""

_ASSEMBLE_TEMPLATE = """using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{{
    public void Execute(ExecutionResult result)
    {{
        var sb = new System.Text.StringBuilder();
        for (int i = 1; i <= {slices}; i++)
        {{
            var part = SessionState.GetString("SketchScape.RoomSpec.{slug}." + i, "");
            if (part.Length == 0) {{ result.LogError("ERROR: part " + i + " of room {slug} is missing: send BUILD CODE part " + i + " again, then this last part"); return; }}
            sb.Append(part);
        }}
        var spec = sb.ToString();
        uint h = 2166136261;
        foreach (char c in spec) {{ h ^= c; h *= 16777619; }}
        if (spec.Length != {length} || h != {fnv}u)
        {{
            result.LogError("ERROR: the room spec parts of {slug} do not match (" + spec.Length + " chars, expected {length}): a part changed while copying. Run build_code {slug} again and resend every part verbatim.");
            return;
        }}
        for (int i = 1; i <= {slices}; i++) SessionState.EraseString("SketchScape.RoomSpec.{slug}." + i);
        var kit = System.Type.GetType("{roomkit}");
        if (kit == null) {{ result.LogError("{missing}"); return; }}
        try
        {{
            var report = (string)kit.GetMethod("Build", new[] {{ typeof(string) }}).Invoke(null, new object[] {{ spec }});
            report = (report ?? "").Replace("{{", "{{{{").Replace("}}", "}}}}");
            if (report.StartsWith("ERROR")) result.LogError(report); else result.Log(report);
        }}
        catch (System.Reflection.TargetInvocationException e) {{ result.LogError("RoomKit.Build failed: " + e.InnerException); }}
    }}
}}
"""


def room_build_parts(spec: Mapping[str, Any]) -> list[str]:
    """The build as ``Unity_RunCommand`` snippets, sent in order. A small spec is one snippet
    (``room_build_command``); a bigger one is several short parts that store slices of the spec
    in the Editor's SessionState plus a last part that reassembles them, checks the length and
    FNV-1a hash (a part mangled while copying is caught) and builds."""
    slug = _checked_slug(str(spec.get("slug") or ""))
    _check_jsonutility(spec)
    text = json.dumps(spec, separators=(",", ":"), ensure_ascii=False)
    if len(text) <= BUILD_SINGLE_MAX_CHARS:
        return [room_build_command(spec)]
    slices = [text[i:i + BUILD_PART_CHARS] for i in range(0, len(text), BUILD_PART_CHARS)]
    total = len(slices) + 1
    parts = [
        _STAGE_TEMPLATE.format(text=_cs_verbatim(s), index=k, total=total, next=k + 1, slug=slug)
        for k, s in enumerate(slices, start=1)
    ]
    units, fnv = _utf16_fnv1a(text)
    parts.append(_ASSEMBLE_TEMPLATE.format(
        slices=len(slices), slug=slug, length=units, fnv=fnv, roomkit=ROOMKIT_TYPE, missing=_MISSING_ROOMKIT,
    ))
    return parts


def _utf16_fnv1a(text: str) -> tuple[int, int]:
    """(length, 32-bit FNV-1a) over UTF-16 code units: what a C# string's Length and chars give."""
    data = text.encode("utf-16-le")
    h = 2166136261
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 16777619) & 0xFFFFFFFF
    return len(data) // 2, h


def room_build_command(spec: Mapping[str, Any]) -> str:
    """C# for ``Unity_RunCommand``: ``SketchScape.RoomKit.Build(spec)`` via reflection."""
    _checked_slug(str(spec.get("slug") or ""))
    _check_jsonutility(spec)
    return _BUILD_TEMPLATE.format(
        spec=_cs_verbatim(json.dumps(spec, separators=(",", ":"), ensure_ascii=False)),
        roomkit=ROOMKIT_TYPE,
        missing=_MISSING_ROOMKIT,
    )


def room_finalize_command(slug: str, spec: Optional[Mapping[str, Any]] = None) -> str:
    """C# for ``Unity_RunCommand``: ``RoomKit.Finalize(slug, spawnX, spawnZ, yaw)``."""
    slug = _checked_slug(slug)
    player = (spec or {}).get("player") or {}
    spawn = player.get("spawn") or [0.0, 0.0, 0.0]
    return _FINALIZE_TEMPLATE.format(
        roomkit=ROOMKIT_TYPE, missing=_MISSING_ROOMKIT, slug=slug,
        x=repr(_r(spawn[0])), z=repr(_r(spawn[2])), yaw=repr(_r(player.get("yaw") or 0.0, 2)),
    )
