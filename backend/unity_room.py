"""Compose a whole Shared Room in the Unity Editor (Build Plan steps 4 + 6, Unity write path).

``compose_room`` is the one job-shaped entry point a NemoClaw agent calls
(through ``unity_room_cli.py``) to turn contributed objects into a walkable,
grabbable Meta Quest room in the Editor:

1. ``scene_tools.place_objects_in_scene`` lays the objects out.
2. ``scene_tools.stage_immersive_reveal`` choreographs the connection, when a
   ``connection_insight`` is given.
3. ``room_build_command`` generates the ``Unity_RunCommand`` C# that creates
   the room in its **own** scene file (``Assets/SketchScape/AgentRooms/<slug>.unity``),
   so the team's working scenes are never touched: mood-tinted key and
   ambient light, a floor, one tinted placeholder cube per object, a glow at
   the shared center, and the connecting light-path motif on the floor.
4. It lists the exact Meta Unity MCP Extension calls that make the room a
   Quest room (camera rig, interaction rig, grabbable per object, teleport
   hotspots), in order.
5. ``room_finalize_command`` saves the scene and reports what is actually in
   it, so the agent can confirm the room from real Editor state.

Like ``blueprint_to_unity``, values are baked into the generated C# at
generation time; nothing parses JSON inside Unity (``JsonUtility`` silently
fails on nested classes in the RunCommand context).

Narration text and haptic signatures from staging are returned to the agent
but not applied in the Editor: their runtime (``ImmersiveStagingDirector``)
lives in the repo's ``unity/`` project, not in the Editor scene.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import scene_tools as st
from scene_tools import _DEFAULT_SIZE, SceneToolError, _validate_blueprint_input

__all__ = [
    "AGENT_ROOMS_FOLDER",
    "compose_room",
    "room_build_command",
    "room_finalize_command",
    "room_slug",
    "load_catalog",
    "match_catalog",
]

AGENT_ROOMS_FOLDER = "Assets/SketchScape/AgentRooms"
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")

# Soft, distinguishable object tints; each is blended toward the mood color.
_OBJECT_TINTS = (
    (0.85, 0.55, 0.45),
    (0.45, 0.65, 0.85),
    (0.60, 0.80, 0.50),
    (0.90, 0.80, 0.45),
    (0.70, 0.55, 0.85),
    (0.50, 0.80, 0.78),
    (0.88, 0.62, 0.70),
    (0.75, 0.70, 0.60),
)
_NEUTRAL_LIGHT = (1.0, 0.96, 0.9)
_HOTSPOT_STANDOFF = 0.9  # meters in front of each object, toward the room's entry point


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
# C# literal helpers
# ---------------------------------------------------------------------------


def _cs_string(value: str) -> str:
    return json.dumps(value)


def _cs_float(value: float) -> str:
    return f"{round(float(value), 4)!r}f"


def _cs_floats(values: Sequence[float]) -> str:
    """Comma-separated compact float literals (3 decimals), e.g. ``1.5f, -0.25f``."""
    return ", ".join(f"{round(float(v), 3):g}f" for v in values)


def _cs_vec3(values: Sequence[float]) -> str:
    return "new Vector3({}, {}, {})".format(*(_cs_float(v) for v in values))


def _cs_color(rgb: Sequence[float]) -> str:
    return "new Color({}, {}, {})".format(*(_cs_float(max(0.0, min(1.0, c))) for c in rgb))


def _mix(a: Sequence[float], b: Sequence[float], t: float) -> list[float]:
    return [a[i] * (1.0 - t) + b[i] * t for i in range(3)]


# ---------------------------------------------------------------------------
# Geometry baked at generation time
# ---------------------------------------------------------------------------


def _catmull_rom(points: Sequence[Sequence[float]], samples_per_segment: int = 5) -> list[list[float]]:
    """A smooth curve through ``points`` (uniform Catmull-Rom, endpoints clamped)."""
    pts = [list(map(float, p)) for p in points]
    if len(pts) < 3:
        return pts
    padded = [pts[0]] + pts + [pts[-1]]
    curve: list[list[float]] = []
    for i in range(1, len(padded) - 2):
        p0, p1, p2, p3 = padded[i - 1], padded[i], padded[i + 1], padded[i + 2]
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            t2, t3 = t * t, t * t * t
            curve.append(
                [
                    0.5
                    * (
                        2 * p1[k]
                        + (-p0[k] + p2[k]) * t
                        + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                        + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3
                    )
                    for k in range(3)
                ]
            )
    curve.append(pts[-1])
    return curve


def _motif_floor_points(staging: Mapping[str, Any]) -> list[list[float]]:
    control = (staging.get("connecting_motif") or {}).get("control_points") or []
    on_floor = [[float(p[0]), 0.03, float(p[2])] for p in control]
    return [[round(v, 3) for v in p] for p in _catmull_rom(on_floor)]


def _teleport_hotspots(objects: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    """One hotspot per object, ``_HOTSPOT_STANDOFF`` m in front of it toward the entry (origin)."""
    hotspots = []
    for obj in objects:
        x, _, z = (float(v) for v in obj["position"])
        dist = math.hypot(x, z)
        if dist <= _HOTSPOT_STANDOFF + 0.3:
            continue
        k = (dist - _HOTSPOT_STANDOFF) / dist
        hotspots.append([round(x * k, 3), 0.0, round(z * k, 3)])
    return hotspots


# ---------------------------------------------------------------------------
# Generated C#
# ---------------------------------------------------------------------------

_BUILD_TEMPLATE = """using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;

