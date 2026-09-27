#!/usr/bin/env python3
"""Pull real Fast-SAM3D reconstructions (and photo scenes) from AWS into the Unity project.

Label mode (default): for every catalog asset in DynamoDB (``ASSET#<id>``)
that is ``ready``, is a ``reconstruction`` and has a real label (not the
placeholder ``object``), this picks the newest asset per label, downloads its
``reconstruction.ply`` from the artifacts bucket, repairs non-finite opacity
values (the same repair as ``worker/gaussian_ply_safety.py``; Unity's Gsplat
importer rejects the whole file on the first one), and writes it into the
Unity project at ``Assets/SketchScape/AssetLibrary/<label>_<id8>.ply``, where
the Gsplat importer picks it up.

Project mode (``--project-id``): every ready reconstruction of the project,
duplicates included, plus each source photo's **scene** (docs/
IMMERSIVE_SCENE_PIPELINE.md section 1b: ``artifacts/scenes/<upload_id>/
{scene.ply, scene.json, analysis.json}``). The objects that are placed
separately (pose v2 with a verified ``splat_to_cam`` and ``mask_area_frac`` < 0.3;
see ``CUT_UNVERIFIED``) are **cut out of the scene splat**: scene Gaussians whose centres project into the object's dilated
mask and lie in front of / at the object's depth are removed, so the room
doesn't show every cat twice; the background behind them stays. Large objects
(e.g. a blanket filling the photo) stay part of the scene. The cut scene is
written to ``Assets/SketchScape/Scenes/<upload_id[:8]>/scene.ply``. Objects
whose pose v2 is not in the same geometry as the photo's scene.json (another
geometry version / scale, see ``scene_layout.pose_frame_mismatch``) are never
cut: they stay in the splat. A verified ``splat_to_cam`` is first checked
against the photo (``refine_against_photo``): the placed scan's front surface
is pulled onto the photo's visible surface (a scale about the camera centre,
so its silhouette is unchanged; recorded as ``pose.sync_refine`` with the GPU
value kept as ``splat_to_cam_gpu``, catalog copy only), and only the part of
the mask the scan really covers is cut, so parts it misses (a tail) stay in
the photo splat instead of leaving holes; the scan's colours are matched to
the photo (per-channel gain, clamped, applied to its library PLY;
``--no-colour-gain`` turns it off). Under each cut object the surface it
rests on is patched from its surroundings (``fill_under_cut``), so lifting it
shows the sofa / floor, and scene Gaussians clearly below the support plane
(SHARP's depth-edge floaters; ``prune_below_support``) are dropped first.

Standalone scenes (``--scene-id ID``, repeatable): a photo scene that is not a
project upload (e.g. the eye-level test room ``testroom1``) is synced with no
objects to ``Assets/SketchScape/Scenes/<id[:8]>/scene.ply`` and a catalog
scene with ``project_id`` "". With only ``--scene-id`` nothing else is synced.
Every synced scene ends with a preview of ``photo_room_layout`` (what
compose_room will get).

Both modes write ``config/nemoclaw/asset-catalog.json`` (contract section 4),
merged by ``asset_id`` / ``scene_id`` into what is already there. Each asset
records its ``pose`` (pose.json v2 when the GPU host has one: the asset
document's, else ``artifacts/<job_id>/pose.json``), ``photo``, ``upload_id``,
``job_id``, ``mask_area_frac`` and PLY bounds, so ``backend/scene_layout.
photo_room_layout`` can rebuild the photo as a room.

Quest copies (docs/IMMERSIVE_SCENE_PIPELINE.md, "Quest budgets"): every splat
written into the Unity project also gets a headset-sized copy next to it,
``<name>_quest.ply`` (``decimate_splats.decimate``: 25k splats per object,
120k per photo scene; a smaller source is copied as is), which RoomKit renders
when the room spec's ``performance.prefer_quest_lod`` is on (a 3.37M-splat
room ran at 5 FPS on a Quest 2). Each copy gets a ``.meta`` with the source's
Gsplat importer settings and a new GUID, written before the PLY appears in
``Assets`` (the copy is staged outside it, then moved in). A copy newer than
its source with the right splat count is left alone; a regenerated copy keeps
its GUID. The copies are not catalog assets. ``--quest-lod-only [PATH ...]``
makes / refreshes them for splats already in the project (no AWS, catalog
untouched); ``--no-quest-lod`` skips them.

Standard library only (plus the AWS CLI, already logged in via
``aws login``), so it runs from any Python 3.10+ on this machine.

    python scripts/sync_s3_assets_to_unity.py [--unity-project ../HackGTUnity]
        [--bucket NAME] [--table NAME] [--region us-east-1] [--labels cat tomato]
        [--project-id ID]   # every ready scan of one project + its photos' scenes
        [--scene-id ID ...] # standalone photo scenes (no objects), e.g. testroom1
        [--quest-object-splats 25000] [--quest-scene-splats 120000] [--no-quest-lod]
    python scripts/sync_s3_assets_to_unity.py --quest-lod-only [Assets/SketchScape/AssetLibrary/cat_1234abcd.ply ...]
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "sketchscape-artifacts-20260922133334256700000003"
DEFAULT_TABLE = "sketchscape-authoring"
LIBRARY_DIR = "Assets/SketchScape/AssetLibrary"
SCENES_DIR = "Assets/SketchScape/Scenes"
CATALOG_PATH = REPO / "config" / "nemoclaw" / "asset-catalog.json"
PLACEHOLDER_LABELS = {"", "object"}
SAFE_LOGIT = 10.0  # matches worker/gaussian_ply_safety.SAFE_LOGIT

# Scene cut-out (objects placed separately are removed from the scene splat).
CUT_MAX_MASK_AREA_FRAC = 0.3  # objects at least this big stay inside the scene splat
# Objects whose pose has no verified splat_to_cam stay inside the photo splat: from the spawn point the photo
# shows them exactly, while an "upright at base_cam" guess floats when the photo crops the object (a table
# cut off by the frame has its lowest *visible* point at seat height) and leaves a hole where it was.
CUT_UNVERIFIED = False
CUT_DILATE_FRAC = 0.012  # mask dilation radius, as a fraction of the mask's diagonal
CUT_DEPTH_MARGIN = (0.04, 0.2)  # metres behind the object's surface still removed: clamp(0.25 * largest side)
CUT_MAX_REACH = 1.5  # a verified pose's box may extend the cut this many largest sides behind the surface
# Verified poses are checked against the photo before cutting (refine_against_photo):
REFINE_MIN_PIXELS = 200  # mask pixels where both the photo surface and the placed object are seen
REFINE_TOLERANCE = 0.02  # depth factors within 2 % of 1 are left alone
REFINE_RANGE = (0.8, 1.25)  # the most a depth factor may move an object toward / away from the camera
REFINE_MAX_POINTS = 150000  # object Gaussians projected (every n-th beyond this)
PHOTO_MIN_OPACITY = -2.0  # logit: fainter scene Gaussians don't define the photo's visible surface
OBJECT_MIN_OPACITY = 0.0  # logit: object Gaussians that define its front surface / coverage
COVER_CLOSE_PX = 2  # closes the gaps between an object's projected Gaussian centres
COLOUR_GAIN_RANGE = (0.7, 1.6)  # per-channel gain that matches a scan's colour to the photo
COLOUR_GAIN_MIN_CHANGE = 0.03  # smaller gains are left alone
COLOUR_GAIN_ENABLED = True  # --no-colour-gain turns it off
SH_C0 = 0.28209479177387814  # colour = 0.5 + SH_C0 * f_dc
COVER_DILATE_FRAC = 0.003  # cut margin around the covered part of the mask (~2 px at 640x480)
# Under each cut object the surface it rests on is patched (fill_under_cut), so picking it up
# reveals the sofa / floor instead of a hole (a single photo has nothing behind the object):
FILL_RING_PX = 6  # kept scene pixels this close around the cut region give the patch its colours
FILL_OPACITY = 4.0  # logit
FILL_SIZE_PX = 0.7  # Gaussian radius (sigma) in photo pixels at its depth
FILL_DEPTH_TOL = 0.025  # metres: ring pixels this close to the surface plane colour the patch
FILL_BLUR_PX = 5  # box blur radius over the patch colours (pixels)
PRUNE_BELOW_M = {"surface": 0.05, "floor": 0.12}  # scene Gaussians this far below the support are floaters
CATALOG_GRID = (16, 12)  # the scene's depth grid is kept in the catalog at this coarser size

# Quest copies (<name>_quest.ply next to each synced splat; RoomKit renders them for the headset).
# A Quest 2 ran a 3.37M-splat room at 5 FPS; these budgets keep a photo scene + ~6 objects near 270k.
QUEST_SUFFIX = "_quest"
QUEST_OBJECT_SPLATS = 25000
QUEST_SCENE_SPLATS = 120000
QUEST_MAX_SCALE_UP = 1.3  # decimate_splats' cap on the coverage-preserving scale-up of kept splats
QUEST_STAGE_DIR = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "SketchScape" / "questlod-stage"
# What Unity writes for a PLY the Gsplat importer (com.arloopa.unitysplats) imports with its defaults
# (Compression 1 = Spark, SourceCoordinates 0 = Unspecified); used when the source has no .meta yet.
GSPLAT_META_TEMPLATE = (
    "fileFormatVersion: 2\n"
    "guid: {guid}\n"
    "ScriptedImporter:\n"
    "  internalIDToNameTable: []\n"
    "  externalObjects: {{}}\n"
    "  serializedVersion: 2\n"
    "  userData: \n"
    "  assetBundleName: \n"
    "  assetBundleVariant: \n"
    "  script: {{fileID: 11500000, guid: 7468ea6559404cbc8f3e83b0b1a00683, type: 3}}\n"
    "  Compression: 1\n"
    "  SourceCoordinates: 0\n"
)
_GUID_LINE = re.compile(r"^guid: *[0-9a-fA-F]*[ \t]*$", re.MULTILINE)


def _load_scene_layout():
    """backend/scene_layout.py (stdlib only), loaded by path so backend/'s
    other modules can never shadow anything here. None if it's missing."""
    import importlib.util

    path = REPO / "backend" / "scene_layout.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("scene_layout", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scene_layout = _load_scene_layout()


