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

Backend is selected by ``SKETCHSCAPE_SUBJECT_LABELER`` (``mock`` | ``nemoclaw``).

A label is a reading of the photo, not a guess: when no confident label is
available the backend returns ``None`` and the job keeps the worker's normal
``mask_review`` behaviour.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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


def _tail(data: bytes) -> str:
    return data.decode(errors="replace").strip()[-300:]


def create_subject_labeler(*, backend: Optional[str] = None) -> SubjectLabeler:
    """Return the configured labeler; ``mock`` unless explicitly overridden."""
    selected = (backend or os.environ.get("SKETCHSCAPE_SUBJECT_LABELER", "mock")).strip().lower()
    if selected in {"", "mock", "test", "demo"}:
        return MockSubjectLabeler()
    if selected == "nemoclaw":
        return NemoClawSubjectLabeler()
    raise RuntimeError(
        f"Unknown SKETCHSCAPE_SUBJECT_LABELER '{selected}'. Use 'mock' or 'nemoclaw'."
    )