internal class CommandScript : IRunCommand
{{
    const string ScenePath = {scene_path};
    const string AgentRoomsFolder = {folder};

    public void Execute(ExecutionResult result)
    {{
        for (int i = 0; i < SceneManager.sceneCount; i++)
        {{
            var open = SceneManager.GetSceneAt(i);
            if (open.isDirty && !open.path.StartsWith(AgentRoomsFolder + "/"))
            {{
                result.LogError("Scene '" + open.name + "' has unsaved changes. Save or discard them in the Unity Editor, then rerun. Nothing was changed.");
                return;
            }}
        }}
        EnsureFolder(AgentRoomsFolder);
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        var mood = {mood_color};
        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = mood * 0.35f;
        var keyLight = new GameObject("Key Light").AddComponent<Light>();
        keyLight.type = LightType.Directional;
        keyLight.color = Color.Lerp(Color.white, mood, 0.45f);
        keyLight.intensity = 1.1f;
        keyLight.shadows = LightShadows.Soft;
        keyLight.transform.rotation = Quaternion.Euler(50f, -30f, 0f);
        result.RegisterObjectCreation(keyLight.gameObject);

        var root = new GameObject({root_name});
        result.RegisterObjectCreation(root);
        bool wantsFloor = {wants_floor};
        if (wantsFloor)
        {{
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.SetParent(root.transform, false);
            floor.transform.localScale = new Vector3({floor_scale}, 1f, {floor_scale});
            floor.GetComponent<Renderer>().sharedMaterial = Tinted(Color.Lerp(new Color(0.32f, 0.3f, 0.28f), mood, 0.15f), false);
            result.RegisterObjectCreation(floor);
        }}

{place_calls}
{staging_block}
        EditorSceneManager.SaveScene(scene, ScenePath);
        result.Log("Built {object_count} object(s) under {{0}} and saved " + ScenePath + ".", root);
    }}

    // v = position xyz, rotation xyz (degrees), size xyz (m), tint rgb.
    // splat = a Gsplat .ply asset path, or "" for a tinted placeholder cube.
    static void Place(ExecutionResult result, GameObject root, string id, string assetId, string splat, params float[] v)
    {{
        GameObject go = splat.Length > 0 ? PlaceSplat(result, id, splat, Mathf.Max(v[6], Mathf.Max(v[7], v[8]))) : null;
        if (go == null)
        {{
            go = GameObject.CreatePrimitive(PrimitiveType.Cube);
            go.name = id;
            go.transform.localScale = new Vector3(v[6], v[7], v[8]);
            go.GetComponent<Renderer>().sharedMaterial = Tinted(new Color(v[9], v[10], v[11]), false);
        }}
        bool real = go.transform.childCount > 0;
        go.transform.SetParent(root.transform, false);
        // A splat rests on the floor at its own scanned height; a cube uses the planned height.
        go.transform.localPosition = new Vector3(v[0], real ? go.GetComponent<BoxCollider>().size.y / 2f : v[1], v[2]);
        go.transform.localEulerAngles = new Vector3(v[3], v[4], v[5]);
        result.RegisterObjectCreation(go);
        result.Log("Placed " + id + " (asset=" + assetId + (real ? ", real splat" : ", placeholder") + ") at " + go.transform.position);
    }}

    // A real Fast-SAM3D Gaussian splat, scaled so its largest side is maxSize
    // metres. Scans are Z-up; with the importer's default (RUB) frame, +90
    // degrees about X maps them to Unity's Y-up without mirroring. The
    // parent carries a BoxCollider fitted to the splat, for grabbing.
    static GameObject PlaceSplat(ExecutionResult result, string id, string path, float maxSize)
    {{
        var asset = AssetDatabase.LoadMainAssetAtPath(path);
        var rendererType = System.Type.GetType("Gsplat.GsplatRenderer, Gsplat");
        if (asset == null || rendererType == null)
        {{
            result.LogWarning(id + ": splat " + path + " is not imported (or Gsplat is missing); using a placeholder cube.");
            return null;
        }}
        var bounds = (Bounds)asset.GetType().GetField("Bounds").GetValue(asset);
        var size = bounds.size;
        float scale = maxSize / Mathf.Max(0.001f, Mathf.Max(size.x, Mathf.Max(size.y, size.z)));
        var go = new GameObject(id);
        var box = go.AddComponent<BoxCollider>();
        box.size = new Vector3(size.x, size.z, size.y) * scale;
        var child = new GameObject("Splat");
        child.transform.SetParent(go.transform, false);
        child.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
        child.transform.localScale = Vector3.one * scale;
        child.transform.localPosition = -(child.transform.localRotation * bounds.center) * scale;
        rendererType.GetField("GsplatAsset").SetValue(child.AddComponent(rendererType), asset);
        return go;
    }}

    static Material Tinted(Color color, bool unlit)
    {{
        var shader = Shader.Find(unlit ? "Sprites/Default" : "Standard");
        if (shader == null) shader = Shader.Find("Universal Render Pipeline/" + (unlit ? "Unlit" : "Lit"));
        var material = new Material(shader);
        material.color = color;
        return material;
    }}

    static void EnsureFolder(string path)
    {{
        if (AssetDatabase.IsValidFolder(path)) return;
        var parent = System.IO.Path.GetDirectoryName(path).Replace('\\\\', '/');
        EnsureFolder(parent);
        AssetDatabase.CreateFolder(parent, System.IO.Path.GetFileName(path));
    }}
}}
"""

_STAGING_TEMPLATE = """        var glow = new GameObject("Connection Glow").AddComponent<Light>();
        glow.type = LightType.Point;
        glow.color = mood;
        glow.range = {glow_range};
        glow.intensity = 1.6f;
        glow.transform.SetParent(root.transform, false);
        glow.transform.localPosition = {glow_position};
        result.RegisterObjectCreation(glow.gameObject);

        var motif = new GameObject("Connecting Motif").AddComponent<LineRenderer>();
        motif.transform.SetParent(root.transform, false);
        motif.useWorldSpace = false;
        motif.widthMultiplier = 0.05f;
        motif.numCapVertices = 4;
        motif.sharedMaterial = Tinted(mood, true);
        motif.startColor = mood;
        motif.endColor = mood;
        motif.shadowCastingMode = ShadowCastingMode.Off;
        // Floor-level curve, as x,z pairs.
        var xz = new float[] {{ {motif_points} }};
        motif.positionCount = xz.Length / 2;
        for (int i = 0; i < motif.positionCount; i++) motif.SetPosition(i, new Vector3(xz[2 * i], 0.03f, xz[2 * i + 1]));
        result.RegisterObjectCreation(motif.gameObject);
        result.Log("Staging: lighting={lighting_preset}, reveal order={reveal_order}");
