"""Object pose in its photo: pose.json (v1 raw record, v2 verified placement).

SAM 3D Objects decodes each object's pose in the photo's camera frame
(``pipeline.pose_decoder`` -> ``rotation``, ``translation``, ``scale``, from
MoGe's pointmap). This module turns that into the contract's pose.json
(docs/IMMERSIVE_SCENE_PIPELINE.md section 1a), numpy only, so it is testable
without torch.

The transform, proven from source and by reprojection
-----------------------------------------------------
Source (Fast-SAM3D, ``notebook/inference.py::make_scene`` ->
``SceneVisualizer.object_pointcloud`` -> ``transforms_3d.compose_transform``):
the Gaussians' ``get_xyz`` (exactly what ``save_ply`` writes as x, y, z) are
moved into the scene with a PyTorch3D ``Transform3d().scale(s).rotate(R)
.translate(t)``, where ``R = quaternion_to_matrix(q)`` (q real-first, wxyz).
PyTorch3D transforms act on ROW vectors, so

    p_p3d = s * (p_ply @ R) + t          (= s * R^T p + t for column vectors)

in the PyTorch3D camera frame (x left, y up, z forward): ``compute_pointmap``
rotates MoGe's OpenCV pointmap into it with ``camera_to_pytorch3d_camera``
(``look_at_view_transform(eye=(0,0,-1), up=(0,-1,0))`` = diag(-1, -1, 1)).
Hence, in the contract's OpenCV camera frame (x right, y down, z forward):

    p_cv = F (s R^T p + t) = s (F R^T) p + F t,   F = diag(-1, -1, 1)

``F R^T`` is a proper rotation (det F = +1), stored as ``rotation_wxyz``.
``scale`` already includes the pose decoder's ``downsample_factor`` (the
worker multiplies it in, like ``InferencePipelinePointMap.run``).
The units are those of SAM 3D's (MoGe-1, scale-ambiguous) pointmap; they are
re-based onto the metric scene camera (MoGe-2, gpu-scene) by
``rebase_similarity``. ``reprojection_iou`` checks the result: the PLY's
Gaussian centres, transformed and projected with the camera intrinsics, must
cover the object's mask.

What pose.json v2 publishes
---------------------------
SAM 3D's pose is coarse (IoU ~0.5 on real photos; a TV remote came out at a
quarter of its size, IoU 0.05), so the published ``splat_to_cam`` is
``refine_pose``'s registration of the splat to the scene's metric pointmap
(the geometry of scene.json/scene.ply) inside the mask, a similarity

    p_cam = scale * R(rotation_wxyz) @ p_ply + translation

from the stored reconstruction.ply's vertex coordinates straight into the
scene.json camera frame (OpenCV axes, metres, scene.json intrinsics). It is
published only when its reprojection IoU >= ``VERIFIED_IOU`` and its depth
residual <= ``MAX_VERIFIED_DEPTH_RESIDUAL``; else null (consumers place the
object upright). SAM 3D's PLY frame is z-up (``PLY_UP``).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

POSE_KEYS = ("rotation", "translation", "scale", "downsample_factor")
FLOOR_PERCENTILES = (1, 2, 5, 50, 95, 98, 99)
# PyTorch3D camera (x left, y up, z fwd) <-> OpenCV camera (x right, y down, z fwd).
P3D_TO_CV = np.diag([-1.0, -1.0, 1.0])
MIN_OPACITY = 0.1  # Gaussians fainter than this do not count toward the silhouette
VERIFIED_IOU = 0.6  # splat_to_cam is published only when reprojection reaches this
MAX_VERIFIED_DEPTH_RESIDUAL = 0.15  # ... and the placed splat's depth agrees with the scene within 15 %


def _to_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().float().cpu().numpy()
    return np.asarray(value, dtype=np.float64)


# ---------------------------------------------------------------------------
# v1: the raw pose-decoder record (kept verbatim as v2's "raw")
# ---------------------------------------------------------------------------

def pose_record(ss_return: Mapping[str, Any], pointmap: Any = None, *, image_size: tuple[int, int] | None = None) -> dict:
    """JSON-safe pose (+ floor statistics) from the pose decoder's output."""
    record: dict[str, Any] = {"version": 1, "camera_convention": "sam3d-pointmap", "ss_keys": sorted(ss_return)}
    for key in POSE_KEYS:
        if key in ss_return and ss_return[key] is not None:
            array = _to_numpy(ss_return[key])
            record[key] = [round(float(v), 6) for v in array.reshape(-1)]
            record[f"{key}_shape"] = list(array.shape)
    if image_size:
        record["image_size"] = [int(image_size[0]), int(image_size[1])]
    if pointmap is not None:
        record["pointmap"] = pointmap_stats(pointmap)
    return record


def pointmap_stats(pointmap: Any) -> dict:
    """Per-axis percentiles of the valid camera-frame points. The floor is
    the extreme percentile on the vertical axis (sign depends on the frame)."""
    points = _hwc(pointmap).reshape(-1, 3)
    points = points[np.all(np.isfinite(points), axis=1)]
    if not len(points):
        return {"valid_points": 0}
    return {
        "valid_points": int(len(points)),
        "percentiles": {
            axis: {str(p): round(float(np.percentile(points[:, i], p)), 6) for p in FLOOR_PERCENTILES}
            for i, axis in enumerate("xyz")
        },
    }


