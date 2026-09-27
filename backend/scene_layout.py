"""Reconstruct a photo's scene layout in Unity from Fast-SAM3D poses.

Each reconstruction's ``pose`` (worker/scene_pose.py) is the object's pose in
the photo's camera frame: ``rotation`` (quaternion), ``translation`` and
``scale``, from SAM 3D's pose decoder over MoGe's depth pointmap, plus
percentiles of the pointmap for finding the floor.

``layout_from_poses`` turns the objects of one photo into Unity transforms
that reproduce the photo:

- **Where things are:** each object at its camera-frame position, converted
  to Unity axes, with the photo's camera placed at the player's eyes
  (``(0, player_eye_height, 0)``, looking down +Z).
- **How big things are, relative to the player:** the photo's camera height
  above the floor (from the pointmap) is set equal to the player's eye height,
  which fixes the one global scale MoGe's depth leaves open. Every object gets
  that scale times its own pose scale, so relative sizes come from the photo
  and absolute sizes from the player. If the floor isn't visible, label sizes
  (scene_tools' size table) set the scale instead.
- **Orientation:** the object's rotation, carried into Unity's axes.

Frame conventions live in constants below so they can be confirmed against a
real reconstruction and changed in one place. Standard library only (runs in
the NemoClaw sandbox too).

``photo_room_layout`` (below) is the version-2 path, per
docs/IMMERSIVE_SCENE_PIPELINE.md sections 0/1: it takes the photo's
``scene.json`` and pose.json v2 records (metric, OpenCV camera frame, gravity
and support plane) and returns exact Unity transforms for the scene splat and
each object splat, plus the player's spawn. ``layout_from_poses`` /
``apply_photo_layout`` are the older version-1 path (raw SAM 3D pose decoder
output) kept for the blueprint pipeline.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Optional, Sequence

# SAM 3D's camera frame -> Unity (x right, y up, z forward). SAM 3D follows
# PyTorch3D's camera convention (x left, y up, z forward): flip x.
CAMERA_TO_UNITY = (-1.0, 1.0, 1.0)
# The pose quaternion's component order.
QUATERNION_ORDER = "wxyz"
# How HackGTUnity's Gsplat importer maps a PLY's (x, y, z) to the imported
# asset's local coordinates: local = GSPLAT_IMPORT_MAP * ply (row-major 3x3).
# Default RUB import = flip z. The single source of truth for every splat
# transform in this module (the unity-kit work measures the real one).
GSPLAT_IMPORT_MAP = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, -1.0))
# (The version-1 path undoes it with GSPLAT_IMPORT_MAP^-1 so the pose applies
# to the scan's own coordinates.)
# The pointmap axis that points up in SAM 3D's camera frame (y, positive up):
# the floor is a low percentile of it.
UP_AXIS, UP_SIGN, FLOOR_PERCENTILE = "y", 1.0, "2"

DEFAULT_PLAYER_EYE_HEIGHT = 1.6
MIN_CAMERA_HEIGHT = 1e-3


class LayoutError(ValueError):
    """The poses can't produce a layout (missing or malformed pose data)."""


Matrix = list[list[float]]


def _quat_to_matrix(q: Sequence[float]) -> Matrix:
    if QUATERNION_ORDER == "wxyz":
        w, x, y, z = q
    else:
        x, y, z, w = q
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-9:
        raise LayoutError("zero-length rotation quaternion")
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ]


def _diag_left(d: Sequence[float], m: Matrix) -> Matrix:
    return [[d[i] * m[i][j] for j in range(3)] for i in range(3)]


def unity_euler_from_matrix(m: Matrix) -> list[float]:
    """Unity Euler angles (degrees) for a proper rotation matrix.

    Unity's ``Quaternion.Euler(x, y, z)`` is ``Ry(y) * Rx(x) * Rz(z)``, so
    ``m[1][2] = -sin(x)``, ``m[0][2] / m[2][2] = tan(y)`` and
    ``m[1][0] / m[1][1] = tan(z)``.
    """
    sx = max(-1.0, min(1.0, -m[1][2]))
    x = math.asin(sx)
    if abs(math.cos(x)) > 1e-6:
        y = math.atan2(m[0][2], m[2][2])
        z = math.atan2(m[1][0], m[1][1])
    else:  # gimbal lock: fold all yaw into y
        y = math.atan2(-m[2][0], m[0][0])
        z = 0.0
    return [round(math.degrees(v) % 360.0, 3) for v in (x, y, z)]


