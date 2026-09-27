#!/usr/bin/env python3
"""NemoClaw ``identify_subject``, live path (Build Plan step 4a).

Runs **inside the NemoClaw sandbox** (deployed as the
``sketchscape-subject-labeler`` OpenClaw skill): it sends the photo to the
sandbox's managed inference endpoint (``https://inference.local/v1``), i.e.
whatever model NemoClaw is configured with (Muse Spark), with NemoClaw
injecting the credentials. No key is ever visible here, and nothing calls a
model API from outside NemoClaw.

Labels are SAM 3.1 concept prompts: a noun plus one or two attributes
("brown tabby cat"), never a relational sentence. With ``--mask``, the second
image is a binary mask and the model names only the masked object; that is
how existing reconstructions are relabeled from their ``mask.png``.

Standard library only (the sandbox has no extra packages).

    python3 nemoclaw_vision.py <image> [--mask <mask.png>] [--max 8] [--model muse-spark-1.3] [--cleanup]

Prints one JSON line: {"labels": [...], "backend": "nemoclaw:<model>"}.
Exit 1 with {"error": ...} on failure.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

INFERENCE_URL = "https://inference.local/v1/chat/completions"
DEFAULT_MODEL = "muse-spark-1.3"
MAX_LABEL_LENGTH = 100
MAX_LABEL_WORDS = 5
# Muse Spark reasons before answering (~1.6k tokens for a busy photo).
MAX_TOKENS = 6000

_ARTICLES = re.compile(r"^(a|an|the|my|our|some|this|that)\s+", re.I)
_RELATIONAL = re.compile(
    r"\b(left of|right of|next to|behind|in front of|on top of|under|beside|near|between|holding|with the)\b", re.I
)
_GENERIC = {"object", "thing", "item", "stuff", "background", "photo", "image", "picture"}

_PHOTO_PROMPT = (
    "List the distinct physical objects in this photo that a person might want as a 3D keepsake, "
    "most prominent first, at most {max} of them. Each must be a short noun phrase: a noun plus one "
    "or two visual attributes (e.g. \"brown tabby cat\", \"blue ceramic mug\"). Never describe positions "
    "or relations. Skip walls, floors and ceilings. "
    'Reply with JSON only: {{"labels": ["...", "..."]}}'
)
_MASK_PROMPT = (
    "The first image is a photo. The second image is a black-and-white mask of the same photo: the white "
    "region marks exactly one object. Name only that masked object as a short noun phrase: a noun plus one "
    "or two visual attributes (e.g. \"gray striped cat\", \"white tv remote\"). Never describe positions "
    'or relations. Reply with JSON only: {"labels": ["..."]}'
)


def _data_url(data: bytes, path: str) -> str:
    suffix = Path(path).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def build_request(
    image: bytes, image_name: str, *, mask: Optional[bytes] = None, max_labels: int = 8, model: str = DEFAULT_MODEL
) -> dict:
    content: list[dict] = [
        {"type": "text", "text": _MASK_PROMPT if mask is not None else _PHOTO_PROMPT.format(max=max_labels)},
        {"type": "image_url", "image_url": {"url": _data_url(image, image_name)}},
    ]
    if mask is not None:
        content.append({"type": "image_url", "image_url": {"url": _data_url(mask, "mask.png")}})
    return {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": content}]}


def clean_label(raw: object) -> Optional[str]:
    """A SAM 3.1-safe noun phrase, or None if the label can't be one."""
    if not isinstance(raw, str):
        return None
    label = re.sub(r"\s+", " ", raw.strip().strip(".,;:!\"'")).lower()
    label = _ARTICLES.sub("", label)
    if (
        not label
        or label in _GENERIC
        or _RELATIONAL.search(label)
        or len(label) > MAX_LABEL_LENGTH
        or len(label.split()) > MAX_LABEL_WORDS
        or not re.search(r"[a-z]{3}", label)
    ):
        return None
    return label


def parse_labels(text: Optional[str], max_labels: int) -> list[str]:
    """Labels from the model's reply: JSON ``{"labels": [...]}`` (possibly
    fenced or surrounded by prose), cleaned, de-duplicated, capped."""
    if not text:
        return []
    match = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(match.group(0) if match else text).get("labels", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    labels: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        label = clean_label(item)
        if label and label not in labels:
            labels.append(label)
    return labels[:max_labels]


def _post(url: str, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def identify(
    image_path: str,
    *,
    mask_path: Optional[str] = None,
    max_labels: int = 8,
    model: str = DEFAULT_MODEL,
    url: str = INFERENCE_URL,
    post: Optional[Callable[[str, dict, float], dict]] = None,
    timeout: float = 180.0,
) -> list[str]:
    body = build_request(
        Path(image_path).read_bytes(),
        image_path,
        mask=Path(mask_path).read_bytes() if mask_path else None,
        max_labels=1 if mask_path else max_labels,
        model=model,
    )
    reply = (post or _post)(url, body, timeout)
    text = ((reply.get("choices") or [{}])[0].get("message") or {}).get("content")
    return parse_labels(text, 1 if mask_path else max_labels)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NemoClaw identify_subject (live, inside the sandbox)")
    parser.add_argument("image")
    parser.add_argument("--mask")
    parser.add_argument("--max", type=int, default=8)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=INFERENCE_URL)
    parser.add_argument("--cleanup", action="store_true", help="delete the input file(s) afterwards")
    args = parser.parse_args(argv)
    try:
        labels = identify(args.image, mask_path=args.mask, max_labels=max(1, args.max), model=args.model, url=args.url)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    finally:
        if args.cleanup:
            for path in (args.image, args.mask):
                if path:
                    Path(path).unlink(missing_ok=True)
    print(json.dumps({"labels": labels, "backend": f"nemoclaw:{args.model}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
