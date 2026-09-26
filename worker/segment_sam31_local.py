#!/usr/bin/env python3
"""Turn SAM 3.1 text-concept predictions into Fast-SAM3D masks.

Two paths:

* ``choose_one`` / ``segment`` -- the legacy single-object path (one typed
  ``subject_hint`` per photo). SAM 3.1 returns every instance matching the
  concept; this adapter accepts only a clear centre-most instance and exits 2
  for review instead of silently unioning two objects into one invalid 3D
  reconstruction. Unchanged by Build Plan step 27.
* ``segment_selections`` -- Build Plan step 27. The person types a name for
  every object they want in 3D; one SAM 3.1 pass over the photo batches all
  of those typed names into a single predictor call
  (``predictor(text=[...])``), and each selection keeps its own best
  instance plus alternatives. ``segment_many`` is the optional auto-detect
  helper: every instance across a list of concept prompts, deduped and
  capped, not tied to a person's selection.

This script is run from the isolated SAM 3.1 environment created by
``bootstrap_sam31_local.sh``. It intentionally has no API key or network call
during inference; its gated weights are downloaded once at bootstrap time.

Everything below the "adapter boundary" comment only runs on a real GPU
host and is never imported by tests. Everything above it is plain
Python/PIL/NumPy so it can be unit-tested on a CPU machine with a stubbed
predictor -- ``torch`` and ``ultralytics`` are imported lazily, inside the
functions that actually need a GPU, so importing this module for its
testable functions never requires either package to be installed.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


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


def _to_numpy(value: Any) -> np.ndarray:
    """Accept a real torch tensor or a plain array/list; never import torch.

    Real Ultralytics results carry torch tensors (``.detach().float().cpu()
    .numpy()``); a test stub can hand this a plain ``numpy.ndarray`` (or a
    list) directly -- it has no ``.detach``, so it falls straight to
    ``np.asarray``. This is the seam that keeps ``candidate_masks`` runnable
    on a CPU machine with a fake predictor.
    """
    detach = getattr(value, "detach", None)
    if callable(detach):
        return detach().float().cpu().numpy()
    return np.asarray(value)


def _classed_masks(results: object, height: int, width: int) -> list[tuple[float, np.ndarray, int]]:
    """(score, mask, prompt class) for every usable instance; class 0 if untagged."""
    candidates: list[tuple[float, np.ndarray, int]] = []
    for result in results:
        masks = getattr(getattr(result, "masks", None), "data", None)
        if masks is None:
            continue
        raw_masks = _to_numpy(masks)
        boxes = getattr(result, "boxes", None)
        confidences = getattr(boxes, "conf", None)
        scores = _to_numpy(confidences) if confidences is not None else []
        classes = getattr(boxes, "cls", None)
        class_ids = _to_numpy(classes) if classes is not None else []
        for index, raw_mask in enumerate(raw_masks):
            mask = resize_mask(raw_mask > 0.5, height, width)
            if mask is None:
                continue
            score = float(scores[index]) if index < len(scores) else 0.0
            class_id = int(class_ids[index]) if index < len(class_ids) else 0
            candidates.append((score, mask, class_id))
    return candidates


def candidate_masks(results: object, height: int, width: int) -> list[tuple[float, np.ndarray]]:
    return [(score, mask) for score, mask, _class_id in _classed_masks(results, height, width)]


def candidates_per_prompt(
    results: list[object], prompt_count: int, height: int, width: int
) -> list[list[tuple[float, np.ndarray]]]:
    """Per-prompt candidates for a text batch.

    One Results per prompt (positionally aligned) is used as-is. The real
    SAM3SemanticPredictor instead returns ONE Results for the whole batch with
    each instance's prompt index in ``boxes.cls``, so that shape is bucketed
    by class.
    """
    if len(results) == prompt_count:
        return [candidate_masks([result], height, width) for result in results]
    buckets: list[list[tuple[float, np.ndarray]]] = [[] for _ in range(prompt_count)]
    for score, mask, class_id in _classed_masks(results, height, width):
        if 0 <= class_id < prompt_count:
            buckets[class_id].append((score, mask))
    return buckets


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


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection-over-union of two boolean masks; 0.0 if both are empty."""
    a_bool, b_bool = np.asarray(a, dtype=bool), np.asarray(b, dtype=bool)
    union = int(np.count_nonzero(a_bool | b_bool))
    if union == 0:
        return 0.0
    return float(np.count_nonzero(a_bool & b_bool)) / union