def _vector(pose: Mapping[str, Any], key: str, size: int) -> list[float]:
    values = pose.get(key)
    if not isinstance(values, list) or len(values) < size:
        raise LayoutError(f"pose is missing a {size}-value {key!r}")
    return [float(v) for v in values[-size:]] if key != "scale" else [float(v) for v in values]


def _uniform_scale(pose: Mapping[str, Any]) -> float:
    scale = [abs(v) for v in _vector(pose, "scale", 1)]
    return statistics.fmean(scale[:3]) if len(scale) >= 3 else scale[0]


def camera_height(pose: Mapping[str, Any]) -> Optional[float]:
    """The photo camera's height above the floor, in pose units, or None."""
    try:
        up = float(pose["pointmap"]["percentiles"][UP_AXIS][FLOOR_PERCENTILE]) * UP_SIGN
    except (KeyError, TypeError, ValueError):
        return None
    height = -up
    return height if height > MIN_CAMERA_HEIGHT else None


def has_pose(pose: Any) -> bool:
    if not isinstance(pose, Mapping):
        return False
    try:
        _quat_to_matrix(_vector(pose, "rotation", 4))
        _vector(pose, "translation", 3)
        _uniform_scale(pose)
    except (LayoutError, ValueError, TypeError):
        return False
    return True


def layout_from_poses(
    objects: Sequence[Mapping[str, Any]],
    *,
    player_eye_height: float = DEFAULT_PLAYER_EYE_HEIGHT,
    label_sizes: Optional[Mapping[str, float]] = None,
) -> dict:
    """Unity transforms reproducing one photo's layout.

    ``objects`` are ``{"id", "pose", "label"?}``. ``label_sizes`` maps id ->
    expected largest side in metres (for the no-floor fallback; scans are
    normalized so their largest side is about 1 pose unit before scaling).

    Returns ``{"objects": {id: {"position", "rotation", "scale"}}, "scene_scale",
    "scale_source", "camera_height"}``: positions/rotations in Unity world
    (floor y = 0, player at the origin looking +Z), uniform ``scale``.
    """
    if not objects:
        raise LayoutError("no objects to lay out")
    if player_eye_height <= 0:
        raise LayoutError("player_eye_height must be positive")
    poses = {obj["id"]: obj["pose"] for obj in objects}
    for obj_id, pose in poses.items():
        if not has_pose(pose):
            raise LayoutError(f"{obj_id} has no usable pose")

    heights = [h for h in (camera_height(p) for p in poses.values()) if h is not None]
    if heights:
        scene_scale = player_eye_height / statistics.median(heights)
        source = "floor"
    elif label_sizes:
        ratios = [label_sizes[i] / _uniform_scale(p) for i, p in poses.items() if label_sizes.get(i) and _uniform_scale(p) > 0]
        if not ratios:
            raise LayoutError("no floor in view and no label sizes to scale by")
        scene_scale = statistics.median(ratios)
        source = "labels"
    else:
        raise LayoutError("no floor in view and no label sizes to scale by")

    placed: dict[str, dict] = {}
    for obj_id, pose in poses.items():
        t = _vector(pose, "translation", 3)
        rotation = _matmul(
            _diag_left(CAMERA_TO_UNITY, _quat_to_matrix(_vector(pose, "rotation", 4))), _inverse(GSPLAT_IMPORT_MAP)
        )
        placed[obj_id] = {
            "position": [
                round(scene_scale * CAMERA_TO_UNITY[0] * t[0], 4),
                round(scene_scale * CAMERA_TO_UNITY[1] * t[1] + player_eye_height, 4),
                round(scene_scale * CAMERA_TO_UNITY[2] * t[2], 4),
            ],
            "rotation": unity_euler_from_matrix(rotation),
            "scale": round(scene_scale * _uniform_scale(pose), 4),
        }
    return {
        "objects": placed,
        "scene_scale": round(scene_scale, 6),
        "scale_source": source,
        "camera_height": round(statistics.median(heights), 6) if heights else None,
        "player_eye_height": player_eye_height,
    }


def player_eye_height_from_env(default: float = DEFAULT_PLAYER_EYE_HEIGHT) -> float:
    import os

    try:
        value = float(os.environ.get("SKETCHSCAPE_PLAYER_EYE_HEIGHT", default))
    except ValueError:
        return default
    return value if value > 0 else default


