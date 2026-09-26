"""Upload selection validation, EXIF orientation, and mock segment masks (step 26).

Kept out of ``main.py`` so the durable-jobs path stays readable. Mock mode
draws deterministic masks offline — no GPU, no network.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageOps


def max_objects_per_upload() -> int:
    import os

    return max(1, int(os.environ.get("SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD", "8")))


def job_max_attempts() -> int:
    import os

    return max(1, int(os.environ.get("SKETCHSCAPE_JOB_MAX_ATTEMPTS", "2")))


def job_lease_seconds() -> int:
    import os

    return max(30, int(os.environ.get("SKETCHSCAPE_JOB_LEASE_SECONDS", "900")))


def validate_selection_prompt(prompt: Any) -> None:
    """Raise 422 if the prompt is empty, mixed, or has out-of-range coords."""
    ptype = getattr(prompt, "type", None)
    points = getattr(prompt, "points", None)
    box = getattr(prompt, "box", None)
    text = getattr(prompt, "text", None)

    filled = sum(
        [
            points is not None and len(points) > 0,
            box is not None and len(box) > 0,
            bool(text and str(text).strip()),
        ]
    )
    if filled != 1:
        raise HTTPException(422, "Each selection needs exactly one of points, box, or text.")
    if ptype == "points":
        if not points:
            raise HTTPException(422, "points prompt requires at least one point.")
        for point in points:
            if len(point) != 3:
                raise HTTPException(422, "Each point must be [x, y, 1|0].")
            x, y, flag = point
            if not (0.0 <= float(x) <= 1.0 and 0.0 <= float(y) <= 1.0):
                raise HTTPException(422, "Selection coordinates must be normalized 0–1.")
            if int(flag) not in (0, 1):
                raise HTTPException(422, "Point flag must be 1 (include) or 0 (exclude).")
    elif ptype == "box":
        if not box or len(box) != 4:
            raise HTTPException(422, "box prompt requires [x0, y0, x1, y1].")
        if any(not (0.0 <= float(v) <= 1.0) for v in box):
            raise HTTPException(422, "Selection coordinates must be normalized 0–1.")
    elif ptype == "text":
        if not text or not str(text).strip():
            raise HTTPException(422, "text prompt requires a non-empty string.")
        if len(str(text)) > 100:
            raise HTTPException(422, "text prompt must be ≤100 characters.")
    else:
        raise HTTPException(422, f"Unknown prompt type: {ptype!r}.")


def apply_exif_transpose(image_bytes: bytes) -> tuple[bytes, int, int, str]:
    """Return upright image bytes, width, height, and format suffix (.jpg/.png/.webp)."""
    with Image.open(io.BytesIO(image_bytes)) as img:
        oriented = ImageOps.exif_transpose(img)
        assert oriented is not None
        width, height = oriented.size
        fmt = (oriented.format or img.format or "PNG").upper()
        if fmt == "JPEG":
            suffix = ".jpg"
            save_kwargs: dict[str, Any] = {"format": "JPEG", "quality": 92}
            if oriented.mode not in ("RGB", "L"):
                oriented = oriented.convert("RGB")
        elif fmt == "WEBP":
            suffix = ".webp"
            save_kwargs = {"format": "WEBP", "quality": 92}
        else:
            suffix = ".png"
            save_kwargs = {"format": "PNG"}
        out = io.BytesIO()
        oriented.save(out, **save_kwargs)
        return out.getvalue(), width, height, suffix


def _to_pixels(norm: float, size: int) -> int:
    return max(0, min(size - 1, int(round(float(norm) * (size - 1)))))


def render_mock_mask(width: int, height: int, prompt: Any) -> Image.Image:
    """Deterministic white-on-black mask for mock segment jobs."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    ptype = prompt.type
    if ptype == "box" and prompt.box:
        x0, y0, x1, y1 = prompt.box
        box = [
            _to_pixels(min(x0, x1), width),
            _to_pixels(min(y0, y1), height),
            _to_pixels(max(x0, x1), width),
            _to_pixels(max(y0, y1), height),
        ]
        draw.rectangle(box, fill=255)
    elif ptype == "points" and prompt.points:
        radius = max(8, min(width, height) // 20)
        for x, y, flag in prompt.points:
            cx, cy = _to_pixels(x, width), _to_pixels(y, height)
            fill = 255 if int(flag) == 1 else 0
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=fill)
    else:
        # Text → centered ellipse.
        rx, ry = width // 4, height // 4
        cx, cy = width // 2, height // 2
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    return mask


def write_mask_png(path: Path, mask: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path, format="PNG")