"""

_FINALIZE_TEMPLATE = """using UnityEngine;
using UnityEngine.SceneManagement;
using UnityEditor;
using UnityEditor.SceneManagement;
using System.Collections.Generic;

internal class CommandScript : IRunCommand
{{
    const string ScenePath = {scene_path};
    const string RootName = {root_name};

    public void Execute(ExecutionResult result)
    {{
        var scene = SceneManager.GetActiveScene();
        if (scene.path != ScenePath)
        {{
            result.LogError("Active scene is '" + scene.path + "', not " + ScenePath + ". Run the room's build step first.");
            return;
        }}
        GameObject root = null;
        var rigs = new List<string>();
        int hotspots = 0;
        foreach (var go in scene.GetRootGameObjects())
        {{
            if (go.name == RootName) root = go;
            foreach (var c in go.GetComponentsInChildren<Component>(true))
            {{
                if (c == null) continue;
                var type = c.GetType().Name;
                if (type == "OVRCameraRig") rigs.Add(c.gameObject.name);
                if (type == "TeleportInteractable") hotspots++;
            }}
        }}
        if (root == null)
        {{
            result.LogError("Room root " + RootName + " is missing from the scene. Rerun the room's build step.");
            return;
        }}
        var lines = new List<string>();
        foreach (Transform child in root.transform)
        {{
            var kinds = new List<string>();
            foreach (var c in child.GetComponentsInChildren<Component>(true))
            {{
                if (c == null) continue;
                var type = c.GetType().Name;
                if (type == "Grabbable" || type == "DistanceGrabInteractable" || type == "HandGrabInteractable" || type == "GrabInteractable" || type == "Rigidbody")
                    if (!kinds.Contains(type)) kinds.Add(type);
            }}
            lines.Add(child.name + " at " + child.position + (kinds.Count > 0 ? " [" + string.Join(", ", kinds) + "]" : ""));
        }}
        EditorSceneManager.SaveScene(scene, ScenePath);
        var view = SceneView.lastActiveSceneView;
        if (view != null) {{ Selection.activeGameObject = root; view.FrameSelected(); }}
        result.Log("Saved " + ScenePath + ". Camera rig: " + (rigs.Count > 0 ? string.Join(", ", rigs) : "MISSING") + ". Teleport hotspots: " + hotspots + ".\\n" + string.Join("\\n", lines));
    }}
}}
"""


def room_build_command(
    blueprint: dict,
    staging: Optional[Mapping[str, Any]] = None,
    *,
    slug: str,
    splats: Optional[Mapping[str, str]] = None,
) -> str:
    """C# for ``Unity_RunCommand`` that builds ``blueprint`` in its own saved scene.

    ``blueprint`` must be schema-valid (validated here). ``staging`` is the
    optional ``stage_immersive_reveal`` result for the same objects.
    ``splats`` maps object id -> Unity asset path of a real Gaussian-splat
    ``.ply`` (see ``match_catalog``); other objects become placeholder cubes.
    """
    slug = _checked_slug(slug)
    objects: Any = blueprint.get("objects")
    if not objects:
        raise SceneToolError("room_build_command needs at least one object")
    _validate_blueprint_input(blueprint, project_id="unity-room-preview")

    mood = list((staging or {}).get("connecting_motif", {}).get("color") or _NEUTRAL_LIGHT)
    splats = splats or {}
    place_calls = "\n".join(
        "        Place(result, root, {id_}, {asset}, {splat}, {values});".format(
            id_=_cs_string(obj["id"]),
            asset=_cs_string(obj["asset_id"]),
            splat=_cs_string(splats.get(obj["id"], "")),
            values=_cs_floats(
                list(obj["position"])
                + list(obj["rotation"])
                + [obj["scale"][k] * _DEFAULT_SIZE[k] for k in range(3)]
                + [max(0.0, min(1.0, c)) for c in _mix(_OBJECT_TINTS[i % len(_OBJECT_TINTS)], mood, 0.3)]
            ),
        )
        for i, obj in enumerate(objects)
    )

    extent = max(math.hypot(float(o["position"][0]), float(o["position"][2])) for o in objects)
    staging_block = ""
    if staging:
        center = st._shared_center(objects)
        points = _motif_floor_points(staging)
        if len(points) >= 2:
            staging_block = _STAGING_TEMPLATE.format(
                glow_range=_cs_float(max(4.0, extent * 1.6)),
                glow_position=_cs_vec3([center[0], 1.4, center[2]]),
                motif_points=_cs_floats([c for p in points for c in (p[0], p[2])]),
                lighting_preset=str(staging.get("lighting_preset", "")).replace('"', ""),
                reveal_order=", ".join(staging.get("reveal_order", [])).replace('"', ""),
            )

    return _BUILD_TEMPLATE.format(
        scene_path=_cs_string(_scene_path(slug)),
        folder=_cs_string(AGENT_ROOMS_FOLDER),
        mood_color=_cs_color(mood),
        root_name=_cs_string(_root_name(slug)),
        wants_floor="true" if blueprint.get("environment", {}).get("floor") else "false",
        # A Unity plane is 10 m across; cover the arc plus a margin.
        floor_scale=_cs_float(max(1.0, (extent + 2.0) / 5.0)),
        place_calls=place_calls,
        staging_block=staging_block,
        object_count=len(objects),
    )


_CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "nemoclaw" / "asset-catalog.json"


def load_catalog(path: Optional[str] = None) -> list[dict]:
    """Real reconstructed assets imported into Unity by
    ``scripts/sync_s3_assets_to_unity.py``. Missing file -> empty catalog."""
    target = Path(path or os.environ.get("SKETCHSCAPE_ASSET_CATALOG") or _CATALOG_PATH)
    if not target.is_file():
        return []
    return list(json.loads(target.read_text(encoding="utf-8")).get("assets", []))


def _words(text: str) -> set[str]:
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z0-9]+", (text or "").lower())}


def match_catalog(objects: Sequence[Any], catalog: Sequence[Mapping[str, Any]]) -> list[Optional[dict]]:
    """For each input object, the catalog asset to render it with, or None.

    An exact ``asset_id`` match wins; otherwise the longest catalog label
    whose words all appear in the object's label ("our cat Miso" -> "cat",
    "the old TV remote control" -> "remote control")."""
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


def room_finalize_command(slug: str) -> str:
    """C# for ``Unity_RunCommand`` that saves the room's scene and reports its real contents."""
    slug = _checked_slug(slug)
    return _FINALIZE_TEMPLATE.format(
        scene_path=_cs_string(_scene_path(slug)),
        root_name=_cs_string(_root_name(slug)),
    )