def _load_decimate():
    """scripts/decimate_splats.py (stdlib only), loaded by path like scene_layout."""
    import importlib.util

    path = Path(__file__).resolve().parent / "decimate_splats.py"
    spec = importlib.util.spec_from_file_location("decimate_splats", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


decimate_splats = _load_decimate()


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------


def _aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"aws {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def _aws_try(*args: str) -> bool:
    return subprocess.run(["aws", *args], capture_output=True, text=True, check=False).returncode == 0


def _s3_get(bucket: str, key: str, dest: Path) -> bool:
    """Download s3://bucket/key to dest; False when it doesn't exist."""
    return _aws_try("s3", "cp", f"s3://{bucket}/{key}", str(dest), "--only-show-errors")


def _s3_list(bucket: str, prefix: str) -> set[str]:
    result = subprocess.run(
        ["aws", "s3", "ls", f"s3://{bucket}/{prefix}"], capture_output=True, text=True, check=False
    )
    return {line.split()[-1] for line in result.stdout.splitlines() if line.strip() and not line.strip().startswith("PRE")}


def _plain(value: dict):
    kind, inner = next(iter(value.items()))
    if kind == "M":
        return {k: _plain(v) for k, v in inner.items()}
    if kind == "L":
        return [_plain(v) for v in inner]
    return inner


def load_assets(table: str, region: str) -> list[dict]:
    raw = json.loads(
        _aws(
            "dynamodb", "scan", "--table-name", table, "--region", region, "--output", "json",
            "--filter-expression", "begins_with(pk, :a)",
            "--expression-attribute-values", json.dumps({":a": {"S": "ASSET#"}}),
        )
    )
    return [json.loads(_plain(item["document"])) for item in raw.get("Items", [])]


def pick_project(assets: list[dict], project_id: str) -> list[dict]:
    """Every ready reconstruction of one project (a whole photo's scene)."""
    return [
        a for a in assets
        if a.get("project_id") == project_id
        and a.get("status") == "ready"
        and a.get("kind", "reconstruction") == "reconstruction"
        and a.get("reconstruction_job_id")
    ]


def pick_newest_per_label(assets: list[dict], labels: set[str] | None) -> list[dict]:
    newest: dict[str, dict] = {}
    for asset in assets:
        label = (asset.get("label") or "").strip().lower()
        if (
            asset.get("status") != "ready"
            or asset.get("kind") != "reconstruction"
            or label in PLACEHOLDER_LABELS
            or not asset.get("reconstruction_job_id")
            or (labels and label not in labels)
        ):
            continue
        stamp = asset.get("updated_at") or asset.get("created_at") or ""
        if label not in newest or stamp > (newest[label].get("updated_at") or newest[label].get("created_at") or ""):
            newest[label] = asset
    return [newest[k] for k in sorted(newest)]


def photo_key(asset: dict) -> str | None:
    for view in asset.get("views") or []:
        if isinstance(view, dict) and view.get("image_key"):
            return view["image_key"]
    return None


def upload_id_of(image_key: str | None) -> str | None:
    """``uploads/<project>/<upload>/source.jpg`` -> ``<upload>``."""
    parts = (image_key or "").split("/")
    return parts[2] if len(parts) >= 4 and parts[0] == "uploads" and parts[2] else None


def is_pose_v2(pose) -> bool:
    return isinstance(pose, dict) and isinstance(pose.get("object"), dict) and (pose.get("version") or 0) >= 2


# ---------------------------------------------------------------------------
# PLY (float-only binary little-endian Gaussian splats)
# ---------------------------------------------------------------------------


class GaussianPly:
    """A float-only binary little-endian PLY with a single ``vertex`` element."""

    def __init__(self, header_lines: list[str], names: list[str], count: int, floats: array, tail: bytes = b""):
        self.header_lines, self.names, self.count, self.floats, self.tail = header_lines, names, count, floats, tail

    @property
    def stride(self) -> int:
        return len(self.names)

    @classmethod
    def read(cls, path: Path) -> "GaussianPly":
        data = path.read_bytes()
        end = data.index(b"end_header") + len(b"end_header")
        end += 2 if data[end:end + 2] == b"\r\n" else 1
        header = data[:end].decode("ascii").splitlines()
        if "format binary_little_endian 1.0" not in header:
            raise ValueError(f"{path.name}: expected binary_little_endian PLY")
        elements = [line.split() for line in header if line.startswith("element")]
        if not elements or elements[0][1] != "vertex":
            raise ValueError(f"{path.name}: expected a vertex element first")
        props = [line.split() for line in header if line.startswith("property")]
        if any(p[1] != "float" for p in props):
            raise ValueError(f"{path.name}: expected float-only vertex properties")
        if len(elements) > 1:
            raise ValueError(f"{path.name}: expected only a vertex element")
        names = [p[2] for p in props]
        count = int(elements[0][2])
        stride = len(names)
        floats = array("f")
        floats.frombytes(data[end:end + 4 * stride * count])
        if len(floats) != stride * count:
            raise ValueError(f"{path.name}: truncated ({len(floats)} of {stride * count} floats)")
        if sys.byteorder != "little":
            floats.byteswap()
        return cls(header, names, count, floats, data[end + 4 * stride * count:])

    def write(self, path: Path) -> None:
        header = [
            f"element vertex {self.count}" if line.startswith("element vertex") else line for line in self.header_lines
        ]
        floats = self.floats
        if sys.byteorder != "little":
            floats = array("f", floats)
            floats.byteswap()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(("\n".join(header) + "\n").encode("ascii") + floats.tobytes())
        tmp.replace(path)

    def column(self, name: str) -> array:
        return self.floats[self.names.index(name)::self.stride]

    def repair_opacity(self) -> int:
        o, stride, floats, repaired = self.names.index("opacity"), self.stride, self.floats, 0
        for i in range(o, len(floats), stride):
            v = floats[i]
            if not math.isfinite(v):
                floats[i] = SAFE_LOGIT if v == math.inf else -SAFE_LOGIT
                repaired += 1
        return repaired

    def keep(self, mask: bytearray | bytes) -> None:
        """Keep only the rows whose mask byte is non-zero."""
        stride, src = self.stride, self.floats
        out = array("f")
        i = 0
        n = self.count
        while i < n:  # copy runs of kept rows in one slice each
            if not mask[i]:
                i += 1
                continue
            j = i
            while j < n and mask[j]:
                j += 1
            out.extend(src[i * stride:j * stride])
            i = j
        self.floats, self.count = out, len(out) // stride

    def finite_rows(self) -> bytearray:
        stride, floats = self.stride, self.floats
        ok = bytearray(b"\x01") * self.count
        for k in range(stride):
            col = floats[k::stride]
            for i, v in enumerate(col):
                if not math.isfinite(v):
                    ok[i] = 0
        return ok


def repair_ply(path: Path) -> dict:
    """Validate a float-only binary little-endian Gaussian PLY and repair
    non-finite opacity in place. Returns vertex count, repair count and the
    position bounds of splats that are not fully transparent."""
    data = path.read_bytes()
    end = data.index(b"end_header") + len(b"end_header")
    end += 2 if data[end:end + 2] == b"\r\n" else 1
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError(f"{path.name}: expected binary_little_endian PLY")
    props = [line.split() for line in header if line.startswith("property")]
    if any(p[1] != "float" for p in props):
        raise ValueError(f"{path.name}: expected float-only vertex properties")
    names = [p[2] for p in props]
    count = int(next(line for line in header if line.startswith("element vertex")).split()[2])
    stride = len(names)
    floats = array("f")
    floats.frombytes(data[end:end + 4 * stride * count])
    if sys.byteorder != "little":
        floats.byteswap()

    o = names.index("opacity")
    repaired = 0
    for i in range(o, len(floats), stride):
        v = floats[i]
        if not math.isfinite(v):
            floats[i] = SAFE_LOGIT if v == math.inf else -SAFE_LOGIT
            repaired += 1
    if repaired:
        out = array("f", floats)
        if sys.byteorder != "little":
            out.byteswap()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data[:end] + out.tobytes() + data[end + 4 * stride * count:])
        tmp.replace(path)

    lo, hi = [math.inf] * 3, [-math.inf] * 3
    x = names.index("x")
    for i in range(0, len(floats), stride):
        if floats[i + o] < -4.0:  # sigmoid < ~2%: effectively invisible
            continue
        for k in range(3):
            v = floats[i + x + k]
            if math.isfinite(v):
                lo[k] = min(lo[k], v)
                hi[k] = max(hi[k], v)
    return {"vertices": count, "repaired_opacity": repaired, "bounds_min": lo, "bounds_max": hi}