_NO_MATCH_REASON = "nothing found matching that name; try being more specific"

# ---------------------------------------------------------------------------
# Build Plan step 27: person-chosen, text-only multi-object segmentation.
# ---------------------------------------------------------------------------


def segment_selections(
    predictor: Any,
    image_path: Path,
    selections: list[tuple[str, str]],
    *,
    min_area_ratio: float = 0.005,
    max_area_ratio: float = 0.90,
    duplicate_iou: float = 0.85,
) -> dict[str, dict[str, Any]]:
    """One SAM 3.1 pass over every selection's typed name for one photo.

    ``selections`` is ``[(selection_id, text), ...]`` -- every pending
    selection for the upload's `segment` job (skill item 1: SAM loads the
    image once, and every selection is a text prompt batched into one
    ``predictor(text=[...])`` call). ``predictor`` is any callable that
    accepts ``text=`` and returns either one results-like object per prompt
    (positionally aligned) or, like the real `SAM3SemanticPredictor`, one
    combined result with each instance's prompt index in ``boxes.cls`` (see
    ``candidates_per_prompt``) -- a real predictor on the GPU, or a stub.

    Returns ``{selection_id: {"status", "score", "mask", "alternatives",
    "reason"}}``. A selection with no usable mask -- nothing above the area
    filter, or flagged as a near-duplicate of a higher-scoring selection --
    is ``"failed"`` with a reason (Hard Rule 7: it never blocks the others).
    """
    if not selections:
        return {}

    image = Image.open(image_path).convert("RGB")
    width, height = image.size

    texts = [text.strip() for _selection_id, text in selections]
    raw_results = predictor(text=texts)
    per_prompt_candidates = candidates_per_prompt(list(raw_results), len(selections), height, width)

    def failed(reason: str) -> dict[str, Any]:
        return {"status": "failed", "score": None, "mask": None, "alternatives": [], "reason": reason}

    outcomes: dict[str, dict[str, Any]] = {}
    chosen_masks: dict[str, np.ndarray] = {}
    for index, (selection_id, _text) in enumerate(selections):
        candidates = [
            (score, mask)
            for score, mask in per_prompt_candidates[index]
            if min_area_ratio < float(mask.mean()) < max_area_ratio
        ]
        if not candidates:
            outcomes[selection_id] = failed(_NO_MATCH_REASON)
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_mask = candidates[0]
        alternatives = [
            {"score": round(float(score), 4), "area_ratio": round(float(mask.mean()), 4)}
            for score, mask in candidates[1:]
        ]
        outcomes[selection_id] = {
            "status": "segmented",
            "score": float(best_score),
            "mask": best_mask,
            "alternatives": alternatives,
            "reason": None,
        }
        chosen_masks[selection_id] = best_mask

    # Cross-selection duplicate flagging (skill item 1): two selections
    # whose chosen masks overlap heavily are almost certainly the same real
    # object picked twice. Keep the higher score, fail the other with a
    # reason instead of reconstructing the same object twice.
    ids = sorted(chosen_masks.keys())
    for i in range(len(ids)):
        id_a = ids[i]
        if outcomes[id_a]["status"] != "segmented":
            continue
        for j in range(i + 1, len(ids)):
            id_b = ids[j]
            if outcomes[id_b]["status"] != "segmented":
                continue
            overlap = mask_iou(chosen_masks[id_a], chosen_masks[id_b])
            if overlap <= duplicate_iou:
                continue
            loser = id_a if outcomes[id_a]["score"] <= outcomes[id_b]["score"] else id_b
            outcomes[loser] = failed(f"duplicate of another selection (IoU {overlap:.2f})")
    return outcomes