def write_pose(path: Path, ss_return: Mapping[str, Any], pointmap: Any = None, *, image_size=None) -> Path:
    path.write_text(json.dumps(pose_record(ss_return, pointmap, image_size=image_size), indent=1))
    return path


# ---------------------------------------------------------------------------
# Rotations and similarities
# ---------------------------------------------------------------------------

def quat_wxyz_to_matrix(q: Sequence[float]) -> np.ndarray:
    """Same as pytorch3d.transforms.quaternion_to_matrix (real part first)."""
    w, x, y, z = np.asarray(q, dtype=np.float64).reshape(4) / np.linalg.norm(q)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def matrix_to_quat_wxyz(matrix: np.ndarray) -> list[float]:
    """Unit quaternion (w >= 0) of a proper rotation matrix."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    q = np.asarray(q)
    q /= np.linalg.norm(q)
    if q[0] < 0:
        q = -q
    return [float(v) for v in q]


def sam3d_splat_to_cam(rotation_wxyz: Sequence[float], translation: Sequence[float], scale: Any) -> dict:
    """The pose decoder's (q, t, s) as a similarity PLY -> OpenCV camera
    frame (SAM 3D pointmap units). ``scale`` must already include
    ``downsample_factor``; SAM 3D's scale is isotropic (asserted in make_scene)."""
    rot = quat_wxyz_to_matrix(np.asarray(rotation_wxyz, dtype=np.float64).reshape(-1)[:4])
    s = float(np.mean(np.asarray(scale, dtype=np.float64).reshape(-1)))
    t = np.asarray(translation, dtype=np.float64).reshape(-1)[:3]
    return {
        "rotation_wxyz": matrix_to_quat_wxyz(P3D_TO_CV @ rot.T),
        "translation": [float(v) for v in P3D_TO_CV @ t],
        "scale": s,
    }


def similarity_matrix(sim: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, float]:
    return quat_wxyz_to_matrix(sim["rotation_wxyz"]), np.asarray(sim["translation"], dtype=np.float64), float(sim["scale"])


def apply_similarity(points: np.ndarray, sim: Mapping[str, Any]) -> np.ndarray:
    rot, t, s = similarity_matrix(sim)
    return s * (np.asarray(points, dtype=np.float64) @ rot.T) + t


def round_similarity(sim: Mapping[str, Any], digits: int = 6) -> dict:
    return {
        "rotation_wxyz": [round(float(v), digits) for v in sim["rotation_wxyz"]],
        "translation": [round(float(v), digits) for v in sim["translation"]],
        "scale": round(float(sim["scale"]), digits),
    }


# ---------------------------------------------------------------------------
# Pointmaps, intrinsics, projection
# ---------------------------------------------------------------------------

def _hwc(pointmap: Any) -> np.ndarray:
    points = _to_numpy(pointmap)
    if points.ndim == 4:  # batch
        points = points[0]
    if points.shape[0] == 3 and points.shape[-1] != 3:  # (3, H, W) -> (H, W, 3)
        points = np.moveaxis(points, 0, -1)
    return points


def p3d_pointmap_to_cv(pointmap: Any) -> np.ndarray:
    """SAM 3D's pointmap ((3,H,W) or (H,W,3), PyTorch3D camera) -> (H,W,3) OpenCV."""
    return _hwc(pointmap) @ P3D_TO_CV


def intrinsics_from_pointmap(pointmap_cv: np.ndarray, image_size: tuple[int, int] | None = None) -> dict:
    """Pinhole intrinsics that reproduce a camera-frame pointmap (least
    squares of u = fx x/z + cx, v = fy y/z + cy over valid pixels, pixel
    centres at +0.5). Expressed for ``image_size`` (W, H) when given."""
    pm = np.asarray(pointmap_cv, dtype=np.float64)
    h, w = pm.shape[:2]
    v, u = np.mgrid[0:h, 0:w].astype(np.float64) + 0.5
    ok = np.all(np.isfinite(pm), axis=-1) & (pm[..., 2] > 1e-6)
    if ok.sum() < 16:
        raise ValueError("pointmap has too few valid points")
    x = pm[..., 0][ok] / pm[..., 2][ok]
    y = pm[..., 1][ok] / pm[..., 2][ok]
    fx, cx = np.linalg.lstsq(np.stack([x, np.ones_like(x)], 1), u[ok], rcond=None)[0]
    fy, cy = np.linalg.lstsq(np.stack([y, np.ones_like(y)], 1), v[ok], rcond=None)[0]
    k = {"fx": float(fx), "fy": float(fy), "cx": float(cx), "cy": float(cy)}
    return scale_intrinsics(k, (w, h), image_size) if image_size else k


def scale_intrinsics(k: Mapping[str, float], from_size: tuple[int, int], to_size: tuple[int, int]) -> dict:
    sx, sy = to_size[0] / from_size[0], to_size[1] / from_size[1]
    return {"fx": k["fx"] * sx, "fy": k["fy"] * sy, "cx": k["cx"] * sx, "cy": k["cy"] * sy}


