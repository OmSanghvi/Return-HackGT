"""Subject labeling for uploaded photos (Build Plan step 4a).

When a contributor uploads a photo without typing a ``subject_hint``,
NemoClaw's ``identify_subject`` tool looks at the image, decides which object
is the subject, and returns a short noun phrase SAM 3.1 can segment
("wicker armchair", not "the chair left of the table").

Backends:

- ``mock`` (default): deterministic and offline. Derives a label from a
  descriptive upload filename ("blue-backpack.jpg" -> "blue backpack") and
  returns no label for camera-style names ("IMG_1234.jpg"). No model call.

- ``nemoclaw``: the live path. Copies the photo into the NemoClaw sandbox and
  runs the ``sketchscape-subject-labeler`` skill there
  (``nemoclaw_vision.py``), which asks NemoClaw's configured model (Muse
  Spark) through the sandbox's managed ``inference.local`` route. Needs the
  ``nemoclaw`` CLI on this machine: directly on Linux/WSL, or through
  ``wsl.exe`` on Windows (``NEMOCLAW_WSL_DISTRO``, default ``Ubuntu``).
  ``NEMOCLAW_SANDBOX`` defaults to ``sketchscape``. Any failure raises
  ``SubjectLabelError``, so callers keep the no-label behaviour, never a
  standalone model call that bypasses NemoClaw. Each call takes ~20-40 s.

- ``gpu``: the GPU host's own vision model (``worker/vlm_server.py``, loopback
  ``SKETCHSCAPE_VLM_URL``, default ``http://127.0.0.1:8003``) through
  ``POST /v1/detect`` (docs/IMMERSIVE_SCENE_PIPELINE.md section 3). It returns
  every concrete, SAM-promptable object in the photo, most salient first, so an
  upload with no typed names can reconstruct all of them. Any failure (server
  down, timeout, bad JSON) raises ``SubjectLabelError``; callers treat that as
  "no suggestions", never as a failed upload. ``SKETCHSCAPE_VLM_TIMEOUT``
  (seconds, default 90) bounds each call.

Backend is selected by ``SKETCHSCAPE_SUBJECT_LABELER`` (``mock`` | ``nemoclaw`` | ``gpu``).

A label is a reading of the photo, not a guess: when no confident label is
available the backend returns ``None`` and the job keeps the worker's normal
``mask_review`` behaviour.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

MAX_LABEL_LENGTH = 100

# Camera, screenshot, and messaging-app names carry no subject information.
_CAMERA_NAME = re.compile(
    r"^(img|dsc|dscn|pxl|photo|image|screenshot|screen shot|whatsapp image|signal)?[\s_-]*\d[\d\s_-]*$",
    re.IGNORECASE,
)


class SubjectLabelError(RuntimeError):
    """Raised when a labeling backend is misconfigured or fails."""


@dataclass(frozen=True)
class SubjectLabel:
    """NemoClaw's reading of which object an uploaded photo is about."""

    label: str
    backend: str
    # Other plausible subjects, most prominent first. Kept as a list so a
    # capped "reconstruct every object" mode is a flag later, not a rewrite.
    alternatives: list[str] = field(default_factory=list)
    # Optional pixel boxes [x0, y0, x1, y1] keyed by label, when the backend
    # localises objects (the GPU vision server does).
    boxes: dict[str, list[float]] = field(default_factory=dict)


class SubjectLabeler(ABC):
    @abstractmethod
    def identify_subject(self, image_path: Path, original_filename: str) -> Optional[SubjectLabel]:
        """Return the main subject as a SAM 3.1 noun phrase, or ``None``."""


class MockSubjectLabeler(SubjectLabeler):
    """Deterministic, offline stand-in for NemoClaw's vision labeling."""

    def identify_subject(self, image_path: Path, original_filename: str) -> Optional[SubjectLabel]:  # noqa: ARG002
        stem = Path(original_filename or "").stem
        words = re.sub(r"[_\-.]+", " ", stem).strip()
        words = re.sub(r"\s+", " ", words)
        if not words or _CAMERA_NAME.match(words) or not re.search(r"[A-Za-z]{3}", words):
            return None
        return SubjectLabel(label=words.lower()[:MAX_LABEL_LENGTH], backend="mock")