def segment_many(
    predictor: Any,
    image_path: Path,
    prompts: list[str],
    *,
    confidence: float = 0.35,
    min_area_ratio: float = 0.005,
    max_area_ratio: float = 0.90,
    duplicate_iou: float = 0.85,
    cap: int = 8,
) -> list[dict[str, Any]]:
    """Optional auto-detect helper (skill item 6): NemoClaw-labelled concept
    prompts, not the person's own selections. Every instance across every
    prompt, thresholded, area-filtered, deduped by IoU, capped, sorted by
    score descending -- the results are only *suggested* selections; nothing
    generates until the person keeps one (Build Plan step 26/27).
    """
    if not prompts:
        return []
    image = Image.open(image_path).convert("RGB")
    width, height = image.size

    raw_results = predictor(text=[prompt.strip() for prompt in prompts])
    candidates = candidate_masks(list(raw_results), height, width)
    candidates = [
        (score, mask)
        for score, mask in candidates
        if score >= confidence and min_area_ratio < float(mask.mean()) < max_area_ratio
    ]
    candidates.sort(key=lambda item: item[0], reverse=True)

    kept: list[tuple[float, np.ndarray]] = []
    for score, mask in candidates:
        if any(mask_iou(mask, kept_mask) > duplicate_iou for _, kept_mask in kept):
            continue
        kept.append((score, mask))
        if len(kept) >= cap:
            break
    return [{"score": float(score), "mask": mask} for score, mask in kept]


def segment(predictor: Any, image_path: Path, output: Path, prompt: str) -> int:
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


# ---------------------------------------------------------------------------
# Adapter boundary: everything below here touches a real GPU (torch,
# ultralytics) and is only exercised on the GPU host, never by unit tests.
# ---------------------------------------------------------------------------


def build_predictor(checkpoint: Path, confidence: float) -> Any:
    import torch
    from ultralytics.models.sam import SAM3SemanticPredictor

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


def _segment_selections_to_disk(
    predictor: Any, image_path: Path, output_dir: Path, selections: list[tuple[str, str]]
) -> dict[str, dict[str, Any]]:
    """``segment_selections`` plus writing one mask PNG per segmented
    selection to ``output_dir/{selection_id}.png`` -- the on-disk contract
    the warm SAM 3.1 server's ``/segment_many`` route and the GPU dispatcher
    (``worker/gpu_dispatcher.py``) share, since masks are too large to
    return inline over HTTP."""
    predictor.set_image(str(image_path))
    outcomes = segment_selections(predictor, image_path, selections)
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict[str, Any]] = {}
    for selection_id, outcome in outcomes.items():
        mask = outcome.pop("mask", None)
        if mask is not None:
            mask_path = output_dir / f"{selection_id}.png"
            Image.fromarray((np.asarray(mask, dtype=bool) * 255).astype(np.uint8), mode="L").save(mask_path)
            outcome["mask_path"] = str(mask_path)
        report[selection_id] = outcome
    return report


def serve(predictor: Any, port: int) -> None:
    """Keep SAM 3.1 loaded between jobs. Loopback only; one request at a time."""
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
            import torch

            if self.path == "/segment":
                self._do_segment()
                return
            if self.path == "/segment_many":
                self._do_segment_many()
                return
            self._respond(404, {"error": "not found"})

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 256 * 1024:
                raise ValueError("invalid content length")
            return json.loads(self.rfile.read(length))

        def _do_segment(self):
            import torch

            try:
                body = self._read_json()
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

        def _do_segment_many(self):
            import torch

            try:
                body = self._read_json()
                image_path = Path(body["image"])
                output_dir = Path(body["output_dir"])
                selections = [(str(item["selection_id"]), str(item["text"])) for item in body["selections"]]
            except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                self._respond(400, {"error": "invalid request"})
                return
            try:
                report = _segment_selections_to_disk(predictor, image_path, output_dir, selections)
            except torch.cuda.OutOfMemoryError:
                self._respond(500, {"error": "cuda out of memory"})
                os._exit(1)
            except Exception as exc:
                self._respond(200, {"error": str(exc)[:500], "results": {}})
                return
            finally:
                torch.cuda.empty_cache()
            self._respond(200, {"results": report})

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
    import torch

    torch.cuda.empty_cache()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
