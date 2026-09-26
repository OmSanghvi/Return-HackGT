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
import re
from typing import Any, Mapping, Optional, Sequence

import scene_tools as st
from scene_tools import _DEFAULT_SIZE, SceneToolError, _validate_blueprint_input

__all__ = [
    "AGENT_ROOMS_FOLDER",
    "compose_room",
    "room_build_command",
    "room_finalize_command",
    "room_slug",
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

    // v = position xyz, rotation xyz (degrees), size xyz (m), tint rgb
    static void Place(ExecutionResult result, GameObject root, string id, string assetId, params float[] v)
    {{
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = id;
        go.transform.SetParent(root.transform, false);
        go.transform.localPosition = new Vector3(v[0], v[1], v[2]);
        go.transform.localEulerAngles = new Vector3(v[3], v[4], v[5]);
        go.transform.localScale = new Vector3(v[6], v[7], v[8]);
        go.GetComponent<Renderer>().sharedMaterial = Tinted(new Color(v[9], v[10], v[11]), false);
        result.RegisterObjectCreation(go);
        result.Log("Placed " + id + " (asset=" + assetId + ") at " + go.transform.position);
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


def room_build_command(blueprint: dict, staging: Optional[Mapping[str, Any]] = None, *, slug: str) -> str:
    """C# for ``Unity_RunCommand`` that builds ``blueprint`` in its own saved scene.

    ``blueprint`` must be schema-valid (validated here). ``staging`` is the
    optional ``stage_immersive_reveal`` result for the same objects.
    """
    slug = _checked_slug(slug)
    objects: Any = blueprint.get("objects")
    if not objects:
        raise SceneToolError("room_build_command needs at least one object")
    _validate_blueprint_input(blueprint, project_id="unity-room-preview")

    mood = list((staging or {}).get("connecting_motif", {}).get("color") or _NEUTRAL_LIGHT)
    place_calls = "\n".join(
        "        Place(result, root, {id_}, {asset}, {values});".format(
            id_=_cs_string(obj["id"]),
            asset=_cs_string(obj["asset_id"]),
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
) -> dict:
    """Plan a full Quest room: layout, staging, build C#, and the Meta XR tool calls.

    Returns ``{"summary", "room", "objects", "staging", "unity_steps",
    "build_code"}``. ``unity_steps`` is the ordered list of Unity MCP calls
    to make; the build step's ``Code`` is ``build_code`` verbatim.
    """
    blueprint = st.place_objects_in_scene(
        objects, sketch_layout_hint=sketch_layout_hint, project_id=project_id, theme=theme
    )
    staging = st.stage_immersive_reveal(connection_insight, blueprint["objects"]) if connection_insight else None
    slug = room_slug(room_name or theme)
    build_code = room_build_command(blueprint, staging, slug=slug)
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
        }
        for o in blueprint["objects"]
    ]
    return {
        "summary": (
            f"Room '{slug}': {len(placed)} object(s) in an arc facing the entry, "
            f"{len(hotspots)} teleport hotspot(s)"
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