def compose_room(
    objects: Sequence[Any],
    *,
    theme: str = "Shared Room",
    connection_insight: Optional[Mapping[str, Any]] = None,
    sketch_layout_hint: Optional[st.LayoutHint] = None,
    room_name: Optional[str] = None,
    project_id: str = "preview",
    catalog: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict:
    """Plan a full Quest room: layout, staging, build C#, and the Meta XR tool calls.

    Objects that match a real asset in ``catalog`` (default: ``load_catalog()``)
    are built from their Gaussian-splat reconstruction; the rest are cubes.

    Returns ``{"summary", "room", "objects", "staging", "unity_steps",
    "build_code"}``. ``unity_steps`` is the ordered list of Unity MCP calls
    to make; the build step's ``Code`` is ``build_code`` verbatim.
    """
    blueprint = st.place_objects_in_scene(
        objects, sketch_layout_hint=sketch_layout_hint, project_id=project_id, theme=theme
    )
    staging = st.stage_immersive_reveal(connection_insight, blueprint["objects"]) if connection_insight else None
    slug = room_slug(room_name or theme)
    matches = match_catalog(objects, load_catalog() if catalog is None else catalog)
    splats = {o["id"]: m["unity_path"] for o, m in zip(blueprint["objects"], matches) if m}
    build_code = room_build_command(blueprint, staging, slug=slug, splats=splats)
    hotspots = _teleport_hotspots(blueprint["objects"])

    steps: list[dict] = [
        {"tool": "unity-mcp__Unity_RunCommand", "args": {"Title": f"Build room {slug}", "Code": f"<output of: unity_room_cli.py build_code {slug}>"}},
        {"tool": "unity-mcp__meta_get_config_information", "args": {}},
        {"tool": "unity-mcp__meta_add_camerarig", "args": {}},
        {"tool": "unity-mcp__meta_add_interactionrig", "args": {}},
    ]
    steps += [{"tool": "unity-mcp__meta_add_grabbable", "args": {"NameOrID": o["id"]}} for o in blueprint["objects"]]
    steps += [
        {"tool": "unity-mcp__meta_add_teleport_hotspot", "args": {"Position": p, "Snap": "SnapPosition"}}
        for p in hotspots
    ]
    steps.append(
        {
            "tool": "unity-mcp__Unity_RunCommand",
            "args": {"Title": f"Finalize room {slug}", "Code": f"<output of: unity_room_cli.py finalize_code {slug}>"},
        }
    )

    labels = {o["id"]: raw_label for o, raw_label in zip(blueprint["objects"], (st._get(r, "label") for r in objects))}
    placed = [
        {
            "id": o["id"],
            "label": labels.get(o["id"]) or o["id"],
            "position": o["position"],
            "size_m": [round(o["scale"][k] * _DEFAULT_SIZE[k], 3) for k in range(3)],
            "visual": f"real 3D scan ({m['label']})" if m else "placeholder cube (no real scan for this label)",
        }
        for o, m in zip(blueprint["objects"], matches)
    ]
    return {
        "summary": (
            f"Room '{slug}': {len(placed)} object(s) in an arc facing the entry, "
            f"{len(splats)} of them real 3D scans, {len(hotspots)} teleport hotspot(s)"
            + (f", lighting={staging['lighting_preset']}" if staging else ", neutral lighting (no connection_insight)")
            + f". Scene: {_scene_path(slug)} (new file; other scenes untouched)."
        ),
        "room": {"slug": slug, "scene_path": _scene_path(slug), "root": _root_name(slug)},
        "objects": placed,
        "staging": None
        if not staging
        else {
            "lighting_preset": staging["lighting_preset"],
            "reveal_order": staging["reveal_order"],
            "narration": staging["narration"]["text"],
            "haptic_signatures": staging["haptic_signatures"],
        },
        "unity_steps": steps,
        "build_code": build_code,
    }