def apply_photo_layout(
    objects: list[dict],
    sources: Mapping[str, Mapping[str, Any]],
    *,
    player_eye_height: Optional[float] = None,
) -> Optional[dict]:
    """Reproduce one photo's layout on blueprint-style ``objects`` in place.

    ``sources`` maps object id -> ``{"pose", "photo", "label_size"}``. The
    photo with the most posed objects is laid out with ``layout_from_poses``;
    those objects get the photo's positions, rotations and player-relative
    uniform scale, and ``placement="pose"``. Everything else keeps its planned
    transform. Returns a short report, or None when nothing had a usable pose.
    """
    eye = player_eye_height if player_eye_height else player_eye_height_from_env()
    groups: dict[str, list[str]] = {}
    for obj in objects:
        source = sources.get(obj["id"]) or {}
        if has_pose(source.get("pose")):
            groups.setdefault(str(source.get("photo") or ""), []).append(obj["id"])
    if not groups:
        return None
    photo, ids = max(groups.items(), key=lambda item: len(item[1]))
    try:
        layout = layout_from_poses(
            [{"id": i, "pose": sources[i]["pose"]} for i in ids],
            player_eye_height=eye,
            label_sizes={i: float(sources[i]["label_size"]) for i in ids if sources[i].get("label_size")},
        )
    except LayoutError:
        return None
    for obj in objects:
        placed = layout["objects"].get(obj["id"])
        if placed:
            obj["position"] = placed["position"]
            obj["rotation"] = placed["rotation"]
            obj["scale"] = [placed["scale"]] * 3
            obj["placement"] = "pose"
    return {
        "photo": photo or None,
        "objects": ids,
        "scale_source": layout["scale_source"],
        "scene_scale": layout["scene_scale"],
        "player_eye_height": eye,
    }


# ---------------------------------------------------------------------------
# Version 2: metric photo scenes (scene.json + pose.json v2) -> Unity transforms
# ---------------------------------------------------------------------------
#
# Frames (contract section 0):
#   camera ("opencv"): x right, y down, z forward, metres, right-handed.
#   Unity world: x right, y up, z forward, left-handed, floor at y = 0.
# World = A * cam with A = T * R_align * F:
#   F = diag(1, -1, 1) re-describes an OpenCV point in left-handed y-up axes;
#   R_align (proper rotation) takes gravity-up to +Y and the camera's viewing
#   direction on the ground plane to +Z (so the player, facing yaw 0, sees
#   what the photo saw);
#   T lifts the camera to (0, camera_world_y, 0), which puts the support
#   plane at its chosen height.
# A Gsplat asset imported from a PLY has local = G * ply (GSPLAT_IMPORT_MAP),
# so a camera-frame PLY gets the Unity transform M = A * G^-1 and an object
# PLY with splat_to_cam S gets M = A * S * G^-1.

OPENCV_TO_UNITY = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0))  # F
SURFACE_HEIGHT_RANGE = (0.35, 1.2)  # where a raised support ("surface") may sit, metres
SPAWN_BACKOFF_M = 0.45  # a surface-kind spawn stands this far behind the nearest content
DEFAULT_CAMERA_HEIGHT = 1.4  # surface kind without a camera height (noted)
_EPS = 1e-9


def _mat(rows: Sequence[Sequence[float]]) -> Matrix:
    return [[float(v) for v in row] for row in rows]