SKILL_DIR = "/sandbox/.openclaw/workspace/skills/sketchscape-subject-labeler"
_SAFE_SUFFIX = re.compile(r"^\.[a-z0-9]{1,5}$")


def max_objects_per_upload() -> int:
    try:
        return max(1, int(os.environ.get("SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD", "8")))
    except ValueError:
        return 8


class NemoClawSubjectLabeler(SubjectLabeler):
    """Live ``identify_subject``: runs inside the NemoClaw sandbox on its model.

    Shell commands only ever contain fixed text, the sandbox name, and random
    hex file names (no quoting), and every ``nemoclaw`` call carries its own
    ``timeout`` inside WSL: a Windows-side timeout around ``wsl.exe`` can
    orphan NemoClaw's lifecycle lock (scripts/unity-mcp-bridge/README.md).
    """

    def __init__(self, *, sandbox: Optional[str] = None, wsl_distro: Optional[str] = None, run=subprocess.run) -> None:
        self.sandbox = sandbox or os.environ.get("NEMOCLAW_SANDBOX", "sketchscape")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.sandbox):
            raise SubjectLabelError(f"invalid NEMOCLAW_SANDBOX {self.sandbox!r}")
        default_distro = "Ubuntu" if os.name == "nt" else ""
        self.wsl_distro = wsl_distro if wsl_distro is not None else os.environ.get("NEMOCLAW_WSL_DISTRO", default_distro)
        self._run = run

    def _bash(self, script: str, stdin: Optional[bytes] = None) -> subprocess.CompletedProcess:
        prefix = ["wsl.exe", "-d", self.wsl_distro, "--"] if self.wsl_distro else []
        return self._run([*prefix, "bash", "-lc", script], input=stdin, capture_output=True, check=False)

    def _stage(self, data: bytes, suffix: str) -> str:
        name = uuid.uuid4().hex + (suffix.lower() if _SAFE_SUFFIX.match(suffix.lower()) else ".img")
        # Staged on the WSL/Linux filesystem, then uploaded: uploading a file
        # freshly written under /mnt/c can arrive as zero bytes.
        staged = self._bash(f"mkdir -p ~/.sketchscape-label && cat > ~/.sketchscape-label/{name}", stdin=data)
        if staged.returncode != 0:
            raise SubjectLabelError(f"could not stage the image for NemoClaw: {_tail(staged.stderr)}")
        uploaded = self._bash(
            f"timeout 90 nemoclaw {self.sandbox} upload ~/.sketchscape-label/{name} /tmp; rc=$?; "
            f"rm -f ~/.sketchscape-label/{name}; exit $rc"
        )
        if uploaded.returncode != 0:
            raise SubjectLabelError(f"nemoclaw upload failed: {_tail(uploaded.stderr)}")
        return f"/tmp/{name}"

    def labels(self, image_path: Path, *, mask_path: Optional[Path] = None, max_labels: int = 8) -> tuple[list[str], str]:
        """All labels (most prominent first) and the backend name. With a
        mask, a single label for the masked object."""
        image = self._stage(Path(image_path).read_bytes(), Path(image_path).suffix)
        mask_arg = f" --mask {self._stage(Path(mask_path).read_bytes(), '.png')}" if mask_path else ""
        result = self._bash(
            f"timeout 300 nemoclaw {self.sandbox} exec -- python3 {SKILL_DIR}/backend/nemoclaw_vision.py "
            f"{image}{mask_arg} --max {int(max_labels)} --cleanup"
        )
        lines = [line for line in result.stdout.decode(errors="replace").splitlines() if line.startswith("{")]
        try:
            payload = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            raise SubjectLabelError(
                f"identify_subject gave no result (exit {result.returncode}): {_tail(result.stdout + result.stderr)}"
            ) from None
        if "error" in payload:
            raise SubjectLabelError(f"identify_subject failed inside NemoClaw: {payload['error']}")
        labels = [str(label)[:MAX_LABEL_LENGTH] for label in payload.get("labels", []) if str(label).strip()]
        return labels, str(payload.get("backend") or "nemoclaw")

    def identify_subject(self, image_path: Path, original_filename: str) -> Optional[SubjectLabel]:  # noqa: ARG002
        labels, backend = self.labels(image_path, max_labels=max_objects_per_upload())
        if not labels:
            return None
        return SubjectLabel(label=labels[0], backend=backend, alternatives=labels[1:])