# ---------------------------------------------------------------------------
# PNG masks (minimal stdlib decoder)
# ---------------------------------------------------------------------------


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png_mask(data: bytes, threshold: int = 127) -> tuple[int, int, bytearray]:
    """Decode a PNG into a binary mask (1 = on). Supports non-interlaced
    grayscale (1/2/4/8-bit), palette (1/2/4/8-bit), RGB, gray+alpha and RGBA
    (8-bit). A pixel is on when its brightness (max channel; palette colour)
    exceeds ``threshold`` and, with alpha, its alpha does too."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, palette, trns = 8, bytearray(), None, None
    width = height = depth = ctype = interlace = None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = [max(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None:
        raise ValueError("PNG without IHDR")
    if interlace:
        raise ValueError("interlaced PNG masks are not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None:
        raise ValueError(f"unsupported PNG color type {ctype}")
    if depth != 8 and not (ctype in (0, 3) and depth in (1, 2, 4)):
        raise ValueError(f"unsupported PNG bit depth {depth} for color type {ctype}")
    raw = zlib.decompress(bytes(idat))
    bits_pp = channels * depth
    row_bytes = (width * bits_pp + 7) // 8
    bpp = max(1, bits_pp // 8)
    prev = bytearray(row_bytes)
    out = bytearray(width * height)
    p = 0
    for y in range(height):
        ftype = raw[p]
        line = bytearray(raw[p + 1:p + 1 + row_bytes])
        p += 1 + row_bytes
        if ftype == 1:
            for i in range(bpp, row_bytes):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(row_bytes):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(row_bytes):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(row_bytes):
                left = line[i - bpp] if i >= bpp else 0
                upleft = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], upleft)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"bad PNG filter {ftype}")
        prev = line
        base = y * width
        if depth < 8:
            per, maxv = 8 // depth, (1 << depth) - 1
            for x in range(width):
                v = (line[x // per] >> ((per - 1 - x % per) * depth)) & maxv
                if ctype == 3:
                    alpha = trns[v] if trns is not None and v < len(trns) else 255
                    lum = palette[v] if palette and v < len(palette) else 0
                    out[base + x] = 1 if lum > threshold and alpha > threshold else 0
                else:
                    out[base + x] = 1 if v * 255 // maxv > threshold else 0
        elif ctype == 0:
            for x in range(width):
                out[base + x] = 1 if line[x] > threshold else 0
        elif ctype == 3:
            for x in range(width):
                v = line[x]
                alpha = trns[v] if trns is not None and v < len(trns) else 255
                lum = palette[v] if palette and v < len(palette) else 0
                out[base + x] = 1 if lum > threshold and alpha > threshold else 0
        else:
            color = 1 if ctype == 4 else 3
            for x in range(width):
                px = line[x * channels:(x + 1) * channels]
                on = max(px[:color]) > threshold
                if ctype in (4, 6):
                    on = on and px[color] > threshold
                out[base + x] = 1 if on else 0
    return width, height, out


def dilate(mask: bytearray, width: int, height: int, radius: int) -> bytearray:
    """Square (Chebyshev) dilation by ``radius`` pixels, two separable passes."""
    if radius <= 0:
        return bytearray(mask)
    horiz = bytearray(width * height)
    for y in range(height):
        row = mask[y * width:(y + 1) * width]
        prefix = [0] * (width + 1)
        for x in range(width):
            prefix[x + 1] = prefix[x] + row[x]
        base = y * width
        for x in range(width):
            if prefix[min(width, x + radius + 1)] - prefix[max(0, x - radius)]:
                horiz[base + x] = 1
    out = bytearray(width * height)
    for x in range(width):
        col = horiz[x::width]
        prefix = [0] * (height + 1)
        for y in range(height):
            prefix[y + 1] = prefix[y] + col[y]
        for y in range(height):
            if prefix[min(height, y + radius + 1)] - prefix[max(0, y - radius)]:
                out[y * width + x] = 1
    return out


# ---------------------------------------------------------------------------
# Scene cut-out
# ---------------------------------------------------------------------------


def object_depth_limit(pose: dict, bounds: tuple | None = None) -> float | None:
    """Camera-frame depth (z) up to which scene Gaussians inside the object's
    mask belong to the object: its visible surface (centroid / contact point)
    plus a margin that grows with its size. Behind that is background.

    With a verified ``splat_to_cam`` and the object PLY's ``bounds``
    (``(bounds_min, bounds_max)``), the limit also reaches the far side of the
    placed object's box (+ the small margin), so an object that recedes from
    the camera (a sofa seen at an angle) leaves no ghost of its far half in
    the scene splat; capped at ``CUT_MAX_REACH`` x its largest side behind the
    visible surface."""
    obj = pose.get("object") or {}
    zs = [p[2] for p in (obj.get("centroid_cam"), obj.get("base_cam")) if isinstance(p, list) and len(p) == 3]
    if not zs:
        return None
    extent = obj.get("extent_m") or {}
    largest = max([float(v) for v in extent.values() if isinstance(v, (int, float)) and v > 0] or [0.2])
    lo, hi = CUT_DEPTH_MARGIN
    limit = max(zs) + min(hi, max(lo, 0.25 * largest))
    far = _box_far_depth(obj.get("splat_to_cam"), bounds)
    if far is not None and far + lo > limit:
        limit = min(far + lo, max(zs) + max(hi, CUT_MAX_REACH * largest))
    return limit


def _box_far_depth(s2c, bounds) -> float | None:
    """Largest camera z of the object PLY's bounding box under ``splat_to_cam``."""
    if not isinstance(s2c, dict) or not bounds or not scene_layout:
        return None
    try:
        bmin, bmax = [[float(v) for v in b] for b in bounds]
        q, t, s = s2c["rotation_wxyz"], [float(v) for v in s2c["translation"]], float(s2c["scale"])
        rot = scene_layout._quat_to_matrix_wxyz(q)
    except (KeyError, TypeError, ValueError, scene_layout.LayoutError):
        return None
    if len(bmin) != 3 or len(bmax) != 3 or len(t) != 3 or not s > 0:
        return None
    far = max(
        s * sum(rot[2][k] * (bmax[k] if c >> k & 1 else bmin[k]) for k in range(3)) + t[2] for c in range(8)
    )
    return far if math.isfinite(far) else None


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def photo_depth_buffer(ply: GaussianPly, scene: dict) -> tuple:
    """The photo's visible surface: ``(w, h, depth, colour)`` with the nearest
    scene-Gaussian depth per photo pixel (inf where none) and its colour
    (``0.5 + SH_C0 * f_dc``, dict by pixel), pixel centres at integer
    coordinates as in ``cut_scene``."""
    intr = scene.get("intrinsics") or {}
    fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
    w, h = (int(v) for v in scene.get("image_size") or [0, 0])
    zbuf = array("f", [math.inf]) * (w * h)
    colours: dict[int, int] = {}  # pixel -> row of its nearest Gaussian
    xs, ys, zs, op = ply.column("x"), ply.column("y"), ply.column("z"), ply.column("opacity")
    for i in range(ply.count):
        z = zs[i]
        if not z > 1e-6 or not op[i] >= PHOTO_MIN_OPACITY:
            continue
        u = math.floor(fx * xs[i] / z + cx + 0.5)
        v = math.floor(fy * ys[i] / z + cy + 0.5)
        if 0 <= u < w and 0 <= v < h and z < zbuf[v * w + u]:
            zbuf[v * w + u] = z
            colours[v * w + u] = i
    dc = [ply.column(f"f_dc_{j}") for j in range(3)] if all(f"f_dc_{j}" in ply.names for j in range(3)) else None
    photo_rgb = {k: tuple(0.5 + SH_C0 * dc[j][i] for j in range(3)) for k, i in colours.items()} if dc else {}
    return w, h, zbuf, photo_rgb


