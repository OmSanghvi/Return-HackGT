"""Whole-photo scene capture on the GPU host (docs/IMMERSIVE_SCENE_PIPELINE.md 1a/1b).

One photo becomes:

- **geometry** (MoGe-2, ``Ruicheng/moge-2-vitl-normal``): a metric pointmap in
  the OpenCV camera frame (x right, y down, z forward, metres), the camera
  intrinsics, per-pixel normals;
- **gravity** ("up" in the camera frame): GeoCalib's gravity (when installed)
  as a prior, refined on MoGe-2's normals (mean shift toward the dominant
  horizontal-surface direction), then snapped to the floor's plane normal
  when the support is a floor;
- **support plane**: the lowest substantial plane perpendicular to gravity
  below the camera (area-weighted height histogram of up-facing points).
  ``kind`` is ``floor`` when the camera is 0.9-2.3 m above it, else
  ``surface``. Plane equation: ``normal_cam . p + offset = 0`` with
  ``normal_cam`` = up, so ``offset == camera_height`` (> 0);
- **scene splat** (Apple SHARP): 3D Gaussians of the whole photo, predicted
  with MoGe-2's focal length (so both share the intrinsics), scale-aligned to
  MoGe-2's depth (robust median of front-surface depth ratios), pruned to
  <= 600k by screen-space importance, SH degree 0, sRGB colours, written as
  the contract's standard 3DGS PLY;
- **object placement** for a mask (the pose.json v2 ``object`` block without
  ``splat_to_cam``/``reprojection_iou``).

Run modes:

    python scene_capture.py --image photo.jpg --out DIR [--upload-id U --photo KEY]
    python scene_capture.py --serve --port 8004        # warm loopback server

HTTP API (loopback only):

    GET  /health
    POST /v1/scene     {"image_path", "out_dir", "upload_id"?, "photo"?}
         -> {"scene_json": {...}, "scene_ply": "<out_dir>/scene.ply",
             "scene_json_path": "<out_dir>/scene.json", "timings_s": {...}}
    POST /v1/geometry  {"image_path"}
         -> {"image_size", "intrinsics", "gravity_up_cam", "support_plane",
             "pointmap_npy", ...}
    POST /v1/placement {"image_path", "mask_path"}
         -> geometry fields + {"object": {...}}

The pure functions (plane fit, gravity refinement, PLY writer, pruning,
projection, placement) only need numpy and are unit-tested in
test_scene_capture.py; torch and the models are imported lazily.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import math
import os
import struct
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import disk_hygiene  # noqa: E402 - sibling module (stdlib only)

log = logging.getLogger("scene_capture")

SCENE_ROOT = Path(os.environ.get("SKETCHSCAPE_SCENE_ROOT", "/opt/sketchscape/runtime/scene"))
SHARP_CHECKPOINT = Path(os.environ.get("SKETCHSCAPE_SHARP_CHECKPOINT", str(SCENE_ROOT / "models" / "sharp_2572gikvuh.pt")))
MOGE_MODEL = os.environ.get("SKETCHSCAPE_MOGE_MODEL", "Ruicheng/moge-2-vitl-normal")
CACHE_DIR = Path(os.environ.get("SKETCHSCAPE_SCENE_CACHE", "/opt/sketchscape/data/scene-cache"))
# The geometry cache is LRU-evicted (by entry mtime, touched on every hit)
# down to this size after each request; entries in use are never evicted.
CACHE_MAX_GB = float(os.environ.get("SKETCHSCAPE_SCENE_CACHE_MAX_GB", "3"))
VRAM_BUDGET_GB = float(os.environ.get("SKETCHSCAPE_SCENE_VRAM_GB", "12"))
KEEP_RESIDENT = os.environ.get("SKETCHSCAPE_SCENE_RESIDENT", "1") not in ("0", "false", "no")
USE_GEOCALIB = os.environ.get("SKETCHSCAPE_SCENE_GEOCALIB", "1") not in ("0", "false", "no")

MAX_GAUSSIANS = 600_000
MIN_OPACITY = 0.02
GEOMETRY_MAX_SIDE = 1280           # MoGe-2 inference / cached pointmap resolution
DEPTH_GRID_W = 64
FLOOR_HEIGHT_RANGE = (0.9, 2.3)
HORIZONTAL_MAX_DEG = 12.0           # a point is "up-facing" within this of gravity
HEIGHT_BIN_M = 0.02
SUPPORT_MIN_FRACTION = 0.3          # lowest peak with >= this share of the biggest one
FLOOR_SNAP_MAX_DEG = 8.0
MAX_PRIOR_REFINE_DEG = 35.0
CLOSEUP_PITCH_DEG = 50.0            # see classify_support
SH_C0 = 0.28209479177387814
GEOMETRY_VERSION = 2
# Which monocular metric scale the whole photo geometry uses. MoGe-2 and SHARP
# agree on eye-level rooms (ratio 0.9985 on the test room) but not on close-ups:
# on the demo cats photo MoGe-2 is 1.56x larger than SHARP, and known sizes
# side with SHARP (TV remote 0.21 m vs 0.32 m, stretched cat incl. tail
# 0.68 m vs 1.06 m). "sharp": rescale MoGe-2's pointmap to SHARP's scale;
# "moge": keep MoGe-2's; "geomean": halfway (in log).
METRIC_SCALE_SOURCE = os.environ.get("SKETCHSCAPE_SCENE_METRIC", "sharp")
PLY_PROPERTIES = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
                  "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _unit(v: Sequence[float]) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-12:
        raise ValueError("zero-length vector")
    return v / n


def _r(x: float, nd: int = 6) -> float:
    return round(float(x), nd)


def _rl(v, nd: int = 6) -> list:
    return [_r(x, nd) for x in np.asarray(v, dtype=np.float64).reshape(-1)]


def angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    c = float(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))
    return math.degrees(math.acos(c))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------

def intrinsics_dict(fx: float, fy: float, cx: float, cy: float) -> dict:
    """Pixel intrinsics. Convention: the image spans [0, W] x [0, H], so the
    centre of pixel (i, j) is (i + 0.5, j + 0.5)."""
    return {"fx": _r(fx, 4), "fy": _r(fy, 4), "cx": _r(cx, 4), "cy": _r(cy, 4)}


def intrinsics_from_normalized(k_norm: np.ndarray, width: int, height: int) -> dict:
    """MoGe's normalized 3x3 intrinsics (UV in [0, 1]) -> pixel intrinsics."""
    k = np.asarray(k_norm, dtype=np.float64)
    return intrinsics_dict(k[0, 0] * width, k[1, 1] * height, k[0, 2] * width, k[1, 2] * height)


def scale_intrinsics(intr: Mapping[str, float], sx: float, sy: float) -> dict:
    return intrinsics_dict(intr["fx"] * sx, intr["fy"] * sy, intr["cx"] * sx, intr["cy"] * sy)