# Background surfaces SAM should never be asked to cut out as an "object".
_BACKGROUND_NAMES = frozenset(
    {
        "wall", "walls", "floor", "floors", "ceiling", "ceilings", "ground", "sky",
        "background", "room", "scene", "photo", "image", "shadow", "shadows",
        "sunlight", "air",
    }
)
_NAME_CLEAN = re.compile(r"[^0-9A-Za-z' -]+")
_LEADING_ARTICLE = re.compile(r"^(a|an|the|some)\s+")
# "wooden chair 2" / "chair #3": a vision model numbering instances. A text
# prompt can't tell SAM which instance a number means, so they collapse into
# the base name (the first one's box is kept) instead of using up the cap.
_INSTANCE_NUMBER = re.compile(r"\s+(?:no\.?\s*|#)?\d{1,2}$")
MAX_DETECT_RESPONSE_BYTES = 1024 * 1024


def clean_object_names(names: list, *, limit: int) -> list[str]:
    """Short, concrete, SAM-promptable names: trimmed, lower-case, background
    surfaces dropped, case-insensitive duplicates removed, order kept, capped."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in names:
        text = _NAME_CLEAN.sub(" ", str(raw or "")).strip().lower()
        text = _LEADING_ARTICLE.sub("", re.sub(r"\s+", " ", text)).strip()
        text = _INSTANCE_NUMBER.sub("", text).strip()
        text = text[:MAX_LABEL_LENGTH].strip()
        if len(text) < 2 or text in _BACKGROUND_NAMES or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _detect_image_payload(image_path: Path, max_side: int = 1280) -> tuple[bytes, float]:
    """The photo as JPEG bytes, downscaled to ``max_side`` (the vision model
    works at far lower resolution; this keeps the loopback request small),
    and the factor that maps the sent image's pixels back to the photo's.
    Falls back to the original bytes when Pillow is missing or can't read it."""
    data = Path(image_path).read_bytes()
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            original_width = rgb.size[0]
            if max(rgb.size) > max_side:
                rgb.thumbnail((max_side, max_side))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=90)
            return out.getvalue(), original_width / max(1, rgb.size[0])
    except Exception:  # noqa: BLE001 - any decode problem: let the server try the raw bytes
        return data, 1.0


