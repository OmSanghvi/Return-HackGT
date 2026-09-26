#!/usr/bin/env python3
"""Create a conservative automatic mask for a single prominent centre object.

Exit code 2 means the image is ambiguous and the caller should request a tap or
box from the user. That is a product outcome, not a reconstruction failure.
"""

from __future__ import annotations

import argparse
import gc
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import pipeline


def normalized_mask(raw_mask: object, height: int, width: int) -> np.ndarray | None:
    candidate = np.asarray(raw_mask, dtype=bool)
    # Some mask-generation outputs transpose portrait images.
    if candidate.shape == (width, height):
        candidate = candidate.T
    if candidate.shape != (height, width):
        return None
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="facebook/sam-vit-base")
    parser.add_argument("--min-area", type=float, default=0.01)
    parser.add_argument("--max-area", type=float, default=0.70)
    args = parser.parse_args()
    image = Image.open(args.image).convert("RGB")
    pixels = np.asarray(image)
    height, width = pixels.shape[:2]
    segmenter = pipeline("mask-generation", model=args.model, device=0 if torch.cuda.is_available() else -1)
    result = segmenter(image, points_per_batch=16, pred_iou_thresh=0.88)
    centre_y, centre_x = height // 2, width // 2
    candidates: list[tuple[float, np.ndarray]] = []
    scores = result.get("scores", [])
    for index, raw_mask in enumerate(result.get("masks", [])):
        candidate = normalized_mask(raw_mask, height, width)
        if candidate is None or not candidate[centre_y, centre_x]:
            continue
        area = float(candidate.mean())
        if not args.min_area < area < args.max_area:
            continue
        score = float(scores[index]) if index < len(scores) else 0.0
        # Prefer a foreground object over a whole-scene/background mask.
        rank = score - 0.20 * abs(area - 0.25)
        candidates.append((rank, candidate))
    del segmenter
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    if not candidates:
        return 2
    mask = max(candidates, key=lambda item: item[0])[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((mask * 255).astype(np.uint8)).save(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