def _dilate(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    out = mask.copy()
    padded = np.pad(mask, radius)
    h, w = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            out |= padded[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
    return out


def project_silhouette(points_cam: np.ndarray, k: Mapping[str, float], size: tuple[int, int], *, close: int = 1) -> np.ndarray:
    """Boolean (H, W) image of the pixels hit by camera-frame points, with a
    small morphological closing to fill gaps between Gaussian centres."""
    w, h = int(size[0]), int(size[1])
    pts = np.asarray(points_cam, dtype=np.float64)
    pts = pts[np.all(np.isfinite(pts), axis=1) & (pts[:, 2] > 1e-6)]
    sil = np.zeros((h, w), dtype=bool)
    if len(pts):
        u = np.floor(k["fx"] * pts[:, 0] / pts[:, 2] + k["cx"]).astype(np.int64)
        v = np.floor(k["fy"] * pts[:, 1] / pts[:, 2] + k["cy"]).astype(np.int64)
        inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
        sil[v[inside], u[inside]] = True
    if close > 0:
        sil = ~_dilate(~_dilate(sil, close), close)
    return sil


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def resize_mask_nearest(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    h, w = mask.shape
    tw, th = int(size[0]), int(size[1])
    if (tw, th) == (w, h):
        return mask.astype(bool)
    rows = np.minimum(((np.arange(th) + 0.5) * h / th).astype(np.int64), h - 1)
    cols = np.minimum(((np.arange(tw) + 0.5) * w / tw).astype(np.int64), w - 1)
    return mask[rows][:, cols].astype(bool)


def reprojection_iou(points_ply: np.ndarray, sim: Mapping[str, Any], k: Mapping[str, float],
                     mask: np.ndarray, *, max_side: int = 512) -> float:
    """Mask IoU of the transformed, projected PLY centres. ``k`` is for the
    mask's resolution; both are evaluated at <= ``max_side`` pixels (so the
    gap-filling closing is resolution independent)."""
    h, w = mask.shape
    f = min(1.0, max_side / max(h, w))
    size = (max(1, round(w * f)), max(1, round(h * f)))
    kk = scale_intrinsics(k, (w, h), size)
    sil = project_silhouette(apply_similarity(points_ply, sim), kk, size)
    return mask_iou(sil, resize_mask_nearest(mask, size))


# ---------------------------------------------------------------------------
# Metric re-basing onto the scene camera (gpu-scene, MoGe-2)
# ---------------------------------------------------------------------------

def _sample_at_mask(pointmap_cv: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(N, 3) pointmap values at the mask's pixels (pointmap resampled to the
    mask's resolution by nearest neighbour), finite and in front of the camera."""
    pm = np.asarray(pointmap_cv, dtype=np.float64)
    ph, pw = pm.shape[:2]
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    py = np.minimum(((ys + 0.5) * ph / h).astype(np.int64), ph - 1)
    px = np.minimum(((xs + 0.5) * pw / w).astype(np.int64), pw - 1)
    return pm[py, px]


def depth_ratio(source_pm_cv: np.ndarray, target_pm_cv: np.ndarray, mask: np.ndarray) -> float | None:
    """Robust (median) per-pixel ratio target depth / source depth inside the
    mask (eroded when it is large, to avoid edge bleeding)."""
    core = mask
    if mask.sum() > 400:
        eroded = ~_dilate(~mask, 2)
        if eroded.sum() > 100:
            core = eroded
    a = _sample_at_mask(source_pm_cv, core)[:, 2]
    b = _sample_at_mask(target_pm_cv, core)[:, 2]
    ok = np.isfinite(a) & np.isfinite(b) & (a > 1e-6) & (b > 1e-6)
    if ok.sum() < 10:
        return None
    return float(np.median(b[ok] / a[ok]))


def _focal(k: Mapping[str, float]) -> float:
    return math.sqrt(k["fx"] * k["fy"])


def rebase_similarity(sim: Mapping[str, Any], points_ply: np.ndarray, source_k: Mapping[str, float],
                      target_k: Mapping[str, float], depth_scale: float) -> dict:
    """Move a PLY -> camera similarity from SAM 3D's camera (``source_k``,
    arbitrary units) onto the scene camera (``target_k``, metric), keeping the
    object where it is in the photo: its centre projects to the same pixel,
    at ``depth_scale`` x its depth, and its size is scaled so its image
    footprint is preserved under the new focal length. Both intrinsics are
    for the same image size. Rotation is kept."""
    rot, t, s = similarity_matrix(sim)
    centre_local = np.median(np.asarray(points_ply, dtype=np.float64), axis=0)
    c = s * rot @ centre_local + t
    u = source_k["fx"] * c[0] / c[2] + source_k["cx"]
    v = source_k["fy"] * c[1] / c[2] + source_k["cy"]
    z = depth_scale * c[2]
    c2 = np.array([(u - target_k["cx"]) / target_k["fx"] * z, (v - target_k["cy"]) / target_k["fy"] * z, z])
    s2 = s * depth_scale * _focal(source_k) / _focal(target_k)
    t2 = c2 - s2 * rot @ centre_local
    return {"rotation_wxyz": list(sim["rotation_wxyz"]), "translation": [float(x) for x in t2], "scale": float(s2)}


# ---------------------------------------------------------------------------
# Refinement against the scene's metric pointmap
# ---------------------------------------------------------------------------
# SAM 3D's pose is coarse (reprojection IoU ~0.5 on real photos, and
# sometimes wrong outright), and it lives in SAM 3D's own camera. The
# refinement registers the splat to the scene's metric pointmap (gpu-scene,
# the same geometry as scene.json/scene.ply) inside the object's mask:
# trimmed, symmetric ICP between the splat's camera-facing Gaussians and the
# masked pointmap points, solving a similarity (Umeyama) straight from PLY
# coordinates into the scene camera frame. It starts from several
# hypotheses (SAM 3D's pose re-based, and principal-axis alignments) and
# keeps the one whose silhouette best matches the mask, penalised by its
# depth residual. numpy only; ~1-3 s per object.

REFINE_MAX_SIDE = 320        # working resolution for correspondences/visibility
REFINE_TARGET_POINTS = 3000  # masked pointmap points used as ICP targets (fine stage)
REFINE_SOURCE_POINTS = 4000  # splat centres used as ICP sources (fine stage)
COARSE_TARGET_POINTS = 1500  # hypothesis screening uses fewer points
COARSE_SOURCE_POINTS = 2000
COARSE_ITERS = 15
REFINE_ITERS = 20
REFINE_TRIM = 0.85           # fraction of correspondences kept per iteration
DEPTH_PENALTY = 1.0          # score = IoU - DEPTH_PENALTY * relative depth residual
PRIOR_MARGIN = 0.03          # an alternative hypothesis must beat SAM 3D's rotation by this score
TILT_PENALTY = 0.5           # score -= TILT_PENALTY * (1 - cos(tilt of the PLY's up axis from gravity))
# SAM 3D's canonical object frame is z-up: on every real job measured (cats
# photo: blanket, cat, remote; eye-level room: microwave, sofa) the decoded
# pose maps PLY +z to within 16 deg of the photo's gravity up.
PLY_UP = np.array([0.0, 0.0, 1.0])
POLISH_FACTORS = (0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3)


def umeyama(src: np.ndarray, dst: np.ndarray, *, with_scale: bool = True,
            symmetric_scale: bool = False) -> tuple[float, np.ndarray, np.ndarray]:
    """Least-squares similarity with dst ~= s R src + t (Umeyama 1991).
    ``symmetric_scale`` uses Horn's symmetric scale sqrt(var dst / var src)
    instead, which does not shrink under noisy correspondences (ICP)."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    u, d, vt = np.linalg.svd(xd.T @ xs / len(src))
    sign = np.ones(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[2] = -1.0
    rot = u @ np.diag(sign) @ vt
    var_s = float((xs ** 2).sum(1).mean())
    if not with_scale or var_s <= 0:
        s = 1.0
    elif symmetric_scale:
        s = math.sqrt(float((xd ** 2).sum(1).mean()) / var_s)
    else:
        s = float((d * sign).sum() / var_s)
    return s, rot, mu_d - s * rot @ mu_s


def make_similarity(rot: np.ndarray, translation: Sequence[float], scale: float) -> dict:
    return {"rotation_wxyz": matrix_to_quat_wxyz(rot), "translation": [float(v) for v in translation], "scale": float(scale)}


def nearest(a: np.ndarray, b: np.ndarray, chunk: int = 2048) -> tuple[np.ndarray, np.ndarray]:
    """Index and squared distance of the nearest ``b`` point to each ``a`` point (brute force)."""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    bb = (b * b).sum(1)
    idx = np.empty(len(a), dtype=np.int64)
    d2 = np.empty(len(a))
    for i in range(0, len(a), chunk):
        blk = a[i:i + chunk]
        dist = (blk * blk).sum(1)[:, None] + bb[None, :] - 2.0 * (blk @ b.T)
        j = dist.argmin(1)
        idx[i:i + chunk] = j
        d2[i:i + chunk] = np.maximum(dist[np.arange(len(blk)), j].astype(np.float64), 0.0)
    return idx, d2


def _pixels(points_cam: np.ndarray, k: Mapping[str, float]) -> tuple[np.ndarray, np.ndarray]:
    z = points_cam[:, 2]
    return k["fx"] * points_cam[:, 0] / z + k["cx"], k["fy"] * points_cam[:, 1] / z + k["cy"]


def front_points(points_cam: np.ndarray, k: Mapping[str, float], *, cell_px: float, tol: float) -> np.ndarray:
    """Which points are on the camera-facing surface: within ``tol`` of the
    nearest point projecting into the same ``cell_px`` x ``cell_px`` cell."""
    pts = np.asarray(points_cam, dtype=np.float64)
    ok = np.all(np.isfinite(pts), axis=1) & (pts[:, 2] > 1e-6)
    out = np.zeros(len(pts), dtype=bool)
    if not ok.any():
        return out
    p = pts[ok]
    u, v = _pixels(p, k)
    cu = np.clip(np.floor(u / cell_px), -2**20, 2**20).astype(np.int64)
    cv = np.clip(np.floor(v / cell_px), -2**20, 2**20).astype(np.int64)
    _, inv = np.unique((cu + 2**20) * 2**21 + (cv + 2**20), return_inverse=True)
    inv = inv.reshape(-1)
    zmin = np.full(int(inv.max()) + 1, np.inf)
    np.minimum.at(zmin, inv, p[:, 2])
    out[np.flatnonzero(ok)] = p[:, 2] <= zmin[inv] + tol
    return out


def resample_nearest(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """(H, W, ...) array resampled to ``size`` (W, H) by nearest neighbour (pixel centres)."""
    arr = np.asarray(image)
    h, w = arr.shape[:2]
    tw, th = int(size[0]), int(size[1])
    if (tw, th) == (w, h):
        return arr
    rows = np.minimum(((np.arange(th) + 0.5) * h / th).astype(np.int64), h - 1)
    cols = np.minimum(((np.arange(tw) + 0.5) * w / tw).astype(np.int64), w - 1)
    return arr[rows][:, cols]


def _erode(mask: np.ndarray, radius: int = 1) -> np.ndarray:
    return ~_dilate(~mask, radius)


def _subsample(n: int, count: int, seed: int = 0) -> np.ndarray:
    if n <= count:
        return np.arange(n)
    return np.sort(np.random.default_rng(seed).choice(n, count, replace=False))


def _diag(points: np.ndarray) -> float:
    lo, hi = np.percentile(points, 2, axis=0), np.percentile(points, 98, axis=0)
    return float(np.linalg.norm(hi - lo)) or 1.0


class RefineView:
    """The object's mask and the metric pointmap at the working resolution."""

    def __init__(self, mask: np.ndarray, target_pm: np.ndarray, k: Mapping[str, float], *,
                 max_side: int = REFINE_MAX_SIDE, n_targets: int = REFINE_TARGET_POINTS):
        mask = np.asarray(mask, dtype=bool)
        h, w = mask.shape
        f = min(1.0, max_side / max(h, w))
        self.size = (max(1, round(w * f)), max(1, round(h * f)))
        self.k = scale_intrinsics(k, (w, h), self.size)
        self.full_mask, self.full_k = mask, dict(k)
        self.mask = resize_mask_nearest(mask, self.size)
        self.pm = resample_nearest(np.asarray(target_pm, dtype=np.float64), self.size)
        valid = np.all(np.isfinite(self.pm), axis=-1) & (self.pm[..., 2] > 1e-6)
        core = self.mask & valid
        eroded = _erode(self.mask, 1) & valid
        if eroded.sum() >= max(30, 0.4 * core.sum()):
            core = eroded
        self.valid = valid
        pts = self.pm[core]
        self.targets = pts[_subsample(len(pts), n_targets)]

    def ok(self) -> bool:
        return len(self.targets) >= 30


def _cell_px(points_cam: np.ndarray, k: Mapping[str, float], size: tuple[int, int], per_cell: float = 8.0) -> float:
    u, v = _pixels(points_cam, k)
    fin = np.isfinite(u) & np.isfinite(v)
    if fin.sum() < 10:
        return 2.0
    u = np.clip(u[fin], -size[0], 2 * size[0])
    v = np.clip(v[fin], -size[1], 2 * size[1])
    area = max(1.0, (np.percentile(u, 98) - np.percentile(u, 2)) * (np.percentile(v, 98) - np.percentile(v, 2)))
    return float(np.clip(math.sqrt(area * per_cell / len(points_cam)), 1.0, 16.0))


def icp_similarity(points_ply: np.ndarray, sim0: Mapping[str, Any], view: RefineView, *,
                   iters: int = REFINE_ITERS, trim: float = REFINE_TRIM, with_scale: bool = True) -> dict:
    """Trimmed symmetric ICP (camera-facing splat centres <-> masked metric
    pointmap points) solving a similarity from PLY coordinates to the camera."""
    x = np.asarray(points_ply, dtype=np.float64)
    rot, t, s = similarity_matrix(sim0)
    tgt = view.targets
    diag = _diag(x)
    for _ in range(iters):
        y = s * (x @ rot.T) + t
        vis = front_points(y, view.k, cell_px=_cell_px(y, view.k, view.size), tol=0.04 * s * diag)
        if vis.sum() < 20:
            break
        xv, yv = x[vis], y[vis]
        i_f, d_f = nearest(yv, tgt)
        i_b, d_b = nearest(tgt, yv)
        src = np.concatenate([xv, xv[i_b]])
        dst = np.concatenate([tgt[i_f], tgt])
        d = np.concatenate([d_f, d_b])
        keep = d <= np.quantile(d, trim)
        if keep.sum() < 10:
            break
        s_new, rot_new, t_new = umeyama(src[keep], dst[keep], with_scale=with_scale, symmetric_scale=True)
        if not (np.isfinite(s_new) and s_new > 0):
            break
        s_new = float(np.clip(s_new, 0.8 * s, 1.25 * s))
        t_new = dst[keep].mean(0) - s_new * rot_new @ src[keep].mean(0)
        moved = np.sqrt(np.mean(((s_new * (xv @ rot_new.T) + t_new) - yv) ** 2))
        rot, t, s = rot_new, t_new, s_new
        if moved < 1e-4 * s * diag:
            break
    return make_similarity(rot, t, s)


def depth_residual(points_ply: np.ndarray, sim: Mapping[str, Any], view: RefineView) -> float | None:
    """Median |rendered depth - pointmap depth| / median depth over the mask
    pixels the transformed splat covers (front-most centre per pixel)."""
    y = apply_similarity(points_ply, sim)
    y = y[np.all(np.isfinite(y), axis=1) & (y[:, 2] > 1e-6)]
    if not len(y):
        return None
    u, v = _pixels(y, view.k)
    u, v = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    w, h = view.size
    inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    if not inside.any():
        return None
    zbuf = np.full(h * w, np.inf)
    np.minimum.at(zbuf, v[inside] * w + u[inside], y[inside, 2])
    zbuf = zbuf.reshape(h, w)
    both = view.mask & view.valid & np.isfinite(zbuf)
    if both.sum() < 10:
        return None
    zt = view.pm[..., 2][both]
    return float(np.median(np.abs(zbuf[both] - zt)) / np.median(zt))


def _pca(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    centre = points.mean(0)
    _, sv, vt = np.linalg.svd(points - centre, full_matrices=False)
    return centre, vt.T, sv / math.sqrt(len(points))


def _seat(points_ply: np.ndarray, rot: np.ndarray, s: float, view: RefineView) -> dict:
    """Place (rot, s) so the splat's camera-facing surface centroid lands on
    the masked pointmap's centroid."""
    tgt_c = view.targets.mean(0)
    t = tgt_c - s * rot @ points_ply.mean(0)
    y = s * (points_ply @ rot.T) + t
    vis = front_points(y, view.k, cell_px=_cell_px(y, view.k, view.size), tol=0.04 * s * _diag(points_ply))
    if vis.sum() >= 10:
        t = t + tgt_c - y[vis].mean(0)
    return make_similarity(rot, t, s)


def axis_angle_matrix(axis: Sequence[float], angle: float) -> np.ndarray:
    a = np.asarray(axis, dtype=np.float64)
    a = a / np.linalg.norm(a)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def rotation_between(a: Sequence[float], b: Sequence[float]) -> np.ndarray:
    """Smallest rotation taking direction ``a`` to direction ``b``."""
    a = np.asarray(a, dtype=np.float64) / np.linalg.norm(a)
    b = np.asarray(b, dtype=np.float64) / np.linalg.norm(b)
    axis, c = np.cross(a, b), float(a @ b)
    if np.linalg.norm(axis) < 1e-9:
        if c > 0:
            return np.eye(3)
        perp = np.cross(a, [1.0, 0.0, 0.0] if abs(a[0]) < 0.9 else [0.0, 1.0, 0.0])
        return axis_angle_matrix(perp, math.pi)
    return axis_angle_matrix(axis, math.atan2(np.linalg.norm(axis), c))


def up_alignment(sim: Mapping[str, Any], up: Sequence[float] | None) -> float | None:
    """cos of the angle between the PLY's up axis (as placed) and gravity up."""
    if up is None:
        return None
    u = np.asarray(up, dtype=np.float64)
    return float(quat_wxyz_to_matrix(sim["rotation_wxyz"]) @ PLY_UP @ (u / np.linalg.norm(u)))


def _major_axis(points: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """Principal direction of ``points`` within the plane perpendicular to ``normal``."""
    p = points - points.mean(0)
    p = p - np.outer(p @ normal, normal)
    _, _, vt = np.linalg.svd(p, full_matrices=False)
    axis = vt[0] - (vt[0] @ normal) * normal
    return axis / (np.linalg.norm(axis) or 1.0)


def pose_hypotheses(points_ply: np.ndarray, view: RefineView, prior: Mapping[str, Any] | None = None,
                    up: Sequence[float] | None = None) -> list[tuple[str, dict]]:
    """Initial similarities: the prior (SAM 3D's pose re-based) and its
    rotation re-seated at the pointmap's scale; then, with gravity ``up``,
    four upright yaw hypotheses (the PLY's z axis on gravity, its horizontal
    principal axis on the masked pointmap's, +0/90/180/270 deg), else the four
    proper principal-axis alignments of the splat onto the masked pointmap."""
    x = np.asarray(points_ply, dtype=np.float64)
    c_x, v_x, sd_x = _pca(x)
    c_t, v_t, sd_t = _pca(view.targets)
    s_pca = math.sqrt(max(sd_t[0] * sd_t[1], 1e-12) / max(sd_x[0] * sd_x[1], 1e-12))
    out: list[tuple[str, dict]] = []
    if prior is not None:
        out.append(("prior", dict(prior)))
        rot_p, _, s_p = similarity_matrix(prior)
        out.append(("prior_rot_reseated", _seat(x, rot_p, s_pca, view)))
    if up is not None:
        u = np.asarray(up, dtype=np.float64) / np.linalg.norm(up)
        r_up = rotation_between(PLY_UP, u)
        a_ply = r_up @ _major_axis(x, PLY_UP)
        a_tgt = _major_axis(view.targets, u)
        yaw0 = math.atan2(float(np.cross(a_ply, a_tgt) @ u), float(a_ply @ a_tgt))
        for deg in (0, 90, 180, 270):
            rot = axis_angle_matrix(u, yaw0 + math.radians(deg)) @ r_up
            out.append((f"yaw{deg}", _seat(x, rot, s_pca, view)))
        return out
    for signs in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1), (1, 1, -1), (1, -1, 1), (-1, 1, 1), (-1, -1, -1)):
        rot = v_t @ np.diag(signs) @ v_x.T
        if np.linalg.det(rot) > 0:
            out.append((f"pca{''.join('+' if v > 0 else '-' for v in signs)}", _seat(x, rot, s_pca, view)))
    return out


def _score(iou: float, res: float | None, cos_up: float | None = None) -> float:
    tilt = 0.0 if cos_up is None else TILT_PENALTY * (1.0 - cos_up)
    return iou - DEPTH_PENALTY * (0.5 if res is None else min(res, 0.5)) - tilt


def polish_scale(points_ply: np.ndarray, points_all: np.ndarray, sim: Mapping[str, Any], view: RefineView,
                 factors: Sequence[float] = POLISH_FACTORS) -> tuple[dict, float, float | None, float]:
    """Rescale the placed splat about its camera-facing surface centroid (so
    that surface stays on the pointmap) by the factor with the best
    silhouette/depth score; ICP's trimmed matching tends to shrink objects.
    Returns (sim, iou, depth residual, factor)."""
    rot, t, s = similarity_matrix(sim)
    x = np.asarray(points_ply, dtype=np.float64)
    y = s * (x @ rot.T) + t
    vis = front_points(y, view.k, cell_px=_cell_px(y, view.k, view.size), tol=0.04 * s * _diag(x))
    anchor = y[vis].mean(0) if vis.sum() >= 10 else y.mean(0)
    best = None
    for f in factors:
        cand = make_similarity(rot, f * t + (1.0 - f) * anchor, f * s)
        iou = reprojection_iou(points_all, cand, view.full_k, view.full_mask)
        res = depth_residual(x, cand, view)
        if best is None or _score(iou, res) > _score(best[1], best[2]):
            best = (cand, iou, res, float(f))
    return best


def refine_pose(points_ply: np.ndarray, mask: np.ndarray, target_pm: np.ndarray, k: Mapping[str, float], *,
                prior: Mapping[str, Any] | None = None, up: Sequence[float] | None = None) -> tuple[dict | None, dict]:
    """Best similarity PLY -> metric camera frame for one object, and a report.

    Coarse stage: every hypothesis (``pose_hypotheses``) runs a short ICP on
    few points and is scored by silhouette IoU minus depth residual. Fine
    stage: the best SAM 3D-rotation hypothesis and the best principal-axis
    hypothesis each run a longer ICP on more points plus ``polish_scale``; the
    principal-axis one wins only by ``PRIOR_MARGIN`` (SAM 3D knows which way
    is up; silhouettes do not). With gravity ``up`` (camera frame) the
    alternatives are upright yaw hypotheses and every score is penalised by
    the tilt of the PLY's up axis. ``mask`` (H, W) and ``k`` are for the full
    photo; ``target_pm`` is the scene's metric pointmap (any resolution, same
    camera). Returns (None, report) when the mask has no valid depth."""
    x_all = np.asarray(points_ply, dtype=np.float64)
    x_all = x_all[np.all(np.isfinite(x_all), axis=1)]
    x_coarse = x_all[_subsample(len(x_all), COARSE_SOURCE_POINTS)]
    x_fine = x_all[_subsample(len(x_all), REFINE_SOURCE_POINTS, seed=1)]
    coarse = RefineView(mask, target_pm, k, n_targets=COARSE_TARGET_POINTS)
    report: dict[str, Any] = {"targets": int(len(coarse.targets)), "sources": int(len(x_coarse)), "hypotheses": []}
    if not coarse.ok() or len(x_coarse) < 30:
        report["error"] = "too few valid points"
        return None, report
    fine = RefineView(mask, target_pm, k, n_targets=REFINE_TARGET_POINTS)
    families: dict[str, tuple] = {}
    for name, sim0 in pose_hypotheses(x_coarse, coarse, prior, up):
        sim = icp_similarity(x_coarse, sim0, coarse, iters=COARSE_ITERS)
        iou = reprojection_iou(x_all, sim, k, mask)
        res = depth_residual(x_coarse, sim, coarse)
        cos_up = up_alignment(sim, up)
        score = _score(iou, res, cos_up)
        report["hypotheses"].append({"name": name, "iou_init": round(reprojection_iou(x_all, sim0, k, mask), 4),
                                     "iou": round(iou, 4), "depth_residual": None if res is None else round(res, 4),
                                     "up_cos": None if cos_up is None else round(cos_up, 3), "score": round(score, 4)})
        family = "prior" if name.startswith("prior") else "alt"
        if family not in families or score > families[family][0]:
            families[family] = (score, name, sim)
    finals = {}
    for family, (_, name, sim) in families.items():
        sim = icp_similarity(x_fine, sim, fine, iters=REFINE_ITERS)
        sim, iou, res, factor = polish_scale(x_fine, x_all, sim, fine)
        cos_up = up_alignment(sim, up)
        finals[family] = (_score(iou, res, cos_up), name, sim, iou, res, factor)
        report[f"final_{family}"] = {"name": name, "iou": round(iou, 4), "scale_factor": factor,
                                     "depth_residual": None if res is None else round(res, 4),
                                     "up_cos": None if cos_up is None else round(cos_up, 3)}
    pick = finals.get("prior")
    if pick is None or ("alt" in finals and finals["alt"][0] > pick[0] + PRIOR_MARGIN):
        pick = finals["alt"]
    _, name, sim, iou, res, _ = pick
    cos_up = up_alignment(sim, up)
    report.update({"chosen": name, "iou": round(iou, 4), "depth_residual": None if res is None else round(res, 4),
                   "up_cos": None if cos_up is None else round(cos_up, 3)})
    return sim, report


# ---------------------------------------------------------------------------
# Object geometry (fallback when gpu-scene's /v1/placement is unavailable)
# ---------------------------------------------------------------------------

def mask_bbox_area(mask: np.ndarray) -> tuple[list[int], float]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return [0, 0, 0, 0], 0.0
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], float(mask.mean())


def object_block_from_points(points_cam: np.ndarray, gravity_up_cam: Sequence[float]) -> dict:
    """centroid/base/extent of an object's camera-frame points (e.g. the
    transformed splat), gravity aligned."""
    pts = np.asarray(points_cam, dtype=np.float64)
    pts = pts[np.all(np.isfinite(pts), axis=1)]
    up = np.asarray(gravity_up_cam, dtype=np.float64)
    up = up / np.linalg.norm(up)
    lo, hi = np.percentile(pts, 2, axis=0), np.percentile(pts, 98, axis=0)
    core = pts[np.all((pts >= lo) & (pts <= hi), axis=1)]
    if len(core) < 10:
        core = pts
    centroid = np.median(core, axis=0)
    heights = core @ up
    h_lo, h_hi = np.percentile(heights, 1), np.percentile(heights, 99)
    base = centroid + (h_lo - centroid @ up) * up
    # horizontal axes: camera x projected off gravity, and its complement
    ax = np.array([1.0, 0.0, 0.0]) - up * up[0]
    ax /= np.linalg.norm(ax)
    az = np.cross(ax, up)
    wx = np.percentile(core @ ax, 99) - np.percentile(core @ ax, 1)
    wz = np.percentile(core @ az, 99) - np.percentile(core @ az, 1)
    return {
        "centroid_cam": [round(float(v), 5) for v in centroid],
        "base_cam": [round(float(v), 5) for v in base],
        "extent_m": {"width": round(float(wx), 5), "height": round(float(h_hi - h_lo), 5), "depth": round(float(wz), 5)},
    }


def gravity_from_pointmap_fallback() -> list[float]:
    """Without scene geometry: assume a level camera (OpenCV up = -y)."""
    return [0.0, -1.0, 0.0]


# ---------------------------------------------------------------------------
# pose.json v2
# ---------------------------------------------------------------------------

def pose_record_v2(*, raw: Mapping[str, Any], image_size: tuple[int, int], intrinsics: Mapping[str, float],
                   mask: np.ndarray, splat_to_cam: Mapping[str, Any] | None, reprojection_iou: float | None,
                   placement: Mapping[str, Any] | None = None, points_cam: np.ndarray | None = None,
                   metric: bool = False, extra: Mapping[str, Any] | None = None,
                   depth_residual: float | None = None) -> dict:
    """Assemble the contract's pose.json v2.

    ``placement``: gpu-scene /v1/placement response (intrinsics, gravity,
    support plane, object block) for the same photo; its values win. Without
    it, the object block is derived from ``points_cam`` (the transformed
    splat) and gravity defaults to a level camera; ``metric`` then says whether
    the units are metres. ``splat_to_cam`` is dropped (null) unless the
    reprojection IoU reached ``VERIFIED_IOU`` and the relative depth residual
    against the scene (when measured) is within ``MAX_VERIFIED_DEPTH_RESIDUAL``."""
    placement = dict(placement or {})
    bbox, area = mask_bbox_area(mask)
    obj: dict[str, Any] = {"mask_bbox": bbox, "mask_area_frac": round(area, 6)}
    gravity = placement.get("gravity_up_cam") or gravity_from_pointmap_fallback()
    if points_cam is not None and len(points_cam):
        obj.update(object_block_from_points(points_cam, gravity))
        obj["yaw_deg"] = None
    placed_obj = placement.get("object")
    if isinstance(placed_obj, Mapping):
        obj.update({k: v for k, v in placed_obj.items() if v is not None or k not in obj})
    verified = (splat_to_cam is not None and reprojection_iou is not None and reprojection_iou >= VERIFIED_IOU
                and (depth_residual is None or depth_residual <= MAX_VERIFIED_DEPTH_RESIDUAL))
    obj["splat_to_cam"] = round_similarity(splat_to_cam) if verified else None
    obj["reprojection_iou"] = None if reprojection_iou is None else round(float(reprojection_iou), 4)
    record: dict[str, Any] = {
        "version": 2,
        "frame": "opencv",
        "image_size": [int(image_size[0]), int(image_size[1])],
        "intrinsics": {k: round(float(v), 4) for k, v in (placement.get("intrinsics") or intrinsics).items()},
        "gravity_up_cam": [round(float(v), 6) for v in gravity],
        "support_plane": placement.get("support_plane"),
        "metric": bool(placement) or metric,
        "object": obj,
        "raw": dict(raw),
    }
    if extra:
        record.update(extra)
    return record