class GpuSubjectLabeler(SubjectLabeler):
    """Every object in the photo, from the GPU host's vision server
    (``POST {SKETCHSCAPE_VLM_URL}/v1/detect``, contract section 3).

    Never raises anything but ``SubjectLabelError``, so a down or slow
    vision server only ever means "no suggestions"."""

    def __init__(self, *, url: Optional[str] = None, timeout: Optional[float] = None, opener=None) -> None:
        self.url = (url or os.environ.get("SKETCHSCAPE_VLM_URL") or "http://127.0.0.1:8003").rstrip("/")
        try:
            self.timeout = float(timeout if timeout is not None else os.environ.get("SKETCHSCAPE_VLM_TIMEOUT", "90"))
        except ValueError:
            self.timeout = 90.0
        self._open = opener or urllib.request.urlopen

    def detect(self, image_path: Path, *, max_objects: int = 12) -> tuple[list[dict], str]:
        """The server's ``objects`` (entries without a string name dropped;
        boxes in the photo's pixels) and a backend name."""
        try:
            image, scale = _detect_image_payload(image_path)
        except OSError as exc:
            raise SubjectLabelError(f"could not read the photo: {exc}") from None
        body = json.dumps(
            {"image_b64": base64.b64encode(image).decode("ascii"), "max_objects": int(max_objects)}
        ).encode()
        request = urllib.request.Request(
            f"{self.url}/v1/detect", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with self._open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_DETECT_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise SubjectLabelError(f"vision server answered HTTP {exc.code}") from None
        except Exception as exc:  # noqa: BLE001 - URLError, timeouts, resets: all mean "unavailable"
            raise SubjectLabelError(f"vision server unavailable: {type(exc).__name__}: {exc}") from None
        if len(raw) > MAX_DETECT_RESPONSE_BYTES:
            raise SubjectLabelError("vision server response is too large")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise SubjectLabelError("vision server returned invalid JSON") from None
        objects = payload.get("objects") if isinstance(payload, dict) else None
        if not isinstance(objects, list):
            raise SubjectLabelError("vision server response has no objects list")
        valid = [item for item in objects if isinstance(item, dict) and isinstance(item.get("name"), str)]
        if scale != 1.0:  # boxes in the photo's own pixels, not the downscaled copy's
            for item in valid:
                box = item.get("box")
                if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                    item["box"] = [round(float(v) * scale, 1) for v in box]
        model = re.sub(r"[^0-9A-Za-z._/:-]+", "-", str(payload.get("model") or "")).strip("-")[:60]
        return valid, f"gpu:{model}" if model else "gpu"

    def identify_subject(self, image_path: Path, original_filename: str) -> Optional[SubjectLabel]:  # noqa: ARG002
        limit = max_objects_per_upload()
        objects, backend = self.detect(image_path, max_objects=max(limit, 12))
        # Salient objects first, then the rest; within each, the largest box
        # first (no box last; model order breaks ties), so the per-upload cap
        # keeps the big furniture a room is made of.
        def by_area(item: dict) -> float:
            box = item.get("box")
            try:
                x0, y0, x1, y1 = (float(v) for v in box)
                return -max(0.0, x1 - x0) * max(0.0, y1 - y0)
            except (TypeError, ValueError):
                return 1.0

        ordered = sorted((o for o in objects if o.get("salient", True) is not False), key=by_area)
        ordered += sorted((o for o in objects if o.get("salient", True) is False), key=by_area)
        names = clean_object_names([o["name"] for o in ordered], limit=limit)
        if not names:
            return None
        boxes: dict[str, list[float]] = {}
        for item in ordered:
            key = clean_object_names([item["name"]], limit=1)
            box = item.get("box")
            if not key or key[0] in boxes or not isinstance(box, list) or len(box) != 4:
                continue
            try:
                boxes[key[0]] = [float(v) for v in box]
            except (TypeError, ValueError):
                continue
        return SubjectLabel(label=names[0], backend=backend, alternatives=names[1:], boxes=boxes)


def _tail(data: bytes) -> str:
    return data.decode(errors="replace").strip()[-300:]


def create_subject_labeler(*, backend: Optional[str] = None) -> SubjectLabeler:
    """Return the configured labeler; ``mock`` unless explicitly overridden."""
    selected = (backend or os.environ.get("SKETCHSCAPE_SUBJECT_LABELER", "mock")).strip().lower()
    if selected in {"", "mock", "test", "demo"}:
        return MockSubjectLabeler()
    if selected == "nemoclaw":
        return NemoClawSubjectLabeler()
    if selected in {"gpu", "vlm"}:
        return GpuSubjectLabeler()
    raise RuntimeError(
        f"Unknown SKETCHSCAPE_SUBJECT_LABELER '{selected}'. Use 'mock', 'nemoclaw' or 'gpu'."
    )