def project(points: np.ndarray, intr: Mapping[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Camera-frame points (N, 3) -> continuous pixel coords (u, v) and depth z."""
    p = np.asarray(points, dtype=np.float64)
    z = p[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = intr["fx"] * p[:, 0] / z + intr["cx"]
        v = intr["fy"] * p[:, 1] / z + intr["cy"]
    return u, v, z


def unproject(u: np.ndarray, v: np.ndarray, z: np.ndarray, intr: Mapping[str, float]) -> np.ndarray:
    x = (np.asarray(u, dtype=np.float64) - intr["cx"]) / intr["fx"] * z
    y = (np.asarray(v, dtype=np.float64) - intr["cy"]) / intr["fy"] * z
    return np.stack([x, y, np.asarray(z, dtype=np.float64)], axis=-1)


# --------------------------------------------------------------------------
# Planes and gravity
# --------------------------------------------------------------------------

def fit_plane(points: np.ndarray, weights: Optional[np.ndarray] = None) -> tuple[np.ndarray, float]:
    """Weighted least-squares plane: returns (unit normal n, offset d) with
    n . p + d = 0. The normal is oriented toward the camera origin (d > 0)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) < 3:
        raise ValueError("need at least 3 points for a plane")
    w = np.ones(len(p)) if weights is None else np.asarray(weights, dtype=np.float64).reshape(-1)
    w = w / w.sum()
    centre = (p * w[:, None]).sum(axis=0)
    q = (p - centre) * np.sqrt(w)[:, None]
    _, _, vt = np.linalg.svd(q, full_matrices=False)
    n = vt[-1]
    d = -float(n @ centre)
    if d < 0:
        n, d = -n, -d
    return n, d


def ransac_plane(points: np.ndarray, threshold: float = 0.02, iterations: int = 200,
                 normal_hint: Optional[Sequence[float]] = None, max_hint_deg: float = 20.0,
                 seed: int = 0) -> tuple[np.ndarray, float, np.ndarray]:
    """RANSAC + least-squares refit. Returns (normal, offset, inlier mask)."""
    p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if len(p) < 3:
        raise ValueError("need at least 3 points for a plane")
    rng = np.random.default_rng(seed)
    hint = None if normal_hint is None else _unit(normal_hint)
    cos_hint = math.cos(math.radians(max_hint_deg))
    best = None
    best_count = -1
    for _ in range(iterations):
        idx = rng.choice(len(p), 3, replace=False)
        a, b, c = p[idx]
        n = np.cross(b - a, c - a)
        nn = np.linalg.norm(n)
        if nn < 1e-12:
            continue
        n = n / nn
        if hint is not None and abs(float(n @ hint)) < cos_hint:
            continue
        d = -float(n @ a)
        inl = np.abs(p @ n + d) < threshold
        count = int(inl.sum())
        if count > best_count:
            best_count, best = count, inl
    if best is None or best_count < 3:
        best = np.ones(len(p), dtype=bool)
    n, d = fit_plane(p[best])
    inl = np.abs(p @ n + d) < threshold
    if inl.sum() >= 3:
        n, d = fit_plane(p[inl])
        inl = np.abs(p @ n + d) < threshold
    return n, d, inl


def orient_normals_to_camera(points: np.ndarray, normals: np.ndarray) -> np.ndarray:
    """Visible surfaces face the camera: flip normals with n . p > 0."""
    n = np.asarray(normals, dtype=np.float64).copy()
    flip = np.einsum("ij,ij->i", n, np.asarray(points, dtype=np.float64)) > 0
    n[flip] *= -1
    return n


def normals_from_pointmap(pm: np.ndarray) -> np.ndarray:
    """Normals (H, W, 3) from a pointmap via central differences (NaN where
    undefined), oriented toward the camera."""
    pm = np.asarray(pm, dtype=np.float64)
    dx = np.full_like(pm, np.nan)
    dy = np.full_like(pm, np.nan)
    dx[:, 1:-1] = pm[:, 2:] - pm[:, :-2]
    dy[1:-1, :] = pm[2:, :] - pm[:-2, :]
    n = np.cross(dx, dy)
    norm = np.linalg.norm(n, axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        n = n / norm
    flat = n.reshape(-1, 3)
    ok = np.all(np.isfinite(flat), axis=1)
    flat[ok] = orient_normals_to_camera(pm.reshape(-1, 3)[ok], flat[ok])
    return flat.reshape(pm.shape)


def pixel_area_weights(points: np.ndarray, normals: np.ndarray, intr: Mapping[str, float],
                       stride: float = 1.0) -> np.ndarray:
    """Approximate metric surface area each pixel sample covers (m^2)."""
    p = np.asarray(points, dtype=np.float64)
    z = p[:, 2]
    dist = np.linalg.norm(p, axis=1)
    cos = np.abs(np.einsum("ij,ij->i", normals, p)) / np.maximum(dist, 1e-9)
    cos = np.clip(cos, 0.2, 1.0)
    return (z * z) / (intr["fx"] * intr["fy"]) * (stride * stride) / cos


def refine_gravity(normals: np.ndarray, weights: np.ndarray, prior_up: Sequence[float],
                   cones_deg: Sequence[float] = (35.0, 20.0, 10.0, 6.0), iterations: int = 4) -> tuple[np.ndarray, float]:
    """Mean shift on the sphere, from the prior toward the dominant surface
    orientation near it (the horizontal surfaces). Returns (up, support
    weight fraction within the last cone). Falls back to the prior when no
    normals are near it."""
    n = np.asarray(normals, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    up = _unit(prior_up)
    total = float(w.sum()) or 1.0
    frac = 0.0
    for cone in cones_deg:
        cos_c = math.cos(math.radians(cone))
        for _ in range(iterations):
            sel = (n @ up) > cos_c
            if sel.sum() < 10:
                return up, frac
            m = (n[sel] * w[sel, None]).sum(axis=0)
            if np.linalg.norm(m) < 1e-12:
                return up, frac
            up = _unit(m)
        frac = float(w[(n @ up) > cos_c].sum()) / total
    return up, frac


def default_gravity_candidates() -> list[np.ndarray]:
    """Up directions to try without a learned prior: level camera through
    straight-down, in 15 degree pitch steps (up = (0, -cos t, -sin t))."""
    return [np.array([0.0, -math.cos(math.radians(t)), -math.sin(math.radians(t))]) for t in range(0, 91, 15)]


def gravity_from_normals(normals: np.ndarray, weights: np.ndarray, points: np.ndarray,
                         prior_up: Optional[Sequence[float]] = None) -> tuple[np.ndarray, dict]:
    """Choose "up". With a prior (GeoCalib), refine it on the normals. Without,
    mean-shift from several pitch candidates and keep the mode that (a) is
    supported by up-facing points lying *below* the camera, and (b) has the
    most area; ties go to the smaller pitch (eye-level photos are common)."""
    if prior_up is not None:
        up, frac = refine_gravity(normals, weights, prior_up)
        # GeoCalib is trained on roughly +-45 deg pitch, so steep top-down shots
        # need a large correction; walls are >= ~55 deg from up, so 35 is safe.
        if angle_deg(up, prior_up) > MAX_PRIOR_REFINE_DEG:  # drifted to another surface: trust the prior
            return _unit(prior_up), {"method": "prior", "support_fraction": _r(frac, 4),
                                     "refine_deg": _r(angle_deg(up, prior_up), 2)}
        return up, {"method": "prior+normals", "support_fraction": _r(frac, 4),
                    "refine_deg": _r(angle_deg(up, prior_up), 2)}
    best = None
    p = np.asarray(points, dtype=np.float64)
    for cand in default_gravity_candidates():
        up, frac = refine_gravity(normals, weights, cand)
        sel = (normals @ up) > math.cos(math.radians(HORIZONTAL_MAX_DEG))
        below = float(weights[sel & ((p @ up) < -0.05)].sum()) / (float(weights.sum()) or 1.0)
        score = below
        if best is None or score > best[0] * 1.15:
            best = (score, up, frac)
    return best[1], {"method": "normals", "support_fraction": _r(best[2], 4)}


def gravity_frame(up: Sequence[float]) -> np.ndarray:
    """Rows: right, up, forward. forward = camera +z with the up component
    removed; right = forward x up (so (right, up, forward) maps directly to
    Unity's (x, y, z))."""
    u = _unit(up)
    z = np.array([0.0, 0.0, 1.0])
    f = z - (z @ u) * u
    if np.linalg.norm(f) < 1e-6:  # looking straight along gravity
        y = np.array([0.0, -1.0, 0.0])
        f = y - (y @ u) * u
    f = _unit(f)
    r = _unit(np.cross(f, u))
    return np.stack([r, u, f])


def support_plane(points: np.ndarray, normals: np.ndarray, weights: np.ndarray, up: Sequence[float],
                  *, floor_range: tuple[float, float] = FLOOR_HEIGHT_RANGE) -> tuple[dict, np.ndarray]:
    """The lowest substantial plane perpendicular to gravity below the camera.

    Returns (support_plane dict, possibly refined up). Heights are measured
    down from the camera along gravity (h = -up . p)."""
    u = _unit(up)
    p = np.asarray(points, dtype=np.float64)
    n = np.asarray(normals, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    h = -(p @ u)
    horiz = ((n @ u) > math.cos(math.radians(HORIZONTAL_MAX_DEG))) & (h > 0.05)
    info: dict[str, Any] = {}
    if horiz.sum() < 50:
        # No up-facing surface below the camera: use the lowest visible points.
        cam_h = float(np.percentile(h, 98)) if len(h) else 1.5
        return _plane_dict(u, cam_h, "surface", method="lowest-points"), u
    hb = h[horiz]
    wb = w[horiz]
    hmax = float(np.percentile(hb, 99.5)) + 2 * HEIGHT_BIN_M
    bins = np.arange(0.0, hmax + HEIGHT_BIN_M, HEIGHT_BIN_M)
    hist, _ = np.histogram(hb, bins=bins, weights=wb)
    kernel = np.array([1, 2, 3, 2, 1], dtype=np.float64)
    smooth = np.convolve(hist, kernel / kernel.sum(), mode="same")
    peaks = [i for i in range(len(smooth))
             if smooth[i] > 0 and smooth[i] >= smooth[max(i - 1, 0)] and smooth[i] >= smooth[min(i + 1, len(smooth) - 1)]]
    # merge each peak's mass over +-3 bins
    masses = {i: float(hist[max(i - 3, 0): i + 4].sum()) for i in peaks}
    top = max(masses.values())
    substantial = [i for i in peaks if masses[i] >= SUPPORT_MIN_FRACTION * top]
    chosen = max(substantial)  # lowest = largest height below camera
    h0 = (bins[chosen] + bins[chosen + 1]) / 2
    band = horiz & (np.abs(h - h0) < 0.06)
    pts = p[band]
    if len(pts) > 20000:
        pts = pts[np.random.default_rng(0).choice(len(pts), 20000, replace=False)]
    cam_h = float(np.median(h[band])) if band.any() else float(h0)
    method = "height-histogram"
    if len(pts) >= 50:
        n_p, d_p, inl = ransac_plane(pts, threshold=max(0.01, 0.01 * cam_h), normal_hint=u, max_hint_deg=15.0)
        if n_p @ u < 0:
            n_p, d_p = -n_p, -d_p
        info["plane_fit_deg"] = _r(angle_deg(n_p, u), 3)
        info["plane_inlier_frac"] = _r(float(inl.mean()), 4)
        kind = "floor" if floor_range[0] <= d_p <= floor_range[1] else "surface"
        if kind == "floor" and angle_deg(n_p, u) <= FLOOR_SNAP_MAX_DEG and inl.mean() > 0.5:
            u = _unit(n_p)  # a floor is the best gravity reference we have
            method = "floor-plane"
        cam_h = float(np.median(-(pts[inl] @ u))) if inl.any() else cam_h
    kind, reason = classify_support(cam_h, u, h, floor_range=floor_range)
    info["kind_reason"] = reason
    info["area_m2"] = _r(masses[chosen], 3)
    info["candidates"] = [{"height_m": _r((bins[i] + bins[i + 1]) / 2, 3), "area_m2": _r(masses[i], 3)}
                          for i in sorted(substantial)]
    return _plane_dict(u, cam_h, kind, method=method, **info), u


def classify_support(cam_h: float, up: Sequence[float], heights: np.ndarray,
                     *, floor_range: tuple[float, float] = FLOOR_HEIGHT_RANGE) -> tuple[str, str]:
    """Contract rule: "floor" when the camera is 0.9-2.3 m above the plane,
    else "surface". One narrow exception: a steep close-up (camera pitched
    > 50 deg down, nothing visible farther below the camera than 1.25x the plane
    and the plane < 1.4 m below) is a table/sofa/bed top shot from above, not
    a floor (a standing photographer's floor is ~1.4-1.7 m below)."""
    if not (floor_range[0] <= cam_h <= floor_range[1]):
        return "surface", "camera height outside floor range"
    u = _unit(up)
    pitch = math.degrees(math.asin(float(np.clip(-u[1], -1.0, 1.0))))  # 90 = level camera
    pitch_down = 90.0 - pitch
    h = np.asarray(heights, dtype=np.float64)
    deepest = float(np.percentile(h, 99)) if len(h) else cam_h
    if pitch_down > CLOSEUP_PITCH_DEG and cam_h < 1.4 and deepest < 1.25 * cam_h:
        return "surface", f"close-up from above (pitch {pitch_down:.0f} deg down, plane {cam_h:.2f} m)"
    return "floor", "camera height in floor range"


def _plane_dict(up: np.ndarray, cam_h: float, kind: str, **extra) -> dict:
    d = {"normal_cam": _rl(up), "offset": _r(cam_h, 4), "camera_height": _r(cam_h, 4), "kind": kind}
    d.update(extra)
    return d


# --------------------------------------------------------------------------
# Masks and object placement
# --------------------------------------------------------------------------

def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Binary erosion with a (2r+1)^2 square, numpy only."""
    m = np.asarray(mask, dtype=bool)
    if radius <= 0:
        return m.copy()
    out = m.copy()
    padded = np.pad(m, radius, mode="constant", constant_values=False)
    h, w = m.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            out &= padded[radius + dy: radius + dy + h, radius + dx: radius + dx + w]
    return out


def resize_nearest(mask: np.ndarray, width: int, height: int) -> np.ndarray:
    m = np.asarray(mask)
    h, w = m.shape[:2]
    if (w, h) == (width, height):
        return m
    ys = np.minimum((np.arange(height) + 0.5) * h / height, h - 1).astype(int)
    xs = np.minimum((np.arange(width) + 0.5) * w / width, w - 1).astype(int)
    return m[ys][:, xs]


def object_placement(pointmap: np.ndarray, mask_full: np.ndarray, up: Sequence[float],
                     *, image_size: tuple[int, int], pointmap_intrinsics: Optional[Mapping[str, float]] = None) -> dict:
    """pose.json v2 "object" block (without splat_to_cam/reprojection_iou).

    ``pointmap``: (h, w, 3) camera-frame points, NaN where invalid, at any
    resolution. ``mask_full``: boolean mask at the source photo's size (W, H).

    yaw_deg: rotation about gravity of the object's long horizontal axis
    relative to the camera's right axis, in Unity's convention (Euler y,
    clockwise seen from above; 0 = long side facing the camera), folded to
    (-90, 90]; null when the footprint is nearly round (axis ratio < 1.25) or
    too few points. The visible surface cannot tell front from back.
    """
    W, H = image_size
    mask_full = np.asarray(mask_full, dtype=bool)
    ys, xs = np.nonzero(mask_full)
    if not len(xs):
        raise ValueError("empty mask")
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    area_frac = float(mask_full.sum()) / float(W * H)
    ph, pw = pointmap.shape[:2]
    m = resize_nearest(mask_full, pw, ph).astype(bool)
    radius = max(1, int(round(0.006 * max(pw, ph))))
    eroded = erode(m, radius)
    valid = np.all(np.isfinite(pointmap), axis=-1)
    sel = eroded & valid
    if sel.sum() < 30:
        sel = m & valid
    if sel.sum() < 3:
        raise ValueError("mask covers no valid depth")
    pts = pointmap[sel].astype(np.float64)
    # drop background bleed: depth within 3 MADs (log depth) of the median
    logz = np.log(np.maximum(pts[:, 2], 1e-6))
    med = float(np.median(logz))
    mad = float(np.median(np.abs(logz - med))) * 1.4826 + 1e-3
    pts = pts[np.abs(logz - med) < 3 * mad]
    frame = gravity_frame(up)
    q = pts @ frame.T  # (right, up, forward)
    centre_q = np.median(q, axis=0)
    # The erosion shaved `radius` pixels off every silhouette edge: add it back.
    pad = 0.0
    if pointmap_intrinsics and sel is not None:
        pad = 2.0 * radius * float(np.median(pts[:, 2])) / float(pointmap_intrinsics["fx"])
    low = float(np.percentile(q[:, 1], 1))
    high = float(np.percentile(q[:, 1], 99))
    horiz = q[:, [0, 2]] - centre_q[[0, 2]]
    yaw = None
    axes = np.eye(2)
    if len(horiz) >= 20:
        cov = np.cov(horiz.T)
        evals, evecs = np.linalg.eigh(cov)
        major = evecs[:, 1]
        if evals[0] > 0 and math.sqrt(evals[1] / evals[0]) >= 1.25:
            ang = math.degrees(math.atan2(major[1], major[0]))  # CCW from right, toward forward
            ang = (ang + 90.0) % 180.0 - 90.0
            if ang == -90.0:
                ang = 90.0
            yaw = -ang  # Unity yaw is clockwise from above
            if yaw == -90.0:
                yaw = 90.0
            a = math.radians(ang)
            axes = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
    proj = horiz @ axes.T
    width = float(np.percentile(proj[:, 0], 99) - np.percentile(proj[:, 0], 1)) + pad
    depth = float(np.percentile(proj[:, 1], 99) - np.percentile(proj[:, 1], 1))
    centroid_cam = frame.T @ centre_q
    base_q = centre_q.copy()
    base_q[1] = low
    base_cam = frame.T @ base_q
    return {
        "mask_bbox": bbox,
        "mask_area_frac": _r(area_frac, 6),
        "centroid_cam": _rl(centroid_cam, 5),
        "base_cam": _rl(base_cam, 5),
        "extent_m": {"width": _r(width, 4), "height": _r(high - low + pad / 2, 4), "depth": _r(depth, 4)},
        "yaw_deg": None if yaw is None else _r(yaw, 2),
        "points_used": int(len(pts)),
    }


# --------------------------------------------------------------------------
# Gaussians: colour, alignment, pruning, PLY
# --------------------------------------------------------------------------

def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def rgb_to_sh0(rgb: np.ndarray) -> np.ndarray:
    return (np.asarray(rgb, dtype=np.float64) - 0.5) / SH_C0


def sh0_to_rgb(sh: np.ndarray) -> np.ndarray:
    return np.asarray(sh, dtype=np.float64) * SH_C0 + 0.5


def front_depth(xyz: np.ndarray, intr: Mapping[str, float], width: int, height: int,
                opacity: Optional[np.ndarray] = None, min_opacity: float = 0.3) -> np.ndarray:
    """Per-pixel minimum depth of Gaussian centres (NaN where none), on a
    (height, width) grid with the given intrinsics."""
    xyz = np.asarray(xyz, dtype=np.float64)
    keep = xyz[:, 2] > 1e-3
    if opacity is not None:
        keep &= np.asarray(opacity) >= min_opacity
    u, v, z = project(xyz[keep], intr)
    ui = np.floor(u).astype(np.int64)
    vi = np.floor(v).astype(np.int64)
    ok = (ui >= 0) & (ui < width) & (vi >= 0) & (vi < height) & np.isfinite(z)
    depth = np.full(width * height, np.inf)
    np.minimum.at(depth, vi[ok] * width + ui[ok], z[ok])
    depth[~np.isfinite(depth)] = np.nan
    return depth.reshape(height, width)


def alignment_scale(sharp_depth: np.ndarray, metric_depth: np.ndarray) -> tuple[float, float, int]:
    """Robust median of metric/sharp depth ratios. Returns (scale, MAD of
    log ratio, pixels used)."""
    a = np.asarray(sharp_depth, dtype=np.float64)
    b = np.asarray(metric_depth, dtype=np.float64)
    ok = np.isfinite(a) & np.isfinite(b) & (a > 1e-3) & (b > 1e-3)
    if ok.sum() < 10:
        return 1.0, float("nan"), int(ok.sum())
    lr = np.log(b[ok] / a[ok])
    med = float(np.median(lr))
    mad = float(np.median(np.abs(lr - med)))
    return math.exp(med), mad, int(ok.sum())


def apply_scale(g: dict, s: float) -> dict:
    """Similarity scale about the camera origin: positions x s, log-scales + ln s."""
    out = dict(g)
    out["xyz"] = np.asarray(g["xyz"]) * s
    out["scale_log"] = np.asarray(g["scale_log"]) + math.log(s)
    return out


def importance(g: dict) -> np.ndarray:
    """Screen-space importance for a viewer at the photo's camera:
    opacity x (geometric-mean radius / depth)^2."""
    op = 1.0 / (1.0 + np.exp(-np.asarray(g["opacity_logit"], dtype=np.float64)))
    radius = np.exp(np.asarray(g["scale_log"], dtype=np.float64).mean(axis=1))
    z = np.maximum(np.asarray(g["xyz"], dtype=np.float64)[:, 2], 1e-3)
    return op * (radius / z) ** 2


def sanitize_and_prune(g: dict, max_count: int = MAX_GAUSSIANS, min_opacity: float = MIN_OPACITY) -> tuple[dict, dict]:
    """Drop non-finite / behind-camera / near-transparent Gaussians, then keep
    the ``max_count`` most important. Quaternions normalised."""
    xyz = np.asarray(g["xyz"], dtype=np.float64)
    fields = ("xyz", "f_dc", "opacity_logit", "scale_log", "rot")
    arrays = {k: np.asarray(g[k], dtype=np.float64) for k in fields}
    arrays["opacity_logit"] = arrays["opacity_logit"].reshape(-1)
    n0 = len(xyz)
    finite = np.ones(n0, dtype=bool)
    for k in fields:
        a = arrays[k].reshape(n0, -1)
        finite &= np.all(np.isfinite(a), axis=1)
    qn = np.linalg.norm(arrays["rot"], axis=1)
    finite &= qn > 1e-8
    op = 1.0 / (1.0 + np.exp(-np.clip(arrays["opacity_logit"], -60, 60)))
    keep = finite & (xyz[:, 2] > 1e-3) & (op >= min_opacity)
    stats = {"input": int(n0), "nonfinite": int((~finite).sum()), "after_filter": int(keep.sum())}
    idx = np.nonzero(keep)[0]
    if len(idx) > max_count:
        imp = importance({k: arrays[k][idx] for k in ("xyz", "opacity_logit", "scale_log")})
        top = np.argpartition(-imp, max_count - 1)[:max_count]
        idx = np.sort(idx[top])
    out = {k: arrays[k][idx] for k in fields}
    out["rot"] = out["rot"] / np.linalg.norm(out["rot"], axis=1, keepdims=True)
    out["opacity_logit"] = np.clip(out["opacity_logit"], -20, 20)
    stats["output"] = int(len(idx))
    return out, stats


def write_ply(path: Path, g: dict) -> int:
    """Standard 3DGS binary little-endian PLY with exactly PLY_PROPERTIES."""
    n = len(g["xyz"])
    data = np.empty(n, dtype=[(name, "<f4") for name in PLY_PROPERTIES])
    xyz = np.asarray(g["xyz"], dtype=np.float32)
    f_dc = np.asarray(g["f_dc"], dtype=np.float32)
    sc = np.asarray(g["scale_log"], dtype=np.float32)
    rot = np.asarray(g["rot"], dtype=np.float32)
    for i, k in enumerate("xyz"):
        data[k] = xyz[:, i]
    for i in range(3):
        data[f"f_dc_{i}"] = f_dc[:, i]
        data[f"scale_{i}"] = sc[:, i]
    data["opacity"] = np.asarray(g["opacity_logit"], dtype=np.float32).reshape(-1)
    for i in range(4):
        data[f"rot_{i}"] = rot[:, i]
    for name in PLY_PROPERTIES:
        if not np.all(np.isfinite(data[name])):
            raise ValueError(f"non-finite values in {name}")
    header = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n" + \
        "".join(f"property float {name}\n" for name in PLY_PROPERTIES) + "end_header\n"
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())
    os.replace(tmp, path)
    return n


def read_ply(path: Path) -> dict:
    """Read a PLY written by write_ply (or any float-only binary LE vertex PLY)."""
    raw = Path(path).read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError("not a binary little-endian PLY")
    names, count = [], 0
    for line in header:
        parts = line.split()
        if parts[:2] == ["element", "vertex"]:
            count = int(parts[2])
        elif parts[:1] == ["property"]:
            if parts[1] != "float":
                raise ValueError(f"unsupported property type {parts[1]}")
            names.append(parts[2])
    data = np.frombuffer(raw[end:end + count * 4 * len(names)], dtype=[(n, "<f4") for n in names])
    return {"names": names, "count": count, "data": data}


def splat_render(xyz: np.ndarray, rgb: np.ndarray, intr: Mapping[str, float], width: int, height: int) -> np.ndarray:
    """Nearest-centre point render (front-most wins): (H, W, 3) in [0, 1], NaN
    where no Gaussian projects. Used to verify alignment with the photo."""
    xyz = np.asarray(xyz, dtype=np.float64)
    u, v, z = project(xyz, intr)
    ui = np.floor(u).astype(np.int64)
    vi = np.floor(v).astype(np.int64)
    ok = (z > 1e-3) & (ui >= 0) & (ui < width) & (vi >= 0) & (vi < height)
    order = np.argsort(-z[ok])  # far first, near overwrite
    flat = vi[ok][order] * width + ui[ok][order]
    img = np.full((width * height, 3), np.nan)
    img[flat] = np.asarray(rgb, dtype=np.float64)[ok][order]
    return img.reshape(height, width, 3)


# --------------------------------------------------------------------------
# Depth grid
# --------------------------------------------------------------------------

def depth_grid(pointmap: np.ndarray, width: int = DEPTH_GRID_W) -> dict:
    """Coarse grid of camera-frame points: cell-median over valid pixels.
    ``points_cam`` holds only valid cells, row-major; ``valid`` is a base64
    bitmask over all w*h cells (bit i = byte i // 8, bit i % 8, LSB first),
    or [] when every cell is valid."""
    pm = np.asarray(pointmap, dtype=np.float64)
    ph, pw = pm.shape[:2]
    gh = max(1, int(round(width * ph / pw)))
    gw = width
    pts, valid = [], []
    ys = np.linspace(0, ph, gh + 1).astype(int)
    xs = np.linspace(0, pw, gw + 1).astype(int)
    for j in range(gh):
        for i in range(gw):
            cell = pm[ys[j]:max(ys[j + 1], ys[j] + 1), xs[i]:max(xs[i + 1], xs[i] + 1)].reshape(-1, 3)
            cell = cell[np.all(np.isfinite(cell), axis=1)]
            if len(cell) * 4 >= max(1, (ys[j + 1] - ys[j]) * (xs[i + 1] - xs[i])):
                c = cell[np.argsort(cell[:, 2])[len(cell) // 2]]  # median-depth sample
                pts.extend(_rl(c, 4))
                valid.append(True)
            else:
                valid.append(False)
    if all(valid):
        mask: Any = []
    else:
        bits = np.zeros((len(valid) + 7) // 8, dtype=np.uint8)
        for i, v in enumerate(valid):
            if v:
                bits[i // 8] |= 1 << (i % 8)
        mask = base64.b64encode(bits.tobytes()).decode("ascii")
    return {"grid": {"w": gw, "h": gh, "points_cam": pts}, "valid": mask}


# --------------------------------------------------------------------------
# Models (GPU; lazy)
# --------------------------------------------------------------------------

def load_image(path: Path):
    from PIL import Image, ImageOps
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


class SceneCapture:
    """Holds the models (resident when KEEP_RESIDENT) and a GPU lock."""

    def __init__(self, keep_resident: bool = KEEP_RESIDENT):
        self.keep_resident = keep_resident
        self.lock = threading.Lock()
        self._moge = None
        self._sharp = None
        self._geocalib = None
        self._geocalib_failed = False
        self.device = None

    # ---- setup
    def _torch(self):
        import torch
        if self.device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if self.device.type == "cuda":
                total = torch.cuda.get_device_properties(0).total_memory / 2**30
                frac = min(1.0, VRAM_BUDGET_GB / total)
                torch.cuda.set_per_process_memory_fraction(frac)
                log.info("VRAM budget %.1f GB of %.1f GB", VRAM_BUDGET_GB, total)
        return torch

    def moge(self):
        torch = self._torch()
        if self._moge is None:
            from moge.model.v2 import MoGeModel
            t = time.time()
            self._moge = MoGeModel.from_pretrained(MOGE_MODEL).eval()
            log.info("MoGe-2 loaded in %.1fs", time.time() - t)
        self._moge.to(self.device)
        return self._moge

    def sharp(self):
        torch = self._torch()
        if self._sharp is None:
            from sharp.models import PredictorParams, create_predictor
            t = time.time()
            state = torch.load(SHARP_CHECKPOINT, weights_only=True, map_location="cpu")
            model = create_predictor(PredictorParams())
            model.load_state_dict(state)
            self._sharp = model.eval()
            log.info("SHARP loaded in %.1fs", time.time() - t)
        self._sharp.to(self.device)
        return self._sharp

    def geocalib(self):
        if not USE_GEOCALIB or self._geocalib_failed:
            return None
        self._torch()
        if self._geocalib is None:
            try:
                from geocalib import GeoCalib
                self._geocalib = GeoCalib().eval()
            except Exception:
                log.exception("GeoCalib unavailable; gravity from normals only")
                self._geocalib_failed = True
                return None
        self._geocalib.to(self.device)
        return self._geocalib

    def _offload(self, *models):
        if self.keep_resident:
            return
        torch = self._torch()
        for m in models:
            if m is not None:
                m.to("cpu")
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def warm(self):
        with self.lock:
            self.moge()
            self.sharp()
            self.geocalib()
            self._offload(self._moge, self._sharp, self._geocalib)

    # ---- geometry
    def geometry(self, image_path: Path) -> dict:
        """Cached by image sha256 under CACHE_DIR/<sha>/."""
        image_path = Path(image_path)
        sha = sha256_file(image_path)
        cdir = CACHE_DIR / sha
        meta_path = cdir / "geometry.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text())
            if (meta.get("geometry_version") == GEOMETRY_VERSION and Path(meta["pointmap_npy"]).is_file()
                    and Path(meta.get("sharp_npz", "")).is_file()):
                meta["cached"] = True
                disk_hygiene.touch(cdir)  # LRU: most recently used survives eviction
                return meta
        with self.lock:
            meta = self._compute_geometry(image_path, cdir)
        meta["cached"] = False
        return meta

    def _compute_geometry(self, image_path: Path, cdir: Path) -> dict:
        torch = self._torch()
        t0 = time.time()
        img = load_image(image_path)
        W, H = img.size
        s = min(1.0, GEOMETRY_MAX_SIDE / max(W, H))
        gw, gh = max(1, round(W * s)), max(1, round(H * s))
        small = img.resize((gw, gh), resample=3) if (gw, gh) != (W, H) else img
        arr = np.asarray(small, dtype=np.float32) / 255.0
        model = self.moge()
        with torch.inference_mode():
            x = torch.from_numpy(arr).permute(2, 0, 1).to(self.device)
            out = model.infer(x)
        pm = out["points"].float().cpu().numpy()
        mask = out["mask"].cpu().numpy().astype(bool) if "mask" in out else np.all(np.isfinite(pm), axis=-1)
        normals = out["normal"].float().cpu().numpy() if "normal" in out else None
        k_norm = out["intrinsics"].float().cpu().numpy()
        t_moge = time.time() - t0
        pm[~mask] = np.nan
        pm[~np.all(np.isfinite(pm), axis=-1)] = np.nan
        intr_small = intrinsics_from_normalized(k_norm, gw, gh)
        intr_full = intrinsics_from_normalized(k_norm, W, H)
        if normals is None or not np.all(np.isfinite(normals[mask])):
            normals = normals_from_pointmap(pm)
        # SHARP now (not in scene()), so every consumer of this geometry --
        # placements included -- sees the same metric scale as the splat.
        t2 = time.time()
        g_raw, sharp_info = self._run_sharp(image_path, {"intrinsics": intr_full})
        op = 1.0 / (1.0 + np.exp(-np.clip(g_raw["opacity_logit"], -60, 60)))
        sd = front_depth(g_raw["xyz"], intr_small, gw, gh, opacity=op)
        ratio, spread, used = alignment_scale(sd, pm[..., 2])  # moge / sharp
        k = {"sharp": 1.0 / ratio, "geomean": 1.0 / math.sqrt(ratio)}.get(METRIC_SCALE_SOURCE, 1.0)
        pm = pm * k
        t_sharp = time.time() - t2
        # gravity prior
        prior, prior_src = None, None
        t1 = time.time()
        gc = self.geocalib()
        if gc is not None:
            try:
                prior = self._geocalib_up(gc, arr, intr_small)
                prior_src = "geocalib"
            except Exception:
                log.exception("GeoCalib failed; gravity from normals only")
        t_gc = time.time() - t1
        self._offload(self._moge, self._geocalib)
        # sample pixels for plane/gravity work
        valid = mask & np.all(np.isfinite(pm), axis=-1) & np.all(np.isfinite(normals), axis=-1)
        stride = max(1, int(round(math.sqrt(valid.sum() / 150_000)))) if valid.sum() > 150_000 else 1
        sub = np.zeros_like(valid)
        sub[::stride, ::stride] = True
        sel = valid & sub
        P = pm[sel].astype(np.float64)
        N = orient_normals_to_camera(P, normals[sel].astype(np.float64))
        N /= np.linalg.norm(N, axis=1, keepdims=True)
        A = pixel_area_weights(P, N, intr_small, stride=stride)
        up, ginfo = gravity_from_normals(N, A, P, prior_up=prior)
        if prior is not None:
            ginfo["prior_up"] = _rl(prior)
        plane, up = support_plane(P, N, A, up)
        ginfo["final_minus_prior_deg"] = _r(angle_deg(up, prior), 2) if prior is not None else None
        cdir.mkdir(parents=True, exist_ok=True)
        np.savez(cdir / "sharp_raw.npz", **{key: np.asarray(v, dtype=np.float32) for key, v in g_raw.items()})
        pm_path = cdir / "pointmap.npy"
        np.save(pm_path, pm.astype(np.float32))
        np.save(cdir / "normals.npy", normals.astype(np.float16))
        z = pm[..., 2][np.isfinite(pm[..., 2])]
        meta = {
            "geometry_version": GEOMETRY_VERSION,
            "image_sha256": cdir.name,
            "image_size": [W, H],
            "intrinsics": intr_full,
            "gravity_up_cam": _rl(up),
            "support_plane": plane,
            "depth_range_m": [_r(np.percentile(z, 1), 4), _r(np.percentile(z, 99), 4)] if len(z) else [0.0, 0.0],
            "pointmap_npy": str(pm_path),
            "pointmap_size": [gw, gh],
            "pointmap_intrinsics": intr_small,
            "gravity": {"source": prior_src or "normals", **ginfo},
            "metric_scale": {"source": METRIC_SCALE_SOURCE, "moge_over_sharp": _r(ratio, 5),
                             "moge_factor": _r(k, 5), "align_log_mad": _r(spread, 5) if math.isfinite(spread) else None,
                             "align_pixels": used},
            "sharp_aligned_scale": _r(ratio * k, 6),
            "sharp_npz": str(cdir / "sharp_raw.npz"),
            "sharp_info": sharp_info,
            "models": {"depth": f"moge-2 {MOGE_MODEL}",
                       "gravity": ("geocalib (pinhole, focal prior from moge-2) + moge-2 normals mean-shift + floor-plane snap"
                                   if prior_src else "moge-2 normals mean-shift + floor-plane snap")},
            "timings_s": {"moge": _r(t_moge, 2), "sharp": _r(t_sharp, 2), "geocalib": _r(t_gc, 2),
                          "total": _r(time.time() - t0, 2)},
        }
        tmp = cdir / "geometry.json.part"
        tmp.write_text(json.dumps(meta, indent=1))
        os.replace(tmp, cdir / "geometry.json")
        return meta

    def _geocalib_up(self, model, arr: np.ndarray, intr: Mapping[str, float]) -> np.ndarray:
        torch = self._torch()
        img = torch.from_numpy(arr).permute(2, 0, 1).to(self.device)
        f = torch.tensor([float(intr["fx"])], device=self.device)
        with torch.inference_mode():
            res = model.calibrate(img, camera_model="pinhole", priors={"focal": f})
        g = res["gravity"].vec3d.reshape(-1).float().cpu().numpy().astype(np.float64)
        # GeoCalib's "gravity" vector is the UP direction in the OpenCV camera
        # frame (Gravity.from_rp(0, 0) == (0, -1, 0)).
        return _unit(g)

    # ---- placement
    def placement(self, image_path: Path, mask_path: Path) -> dict:
        geo = self.geometry(Path(image_path))
        from PIL import Image
        m = np.asarray(Image.open(mask_path).convert("L")) > 127
        W, H = geo["image_size"]
        if m.shape != (H, W):
            m = resize_nearest(m, W, H)
        pm = np.load(geo["pointmap_npy"])
        obj = object_placement(pm, m, geo["gravity_up_cam"], image_size=(W, H),
                               pointmap_intrinsics=geo.get("pointmap_intrinsics"))
        return {**_geometry_public(geo), "object": obj}

    # ---- scene
    def scene(self, image_path: Path, out_dir: Path, upload_id: str = "", photo: str = "") -> dict:
        image_path, out_dir = Path(image_path), Path(out_dir)
        t0 = time.time()
        geo = self.geometry(image_path)
        t_geo = time.time() - t0
        raw = np.load(geo["sharp_npz"])
        g = {key: raw[key].astype(np.float64) for key in raw.files}
        sharp_info = geo.get("sharp_info", {})
        ms = geo["metric_scale"]
        scale, spread, used = geo["sharp_aligned_scale"], ms.get("align_log_mad"), ms.get("align_pixels")
        pm = np.load(geo["pointmap_npy"])
        g = apply_scale(g, scale)
        t_sharp = time.time() - t0 - t_geo
        g, prune_stats = sanitize_and_prune(g)
        out_dir.mkdir(parents=True, exist_ok=True)
        count = write_ply(out_dir / "scene.ply", g)
        dg = depth_grid(pm)
        doc = {
            "version": 1,
            "upload_id": upload_id,
            "photo": photo,
            "frame": "opencv",
            "image_size": geo["image_size"],
            "intrinsics": geo["intrinsics"],
            "gravity_up_cam": geo["gravity_up_cam"],
            "support_plane": geo["support_plane"],
            "depth_range_m": geo["depth_range_m"],
            "splat": {"file": "scene.ply", "count": int(count), "source": "apple-sharp",
                      "aligned_scale": _r(scale, 5), "align_log_mad": spread, "metric_scale": ms,
                      "align_pixels": used, "prune": prune_stats, "sh_degree": 0, "color_space": "sRGB"},
            "depth_grid": dg["grid"],
            "depth_grid_valid": dg["valid"],
            "models": {**geo["models"], "splat": "sharp sharp_2572gikvuh.pt (apple/ml-sharp)"},
            "gravity": geo.get("gravity", {}),
            "timings_s": {"geometry": _r(t_geo, 2), "geometry_cached": geo.get("cached", False),
                          "sharp": _r(t_sharp, 2), "sharp_inference": sharp_info.get("inference_s"),
                          "total": _r(time.time() - t0, 2)},
            "vram_peak_gb": sharp_info.get("vram_peak_gb"),
        }
        tmp = out_dir / "scene.json.part"
        tmp.write_text(json.dumps(doc, indent=1))
        os.replace(tmp, out_dir / "scene.json")
        return doc

    def _run_sharp(self, image_path: Path, geo: dict) -> tuple[dict, dict]:
        torch = self._torch()
        import torch.nn.functional as F
        from sharp.utils.gaussians import unproject_gaussians
        img = load_image(image_path)
        W, H = img.size
        f_px = float(geo["intrinsics"]["fx"])
        model = self.sharp()
        if self.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats()
        t = time.time()
        internal = (1536, 1536)
        with torch.no_grad():
            image_pt = torch.from_numpy(np.asarray(img).copy()).float().to(self.device).permute(2, 0, 1) / 255.0
            disparity_factor = torch.tensor([f_px / W]).float().to(self.device)
            resized = F.interpolate(image_pt[None], size=(internal[1], internal[0]), mode="bilinear", align_corners=True)
            g_ndc = model(resized, disparity_factor)
            K = torch.tensor([[f_px, 0, W / 2, 0], [0, f_px, H / 2, 0], [0, 0, 1, 0], [0, 0, 0, 1]]).float().to(self.device)
            K_r = K.clone()
            K_r[0] *= internal[0] / W
            K_r[1] *= internal[1] / H
            g = unproject_gaussians(g_ndc, torch.eye(4).to(self.device), K_r, internal)
            xyz = g.mean_vectors.flatten(0, 1).float().cpu().numpy()
            scales = g.singular_values.flatten(0, 1).float().cpu().numpy()
            rot = g.quaternions.flatten(0, 1).float().cpu().numpy()
            colors = g.colors.flatten(0, 1).float().cpu().numpy()
            opac = g.opacities.flatten(0, 1).float().cpu().numpy().reshape(-1)
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        info = {"inference_s": _r(time.time() - t, 2)}
        if self.device.type == "cuda":
            info["vram_peak_gb"] = _r(torch.cuda.max_memory_allocated() / 2**30, 2)
        del g, g_ndc, resized, image_pt
        self._offload(self._sharp)
        opac = np.clip(opac.astype(np.float64), 1e-6, 1 - 1e-6)
        out = {
            "xyz": xyz.astype(np.float64),
            "f_dc": rgb_to_sh0(linear_to_srgb(colors)),
            "opacity_logit": np.log(opac / (1 - opac)),
            "scale_log": np.log(np.maximum(scales.astype(np.float64), 1e-9)),
            "rot": rot.astype(np.float64),  # (w, x, y, z) as in 3DGS rot_0..rot_3
        }
        return out, info


def _geometry_public(geo: Mapping[str, Any]) -> dict:
    keys = ("image_size", "intrinsics", "gravity_up_cam", "support_plane", "pointmap_npy",
            "depth_range_m", "pointmap_size", "pointmap_intrinsics", "image_sha256", "gravity", "models", "cached")
    return {k: geo[k] for k in keys if k in geo}


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

_capture: Optional[SceneCapture] = None


_cache_users: dict[str, int] = {}
_cache_users_lock = threading.Lock()


def evict_scene_cache(max_gb: Optional[float] = None) -> dict:
    """LRU-evict CACHE_DIR/<sha>/ entries down to ``max_gb`` (default
    SKETCHSCAPE_SCENE_CACHE_MAX_GB), never an entry a request is using."""
    with _cache_users_lock:
        in_use = {sha for sha, count in _cache_users.items() if count > 0}
    limit = CACHE_MAX_GB if max_gb is None else max_gb
    try:
        return disk_hygiene.evict_lru(CACHE_DIR, limit * 2**30, in_use=in_use)
    except Exception:
        log.exception("scene-cache eviction failed")
        return {"removed": 0, "freed_bytes": 0, "kept_bytes": 0}


@contextmanager
def cache_entry_in_use(image_path: Path):
    """Pin the image's cache entry for one request, then evict the LRU
    entries beyond the cap (outside the GPU lock)."""
    try:
        sha = sha256_file(Path(image_path))
    except OSError:
        sha = ""
    with _cache_users_lock:
        _cache_users[sha] = _cache_users.get(sha, 0) + 1
    try:
        yield sha
    finally:
        with _cache_users_lock:
            _cache_users[sha] -= 1
            if _cache_users[sha] <= 0:
                del _cache_users[sha]
        evict_scene_cache()


class Handler(BaseHTTPRequestHandler):
    server_version = "SketchScapeScene/1"

    def log_message(self, fmt, *args):  # route to logging
        log.info("%s %s", self.address_string(), fmt % args)

    def _send(self, code: int, body: Mapping[str, Any]):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            info: dict[str, Any] = {"status": "ok", "models": {"depth": MOGE_MODEL, "splat": SHARP_CHECKPOINT.name},
                                    "resident": _capture.keep_resident,
                                    "loaded": {"moge": _capture._moge is not None, "sharp": _capture._sharp is not None,
                                               "geocalib": _capture._geocalib is not None},
                                    "busy": _capture.lock.locked()}
            try:
                import torch
                if torch.cuda.is_available():
                    info["vram_allocated_gb"] = _r(torch.cuda.memory_allocated() / 2**30, 2)
                    info["vram_reserved_gb"] = _r(torch.cuda.memory_reserved() / 2**30, 2)
            except Exception:
                pass
            return self._send(200, info)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object expected")
            route = self.path.rstrip("/")
            image = Path(str(body.get("image_path") or ""))
            if not image.is_file():
                return self._send(400, {"error": f"image_path not found: {image}"})
            if route not in ("/v1/geometry", "/v1/placement", "/v1/scene"):
                return self._send(404, {"error": "not found"})
            with cache_entry_in_use(image):
                if route == "/v1/geometry":
                    return self._send(200, _geometry_public(_capture.geometry(image)))
                if route == "/v1/placement":
                    mask = Path(str(body.get("mask_path") or ""))
                    if not mask.is_file():
                        return self._send(400, {"error": f"mask_path not found: {mask}"})
                    return self._send(200, _capture.placement(image, mask))
                out_dir = body.get("out_dir")
                if not out_dir:
                    return self._send(400, {"error": "out_dir required"})
                doc = _capture.scene(image, Path(out_dir), str(body.get("upload_id") or ""), str(body.get("photo") or ""))
                return self._send(200, {"scene_json": doc, "scene_ply": str(Path(out_dir) / "scene.ply"),
                                        "scene_json_path": str(Path(out_dir) / "scene.json"),
                                        "timings_s": doc.get("timings_s")})
        except ValueError as exc:
            return self._send(422, {"error": str(exc)})
        except Exception as exc:  # keep the server alive
            log.error("request failed: %s", traceback.format_exc())
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            return self._send(500, {"error": f"{type(exc).__name__}: {exc}"})


def serve(host: str, port: int, warm: bool = True) -> None:
    global _capture
    evicted = evict_scene_cache()
    log.info("scene cache %s: evicted %d entr(ies), %.1f MB freed, %.1f MB kept (cap %.1f GB)", CACHE_DIR,
             evicted["removed"], evicted["freed_bytes"] / 2**20, evicted["kept_bytes"] / 2**20, CACHE_MAX_GB)
    _capture = SceneCapture()
    if warm:
        _capture.warm()
    httpd = ThreadingHTTPServer((host, port), Handler)
    log.info("scene capture listening on %s:%d (resident=%s)", host, port, _capture.keep_resident)
    httpd.serve_forever()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--image", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--mask", type=Path, help="also print the placement for this mask")
    ap.add_argument("--upload-id", default="")
    ap.add_argument("--photo", default="")
    ap.add_argument("--geometry-only", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SKETCHSCAPE_SCENE_PORT", "8004")))
    ap.add_argument("--no-warm", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.serve:
        serve(args.host, args.port, warm=not args.no_warm)
        return 0
    if not args.image:
        ap.error("--image is required (or --serve)")
    cap = SceneCapture(keep_resident=True)
    if args.mask:
        print(json.dumps(cap.placement(args.image, args.mask), indent=1))
    if args.geometry_only:
        print(json.dumps(_geometry_public(cap.geometry(args.image)), indent=1))
        return 0
    if not args.out:
        if args.mask:
            return 0
        ap.error("--out is required")
    doc = cap.scene(args.image, args.out, args.upload_id, args.photo)
    short = {k: v for k, v in doc.items() if k != "depth_grid"}
    print(json.dumps(short, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