def object_front_depths(path: Path, s2c: dict, scene: dict, max_points: int = REFINE_MAX_POINTS, want_rows: bool = False):
    """Nearest camera depth per photo pixel of an object PLY placed by ``splat_to_cam``
    (with ``want_rows``: also the row of that front Gaussian and the PLY itself)."""
    intr = scene["intrinsics"]
    fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
    w, h = (int(v) for v in scene["image_size"])
    rot = scene_layout._quat_to_matrix_wxyz(s2c["rotation_wxyz"])
    t = [float(v) for v in s2c["translation"]]
    s = float(s2c["scale"])
    r = [[s * v for v in row] for row in rot]
    ply = GaussianPly.read(path)
    xs, ys, zs, op = ply.column("x"), ply.column("y"), ply.column("z"), ply.column("opacity")
    front: dict[int, float] = {}
    rows_at: dict[int, int] = {}
    for i in range(0, ply.count, max(1, ply.count // max_points)):
        x, y, z = xs[i], ys[i], zs[i]
        if not (op[i] >= OBJECT_MIN_OPACITY and math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        cz = r[2][0] * x + r[2][1] * y + r[2][2] * z + t[2]
        if not cz > 1e-6:
            continue
        u = math.floor(fx * (r[0][0] * x + r[0][1] * y + r[0][2] * z + t[0]) / cz + cx + 0.5)
        v = math.floor(fy * (r[1][0] * x + r[1][1] * y + r[1][2] * z + t[1]) / cz + cy + 0.5)
        if 0 <= u < w and 0 <= v < h:
            k = v * w + u
            if cz < front.get(k, math.inf):
                front[k] = cz
                rows_at[k] = i
    if want_rows:
        return front, rows_at, ply
    return front


def colour_gain(front: dict, rows_at: dict, optly: GaussianPly, photo_rgb: dict, bits, mask_size, size) -> list[float] | None:
    """Per-channel gain matching the scan's visible colour to the photo's inside
    the mask: mean photo colour / mean colour of the scan's front Gaussians over
    the same pixels, clamped to ``COLOUR_GAIN_RANGE``. None without enough pixels."""
    if not photo_rgb or not all(f"f_dc_{j}" in optly.names for j in range(3)):
        return None
    (mw, mh), (w, h) = mask_size, size
    sx, sy = mw / float(w), mh / float(h)
    dc = [optly.column(f"f_dc_{j}") for j in range(3)]
    sums_p, sums_o, n = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0], 0
    for k, i in rows_at.items():
        mx, my = math.floor((k % w + 0.5) * sx), math.floor((k // w + 0.5) * sy)
        pc = photo_rgb.get(k)
        if pc is None or not (0 <= mx < mw and 0 <= my < mh and bits[my * mw + mx]):
            continue
        for j in range(3):
            sums_p[j] += pc[j]
            sums_o[j] += 0.5 + SH_C0 * dc[j][i]
        n += 1
    if n < REFINE_MIN_PIXELS or min(sums_o) <= 0:
        return None
    lo, hi = COLOUR_GAIN_RANGE
    return [round(min(hi, max(lo, sums_p[j] / sums_o[j])), 4) for j in range(3)]


def apply_colour_gain(ply: GaussianPly, gain: list[float]) -> None:
    """colour' = gain * colour on every Gaussian's DC colour (f_dc), in place."""
    stride, floats = ply.stride, ply.floats
    for j in range(3):
        col, g = ply.names.index(f"f_dc_{j}"), float(gain[j])
        for i in range(col, len(floats), stride):
            floats[i] = (g * (0.5 + SH_C0 * floats[i]) - 0.5) / SH_C0


def refine_against_photo(entry: dict, mask: tuple, scene: dict, zbuf: tuple, unity: Path) -> dict | None:
    """Check a verified pose against the photo before its object is cut out.

    1. **Depth**: the placed object's front surface should coincide with the
       photo's visible surface inside the object's mask. Their median depth
       ratio ``k`` (photo / object) is applied as a scale about the camera
       centre (``translation`` and ``scale`` times ``k``): the silhouette in
       the photo is unchanged, only how deep (and so how big) the object sits.
       Applied when off by more than ``REFINE_TOLERANCE``, clamped to
       ``REFINE_RANGE``; the GPU value is kept as ``splat_to_cam_gpu`` and the
       check as ``pose["sync_refine"]`` (catalog copy only).
    2. **Coverage**: the part of the mask the placed object actually covers
       (``cover``, mask resolution). Only that part (plus a thin margin) is cut
       from the scene splat, so a limb or tail the scan misses stays in the
       photo splat instead of leaving a hole.
    3. **Colour**: a per-channel gain (``colour_gain``, clamped) makes the
       scan's visible colours match the photo's; applied to the scan's PLY in
       the Unity library (recorded as ``colour_gain``).

    Returns ``{"cover": bytearray, "info": {...}}`` or None (no verified pose,
    no local PLY or nothing of it lands in the mask)."""
    pose = entry.get("pose") or {}
    obj = pose.get("object") or {}
    s2c = obj.get("splat_to_cam")
    path = unity / entry["unity_path"] if entry.get("unity_path") else None
    if not isinstance(s2c, dict) or path is None or not path.is_file() or not scene_layout:
        return None
    try:
        front, rows_at, optly = object_front_depths(path, s2c, scene, want_rows=True)
    except (KeyError, TypeError, ValueError, OSError, scene_layout.LayoutError):
        return None
    w, h, zb, photo_rgb = zbuf
    mw, mh, bits = mask
    sx, sy = mw / float(w), mh / float(h)
    cover = bytearray(mw * mh)
    pairs = []  # (object depth, photo depth) over mask pixels seen by both
    for k, oz in front.items():
        mx, my = math.floor((k % w + 0.5) * sx), math.floor((k // w + 0.5) * sy)
        if 0 <= mx < mw and 0 <= my < mh and bits[my * mw + mx]:
            cover[my * mw + mx] = 1
            if math.isfinite(zb[k]):
                pairs.append((oz, zb[k]))
    if not any(cover):
        return None
    cover = bytearray(a & b for a, b in zip(dilate(cover, mw, mh, COVER_CLOSE_PX), bits))
    info = {"pixels": len(pairs), "coverage": round(sum(cover) / float(sum(bits) or 1), 4), "depth_factor": 1.0}
    gain = colour_gain(front, rows_at, optly, photo_rgb, bits, (mw, mh), (w, h)) if COLOUR_GAIN_ENABLED else None
    if gain:
        info["colour_gain"] = gain
        if max(abs(g - 1.0) for g in gain) > COLOUR_GAIN_MIN_CHANGE:
            apply_colour_gain(optly, gain)
            optly.write(path)
        else:
            info["colour_gain"] = [1.0, 1.0, 1.0]
    if pairs:
        info["gap_m_before"] = round(_median([oz - pz for oz, pz in pairs]), 4)
    if len(pairs) >= REFINE_MIN_PIXELS:
        k = _median([pz / oz for oz, pz in pairs])
        if abs(k - 1.0) > REFINE_TOLERANCE:
            k = min(REFINE_RANGE[1], max(REFINE_RANGE[0], k))
            obj["splat_to_cam_gpu"] = dict(s2c)
            obj["splat_to_cam"] = {
                "rotation_wxyz": list(s2c["rotation_wxyz"]),
                "translation": [round(k * float(v), 6) for v in s2c["translation"]],
                "scale": round(k * float(s2c["scale"]), 6),
            }
            info["depth_factor"] = round(k, 4)
            info["gap_m_after"] = round(_median([k * oz - pz for oz, pz in pairs]), 4)
    pose["sync_refine"] = info
    return {"cover": cover, "info": info}


def _box_blur_colours(points: list[tuple[int, int, list[float]]], w: int, h: int, radius: int) -> list[list[float]]:
    """Mean colour of the given pixels within a (2r+1)^2 box around each (only given pixels count)."""
    if radius <= 0 or not points:
        return [list(c) for _, _, c in points]
    acc = [array("d", bytes(8 * w * h)) for _ in range(4)]  # r, g, b, count
    for u, v, c in points:
        k = v * w + u
        acc[0][k] += c[0]
        acc[1][k] += c[1]
        acc[2][k] += c[2]
        acc[3][k] += 1.0
    rows_used = sorted({v for _, v, _ in points})
    lo_v, hi_v = max(0, rows_used[0] - radius), min(h - 1, rows_used[-1] + radius)
    for a in acc:  # horizontal then vertical running sums, within the patch's row span
        for v in range(lo_v, hi_v + 1):
            base = v * w
            prefix = [0.0] * (w + 1)
            for x in range(w):
                prefix[x + 1] = prefix[x] + a[base + x]
            for x in range(w):
                a[base + x] = prefix[min(w, x + radius + 1)] - prefix[max(0, x - radius)]
        cols_used = sorted({u for u, _, _ in points})
        for x in range(max(0, cols_used[0] - radius), min(w - 1, cols_used[-1] + radius) + 1):
            prefix = [0.0] * (hi_v - lo_v + 2)
            for i, v in enumerate(range(lo_v, hi_v + 1)):
                prefix[i + 1] = prefix[i] + a[v * w + x]
            for i, v in enumerate(range(lo_v, hi_v + 1)):
                a[v * w + x] = prefix[min(hi_v - lo_v + 1, i + radius + 1)] - prefix[max(0, i - radius)]
    out = []
    for u, v, c in points:
        k = v * w + u
        n = acc[3][k]
        out.append([acc[0][k] / n, acc[1][k] / n, acc[2][k] / n] if n > 0 else list(c))
    return out


def prune_below_support(ply: GaussianPly, scene: dict) -> dict:
    """Drop scene Gaussians clearly below the support plane (depth-edge floaters).

    Height above the plane is ``n . x + offset`` (``support_plane.normal_cam``
    unit up, ``offset`` = camera height). Nothing in a photo lies under the
    floor, and a surface-kind scene (a sofa / table seen from close) is laid
    out with that surface raised, so what hangs below it is SHARP's streaks
    at depth edges. Removed: height < -max(margin, 3 x the plane noise),
    margin ``PRUNE_BELOW_M[kind]``; the noise is the robust spread (MAD) of
    the heights of Gaussians within 10 cm of the plane. Returns counts."""
    plane = scene.get("support_plane") or {}
    normal, offset = plane.get("normal_cam") or scene.get("gravity_up_cam"), plane.get("offset")
    kind = str(plane.get("kind") or "floor").lower()
    if not (isinstance(normal, list) and len(normal) == 3 and isinstance(offset, (int, float))):
        return {"removed": 0, "reason": "no support plane"}
    nn = math.sqrt(sum(float(a) * float(a) for a in normal))
    if nn < 1e-9:
        return {"removed": 0, "reason": "no support plane"}
    n = [float(a) / nn for a in normal]
    xs, ys, zs = ply.column("x"), ply.column("y"), ply.column("z")
    heights = array("f", (n[0] * xs[i] + n[1] * ys[i] + n[2] * zs[i] + offset for i in range(ply.count)))
    near = sorted(v for v in heights if abs(v) < 0.1)
    noise = 0.0
    if len(near) > 100:
        med = near[len(near) // 2]
        noise = 1.4826 * sorted(abs(v - med) for v in near)[len(near) // 2]
    margin = max(PRUNE_BELOW_M.get(kind, PRUNE_BELOW_M["floor"]), 3.0 * noise)
    keep = bytearray(1 if not heights[i] < -margin else 0 for i in range(ply.count))
    removed = ply.count - sum(keep)
    if removed:
        ply.keep(keep)
    return {"removed": removed, "margin_m": round(margin, 4), "plane_noise_m": round(noise, 4), "kind": kind}


def fill_under_cut(ply: GaussianPly, scene: dict, cutters: list[dict], keep: bytearray) -> dict[str, int]:
    """Patch the surface under each cut object (call after ``cut_scene``).

    For every photo pixel of a cutter's cut region (its mask, dilated as the
    cut was) the ray is intersected with the plane through the object's
    contact point ``base`` (camera frame) perpendicular to gravity, i.e. the
    surface it rests on; points beyond the cut's depth limit are skipped (that
    ray misses the surface under the object). Each gets one small opaque
    Gaussian whose colour blends (inverse distance) the nearest kept scene
    pixels left / right / above / below it among those within ``FILL_RING_PX``
    of the region that lie on that surface (``FILL_DEPTH_TOL``), else their
    median. The placed object hides the
    patch from the photo's view; lifting the object shows the surface.
    ``cutters`` need ``"base"`` (camera-frame point) to be filled; ``keep`` is
    ``cut_scene``'s keep mask over the original rows. Returns rows added."""
    intr = scene.get("intrinsics") or {}
    fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
    w, h = (int(v) for v in scene.get("image_size") or [0, 0])
    up = scene.get("gravity_up_cam")
    if not (isinstance(up, list) and len(up) == 3) or w <= 0 or h <= 0:
        return {}
    names = ply.names
    need = ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0")
    if not all(n in names for n in need):
        return {}
    # Colour / depth buffer of the kept scene: nearest kept Gaussian per pixel. ``keep`` refers to
    # the rows before the cut, so rebuild from the kept rows now in ``ply``.
    xs, ys, zs = ply.column("x"), ply.column("y"), ply.column("z")
    c0, c1, c2 = ply.column("f_dc_0"), ply.column("f_dc_1"), ply.column("f_dc_2")
    op = ply.column("opacity")
    zbuf = array("f", [math.inf]) * (w * h)
    col = {}
    for i in range(ply.count):
        z = zs[i]
        if not z > 1e-6 or not op[i] >= 0.0:
            continue
        u = math.floor(fx * xs[i] / z + cx + 0.5)
        v = math.floor(fy * ys[i] / z + cy + 0.5)
        if 0 <= u < w and 0 <= v < h and z < zbuf[v * w + u]:
            zbuf[v * w + u] = z
            col[v * w + u] = (c0[i], c1[i], c2[i])
    added: dict[str, int] = {}
    rows = array("f")
    stride = len(names)
    idx = {n: names.index(n) for n in names}
    for c in cutters:
        base = c.get("base")
        if not (isinstance(base, list) and len(base) == 3):
            continue
        mw, mh, bits = c["mask"]
        region_m = dilate(bytearray(bits), mw, mh, c.get("radius_used", 0))
        sx, sy = mw / float(w), mh / float(h)
        region = bytearray(w * h)
        for v in range(h):
            my = min(mh - 1, math.floor((v + 0.5) * sy))
            for u in range(w):
                if region_m[my * mw + min(mw - 1, math.floor((u + 0.5) * sx))]:
                    region[v * w + u] = 1
        n_up = math.sqrt(sum(float(a) * float(a) for a in up))
        n = [float(a) / n_up for a in up]
        d0 = sum(n[i] * float(base[i]) for i in range(3))

        def plane_depth(u: int, v: int) -> float | None:
            """Depth where pixel (u, v)'s ray meets the surface under the object."""
            dx, dy = (u - cx) / fx, (v - cy) / fy
            denom = n[0] * dx + n[1] * dy + n[2]
            if abs(denom) < 1e-6:
                return None
            t = d0 / denom  # point = t * (dx, dy, 1): its depth is t
            return t if t > 1e-3 else None

        # Colour sources: kept scene pixels just around the region that lie ON that surface
        # (within FILL_DEPTH_TOL), so leftovers of the object (a tail) or other things lying
        # there don't bleed into the patch.
        grown = dilate(region, w, h, FILL_RING_PX)
        by_row: dict[int, list[int]] = {}
        by_col: dict[int, list[int]] = {}
        src = []
        for k in range(w * h):
            if grown[k] and not region[k] and k in col:
                u, v = k % w, k // w
                t = plane_depth(u, v)
                if t is not None and abs(zbuf[k] - t) <= FILL_DEPTH_TOL:
                    by_row.setdefault(v, []).append(u)
                    by_col.setdefault(u, []).append(v)
                    src.append(col[k])
        if not src:
            continue
        median = [sorted(cc[j] for cc in src)[len(src) // 2] for j in range(3)]
        fills = []  # (u, v, depth, colour)
        for v in range(h):
            row = region[v * w:(v + 1) * w]
            if not any(row):
                continue
            us = by_row.get(v, [])  # built in increasing u
            for u in range(w):
                if not row[u]:
                    continue
                t = plane_depth(u, v)
                if t is None or t > c["z_limit"]:
                    continue  # this ray misses the surface under the object
                # Inverse-distance blend of the nearest surface pixels left / right / above / below.
                picks = []
                j = bisect.bisect_left(us, u)
                if j > 0:
                    picks.append((u - us[j - 1], (v * w + us[j - 1])))
                if j < len(us):
                    picks.append((us[j] - u, (v * w + us[j])))
                vs = by_col.get(u, [])
                j = bisect.bisect_left(vs, v)
                if j > 0:
                    picks.append((v - vs[j - 1], (vs[j - 1] * w + u)))
                if j < len(vs):
                    picks.append((vs[j] - v, (vs[j] * w + u)))
                if picks:
                    wsum = sum(1.0 / max(1, d) for d, _ in picks)
                    colour = [sum(col[k][ch] / max(1, d) for d, k in picks) / wsum for ch in range(3)]
                else:
                    colour = median
                fills.append((u, v, t, colour))
        # Box-blur the patch colours (over patch pixels only) so row / column picks don't streak.
        blurred = _box_blur_colours([(u, v, colour) for u, v, _, colour in fills], w, h, FILL_BLUR_PX)
        for (u, v, t, _), colour in zip(fills, blurred):
            size = math.log(FILL_SIZE_PX * t / fx)
            dx, dy = (u - cx) / fx, (v - cy) / fy
            values = dict.fromkeys(names, 0.0)
            values.update({"x": t * dx, "y": t * dy, "z": t, "f_dc_0": colour[0], "f_dc_1": colour[1],
                           "f_dc_2": colour[2], "opacity": FILL_OPACITY, "scale_0": size, "scale_1": size,
                           "scale_2": size, "rot_0": 1.0})
            rows.extend(values[nm] for nm in names)
        count = len(fills)
        added[c["asset_id"]] = count
    if rows:
        ply.floats.extend(rows)
        ply.count += len(rows) // stride
    return added


def cut_scene(ply: GaussianPly, scene: dict, cutters: list[dict]) -> dict:
    """Remove each cutter's Gaussians from ``ply`` in place.

    ``cutters``: ``{"asset_id", "mask": (w, h, bytes), "z_limit"}``. A Gaussian
    is removed when its centre projects (scene.json intrinsics) into the
    dilated mask and its depth is <= ``z_limit``. Returns counts."""
    intr = scene.get("intrinsics") or {}
    fx, fy, cx, cy = (float(intr[k]) for k in ("fx", "fy", "cx", "cy"))
    img_w, img_h = (int(v) for v in scene.get("image_size") or [0, 0])
    prepared = []
    for c in cutters:
        mw, mh, bits = c["mask"]
        radius = c.get("radius")
        if radius is None:
            radius = max(1, round(CUT_DILATE_FRAC * math.hypot(mw, mh)))
        c["radius_used"] = radius
        prepared.append(
            {
                "asset_id": c["asset_id"], "w": mw, "h": mh, "z": c["z_limit"],
                "bits": dilate(bytearray(bits), mw, mh, radius), "sx": mw / (img_w or mw), "sy": mh / (img_h or mh),
                "removed": 0,
            }
        )
    xs, ys, zs = ply.column("x"), ply.column("y"), ply.column("z")
    keep = bytearray(b"\x01") * ply.count
    for i in range(ply.count):
        z = zs[i]
        if not z > 1e-6:
            continue
        u = fx * xs[i] / z + cx
        v = fy * ys[i] / z + cy
        for c in prepared:
            if z > c["z"]:
                continue
            mx = int(math.floor((u + 0.5) * c["sx"]))
            my = int(math.floor((v + 0.5) * c["sy"]))
            if 0 <= mx < c["w"] and 0 <= my < c["h"] and c["bits"][my * c["w"] + mx]:
                keep[i] = 0
                c["removed"] += 1
                break
    before = ply.count
    finite = ply.finite_rows()
    dropped_nonfinite = 0
    for i in range(before):
        if keep[i] and not finite[i]:
            keep[i] = 0
            dropped_nonfinite += 1
    ply.keep(keep)
    return {
        "before": before,
        "after": ply.count,
        "removed": {c["asset_id"]: c["removed"] for c in prepared},
        "dropped_nonfinite": dropped_nonfinite,
        "keep": keep,
    }


def coarse_depth_grid(scene: dict, size: tuple[int, int] = CATALOG_GRID) -> dict | None:
    """The scene's depth grid resampled (nearest cell) to ``size`` so the
    catalog stays small but still knows where the photo's content is.

    scene.json lists only the valid cells in ``points_cam`` (row-major) and
    marks them in ``depth_grid_valid`` (base64, bit i = byte i // 8, bit
    i % 8, LSB first; [] when every cell is valid). The result lists only its
    valid samples, with its own ``depth_grid_valid``-free form: ``w`` x ``h``
    = number of points x 1."""
    grid = scene.get("depth_grid")
    if not isinstance(grid, dict):
        return None
    w, h = int(grid.get("w") or 0), int(grid.get("h") or 0)
    pts = grid.get("points_cam") or []
    if w <= 0 or h <= 0:
        return None
    valid = scene.get("depth_grid_valid")
    if len(pts) == 3 * w * h or not (isinstance(valid, str) and valid):
        is_valid = [True] * (w * h)
    else:
        import base64

        try:
            bits = base64.b64decode(valid)
        except ValueError:
            return None
        if len(bits) * 8 < w * h:
            return None
        is_valid = [bool(bits[i >> 3] >> (i & 7) & 1) for i in range(w * h)]
    index, k = {}, 0
    for i, ok in enumerate(is_valid):
        if ok:
            index[i] = k
            k += 1
    if 3 * k != len(pts):
        return None  # the bitmask doesn't match the listed points
    gw, gh = size
    out = []
    for gy in range(gh):
        for gx in range(gw):
            x, y = min(w - 1, int((gx + 0.5) * w / gw)), min(h - 1, int((gy + 0.5) * h / gh))
            j = index.get(y * w + x)
            if j is None:
                continue
            p = pts[3 * j:3 * j + 3]
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) and p[2] > 0:
                out.append([round(float(v), 4) for v in p])
    return {"w": len(out), "h": 1, "points_cam": [v for p in out for v in p], "resampled_from": [w, h]}


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def _existing_catalog() -> dict:
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"assets": [], "scenes": []}
    return {"assets": list(data.get("assets", [])), "scenes": list(data.get("scenes", []))}


def merge_catalog(existing: dict, assets: list[dict], scenes: list[dict]) -> dict:
    merged_assets = {a["asset_id"]: a for a in existing.get("assets", []) if a.get("asset_id")}
    merged_assets.update({a["asset_id"]: a for a in assets})
    merged_scenes = {s["scene_id"]: s for s in existing.get("scenes", []) if s.get("scene_id")}
    merged_scenes.update({s["scene_id"]: s for s in scenes})
    return {"assets": list(merged_assets.values()), "scenes": list(merged_scenes.values())}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "asset"


def _r(values, digits: int = 4) -> list[float]:
    return [round(float(v), digits) for v in values]


# ---------------------------------------------------------------------------
# Quest copies (<name>_quest.ply)
# ---------------------------------------------------------------------------


def is_quest_copy(path) -> bool:
    return Path(path).stem.endswith(QUEST_SUFFIX)


def quest_path(ply) -> Path:
    """``.../boat_c1e624fe.ply`` -> ``.../boat_c1e624fe_quest.ply`` (what RoomKit looks for)."""
    ply = Path(ply)
    return ply.with_name(ply.stem + QUEST_SUFFIX + ply.suffix)


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta")


def quest_meta_text(source_meta: Path) -> str:
    """The copy's ``.meta``: the source's (same Gsplat importer settings) with a new GUID, or the
    Gsplat importer's defaults when Unity hasn't imported the source yet (no ``.meta``)."""
    guid = uuid.uuid4().hex  # 32 hex digits, like Unity's
    try:
        text = source_meta.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if not _GUID_LINE.search(text) or "ScriptedImporter:" not in text:
        return GSPLAT_META_TEMPLATE.format(guid=guid)
    return _GUID_LINE.sub(f"guid: {guid}", text, count=1)


def _move_into_place(staged: Path, dest: Path) -> None:
    try:
        os.replace(staged, dest)  # atomic on one volume
    except OSError:
        shutil.move(str(staged), str(dest))  # stage on another drive: copy + delete


def make_quest_copy(src, budget: int, *, stage: Path = QUEST_STAGE_DIR, max_scale_up: float = QUEST_MAX_SCALE_UP,
                    force: bool = False) -> dict:
    """Write ``<src>_quest.ply`` next to ``src``: its ``budget`` most important splats
    (``decimate_splats.decimate``), or a plain copy when it has no more than that.

    Unity must never see a half-written PLY or a PLY without its ``.meta`` (it would give the
    copy its own GUID), so the copy is written in ``stage`` (outside ``Assets``), a new copy's
    ``.meta`` is moved in first, then the PLY. An existing copy keeps its ``.meta`` (and so its
    GUID: rooms that use it keep working). A copy newer than its source with the expected splat
    count is left alone unless ``force``.

    Returns ``{"path", "action": "made"|"copied"|"current"|"failed", "source", "kept", "scale_up", "error"?}``."""
    src = Path(src)
    dst = quest_path(src)
    dst_meta = _meta_path(dst)
    info = {"path": dst, "action": "failed", "source": None, "kept": None, "scale_up": 1.0}
    try:
        _, _, count = decimate_splats.read_header(src)
        info["source"] = count
        want = min(budget, count)
        if not force and dst.is_file() and dst_meta.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            try:
                _, _, have = decimate_splats.read_header(dst)
            except (ValueError, OSError):
                have = None
            if have == want:
                info.update(action="current", kept=have)
                return info
        stage = Path(stage)
        stage.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        staged = stage / f"{token}_{dst.name}"
        staged_meta = stage / f"{token}_{dst_meta.name}"
        try:
            if count <= budget:
                shutil.copyfile(src, staged)
                info.update(action="copied", kept=count)
            else:
                stats = decimate_splats.decimate(src, staged, budget, max_scale_up)
                info.update(action="made", kept=stats["kept"], scale_up=stats["scale_up"])
            if not dst_meta.is_file():
                staged_meta.write_text(quest_meta_text(_meta_path(src)), encoding="utf-8", newline="\n")  # LF, as Unity writes
                _move_into_place(staged_meta, dst_meta)  # the .meta is in Assets before the PLY
            _move_into_place(staged, dst)
        finally:
            for leftover in (staged, staged_meta, staged.with_name(staged.name + ".writing")):
                if leftover.exists():
                    leftover.unlink()
    except (ValueError, OSError) as exc:
        info.update(action="failed", error=f"{type(exc).__name__}: {exc}")
    return info


def quest_budget(rel_path: str, *, object_splats: int, scene_splats: int) -> int:
    """Photo scenes (``Assets/SketchScape/Scenes/...``) get the scene budget, everything else the object one."""
    return scene_splats if rel_path.replace("\\", "/").startswith(SCENES_DIR + "/") else object_splats


def project_splats(unity: Path) -> list[str]:
    """Every synced splat in the Unity project (not the ``_quest`` copies), as project-relative paths."""
    found = []
    for pattern in (f"{LIBRARY_DIR}/*.ply", f"{SCENES_DIR}/*/*.ply"):
        for path in sorted(Path(unity).glob(pattern)):
            if path.is_file() and not is_quest_copy(path):
                found.append(path.relative_to(unity).as_posix())
    return found


def make_quest_copies(unity: Path, rel_paths, *, object_splats: int = QUEST_OBJECT_SPLATS,
                      scene_splats: int = QUEST_SCENE_SPLATS, stage: Path = QUEST_STAGE_DIR, force: bool = False) -> list[dict]:
    """``make_quest_copy`` for each project-relative splat path (``_quest`` copies and missing
    files are skipped with a note); prints one line each and never raises for a bad file."""
    results = []
    for rel in dict.fromkeys(rel_paths):
        if not rel:
            continue
        rel = str(rel).replace("\\", "/")
        src = Path(unity) / rel
        if is_quest_copy(src) or src.suffix.lower() != ".ply":
            print(f"quest  {rel}: skipped (not a source splat)")
            continue
        if not src.is_file():
            print(f"quest  {rel}: skipped (missing)")
            results.append({"path": quest_path(src), "action": "failed", "source": None, "kept": None,
                            "scale_up": 1.0, "error": "source missing"})
            continue
        budget = quest_budget(rel, object_splats=object_splats, scene_splats=scene_splats)
        info = make_quest_copy(src, budget, stage=stage, force=force)
        name = info["path"].name
        if info["action"] == "failed":
            print(f"quest  {name}: FAILED ({info.get('error')})")
        elif info["action"] == "current":
            print(f"quest  {name}: up to date ({info['kept']:,} splats)")
        else:
            print(f"quest  {name}: {info['kept']:,} of {info['source']:,} splats"
                  + (f", scale x{info['scale_up']:.2f}" if info["action"] == "made" else ", copied as is"))
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync_asset(asset: dict, *, bucket: str, library: Path, tmp: Path) -> dict:
    job = asset["reconstruction_job_id"]
    label = (asset.get("label") or "object").strip() or "object"
    name = f"{_slug(label)}_{asset['asset_id'][:8]}.ply"
    local = tmp / name
    key = f"artifacts/{job}/reconstruction.ply"
    _aws("s3", "cp", f"s3://{bucket}/{key}", str(local), "--only-show-errors")
    info = repair_ply(local)
    shutil.copyfile(local, library / name)
    size = _r(info["bounds_max"][k] - info["bounds_min"][k] for k in range(3))

    pose = asset.get("pose")
    if not is_pose_v2(pose):
        pose_file = tmp / f"{job}_pose.json"
        if _s3_get(bucket, f"artifacts/{job}/pose.json", pose_file):
            try:
                s3_pose = json.loads(pose_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                s3_pose = None
            if is_pose_v2(s3_pose) or (s3_pose and not pose):
                pose = s3_pose

    mask = None
    mask_file = tmp / f"{job}_mask.png"
    if _s3_get(bucket, f"artifacts/{job}/mask.png", mask_file):
        try:
            mask = decode_png_mask(mask_file.read_bytes())
        except (ValueError, zlib.error) as exc:
            print(f"  ! {label}: mask.png unreadable ({exc})")
    area = None
    if is_pose_v2(pose) and isinstance(pose["object"].get("mask_area_frac"), (int, float)):
        area = float(pose["object"]["mask_area_frac"])
    elif mask is not None:
        area = sum(mask[2]) / float(mask[0] * mask[1])

    photo = photo_key(asset)
    version = (pose or {}).get("version") if isinstance(pose, dict) else None
    print(
        f"{label:16} {name:34} {info['vertices']:>8} splats, repaired {info['repaired_opacity']}, "
        f"extent {size}, pose v{version or '-'}, mask {'%.3f' % area if area is not None else '-'}"
    )
    entry = {
        "label": label,
        "asset_id": asset["asset_id"],
        "project_id": asset.get("project_id"),
        "upload_id": upload_id_of(photo),
        "job_id": job,
        "unity_path": f"{LIBRARY_DIR}/{name}",
        "source": f"s3://{bucket}/{key}",
        "vertices": info["vertices"],
        "repaired_opacity": info["repaired_opacity"],
        "native_extent": size,
        "bounds_min": _r(info["bounds_min"]),
        "bounds_max": _r(info["bounds_max"]),
        "photo": photo,
        "pose": pose,
        "mask_area_frac": round(area, 5) if area is not None else None,
    }
    return {"entry": entry, "mask": mask}


def sync_scene(upload_id: str, synced: list[dict], *, bucket: str, project_id: str, unity: Path, tmp: Path) -> dict | None:
    prefix = f"artifacts/scenes/{upload_id}/"
    present = _s3_list(bucket, prefix)
    if "scene.json" not in present:
        print(f"scene {upload_id[:8]}: no scene.json yet at s3://{bucket}/{prefix}")
        return None
    scene_dir = tmp / f"scene_{upload_id}"
    scene_dir.mkdir(exist_ok=True)
    _aws("s3", "cp", f"s3://{bucket}/{prefix}scene.json", str(scene_dir / "scene.json"), "--only-show-errors")
    scene = json.loads((scene_dir / "scene.json").read_text(encoding="utf-8"))
    if scene_layout:
        ms = (scene.get("splat") or {}).get("metric_scale") or {}
        print(f"scene {upload_id[:8]}: geometry {scene_layout.scene_geometry(scene)}"
              f"{' (metric scale: ' + str(ms.get('source')) + ')' if ms else ''}")
    analysis = {}
    if "analysis.json" in present and _s3_get(bucket, prefix + "analysis.json", scene_dir / "analysis.json"):
        try:
            analysis = json.loads((scene_dir / "analysis.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            analysis = {}

    members = [s for s in synced if s["entry"]["upload_id"] == upload_id]
    asset_ids = [s["entry"]["asset_id"] for s in members]
    cut_ids: list[str] = []
    unity_path = ""
    stats = None
    splat_file = (scene.get("splat") or {}).get("file") or "scene.ply"
    if splat_file in present:
        local = scene_dir / "scene.ply"
        _aws("s3", "cp", f"s3://{bucket}/{prefix}{splat_file}", str(local), "--only-show-errors")
        ply = GaussianPly.read(local)
        repaired = ply.repair_opacity()
        pruned = prune_below_support(ply, scene)
        print(f"scene {upload_id[:8]}: below-support floaters pruned: {pruned}")
        cutters = []
        zbuf = None
        refined: dict[str, dict] = {}
        for s in members:
            e, pose = s["entry"], s["entry"]["pose"]
            area = e.get("mask_area_frac")
            why = None
            mismatch = scene_layout.pose_frame_mismatch(scene, pose) if scene_layout and is_pose_v2(pose) else None
            if not is_pose_v2(pose):
                why = "no pose v2 (can't be placed where it was)"
            elif mismatch:
                why = f"pose is not in this scene.json's geometry ({mismatch})"
            elif not CUT_UNVERIFIED and not isinstance(pose["object"].get("splat_to_cam"), dict):
                why = "pose not verified (splat_to_cam null): the photo shows it better than an upright guess"
            elif area is None or area >= CUT_MAX_MASK_AREA_FRAC:
                why = f"mask_area_frac {area} >= {CUT_MAX_MASK_AREA_FRAC}: stays in the scene"
            elif s["mask"] is None:
                why = "no mask.png"
            elif object_depth_limit(pose) is None:
                why = "pose without centroid/base"
            if why:
                print(f"  keep {e['label']} ({e['asset_id'][:8]}) in the scene: {why}")
                continue
            cutter = {"asset_id": e["asset_id"], "mask": s["mask"], "base": pose["object"].get("base_cam")}
            if isinstance(pose["object"].get("splat_to_cam"), dict):
                if zbuf is None:
                    zbuf = photo_depth_buffer(ply, scene)
                check = refine_against_photo(e, s["mask"], scene, zbuf, unity)
                if check:
                    mw, mh, _ = s["mask"]
                    cutter["mask"] = (mw, mh, check["cover"])
                    cutter["radius"] = max(1, round(COVER_DILATE_FRAC * math.hypot(mw, mh)))
                    refined[e["asset_id"]] = check["info"]
                    print(f"  check {e['label']} ({e['asset_id'][:8]}) against the photo: {check['info']}")
            bounds = (e["bounds_min"], e["bounds_max"]) if e.get("bounds_min") and e.get("bounds_max") else None
            cutter["z_limit"] = object_depth_limit(pose, bounds)
            print(f"  cut {e['label']} ({e['asset_id'][:8]}) out of the scene: mask {area:.3f}, "
                  f"{'covered part' if 'radius' in cutter else 'whole mask'}, depth <= {cutter['z_limit']:.3f} m")
            cutters.append(cutter)
        stats = cut_scene(ply, scene, cutters)
        stats["before"] += pruned["removed"]  # count from the splat as published
        filled = fill_under_cut(ply, scene, cutters, stats["keep"])
        if filled:
            stats["after"] = ply.count
        cut_ids = [c["asset_id"] for c in cutters]
        out_dir = unity / SCENES_DIR / upload_id[:8]
        out_dir.mkdir(parents=True, exist_ok=True)
        ply.write(out_dir / "scene.ply")
        unity_path = f"{SCENES_DIR}/{upload_id[:8]}/scene.ply"
        print(
            f"scene {upload_id[:8]}: {stats['before']} -> {stats['after']} Gaussians "
            f"(removed {stats['removed']}, surface patched under them {filled}, non-finite dropped {stats['dropped_nonfinite']}, "
            f"opacity repaired {repaired}) -> {unity_path}"
        )
    else:
        print(f"scene {upload_id[:8]}: scene.json but no {splat_file}; catalog only")

    slim = {k: v for k, v in scene.items() if k not in ("depth_grid", "depth_grid_valid")}
    coarse = coarse_depth_grid(scene)
    if coarse:
        slim["depth_grid"] = coarse  # coarse copy (<= 16x12 points) for bounds / spawn in photo_room_layout
    entry = {
        "scene_id": upload_id,
        "project_id": project_id,
        "photo": scene.get("photo") or (members[0]["entry"]["photo"] if members else None),
        "unity_path": unity_path,
        "scene": slim,
        "analysis": analysis,
        "asset_ids": asset_ids,
        "cut_asset_ids": cut_ids,
    }
    if stats:
        entry["cut"] = {"before": stats["before"], "after": stats["after"], "removed": stats["removed"],
                        "below_support_pruned": pruned["removed"]}
        if filled:
            entry["cut"]["filled"] = filled
        if refined:
            entry["cut"]["photo_check"] = refined
    return entry


def layout_preview(scene_entry: dict, assets: list[dict], *, eye: float = 1.6) -> dict | None:
    """What compose_room will get from ``scene_layout.photo_room_layout`` for
    this catalog scene (the objects cut out of the splat are laid out; every
    member when there's no splat), printed so a sync shows the room it made."""
    if not scene_layout:
        return None
    cut = set(scene_entry.get("cut_asset_ids") or [])
    ids = set(scene_entry.get("asset_ids") or [])
    has_splat = bool(scene_entry.get("unity_path"))
    objects = [
        {"id": f"{a.get('label')}_{a['asset_id'][:8]}", "pose": a.get("pose"), "native_extent": a.get("native_extent"),
         "bounds_min": a.get("bounds_min"), "bounds_max": a.get("bounds_max")}
        for a in assets
        if a.get("asset_id") in ids and (a.get("asset_id") in cut or not has_splat)
    ]
    layout = scene_layout.photo_room_layout(scene_entry.get("scene") or None, objects, player_eye_height=eye)
    st = layout["scene_transform"]
    print(f"  layout: support {layout['support']}, camera {layout['camera_world']}, spawn {layout['spawn']}")
    if st:
        print(f"  layout: scene.ply position {st['position']} rotation {st['rotation']} scale {st['scale']}")
    print(f"  layout: bounds {layout['bounds']}")
    for oid, o in layout["objects"].items():
        print(f"  layout: {oid:24} {o['mode']:9} pos {o['position']} rot {o['rotation']} scale {o['scale']} size {o['size_m']} m")
    for note in layout["notes"]:
        print(f"  layout note: {note}")
    return layout


def sync_standalone_scene(scene_id: str, *, bucket: str, unity: Path, tmp: Path, existing: dict) -> dict | None:
    """A photo scene that isn't a project upload (``artifacts/scenes/<id>/``, e.g.
    the eye-level test room ``testroom1``): no objects, nothing cut, project_id "".

    A project upload must go through ``--project-id`` (its objects are cut out
    of the splat), so an id the catalog already knows with objects is refused."""
    known = next((s for s in existing.get("scenes", []) if s.get("scene_id") == scene_id), None)
    if known and (known.get("asset_ids") or known.get("project_id")):
        print(f"scene {scene_id}: belongs to project {known.get('project_id')!r} in the catalog; "
              f"sync it with --project-id {known.get('project_id')} (skipped)")
        return None
    return sync_scene(scene_id, [], bucket=bucket, project_id="", unity=unity, tmp=tmp)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--unity-project", default=str(REPO.parent / "HackGTUnity"))
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--labels", nargs="*", help="only these labels (default: every real label)")
    parser.add_argument("--project-id", help="sync every ready scan of this project and its photos' scenes")
    parser.add_argument(
        "--scene-id", action="append", default=[],
        help="also sync this standalone photo scene (artifacts/scenes/<id>/, no objects, e.g. testroom1); repeatable. "
             "Alone (no --project-id / --labels) it syncs only these scenes.",
    )
    parser.add_argument("--no-colour-gain", action="store_true",
                        help="don't match the colour of cut-out scans to the photo (their PLYs stay as reconstructed)")
    parser.add_argument("--quest-object-splats", type=int, default=QUEST_OBJECT_SPLATS,
                        help=f"splat budget of an object's Quest copy <name>_quest.ply (default {QUEST_OBJECT_SPLATS})")
    parser.add_argument("--quest-scene-splats", type=int, default=QUEST_SCENE_SPLATS,
                        help=f"splat budget of a photo scene's Quest copy scene_quest.ply (default {QUEST_SCENE_SPLATS})")
    parser.add_argument("--no-quest-lod", action="store_true",
                        help="don't write the Quest-sized <name>_quest.ply copies next to the synced splats")
    parser.add_argument("--quest-lod-only", nargs="*", metavar="PATH",
                        help="no AWS and no catalog change: only make / refresh the Quest copies of splats already in "
                             "the Unity project (every AssetLibrary / Scenes PLY, or just these project-relative paths)")
    parser.add_argument("--quest-stage-dir", default=str(QUEST_STAGE_DIR),
                        help="where Quest copies are written before they move into Assets (default %(default)s)")
    args = parser.parse_args(argv)
    global COLOUR_GAIN_ENABLED
    COLOUR_GAIN_ENABLED = not args.no_colour_gain
    if args.quest_object_splats <= 0 or args.quest_scene_splats <= 0:
        parser.error("--quest-object-splats / --quest-scene-splats must be positive")

    unity = Path(args.unity_project)
    quest_opts = {"object_splats": args.quest_object_splats, "scene_splats": args.quest_scene_splats,
                  "stage": Path(args.quest_stage_dir)}
    if args.quest_lod_only is not None:
        if not (unity / "Assets").is_dir():
            print(f"error: {unity} is not a Unity project (no Assets/)", file=sys.stderr)
            return 2
        paths = args.quest_lod_only or project_splats(unity)
        results = make_quest_copies(unity, paths, **quest_opts)
        failed = sum(1 for r in results if r["action"] == "failed")
        print(f"Quest copies: {len(results) - failed} ok, {failed} failed under {unity}. "
              "Refresh the Unity Editor's AssetDatabase so the Gsplat importer imports them.")
        return 1 if failed else 0

    library = unity / LIBRARY_DIR
    library.mkdir(parents=True, exist_ok=True)
    scenes_only = bool(args.scene_id) and not args.project_id and args.labels is None
    chosen: list[dict] = []
    if not scenes_only:
        assets = load_assets(args.table, args.region)
        if args.project_id:
            chosen = pick_project(assets, args.project_id)
        else:
            chosen = pick_newest_per_label(assets, {l.lower() for l in args.labels or []} or None)
        if not chosen and not args.scene_id:
            print("No ready reconstructions found.")
            return 1

    existing = _existing_catalog()
    scenes: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        synced = [sync_asset(a, bucket=args.bucket, library=library, tmp=tmp) for a in chosen]
        if args.project_id:
            uploads = sorted({s["entry"]["upload_id"] for s in synced if s["entry"]["upload_id"]})
            for upload_id in uploads:
                scene = sync_scene(upload_id, synced, bucket=args.bucket, project_id=args.project_id, unity=unity, tmp=tmp)
                if scene:
                    scenes.append(scene)
        for scene_id in dict.fromkeys(args.scene_id):
            if any(s["scene_id"] == scene_id for s in scenes):
                continue  # already synced as a project upload
            scene = sync_standalone_scene(scene_id, bucket=args.bucket, unity=unity, tmp=tmp, existing=existing)
            if scene:
                scenes.append(scene)

    catalog = [s["entry"] for s in synced]
    merged = merge_catalog(existing, catalog, scenes)
    CATALOG_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    for scene in scenes:
        print(f"scene {scene['scene_id'][:8]}: layout preview (as compose_room will see it)")
        try:
            layout_preview(scene, merged["assets"])
        except Exception as exc:  # the preview must never fail a sync
            print(f"  layout preview failed: {type(exc).__name__}: {exc}")
    # Quest copies last: the colour gain above may have rewritten a scan's PLY after it was synced.
    quest_note = "Quest copies off (--no-quest-lod)"
    if not args.no_quest_lod:
        paths = [a["unity_path"] for a in catalog] + [s["unity_path"] for s in scenes if s.get("unity_path")]
        results = make_quest_copies(unity, paths, **quest_opts)
        failed = sum(1 for r in results if r["action"] == "failed")
        quest_note = f"{len(results) - failed} Quest copies ok" + (f", {failed} FAILED (rooms render those full-res)" if failed else "")
    posed = sum(1 for a in catalog if is_pose_v2(a.get("pose")))
    shown = CATALOG_PATH.relative_to(REPO) if CATALOG_PATH.is_relative_to(REPO) else CATALOG_PATH
    print(
        f"Wrote {len(catalog)} asset(s) ({posed} with a pose v2) and {len(scenes)} scene(s) under {unity}; "
        f"{quest_note}; catalog now has {len(merged['assets'])} assets / {len(merged['scenes'])} scenes in {shown}."
    )
    print("Next: refresh the Unity Editor's AssetDatabase so the Gsplat importer imports them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
