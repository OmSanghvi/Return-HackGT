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
    """Raise 422 if the prompt's text is empty or too long."""
    text = getattr(prompt, "text", None)
    if not text or not str(text).strip():
        raise HTTPException(422, "A selection needs a non-empty text prompt.")
    if len(str(text)) > 100:
        raise HTTPException(422, "A selection's text prompt must be ≤100 characters.")


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


def render_mock_mask(width: int, height: int, prompt: Any) -> Image.Image:
    """Deterministic white-on-black mask for mock segment jobs: a centered ellipse."""
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    rx, ry = width // 4, height // 4
    cx, cy = width // 2, height // 2
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    return mask


def write_mask_png(path: Path, mask: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.save(path, format="PNG")
