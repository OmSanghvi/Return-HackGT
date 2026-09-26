"""Blueprint -> Unity scene bridge (Build Plan step 4/6, Unity write path).

Turns any schema-valid ``ExperienceBlueprintInput`` (the output of
``scene_tools.place_objects_in_scene``) into a self-contained Unity Editor
``IRunCommand`` C# script that recreates the blueprint as real GameObjects:
a floor plane if ``environment.floor`` is set, and one placeholder cube per
object, positioned/rotated/scaled to match the blueprint exactly. Paste the
returned source into the ``Unity_RunCommand`` MCP tool to apply it.

Cubes are a placeholder for real per-asset prefabs, which don't exist yet
(no asset pipeline into this Unity project). This bridge proves the
placement math and the write path end to end, not final visuals.

Unity's ``JsonUtility.FromJson`` silently fails to populate nested custom
classes when run inside the AI Assistant "RunCommand" dynamically-compiled
execution context -- confirmed empirically: even a minimal, null-free,
hand-written JSON repro comes back with every nested field null. So this
module does NOT emit a script that parses JSON at runtime in Unity; it bakes
the blueprint's values directly into C# object-creation statements at
generation time instead. Keep doing that if this bridge grows -- don't
reach for JsonUtility here.
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from scene_tools import _DEFAULT_SIZE, SceneToolError, _validate_blueprint_input

__all__ = ["blueprint_to_unity_command"]


def _cs_string(value: str) -> str:
    """A C#-safe string literal.

    JSON and C# string-escaping rules agree closely enough (quotes,
    backslashes, \\n/\\t/...) that ``json.dumps`` produces a valid C#
    literal for the plain text used here.
    """
    return json.dumps(value)


def _cs_float(value: float) -> str:
    return f"{float(value)!r}f"


def _cs_vector3(values: Sequence[float], *, multiplier: Sequence[float] = (1.0, 1.0, 1.0)) -> str:
    x, y, z = (float(v) * float(m) for v, m in zip(values, multiplier))
    return f"new Vector3({_cs_float(x)}, {_cs_float(y)}, {_cs_float(z)})"


_TEMPLATE = """using UnityEngine;

internal class CommandScript : IRunCommand
{{
    public void Execute(ExecutionResult result)
    {{
        var root = new GameObject({root_name});
        result.RegisterObjectCreation(root);

        bool wantsFloor = {wants_floor};
        if (wantsFloor)
        {{
            var floor = GameObject.CreatePrimitive(PrimitiveType.Plane);
            floor.name = "Floor";
            floor.transform.SetParent(root.transform, false);
            floor.transform.localScale = new Vector3(1.5f, 1f, 1.5f);
            result.RegisterObjectCreation(floor);
        }}

{place_calls}

        result.Log("Blueprint applied under {{0}}.", root);
    }}

    private static void Place(ExecutionResult result, GameObject root, string id, string assetId, Vector3 position, Vector3 rotationEuler, Vector3 localScale)
    {{
        var go = GameObject.CreatePrimitive(PrimitiveType.Cube);
        go.name = id;
        go.transform.SetParent(root.transform, false);
        go.transform.localPosition = position;
        go.transform.localEulerAngles = rotationEuler;
        go.transform.localScale = localScale;
        result.RegisterObjectCreation(go);
        result.Log("Placed " + id + " (asset=" + assetId + ") at " + go.transform.position);
    }}
}}
"""


def blueprint_to_unity_command(blueprint: dict, *, root_name: str | None = None) -> str:
    """Generate a Unity Editor ``IRunCommand`` C# script that recreates
    ``blueprint`` as real GameObjects.

    ``blueprint`` must be schema-valid per
    ``shared/experience-blueprint.schema.json`` (an ``ExperienceBlueprintInput``,
    e.g. straight from ``place_objects_in_scene``) -- validated here before
    any code is generated. Accepts any object count (tested 1-8), never a
    fixed shape.
    """
    objects: Any = blueprint.get("objects")
    if not objects:
        raise SceneToolError("blueprint_to_unity_command needs at least one object")
    _validate_blueprint_input(blueprint, project_id="unity-bridge-preview")

    theme = blueprint.get("experience", {}).get("theme") or "Shared Room"
    name = root_name or f"SharedRoom_Blueprint_{theme}"
    wants_floor = bool(blueprint.get("environment", {}).get("floor"))

    place_calls = "\n".join(
        "        Place(result, root, {id_}, {asset_id}, {pos}, {rot}, {scale});".format(
            id_=_cs_string(obj["id"]),
            asset_id=_cs_string(obj["asset_id"]),
            pos=_cs_vector3(obj["position"]),
            rot=_cs_vector3(obj["rotation"]),
            scale=_cs_vector3(obj["scale"], multiplier=_DEFAULT_SIZE),
        )
        for obj in objects
    )

    return _TEMPLATE.format(
        root_name=_cs_string(name),
        wants_floor="true" if wants_floor else "false",
        place_calls=place_calls,
    )
