"""Openly licensed web media for a Shared Room: images, sounds, HDRI skies and textures.

Runs inside the NemoClaw sandbox (standard library only) as part of the
``sketchscape-unity-room`` skill, and on a developer machine.

- ``search_images``: Openverse images (https://api.openverse.org/v1/images/).
- ``search_sounds``: Openverse audio (https://api.openverse.org/v1/audio/),
  ranked toward loopable ambience.
- ``search_environment``: Poly Haven HDRIs and textures (CC0), with the exact
  1k/2k ``.hdr`` / diffuse ``.jpg`` URLs from ``/files/<id>``.

Only the search/metadata JSON is fetched here. The media files themselves are
downloaded later by the Unity Editor (RoomKit), so the sandbox policy
(config/nemoclaw/policies/sketchscape-web-media.yaml) only needs the two API
hosts.

When a search can't reach the network (no sandbox egress, API down), the
functions fall back to a CURATED catalog of hand-picked CC0 / CC BY assets
whose URLs were verified to resolve (2026-09-26). The ``pick_*`` helpers
choose from that catalog deterministically; ``unity_room.compose_room`` uses
them for its defaults, so a room never depends on a live search.

Every result carries a ready-to-show ``attribution`` string.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "CURATED_HDRIS",
    "CURATED_TEXTURES",
    "CURATED_SOUNDS",
    "WebMediaError",
    "search_images",
    "search_sounds",
    "search_environment",
    "pick_hdri",
    "pick_texture",
    "pick_sounds",
    "hdri_by_id",
    "texture_by_id",
    "polyhaven_hdri_url",
]

# Cloudflare in front of both APIs rejects Python's default User-Agent (error 1010).
USER_AGENT = "SketchScape-RoomTools/1.0 (+https://github.com/; HackGT demo)"
OPENVERSE = "https://api.openverse.org/v1"
POLYHAVEN = "https://api.polyhaven.com"
TIMEOUT_S = 12.0
MAX_RESULTS = 12
# Audio/image formats Unity can load at edit time.
_AUDIO_TYPES = {"mp3", "wav", "ogg", "aiff", "aif"}
_IMAGE_TYPES = {"jpg", "jpeg", "png"}
_LICENSE_NAMES = {
    "cc0": "CC0 1.0",
    "pdm": "Public Domain Mark",
    "by": "CC BY",
    "by-sa": "CC BY-SA",
    "by-nd": "CC BY-ND",
    "by-nc": "CC BY-NC",
    "by-nc-sa": "CC BY-NC-SA",
    "by-nc-nd": "CC BY-NC-ND",
}
# Default: licenses that allow reuse with attribution (no NC/ND restrictions).
DEFAULT_LICENSES = "cc0,pdm,by,by-sa"


class WebMediaError(RuntimeError):
    """Bad input to a web media search."""


# ---------------------------------------------------------------------------
# Curated offline catalog (every URL verified to resolve on 2026-09-26)
# ---------------------------------------------------------------------------

_PH_HDR = "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/{res}/{id}_{res}.hdr"
_PH_TEX = "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/{id}/{id}_diff_1k.jpg"


def polyhaven_hdri_url(asset_id: str, res: str = "2k") -> str:
    """The Poly Haven ``.hdr`` URL for an HDRI id (the site's stable file layout)."""
    if not re.match(r"^[a-z0-9_]+$", asset_id or ""):
        raise WebMediaError(f"not a Poly Haven asset id: {asset_id!r}")
    return _PH_HDR.format(id=asset_id, res=res)


def _hdri(asset_id: str, name: str, authors: str, setting: str, times: str, moods: str, words: str,
          exposure: float = 1.0, sun: Optional[float] = None) -> dict:
    return {
        "id": asset_id,
        "name": name,
        "setting": setting,
        "time_of_day": times.split(),
        "mood": moods.split(),
        "keywords": words.split(),
        "exposure": exposure,
        "url_1k": polyhaven_hdri_url(asset_id, "1k"),
        "url_2k": polyhaven_hdri_url(asset_id, "2k"),
        "license": "CC0",
        "attribution": f"'{name}' HDRI by {authors}, CC0, via Poly Haven",
    }


CURATED_HDRIS: list[dict] = [
    _hdri("lythwood_room", "Lythwood Room", "Greg Zaal", "indoor", "day morning afternoon", "cozy homey warm calm family",
          "living room lounge sofa couch fireplace home house bedroom window"),
    _hdri("lebombo", "Lebombo", "Greg Zaal", "indoor", "morning day", "bright airy calm quiet minimal peaceful",
          "house home empty window apartment room"),
    _hdri("photo_studio_loft_hall", "Photo Studio Loft Hall", "Sergej Majboroda", "indoor", "afternoon day", "sunny elegant bright warm",
          "apartment loft hall couch sofa window living"),
    _hdri("fireplace", "Fireplace", "Greg Zaal", "indoor", "night evening", "cozy intimate warm quiet romantic nostalgic",
          "fireplace fire living room lounge couch sofa den cabin", exposure=1.2),
    _hdri("wooden_lounge", "Wooden Lounge", "Greg Zaal", "indoor", "evening night", "warm relaxed cozy social",
          "lounge wood den game room living couch sofa bar", exposure=1.1),
    _hdri("christmas_photo_studio_04", "Christmas Photo Studio 04", "Sergej Majboroda", "indoor", "night evening", "festive holiday joyful",
          "christmas holiday tree presents couch"),
    _hdri("comfy_cafe", "Comfy Cafe", "Sergej Majboroda", "indoor", "day afternoon evening", "lively social warm",
          "cafe coffee shop restaurant store"),
    _hdri("reading_room", "Reading Room", "Greg Zaal", "indoor", "day morning afternoon", "calm studious quiet",
          "reading library study office books chair"),
    _hdri("pine_attic", "Pine Attic", "Sergej Majboroda", "indoor", "day afternoon", "cozy rustic playful",
          "attic wood cabin kids playroom nursery loft"),
    _hdri("cayley_interior", "Cayley Interior", "Greg Zaal", "indoor", "sunset evening", "modern warm golden",
          "dining kitchen modern apartment balcony view"),
    _hdri("hotel_room", "Hotel Room", "Greg Zaal", "indoor", "evening day", "modern neat",
          "bedroom hotel bed tv"),
    _hdri("artist_workshop", "Artist Workshop", "Oliksiy Yakovlyev", "indoor", "day midday", "creative busy",
          "studio workshop art atelier painting garage"),
    _hdri("kloofendal_48d_partly_cloudy_puresky", "Kloofendal 48d Partly Cloudy (Pure Sky)", "Greg Zaal and Jarod Guest", "outdoor",
          "midday day afternoon", "open bright free dreamy", "sky clouds open"),
    _hdri("meadow_2", "Meadow 2", "Sergej Majboroda", "outdoor", "morning day afternoon", "peaceful fresh calm happy",
          "meadow field grass park garden nature summer backyard"),
    _hdri("spruit_sunrise", "Spruit Sunrise", "Greg Zaal", "outdoor", "sunrise dawn morning", "hopeful golden peaceful",
          "sunrise field grass nature countryside"),
    _hdri("venice_sunset", "Venice Sunset", "Greg Zaal", "outdoor", "sunset evening dusk", "romantic golden nostalgic",
          "sea waterfront promenade city travel vacation"),
    _hdri("the_sky_is_on_fire", "The Sky Is On Fire", "Greg Zaal and Rico Cilliers", "outdoor", "sunset dusk evening", "dramatic epic",
          "sunset dusk sky promenade"),
    _hdri("satara_night", "Satara Night", "Greg Zaal", "outdoor", "night", "magical dreamy mysterious calm",
          "stars milky way camping safari night sky campfire", exposure=1.4),
    _hdri("rooftop_night", "Rooftop Night", "Greg Zaal", "outdoor", "night dusk evening", "urban quiet moody",
          "rooftop city night urban roof", exposure=1.2),
    _hdri("shanghai_bund", "Shanghai Bund", "Greg Zaal", "outdoor", "night evening", "vibrant lively festive",
          "city skyline neon lights urban river travel"),
    _hdri("snowy_park_01", "Snowy Park 01", "Oliksiy Yakovlyev", "outdoor", "day morning afternoon", "wintry quiet serene cold",
          "snow winter park trees christmas"),
    _hdri("spiaggia_di_mondello", "Spiaggia di Mondello", "Andreas Mischok", "outdoor", "day midday afternoon", "sunny relaxed happy",
          "beach sand sea ocean coast vacation summer"),
    _hdri("tiergarten", "Tiergarten", "Greg Zaal", "outdoor", "day afternoon", "autumn calm nostalgic",
          "park autumn fall trees grass lawn"),
    _hdri("je_gray_02", "J&E Gray 02", "Greg Zaal", "outdoor", "morning afternoon day", "fresh peaceful",
          "forest woods trees garden park hike"),
]


def _texture(asset_id: str, name: str, authors: str, kind: str, words: str, tile_m: float, color: Sequence[float]) -> dict:
    return {
        "id": asset_id,
        "name": name,
        "kind": kind,  # floor | wall | ground
        "keywords": words.split(),
        "tile_m": tile_m,  # real-world size of one texture repeat
        "color": [round(c, 3) for c in color],  # average color, for tinting/fog
        "url": _PH_TEX.format(id=asset_id),
        "license": "CC0",
        "attribution": f"'{name}' texture by {authors}, CC0, via Poly Haven",
    }


CURATED_TEXTURES: list[dict] = [
    _texture("laminate_floor_02", "Laminate Floor 02", "Dario Barresi and Charlotte Baglioni", "floor",
             "wood wooden oak laminate light floorboards hardwood", 1.7, (0.62, 0.5, 0.38)),
    _texture("wood_floor", "Wood Floor", "Dimitrios Savva", "floor", "wood wooden dark walnut floorboards hardwood", 1.7, (0.45, 0.32, 0.22)),
    _texture("herringbone_parquet", "Herringbone Parquet", "Jenelle van Heerden and Sergej Majboroda", "floor",
             "parquet herringbone wood wooden elegant", 3.4, (0.55, 0.4, 0.28)),
    _texture("weathered_brown_planks", "Weathered Brown Planks", "Dimitrios Savva and Rico Cilliers", "floor",
             "planks rustic weathered barn deck cabin old wood", 1.8, (0.42, 0.33, 0.26)),
    _texture("dirty_carpet", "Dirty Carpet", "Rohit Seervi", "floor", "carpet rug fabric fleece blanket soft", 0.6, (0.55, 0.52, 0.5)),
    _texture("interior_tiles", "Interior Tiles", "Charlotte Baglioni", "floor", "tile tiles tiled kitchen bathroom ceramic", 1.9, (0.78, 0.76, 0.72)),
    _texture("marble_01", "Marble 01", "Rob Tuytel", "floor", "marble stone polished elegant hotel lobby", 1.5, (0.85, 0.84, 0.82)),
    _texture("concrete_floor_02", "Concrete Floor 02", "Rob Tuytel", "floor", "concrete cement garage industrial loft studio grey", 2.0, (0.55, 0.55, 0.53)),
    _texture("cobblestone_floor_04", "Cobblestone Floor 04", "Rob Tuytel", "ground", "cobblestone street plaza stone paving city", 1.5, (0.5, 0.48, 0.45)),
    _texture("leafy_grass", "Leafy Grass", "Charlotte Baglioni", "ground", "grass lawn garden park meadow field backyard", 2.0, (0.33, 0.45, 0.2)),
    _texture("forrest_ground_01", "Forest Ground 01", "Rob Tuytel", "ground", "forest woods leaves dirt soil trail", 2.0, (0.36, 0.3, 0.22)),
    _texture("coast_sand_01", "Coast Sand 01", "Rob Tuytel", "ground", "sand beach coast shore desert dune", 15.0, (0.76, 0.68, 0.55)),
    _texture("snow_02", "Snow 02", "Rob Tuytel", "ground", "snow winter ice frost", 2.0, (0.9, 0.92, 0.95)),
    _texture("white_plaster_02", "White Plaster 02", "Rob Tuytel", "wall", "white plaster painted wall clean", 1.0, (0.86, 0.85, 0.82)),
    _texture("beige_wall_001", "Beige Wall 001", "Dimitrios Savva and Rico Cilliers", "wall", "beige cream warm plaster wall", 3.0, (0.78, 0.7, 0.6)),
    _texture("grey_plaster", "Grey Plaster", "Rob Tuytel", "wall", "grey gray plaster concrete wall modern", 1.0, (0.6, 0.6, 0.6)),
    _texture("red_brick_03", "Red Brick 03", "Rob Tuytel", "wall", "brick red exposed loft industrial wall", 1.0, (0.55, 0.3, 0.25)),
    _texture("brown_planks_03", "Brown Planks 03", "Rob Tuytel", "wall", "wood panel planks cabin paneling wall", 1.0, (0.45, 0.32, 0.22)),
]


def _sound(key: str, title: str, creator: str, license_: str, sound_id: str, path: str, seconds: int, words: str,
           kind: str = "ambient") -> dict:
    lic = _LICENSE_NAMES.get(license_, license_)
    return {
        "id": key,
        "title": title,
        "creator": creator,
        "kind": kind,  # ambient (room bed) | detail (spot sound) | object (attached to a thing)
        "keywords": words.split(),
        "duration_s": seconds,
        "url": f"https://cdn.freesound.org/previews/{path}",
        "landing_url": f"https://freesound.org/s/{sound_id}/",
        "license": lic,
        "attribution": f"'{title}' by {creator}, {lic}{' 4.0' if license_ == 'by' else ''}, via Freesound/Openverse",
    }


CURATED_SOUNDS: list[dict] = [
    _sound("room_tone", "Room Tone Apartment Small Bachelor", "leonelmail", "cc0", "329568", "329/329568_4437257-hq.mp3", 46,
           "room tone indoor quiet home apartment living bedroom house calm"),
    _sound("rain_window", "rain on window", "ikayuka", "cc0", "273333", "273/273333_1158384-hq.mp3", 180,
           "rain window rainy storm cozy drizzle wet", kind="detail"),
    _sound("fireplace", "Fire in the stove", "mcmikai", "cc0", "532191", "532/532191_9735871-hq.mp3", 61,
           "fire fireplace crackling stove hearth campfire cozy cabin", kind="detail"),
    _sound("birds_morning", "Morning Birds", "nick121087", "cc0", "342462", "342/342462_3840537-hq.mp3", 100,
           "birds birdsong morning garden spring park day chirping"),
    _sound("city_evening", "city hum night", "klankbeeld", "by", "346658", "346/346658_1648170-hq.mp3", 55,
           "city urban street traffic evening night hum town"),
    _sound("ocean_waves", "Zen Ocean Waves, Ocean Waves Ambience", "INNORECORDS", "cc0", "456899", "456/456899_9518146-hq.mp3", 96,
           "ocean sea waves beach coast shore surf"),
    _sound("night_crickets", "Countryside at the night crickets", "Martin.Sadoux", "cc0", "422582", "422/422582_8177280-hq.mp3", 91,
           "night crickets countryside summer evening insects camping"),
    _sound("forest_breeze", "forest ambience constant breeze", "kyles", "cc0", "637559", "637/637559_612689-hq.mp3", 118,
           "forest woods trees breeze nature hike"),
    _sound("wind_gentle", "Looping Gentle Wind Ambience on an Open Field", "dhallcomposer", "cc0", "697217", "697/697217_7678208-hq.mp3", 41,
           "wind breeze field open outdoor winter snow"),
    _sound("cafe", "People talking at cafe ambience", "priesjensen", "cc0", "482990", "482/482990_8972317-hq.mp3", 137,
           "cafe coffee restaurant people chatter crowd social"),
    _sound("cat_purring", "Cat purring", "cubilon", "cc0", "130968", "130/130968_2330675-hq.mp3", 38,
           "cat kitten purr purring pet", kind="object"),
    _sound("clock_ticking", "Clock ticks close to mic", "BonnyOrbit", "cc0", "380782", "380/380782_5902878-hq.mp3", 60,
           "clock ticking tick grandfather watch time", kind="object"),
]


def hdri_by_id(asset_id: str) -> Optional[dict]:
    return next((h for h in CURATED_HDRIS if h["id"] == asset_id), None)


def texture_by_id(asset_id: str) -> Optional[dict]:
    return next((t for t in CURATED_TEXTURES if t["id"] == asset_id), None)


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _words(*texts: Any) -> set[str]:
    out: set[str] = set()
    for text in texts:
        if isinstance(text, (list, tuple, set)):
            out |= _words(*text)
            continue
        for w in re.findall(r"[a-z0-9]+", str(text or "").lower()):
            out.add(w)
            if len(w) > 3 and w.endswith("s"):
                out.add(w[:-1])
            if len(w) > 4 and w.endswith("ing"):
                out.add(w[:-3])
    return out


_TIME_ALIASES = {
    "dawn": "sunrise", "sunrise": "sunrise", "morning": "morning", "noon": "midday", "midday": "midday",
    "day": "day", "daytime": "day", "afternoon": "afternoon", "golden": "sunset", "sunset": "sunset",
    "dusk": "dusk", "evening": "evening", "twilight": "dusk", "night": "night", "midnight": "night", "nighttime": "night",
}


def _time_word(time_of_day: Any) -> str:
    for w in _words(time_of_day):
        if w in _TIME_ALIASES:
            return _TIME_ALIASES[w]
    return ""


def pick_hdri(setting: Any = "", time_of_day: Any = "", mood: Any = "", keywords: Any = ()) -> dict:
    """The curated HDRI that best fits a scene analysis (deterministic)."""
    setting_w = _words(setting)
    want_setting = "outdoor" if "outdoor" in setting_w or "outside" in setting_w else ("indoor" if setting_w & {"indoor", "inside", "interior"} else "")
    time = _time_word(time_of_day)
    mood_w = _words(mood)
    key_w = _words(keywords)
    if not want_setting:
        outdoorish = {"beach", "park", "forest", "garden", "field", "sky", "street", "city", "mountain", "lake", "ocean", "camping", "backyard", "meadow"}
        want_setting = "outdoor" if key_w & outdoorish else "indoor"

    def score(h: dict) -> float:
        s = 0.0
        s += 10.0 if h["setting"] == want_setting else -10.0
        if time:
            if time in h["time_of_day"]:
                s += 4.0
            elif time in ("night", "evening", "dusk", "sunset") and set(h["time_of_day"]) & {"night", "evening", "dusk", "sunset"}:
                s += 2.0
            elif time in ("morning", "day", "midday", "afternoon", "sunrise") and set(h["time_of_day"]) & {"morning", "day", "midday", "afternoon"}:
                s += 2.0
            else:
                s -= 3.0
        s += 1.5 * len(mood_w & set(h["mood"]))
        s += 1.0 * len(key_w & set(h["keywords"]))
        return s

    # Stable: ties go to the earlier (more general) catalog entry.
    return max(CURATED_HDRIS, key=lambda h: (score(h), -CURATED_HDRIS.index(h)))


def pick_texture(kind: str, keywords: Any = (), *, setting: str = "indoor") -> Optional[dict]:
    """A curated floor/ground/wall texture matching material words ("light oak wood").

    ``kind`` is "floor" (indoor floors and, outdoors, ground) or "wall".
    Returns None only for "wall" when nothing matches (plain color is better
    than a wrong wall)."""
    words = _words(keywords)
    if kind == "wall":
        pool = [t for t in CURATED_TEXTURES if t["kind"] == "wall"]
    elif setting == "outdoor":
        pool = [t for t in CURATED_TEXTURES if t["kind"] == "ground"] + [t for t in CURATED_TEXTURES if t["kind"] == "floor"]
    else:
        pool = [t for t in CURATED_TEXTURES if t["kind"] == "floor"] + [t for t in CURATED_TEXTURES if t["kind"] == "ground"]
    scored = [(len(words & set(t["keywords"])), -i, t) for i, t in enumerate(pool)]
    best = max(scored, key=lambda s: (s[0], s[1]))
    if best[0] == 0:
        if kind == "wall":
            return pool[0] if words & {"wall", "walls", "plaster", "paint", "painted"} else None
        return pool[0]
    return best[2]


def pick_sounds(keywords: Any = (), *, setting: str = "indoor", time_of_day: str = "", limit: int = 2,
                kinds: Iterable[str] = ("ambient", "detail")) -> list[dict]:
    """Curated ambient sounds for a scene: one bed + details, best match first.

    Always returns at least one bed (room tone indoors, birds or crickets
    outdoors) so every room has a sound floor."""
    words = _words(keywords)
    kinds = set(kinds)
    pool = [s for s in CURATED_SOUNDS if s["kind"] in kinds]
    ranked = sorted(
        ((len(words & set(s["keywords"])), -i, s) for i, s in enumerate(pool)),
        key=lambda r: (r[0], r[1]),
        reverse=True,
    )
    chosen = [s for score, _, s in ranked if score > 0][: max(0, limit)]
    if not any(s["kind"] == "ambient" for s in chosen) and "ambient" in kinds:
        time = _time_word(time_of_day)
        if setting == "outdoor":
            bed_id = "night_crickets" if time in ("night", "evening", "dusk") else "birds_morning"
        else:
            bed_id = "room_tone"
        bed = next(s for s in CURATED_SOUNDS if s["id"] == bed_id)
        chosen = [bed] + [s for s in chosen if s["id"] != bed_id]
        chosen = chosen[: max(1, limit)]
    return chosen


def object_sound(label: str) -> Optional[dict]:
    """A curated sound that belongs to an object ("cat" -> purring), or None."""
    words = _words(label)
    for s in CURATED_SOUNDS:
        if s["kind"] == "object" and words & set(s["keywords"][:3]):
            return s
    return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _get_json(url: str, *, timeout: float = TIMEOUT_S) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https hosts
        return json.loads(response.read().decode("utf-8"))


def _offline_reason(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} from the media API (sandbox egress policy sketchscape-web-media may be missing)"
    return f"network unavailable ({type(exc).__name__}: {str(exc)[:120]})"


_NET_ERRORS = (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError)


def _query(params: Mapping[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})


def _clamp_count(value: Any, default: int = 6) -> int:
    try:
        n = int(value if value is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(MAX_RESULTS, n))


def _attribution(title: str, creator: str, license_: str, version: str, source: str) -> str:
    lic = _LICENSE_NAMES.get((license_ or "").lower(), (license_ or "").upper())
    if version and lic not in ("CC0 1.0", "Public Domain Mark"):
        lic = f"{lic} {version}"
    who = f" by {creator}" if creator else ""
    return f"'{title or 'Untitled'}'{who}, {lic}, via {source or 'Openverse'}"


def _text(value: Any, limit: int = 120) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


# ---------------------------------------------------------------------------
# Searches
# ---------------------------------------------------------------------------


def search_images(query: str, *, count: int = 6, license: str = DEFAULT_LICENSES, aspect_ratio: str = "",
                  min_width: int = 600) -> dict:
    """Openly licensed images from Openverse, as JPG/PNG Unity can load.

    Returns ``{"source": "openverse"|"offline", "results": [{"title", "url",
    "thumbnail", "creator", "license", "attribution", "width", "height",
    "landing_url"}], "note"?}``. ``license`` is an Openverse license list
    (default: cc0, pdm, by, by-sa); ``aspect_ratio``: tall|wide|square."""
    query = _text(query, 200)
    if not query:
        raise WebMediaError("search_images needs a non-empty query")
    count = _clamp_count(count)
    params = {
        "q": query,
        "license": license or DEFAULT_LICENSES,
        "page_size": min(20, count * 3),
        "mature": "false",
        "aspect_ratio": aspect_ratio,
    }
    try:
        data = _get_json(f"{OPENVERSE}/images/?{_query(params)}")
    except _NET_ERRORS as exc:
        return {"source": "offline", "results": [], "note": _offline_reason(exc) + "; no curated image fallback - skip images or retry later."}
    results = []
    for item in data.get("results", []) or []:
        url = str(item.get("url") or "")
        ext = (item.get("filetype") or url.rsplit(".", 1)[-1].split("?")[0]).lower()
        width, height = item.get("width") or 0, item.get("height") or 0
        if not url.startswith("https://") or ext not in _IMAGE_TYPES:
            continue
        if width and width < min_width:
            continue
        title = _text(item.get("title"), 80)
        creator = _text(item.get("creator"), 60)
        results.append({
            "title": title,
            "url": url,
            "thumbnail": item.get("thumbnail") or "",
            "creator": creator,
            "license": _LICENSE_NAMES.get(str(item.get("license", "")).lower(), str(item.get("license", ""))),
            "attribution": _attribution(title, creator, str(item.get("license", "")), str(item.get("license_version") or ""),
                                        str(item.get("source") or item.get("provider") or "Openverse")),
            "width": width,
            "height": height,
            "landing_url": item.get("foreign_landing_url") or "",
        })
        if len(results) >= count:
            break
    return {"source": "openverse", "results": results}


_AMBIENT_WORDS = {"ambience", "ambiance", "ambient", "atmosphere", "loop", "loopable", "looping", "background", "soundscape", "room", "tone", "field"}


def search_sounds(query: str, *, count: int = 5, license: str = DEFAULT_LICENSES, min_seconds: float = 8.0,
                  max_seconds: float = 900.0, prefer_loops: bool = True) -> dict:
    """Openly licensed sounds from Openverse with a direct file URL.

    Ranked toward loops/ambience of a usable length when ``prefer_loops``.
    Falls back to the curated catalog when offline. Returns ``{"source",
    "results": [{"title", "url", "duration_s", "filetype", "creator",
    "license", "attribution", "landing_url"}], "note"?}``."""
    query = _text(query, 200)
    if not query:
        raise WebMediaError("search_sounds needs a non-empty query")
    count = _clamp_count(count, 5)
    params = {"q": query, "license": license or DEFAULT_LICENSES, "page_size": 20, "mature": "false"}
    try:
        data = _get_json(f"{OPENVERSE}/audio/?{_query(params)}")
    except _NET_ERRORS as exc:
        words = _words(query)
        curated = sorted(CURATED_SOUNDS, key=lambda c: len(words & set(c["keywords"])), reverse=True)
        curated = [c for c in curated if words & set(c["keywords"])][:count] or pick_sounds(query, limit=count)
        return {
            "source": "curated",
            "results": [_curated_sound_result(s) for s in curated],
            "note": _offline_reason(exc) + "; returned curated CC0/CC BY sounds instead.",
        }
    candidates = []
    for i, item in enumerate(data.get("results", []) or []):
        url = str(item.get("url") or "")
        ext = str(item.get("filetype") or url.rsplit(".", 1)[-1].split("?")[0]).lower()
        seconds = (item.get("duration") or 0) / 1000.0
        if not url.startswith("https://") or ext not in _AUDIO_TYPES:
            continue
        if seconds and not (min_seconds <= seconds <= max_seconds):
            continue
        title = _text(item.get("title"), 80)
        creator = _text(item.get("creator"), 60)
        words = _words(title, [t.get("name", "") for t in item.get("tags") or [] if isinstance(t, Mapping)])
        rank = -i
        if prefer_loops:
            rank += 8 * len(words & _AMBIENT_WORDS) + (6 if 30 <= seconds <= 400 else 0)
        candidates.append((rank, {
            "title": title,
            "url": url,
            "duration_s": round(seconds, 1),
            "filetype": ext,
            "creator": creator,
            "license": _LICENSE_NAMES.get(str(item.get("license", "")).lower(), str(item.get("license", ""))),
            "attribution": _attribution(title, creator, str(item.get("license", "")), str(item.get("license_version") or ""),
                                        str(item.get("source") or item.get("provider") or "Openverse").title()),
            "landing_url": item.get("foreign_landing_url") or "",
        }))
    candidates.sort(key=lambda c: c[0], reverse=True)
    return {"source": "openverse", "results": [c[1] for c in candidates[:count]]}


def _curated_sound_result(s: Mapping[str, Any]) -> dict:
    return {
        "title": s["title"], "url": s["url"], "duration_s": s["duration_s"], "filetype": "mp3",
        "creator": s["creator"], "license": s["license"], "attribution": s["attribution"],
        "landing_url": s["landing_url"], "curated_id": s["id"],
    }


def _curated_env_result(item: Mapping[str, Any], kind: str) -> dict:
    if kind == "hdri":
        return {"id": item["id"], "name": item["name"], "hdri_url": item["url_2k"], "hdri_url_1k": item["url_1k"],
                "setting": item["setting"], "time_of_day": item["time_of_day"], "mood": item["mood"],
                "license": "CC0", "attribution": item["attribution"]}
    return {"id": item["id"], "name": item["name"], "kind": item["kind"], "texture_url": item["url"], "tile_m": item["tile_m"],
            "license": "CC0", "attribution": item["attribution"]}


def search_environment(query: str = "", *, kind: str = "hdri", categories: str = "", count: int = 4,
                       resolution: str = "2k") -> dict:
    """CC0 HDRI skies or floor/wall textures from Poly Haven, with exact file URLs.

    ``kind``: "hdri" or "texture". ``categories``: Poly Haven categories
    (e.g. "indoor", "night", "outdoor,sunrise-sunset", "floor,wood").
    ``query`` words are matched against names, tags, categories and
    descriptions. Falls back to the curated catalog when offline.

    Returns ``{"source": "polyhaven"|"curated", "results": [...]}`` where
    HDRIs carry ``hdri_url`` (.hdr at ``resolution``) and textures carry
    ``texture_url`` (1k diffuse .jpg) and ``tile_m``."""
    kind = (kind or "hdri").strip().lower()
    if kind in ("hdris", "sky", "skybox"):
        kind = "hdri"
    if kind in ("textures", "floor", "wall", "floor_texture", "wall_texture"):
        kind = "texture"
    if kind not in ("hdri", "texture"):
        raise WebMediaError("search_environment kind must be 'hdri' or 'texture'")
    resolution = resolution if resolution in ("1k", "2k", "4k") else "2k"
    count = _clamp_count(count, 4)
    words = _words(query)
    try:
        assets = _get_json(f"{POLYHAVEN}/assets?{_query({'t': 'hdris' if kind == 'hdri' else 'textures', 'categories': categories})}")
        if not isinstance(assets, Mapping):
            raise ValueError("unexpected Poly Haven response")
        ranked = []
        for asset_id, info in assets.items():
            hay = _words(asset_id.replace("_", " "), info.get("name", ""), info.get("tags", []), info.get("categories", []))
            desc = _words(info.get("description", ""))
            score = 3 * len(words & hay) + len(words & desc)
            if words and score == 0:
                continue
            ranked.append((score, int(info.get("download_count") or 0), asset_id, info))
        ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
        results = []
        for _, _, asset_id, info in ranked[: count]:
            files = _get_json(f"{POLYHAVEN}/files/{urllib.parse.quote(asset_id)}")
            authors = " and ".join(list((info.get("authors") or {}).keys())[:2]) or "Poly Haven"
            name = _text(info.get("name") or asset_id, 60)
            base = {"id": asset_id, "name": name, "categories": list(info.get("categories", []))[:6],
                    "license": "CC0", "attribution": f"'{name}' {'HDRI' if kind == 'hdri' else 'texture'} by {authors}, CC0, via Poly Haven"}
            if kind == "hdri":
                hdr = ((files.get("hdri") or {}).get(resolution) or {}).get("hdr") or {}
                if not hdr.get("url"):
                    continue
                base["hdri_url"] = hdr["url"]
            else:
                diffuse = files.get("Diffuse") or files.get("diffuse") or {}
                jpg = (diffuse.get("1k") or {}).get("jpg") or {}
                if not jpg.get("url"):
                    continue
                base["texture_url"] = jpg["url"]
                dims = info.get("dimensions") or []
                base["tile_m"] = round(float(dims[0]) / 1000.0, 2) if dims else 2.0
            results.append(base)
        return {"source": "polyhaven", "results": results}
    except _NET_ERRORS as exc:
        note = _offline_reason(exc) + "; returned curated CC0 Poly Haven assets instead."
    cat_words = _words(categories)
    if kind == "hdri":
        setting = "outdoor" if "outdoor" in cat_words else ("indoor" if "indoor" in cat_words else "")
        ranked_h = sorted(
            CURATED_HDRIS,
            key=lambda h: (len((words | cat_words) & set(h["keywords"] + h["mood"] + h["time_of_day"] + [h["setting"]]))
                           + (5 if setting and h["setting"] == setting else 0)),
            reverse=True,
        )
        results = [_curated_env_result(h, "hdri") for h in ranked_h[:count]]
    else:
        ranked_t = sorted(CURATED_TEXTURES, key=lambda t: len((words | cat_words) & set(t["keywords"] + [t["kind"]])), reverse=True)
        results = [_curated_env_result(t, "texture") for t in ranked_t[:count]]
    return {"source": "curated", "results": results, "note": note}