def _matmul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _matvec(a: Sequence[Sequence[float]], v: Sequence[float]) -> list[float]:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _det(m: Sequence[Sequence[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def _inverse(m: Sequence[Sequence[float]]) -> Matrix:
    d = _det(m)
    if abs(d) < _EPS:
        raise LayoutError("singular matrix")
    c = [
        [m[1][1] * m[2][2] - m[1][2] * m[2][1], m[0][2] * m[2][1] - m[0][1] * m[2][2], m[0][1] * m[1][2] - m[0][2] * m[1][1]],
        [m[1][2] * m[2][0] - m[1][0] * m[2][2], m[0][0] * m[2][2] - m[0][2] * m[2][0], m[0][2] * m[1][0] - m[0][0] * m[1][2]],
        [m[1][0] * m[2][1] - m[1][1] * m[2][0], m[0][1] * m[2][0] - m[0][0] * m[2][1], m[0][0] * m[1][1] - m[0][1] * m[1][0]],
    ]
    return [[c[i][j] / d for j in range(3)] for i in range(3)]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> list[float]:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _norm(v: Sequence[float]) -> float:
    return math.sqrt(_dot(v, v))


def _unit(v: Sequence[float]) -> list[float]:
    n = _norm(v)
    if n < _EPS:
        raise LayoutError("zero-length vector")
    return [x / n for x in v]


def _vec3(value: Any) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        out = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(v) for v in out) else None


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def quaternion_xyzw_from_matrix(m: Sequence[Sequence[float]]) -> list[float]:
    """Unity quaternion ``[x, y, z, w]`` (w >= 0) of a proper rotation matrix.

    Unity's ``Matrix4x4.Rotate(q)`` is the textbook formula on (x, y, z, w),
    so this is the textbook inverse (Shepperd's method)."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w, x, y, z = 0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        w, x, y, z = (m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        w, x, y, z = (m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        w, x, y, z = (m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z)
    q = [x / n, y / n, z / n, w / n]
    if q[3] < 0:
        q = [-c for c in q]
    return q


def _quat_to_matrix_wxyz(q: Sequence[float]) -> Matrix:
    w, x, y, z = (float(c) for c in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if not math.isfinite(n) or n < _EPS:
        raise LayoutError("zero-length rotation quaternion")
    w, x, y, z = w / n, x / n, y / n, z / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ]


def matrix_from_quaternion_xyzw(q: Sequence[float]) -> Matrix:
    """Rotation matrix of a Unity quaternion ``[x, y, z, w]`` (as Unity builds it)."""
    x, y, z, w = (float(c) for c in q)
    return _quat_to_matrix_wxyz((w, x, y, z))


def _orthonormalize(m: Sequence[Sequence[float]]) -> Matrix:
    """A proper rotation close to ``m`` (Gram-Schmidt on its columns)."""
    c0 = _unit([m[i][0] for i in range(3)])
    c1 = [m[i][1] for i in range(3)]
    k = _dot(c1, c0)
    c1 = _unit([c1[i] - k * c0[i] for i in range(3)])
    c2 = _cross(c0, c1)
    return [[c0[i], c1[i], c2[i]] for i in range(3)]


def decompose_linear(linear: Sequence[Sequence[float]]) -> tuple[list[float], list[float], list[str]]:
    """Split a similarity's 3x3 part into a Unity ``rotation`` (xyzw) and
    ``scale`` so that ``linear == R(rotation) * diag(scale)``.

    Scale is uniform in magnitude. A reflection (det < 0) is expressed as a
    single negative axis (z) and noted, since a rotation can't carry it."""
    notes: list[str] = []
    d = _det(linear)
    if not math.isfinite(d) or abs(d) < _EPS:
        raise LayoutError("degenerate (zero-volume) transform")
    s = abs(d) ** (1.0 / 3.0)
    flip = [1.0, 1.0, -1.0] if d < 0 else [1.0, 1.0, 1.0]
    if d < 0:
        notes.append("transform is a reflection: expressed as scale z < 0")
    rot = [[linear[i][j] * flip[j] / s for j in range(3)] for i in range(3)]
    norms = [_norm([rot[i][j] for i in range(3)]) for j in range(3)]
    if max(abs(n - 1.0) for n in norms) > 0.01:
        notes.append(f"transform is not a similarity (axis scales {[round(n * s, 4) for n in norms]}); using their geometric mean")
    return quaternion_xyzw_from_matrix(_orthonormalize(rot)), [s * f for f in flip], notes


def _r(values: Sequence[float], digits: int = 5) -> list[float]:
    return [round(float(v), digits) + 0.0 for v in values]


def is_pose_v2(pose: Any) -> bool:
    """A pose.json version 2 record (contract section 1a)."""
    if not isinstance(pose, Mapping) or not isinstance(pose.get("object"), Mapping):
        return False
    version = _num(pose.get("version"))
    return version is not None and version >= 2


FRAME_MATCH_TOLERANCE = {"camera_height": 0.03, "focal": 0.02, "gravity_deg": 3.0}


def scene_geometry(scene: Any) -> str:
    """Which photo geometry a scene.json was made with: ``"v2"`` (metric scale
    follows SHARP etc.: ``splat.metric_scale`` present), ``"v1"`` (MoGe-2
    scale, SHARP rescaled to it) or ``""`` (no scene)."""
    if not isinstance(scene, Mapping):
        return ""
    splat = scene.get("splat") if isinstance(scene.get("splat"), Mapping) else {}
    return "v2" if isinstance(splat.get("metric_scale"), Mapping) else "v1"


def pose_frame_mismatch(scene: Any, pose: Any) -> Optional[str]:
    """Why pose.json v2 ``pose`` is NOT in the same camera frame as scene.json
    ``scene`` (a different geometry version / scale), or None when it is or
    it can't be told. Mixing them would put the object at the wrong depth and
    size, so callers skip such objects (they stay part of the photo splat).

    A pose made against the photo's geometry copies its support plane,
    intrinsics and gravity, so those must agree: camera height within 3 %
    (v1 -> v2 rescaled the cats photo by 1.56x), focal within 2 %, gravity
    within 3 degrees. A pose recorded as not metric (made without the scene
    geometry) never matches a scene."""
    if not isinstance(scene, Mapping) or not is_pose_v2(pose):
        return None
    if pose.get("metric") is False:
        return "pose is not metric (made without the photo's scene geometry)"
    tol = FRAME_MATCH_TOLERANCE
    s_plane = scene.get("support_plane") if isinstance(scene.get("support_plane"), Mapping) else {}
    p_plane = pose.get("support_plane") if isinstance(pose.get("support_plane"), Mapping) else {}
    s_h, p_h = _camera_height(s_plane), _camera_height(p_plane)
    if s_h and p_h and abs(p_h / s_h - 1.0) > tol["camera_height"]:
        return (f"camera height {p_h:.4f} m in the pose vs {s_h:.4f} m in scene.json "
                f"(x{p_h / s_h:.3f}: different geometry versions)")
    s_in = scene.get("intrinsics") if isinstance(scene.get("intrinsics"), Mapping) else {}
    p_in = pose.get("intrinsics") if isinstance(pose.get("intrinsics"), Mapping) else {}
    s_fx, p_fx = _num(s_in.get("fx")), _num(p_in.get("fx"))
    s_size, p_size = scene.get("image_size"), pose.get("image_size")
    if s_fx and p_fx and s_fx > 0 and p_fx > 0:
        try:
            p_fx *= float(s_size[0]) / float(p_size[0])
        except (TypeError, ValueError, IndexError, ZeroDivisionError):
            pass
        if abs(p_fx / s_fx - 1.0) > tol["focal"]:
            return f"focal {p_fx:.1f} px in the pose vs {s_fx:.1f} px in scene.json"
    s_g, p_g = _vec3(scene.get("gravity_up_cam")), _vec3(pose.get("gravity_up_cam"))
    if s_g and p_g and _norm(s_g) > _EPS and _norm(p_g) > _EPS:
        cos = max(-1.0, min(1.0, _dot(_unit(s_g), _unit(p_g))))
        if math.degrees(math.acos(cos)) > tol["gravity_deg"]:
            return f"gravity differs by {math.degrees(math.acos(cos)):.1f} deg between the pose and scene.json"
    return None


def _frame_source(scene: Any, poses: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any], str]:
    if isinstance(scene, Mapping) and (scene.get("gravity_up_cam") or scene.get("support_plane")):
        return scene, "scene"
    for pose in poses:
        if pose.get("gravity_up_cam") or pose.get("support_plane"):
            return pose, "pose"
    return {}, "none"


def _camera_height(plane: Mapping[str, Any]) -> Optional[float]:
    h = _num(plane.get("camera_height"))
    if h is not None and h > MIN_CAMERA_HEIGHT:
        return h
    normal, offset = _vec3(plane.get("normal_cam")), _num(plane.get("offset"))
    if normal is not None and offset is not None and _norm(normal) > _EPS:
        h = abs(offset) / _norm(normal)  # distance from the camera to n.x + offset = 0
        return h if h > MIN_CAMERA_HEIGHT else None
    return None


def camera_alignment(gravity_up_cam: Sequence[float]) -> Matrix:
    """``R_align * F``: camera (OpenCV) directions -> Unity world directions,
    gravity-up -> +Y and the camera's view direction on the ground -> +Z.

    The heading is the camera's forward axis flattened onto the ground plus
    the image's "up" axis (flattened) weighted by how far the camera pitches
    down, so a level camera keeps its exact forward and a straight-down photo
    takes the top of the image as forward instead of becoming undefined."""
    f = _mat(OPENCV_TO_UNITY)
    up = _unit(_matvec(f, _unit(gravity_up_cam)))
    forward = _matvec(f, [0.0, 0.0, 1.0])
    image_up = _matvec(f, [0.0, -1.0, 0.0])

    def flat(v: Sequence[float]) -> list[float]:
        k = _dot(v, up)
        return [v[i] - k * up[i] for i in range(3)]

    pitch_down = max(0.0, -_dot(forward, up))
    heading = [a + pitch_down * b for a, b in zip(flat(forward), flat(image_up))]
    if _norm(heading) < 1e-6:  # looking straight up: the bottom of the image is ahead
        heading = [-v for v in flat(image_up)]
    fwd = _unit(heading)
    right = _cross(up, fwd)  # x = y cross z, the usual formula, in Unity axes too
    return _matmul([right, up, fwd], f)


def _depth_grid_points(scene: Mapping[str, Any]) -> list[list[float]]:
    """The scene's coarse depth grid as camera-frame points (valid cells only).

    scene.json lists only the valid cells in ``points_cam`` (row-major) and
    marks them in ``depth_grid_valid`` (base64, bit i = byte i // 8, bit
    i % 8, LSB first; [] when all are valid), so the points are usable as-is."""
    grid = scene.get("depth_grid")
    if not isinstance(grid, Mapping):
        return []
    try:
        values = [float(v) for v in grid.get("points_cam") or []]
    except (TypeError, ValueError):
        return []
    pts = [values[i:i + 3] for i in range(0, len(values) - 2, 3)]
    return [p for p in pts if all(math.isfinite(v) for v in p) and p[2] > 0]


def camera_right_yaw(gravity_up_cam: Sequence[float], rot_cam: Optional[Sequence[Sequence[float]]] = None) -> float:
    """Unity yaw (degrees, clockwise from above) of the camera's right axis
    flattened on the ground, as the GPU worker defines it for ``yaw_deg``
    (scene_capture.gravity_frame: forward = camera +z flattened, or image-up
    when looking along gravity; right = forward x up, in the camera frame).
    0 when it maps to world +X (a level or merely pitched camera)."""
    u = _unit(gravity_up_cam)
    f = [-u[2] * u[0], -u[2] * u[1], 1.0 - u[2] * u[2]]  # z - (z.u) u
    if _norm(f) < 1e-6:
        f = [u[1] * u[0], -1.0 + u[1] * u[1], u[1] * u[2]]  # (0,-1,0) - ((0,-1,0).u) u
    right = _unit(_cross(_unit(f), u))
    w = _matvec(rot_cam if rot_cam is not None else camera_alignment(gravity_up_cam), right)
    return math.degrees(math.atan2(-w[2], w[0]))


def _percentile(values: Sequence[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    k = (len(s) - 1) * q
    lo = int(math.floor(k))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def photo_room_layout(
    scene: Optional[Mapping[str, Any]],
    objects: Sequence[Mapping[str, Any]],
    *,
    player_eye_height: float = DEFAULT_PLAYER_EYE_HEIGHT,
) -> dict:
    """Unity transforms that rebuild one photo as a room you stand in.

    ``scene``: the photo's scene.json (or None when there is no scene).
    ``objects``: ``{"id", "pose", "native_extent"?, "bounds_min"?,
    "bounds_max"?, "label_size_m"?}`` where ``pose`` is pose.json v2; objects
    with a v1 / missing pose are left out of ``objects`` in the result so the
    caller falls back to its own placement.

    Returns (Unity world metres; rotations are Unity quaternions ``[x, y, z, w]``)::

        {"scene_transform": {"position", "rotation", "scale"} | None,  # for scene.ply
         "objects": {id: {"mode": "transform"|"upright", "position", "rotation",
                          "scale", "size_m"}},
         "spawn": {"position", "yaw"},
         "support": {"kind", "height", "camera_height"},
         "camera_world": [..3], "bounds": {"min", "max"},
         "player_eye_height": float, "notes": [...]}

    ``transform`` objects: put position/rotation/scale on the Gsplat object
    itself (they already include GSPLAT_IMPORT_MAP); ``size_m`` is its
    largest side in the world. ``upright`` objects (pose v2 without a verified
    ``splat_to_cam``): ``position`` is the contact point on the support,
    ``rotation`` a yaw only, with the object's +Z toward the photo camera:
    when the pose has ``yaw_deg`` (the long horizontal axis relative to the
    camera's flattened right axis, Unity sense, 0 = long side facing the
    camera) the object's X is that long axis and +Z faces the camera side;
    otherwise +Z points at the camera. ``size_m`` is its largest measured
    side (or ``label_size_m``); ``scale`` is 1.

    ``support.kind == "floor"``: the support plane is the floor (y = 0), the
    camera sits at its real height and the player spawns under it, facing
    the same way (yaw 0). ``"surface"`` (a sofa / table / bed seen from close):
    the surface is raised to ``clamp(eye - camera_height, 0.35, 1.2)`` so the
    player's eyes are about where the camera was, and the player spawns just
    behind the nearest scene content, facing it (yaw 0).
    """
    notes: list[str] = []
    eye = float(player_eye_height) if player_eye_height and player_eye_height > 0 else DEFAULT_PLAYER_EYE_HEIGHT
    items = [o for o in objects or [] if isinstance(o, Mapping) and o.get("id") is not None]
    v2 = [o for o in items if is_pose_v2(o.get("pose"))]
    skipped = [str(o["id"]) for o in items if not is_pose_v2(o.get("pose"))]
    if skipped:
        notes.append(f"no pose v2 (caller places these itself): {', '.join(skipped)}")
    for o in list(v2):
        why = pose_frame_mismatch(scene, o["pose"])
        if why:
            v2.remove(o)
            notes.append(f"{o['id']}: pose not in this scene's geometry ({why}); caller places it itself")

    source, where = _frame_source(scene, [o["pose"] for o in v2])
    if where == "pose":
        notes.append("gravity and support taken from an object pose (no scene.json)")
    gravity = _vec3(source.get("gravity_up_cam"))
    if gravity is None or _norm(gravity) < _EPS:
        gravity = [0.0, -1.0, 0.0]
        notes.append("no gravity: assuming a level camera")
    plane = source.get("support_plane") if isinstance(source.get("support_plane"), Mapping) else {}
    kind = str(plane.get("kind") or "floor").lower()
    if kind not in ("floor", "surface"):
        notes.append(f"unknown support kind {kind!r}: treating it as the floor")
        kind = "floor"
    cam_h = _camera_height(plane)
    if cam_h is None:
        cam_h = eye if kind == "floor" else DEFAULT_CAMERA_HEIGHT
        notes.append(f"no camera height: assuming {cam_h} m above the {kind}")

    if kind == "surface":
        lo_h, hi_h = SURFACE_HEIGHT_RANGE
        support_h = min(hi_h, max(lo_h, eye - cam_h))
        if abs(eye - cam_h - support_h) > 1e-6:
            notes.append(
                f"surface height clamped to {support_h:.2f} m: the photo camera is "
                f"{support_h + cam_h - eye:+.2f} m from the player's eyes"
            )
    else:
        support_h = 0.0
    cam_y = support_h + cam_h

    rot_cam = camera_alignment(gravity)  # R_align * F
    camera_world = [0.0, cam_y, 0.0]  # T

    def to_world(p_cam: Sequence[float]) -> list[float]:
        v = _matvec(rot_cam, p_cam)
        return [v[i] + camera_world[i] for i in range(3)]

    g_inv = _inverse(GSPLAT_IMPORT_MAP)

    def splat_transform(ply_to_cam: Sequence[Sequence[float]], t_cam: Sequence[float]) -> tuple[dict, list[str], float]:
        rotation, scale, extra = decompose_linear(_matmul(_matmul(rot_cam, ply_to_cam), g_inv))
        return {"position": _r(to_world(t_cam)), "rotation": _r(rotation, 6), "scale": _r(scale, 6)}, extra, abs(scale[0])

    scene_transform = None
    content: list[list[float]] = []
    if isinstance(scene, Mapping):
        scene_transform, extra, _ = splat_transform(_mat(((1, 0, 0), (0, 1, 0), (0, 0, 1))), [0.0, 0.0, 0.0])
        notes.extend(f"scene: {n}" for n in extra)
        content.extend(to_world(p) for p in _depth_grid_points(scene))

    placed: dict[str, dict] = {}
    for obj in v2:
        oid = str(obj["id"])
        rec = obj["pose"]["object"]
        extent = rec.get("extent_m") if isinstance(rec.get("extent_m"), Mapping) else {}
        extent_max = max([v for v in (_num(extent.get(k)) for k in ("width", "height", "depth")) if v and v > 0] or [0.0])
        bmin, bmax = _vec3(obj.get("bounds_min")), _vec3(obj.get("bounds_max"))
        native = _vec3(obj.get("native_extent"))
        if native is None and bmin is not None and bmax is not None:
            native = [bmax[i] - bmin[i] for i in range(3)]
        entry: Optional[dict] = None
        s2c = rec.get("splat_to_cam")
        if isinstance(s2c, Mapping):
            q, t, s = s2c.get("rotation_wxyz"), _vec3(s2c.get("translation")), _num(s2c.get("scale"))
            try:
                if not (isinstance(q, (list, tuple)) and len(q) == 4 and t is not None and s is not None and s > 0):
                    raise LayoutError("malformed splat_to_cam")
                lin = [[s * v for v in row] for row in _quat_to_matrix_wxyz(q)]
                transform, extra, total = splat_transform(lin, t)
            except (LayoutError, TypeError, ValueError) as exc:
                notes.append(f"{oid}: {exc}; placed upright instead")
            else:
                notes.extend(f"{oid}: {n}" for n in extra)
                size = total * max(native) if native and max(native) > 0 else extent_max
                entry = {"mode": "transform", **transform, "size_m": round(size, 4)}
                content.append(entry["position"])
                if bmin is not None and bmax is not None:
                    for c in range(8):
                        corner = [bmax[i] if c >> i & 1 else bmin[i] for i in range(3)]
                        content.append(to_world([_dot(lin[i], corner) + t[i] for i in range(3)]))
        if entry is None:
            base = _vec3(rec.get("base_cam")) or _vec3(rec.get("centroid_cam"))
            if base is None:
                notes.append(f"{oid}: pose v2 without base_cam/centroid_cam; left out")
                continue
            size = extent_max or (_num(obj.get("label_size_m")) or 0.0)
            if size <= 0:
                notes.append(f"{oid}: no measured extent or label size (size_m 0)")
            pos = to_world(base)
            yaw_deg = _num(rec.get("yaw_deg"))
            if yaw_deg is not None:
                # Relative to the camera's right axis flattened on the ground
                # (worker gravity_frame: right = forward x up); +Z toward the camera side.
                yaw = (yaw_deg + camera_right_yaw(gravity, rot_cam) + 180.0) % 360.0
            else:
                dx, dz = camera_world[0] - pos[0], camera_world[2] - pos[2]
                yaw = math.degrees(math.atan2(dx, dz)) % 360.0 if math.hypot(dx, dz) > 1e-6 else 180.0
            half = math.radians(yaw) / 2
            entry = {
                "mode": "upright",
                "position": _r(pos),
                "rotation": _r([0.0, math.sin(half), 0.0, math.cos(half)], 6),
                "scale": [1.0, 1.0, 1.0],
                "size_m": round(size, 4),
            }
            content.extend([pos, [pos[0], pos[1] + size, pos[2]]])
        placed[oid] = entry

    if content:
        robust = len(content) > 50
        lo = [_percentile([p[i] for p in content], 0.01) if robust else min(p[i] for p in content) for i in range(3)]
        hi = [_percentile([p[i] for p in content], 0.99) if robust else max(p[i] for p in content) for i in range(3)]
    else:
        lo, hi = list(camera_world), list(camera_world)
        notes.append("no scene content known: bounds are the camera only")
    lo = [min(lo[0], 0.0), min(lo[1], support_h), min(lo[2], 0.0)]
    hi = [max(hi[i], camera_world[i]) for i in range(3)]

    spawn = [0.0, 0.0, 0.0]
    if kind == "surface":
        near = [p[2] for p in content if abs(p[0]) < 1.5] or [0.0]
        near_z = _percentile(near, 0.02) if len(near) > 50 else min(near)
        spawn[2] = min(0.0, near_z) - SPAWN_BACKOFF_M
        lo[2] = min(lo[2], spawn[2])

    return {
        "scene_transform": scene_transform,
        "objects": placed,
        "spawn": {"position": _r(spawn, 4), "yaw": 0.0},
        "support": {"kind": kind, "height": round(support_h, 4), "camera_height": round(cam_h, 4)},
        "camera_world": _r(camera_world, 4),
        "bounds": {"min": _r(lo, 4), "max": _r(hi, 4)},
        "player_eye_height": eye,
        "notes": notes,
    }
