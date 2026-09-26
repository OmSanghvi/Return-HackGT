#!/usr/bin/env python3
"""Turn a SAM 3.1 text-concept prediction into one Fast-SAM3D mask.

SAM 3.1 returns every instance matching a concept. Fast-SAM3D reconstructs
one object, so this adapter accepts only a clear centre-most instance. The
process exits 2 for review instead of silently unioning two objects into an
invalid 3D reconstruction.

This script is run from the isolated SAM 3.1 environment created by
``bootstrap_sam31_local.sh``. It intentionally has no API key or network call
during inference; its gated weights are downloaded once at bootstrap time.
"""

from __future__ import annotations

import argparse
import gc
import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from ultralytics.models.sam import SAM3SemanticPredictor


def resize_mask(mask: np.ndarray, height: int, width: int) -> np.ndarray | None:
    """Normalize an Ultralytics mask to the original source dimensions."""
    candidate = np.asarray(mask, dtype=bool)
    if candidate.shape == (height, width):
        return candidate
    # Pillow nearest-neighbour preserves a binary segmentation boundary.
    try:
        resized = Image.fromarray(candidate.astype(np.uint8) * 255).resize(
            (width, height), Image.Resampling.NEAREST
        )
    except (TypeError, ValueError):
        return None
    return np.asarray(resized, dtype=np.uint8).astype(bool)


def candidate_masks(results: object, height: int, width: int) -> list[tuple[float, np.ndarray]]:
    candidates: list[tuple[float, np.ndarray]] = []
    for result in results:
        masks = getattr(getattr(result, "masks", None), "data", None)
        if masks is None:
            continue
        raw_masks = masks.detach().float().cpu().numpy()
        confidences = getattr(getattr(result, "boxes", None), "conf", None)
        scores = confidences.detach().float().cpu().numpy() if confidences is not None else []
        for index, raw_mask in enumerate(raw_masks):
            mask = resize_mask(raw_mask > 0.5, height, width)
            if mask is None:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            candidates.append((score, mask))
    return candidates


def choose_one(candidates: list[tuple[float, np.ndarray]], height: int, width: int) -> np.ndarray | None:
    """Pick one object near the photo centre, rejecting implausible masks."""
    ranked: list[tuple[float, float, np.ndarray]] = []
    centre_y, centre_x = height / 2, width / 2
    diagonal = max((height**2 + width**2) ** 0.5, 1.0)
    for confidence, mask in candidates:
        area = float(mask.mean())
        if not 0.005 < area < 0.80:
            continue
        ys, xs = np.nonzero(mask)
        if not len(xs):
            continue
        distance = float(((xs.mean() - centre_x) ** 2 + (ys.mean() - centre_y) ** 2) ** 0.5 / diagonal)
        # A photo for reconstruction should frame one main object. Confidence
        # wins, then proximity; masks far from centre are deliberately weak.
        rank = confidence - 0.85 * distance - 0.15 * abs(area - 0.25)
        ranked.append((rank, confidence, mask))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_rank, best_confidence, best = ranked[0]
    # Two similarly good but spatially separate instances need a user click.
    if len(ranked) > 1:
        next_rank, next_confidence, _ = ranked[1]
        if best_confidence > 0 and next_confidence >= best_confidence * 0.92 and best_rank - next_rank < 0.08:
            return None
    return best


def build_predictor(checkpoint: Path, confidence: float) -> SAM3SemanticPredictor:
    if not torch.cuda.is_available():
        raise RuntimeError("SAM 3.1 segmentation requires an NVIDIA CUDA GPU.")
    image_size = int(os.environ.get("SAM31_IMAGE_SIZE", "512"))
    use_fp16 = os.environ.get("SAM31_FP16", "1").strip().lower() not in {"0", "false", "no"}
    return SAM3SemanticPredictor(
        overrides={
            "conf": confidence,
            "task": "segment",
            "mode": "predict",
            "model": str(checkpoint),
            "device": 0,
            "imgsz": image_size,
            "half": use_fp16,
            "save": False,
            "verbose": False,
        }
    )


def segment(predictor: SAM3SemanticPredictor, image_path: Path, output: Path, prompt: str) -> int:
    """Write one mask for ``prompt``; 0 on success, 2 when a human must review."""
    if not image_path.is_file() or not prompt.strip():
        return 2
    image = Image.open(image_path).convert("RGB")
    height, width = np.asarray(image).shape[:2]
    predictor.set_image(str(image_path))
    results = predictor(text=[prompt.strip()])
    selected = choose_one(candidate_masks(results, height, width), height, width)
    if selected is None:
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((selected * 255).astype(np.uint8), mode="L").save(output)
    return 0


def serve(predictor: SAM3SemanticPredictor, port: int) -> None:
    """Keep SAM 3.1 loaded between jobs. Loopback only; one request at a time."""
    import json
    import tempfile
    from http.server import BaseHTTPRequestHandler, HTTPServer

    # Load weights and run one pass now so the first real job is warm.
    with tempfile.TemporaryDirectory() as tmp:
        warm = Path(tmp) / "warmup.png"
        Image.new("RGB", (256, 256), (128, 128, 128)).save(warm)
        segment(predictor, warm, Path(tmp) / "mask.png", "object")
    print(f"SAM 3.1 server ready on 127.0.0.1:{port}", flush=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _respond(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                self._respond(200, {"status": "ready"})
            else:
                self._respond(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/segment":
                self._respond(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 16 * 1024:
                    raise ValueError("invalid content length")
                body = json.loads(self.rfile.read(length))
                code = segment(predictor, Path(body["image"]), Path(body["output"]), str(body["prompt"]))
            except (ValueError, KeyError, json.JSONDecodeError):
                self._respond(400, {"error": "invalid request"})
                return
            except torch.cuda.OutOfMemoryError:
                # CUDA state is unreliable after OOM; let systemd restart us.
                self._respond(500, {"error": "cuda out of memory"})
                os._exit(1)
            except Exception as exc:  # report, keep the warm model alive
                self._respond(200, {"code": 1, "error": str(exc)[:500]})
                return
            finally:
                torch.cuda.empty_cache()
            self._respond(200, {"code": code})

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prompt", help="Short noun phrase, e.g. 'blue backpack'.")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--serve", action="store_true", help="Keep the model loaded behind a loopback HTTP server.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SAM31_SERVER_PORT", "8002")))
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        return 2

    predictor = build_predictor(args.checkpoint, args.confidence)
    if args.serve:
        serve(predictor, args.port)
        return 0
    if args.image is None or args.output is None or not (args.prompt or "").strip():
        return 2
    code = segment(predictor, args.image, args.output, args.prompt)
    del predictor
    gc.collect()
    torch.cuda.empty_cache()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
