"""Subject labeling for uploaded photos (Build Plan step 4a).

When a contributor uploads a photo without typing a ``subject_hint``,
NemoClaw's ``identify_subject`` tool looks at the image, decides which object
is the subject, and returns a short noun phrase SAM 3.1 can segment
("wicker armchair", not "the chair left of the table").

Backends:

- ``mock`` (default): deterministic and offline. Derives a label from a
  descriptive upload filename ("blue-backpack.jpg" -> "blue backpack") and
  returns no label for camera-style names ("IMG_1234.jpg"). No model call.

- ``nemoclaw``: runs inside the NemoClaw agent on its Llama vision runtime.
  Not available until the runtime is set up (Build Plan step 3); selecting it
  earlier raises ``SubjectLabelError`` so nothing silently falls back to a
  standalone model call that bypasses NemoClaw.

Backend is selected by ``SKETCHSCAPE_SUBJECT_LABELER`` (``mock`` | ``nemoclaw``).

A label is a reading of the photo, not a guess: when no confident label is
available the backend returns ``None`` and the job keeps the worker's normal
``mask_review`` behaviour.
"""

from __future__ import annotations

import os
import re
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


class NemoClawSubjectLabeler(SubjectLabeler):
    """Placeholder for the live tool; it runs inside the NemoClaw runtime."""

    def identify_subject(self, image_path: Path, original_filename: str) -> Optional[SubjectLabel]:  # noqa: ARG002
        raise SubjectLabelError(
            "The NemoClaw identify_subject tool needs the NemoClaw runtime "
            "(Build Plan step 3). Use SKETCHSCAPE_SUBJECT_LABELER=mock until then."
        )


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
