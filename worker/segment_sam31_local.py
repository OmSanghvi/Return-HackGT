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

# A VLM box and a SAM 3.1 instance "match" when their boxes overlap at least
# this much (IoU); below it the box is treated as unmatched and the
# selection falls back to the plain highest-score instance.
MIN_BOX_IOU = float(os.environ.get("SAM31_MIN_BOX_IOU", "0.1"))
# Box IoUs this close count as a tie, broken by SAM 3.1's confidence.
BOX_IOU_TIE = 0.02


def parse_box(raw: Any) -> list[float] | None:
    """A selection's optional VLM box ``[x0, y0, x1, y1]`` (stored-photo
    pixels) as four finite floats with x1 > x0 and y1 > y0, else None."""
    if raw is None or isinstance(raw, (str, bytes)):
        return None
    try:
        values = [float(value) for value in raw]
    except (TypeError, ValueError):
        return None
    if len(values) != 4 or not all(np.isfinite(values)):
        return None
    x0, y0, x1, y1 = values
    if x1 <= x0 or y1 <= y0:
        return None
    return values


def mask_bbox(mask: np.ndarray) -> tuple[float, float, float, float] | None:
    """Tight pixel box ``(x0, y0, x1, y1)`` of a boolean mask (x1/y1
    exclusive, matching how a detector's box spans whole pixels)."""
    ys, xs = np.nonzero(np.asarray(mask, dtype=bool))
    if not len(xs):
        return None
    return float(xs.min()), float(ys.min()), float(xs.max()) + 1.0, float(ys.max()) + 1.0


def box_iou(a: Any, b: Any) -> float:
    """Intersection-over-union of two ``[x0, y0, x1, y1]`` boxes."""
    ax0, ay0, ax1, ay1 = (float(v) for v in a)
    bx0, by0, bx1, by1 = (float(v) for v in b)
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = iw * ih
    union = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0) + max(0.0, bx1 - bx0) * max(0.0, by1 - by0) - intersection
    return intersection / union if union > 0 else 0.0


def _normalize_selection(item: Any) -> tuple[str, str, list[float] | None]:
    """``(selection_id, text)``, ``(selection_id, text, box)`` or a
    ``{"selection_id", "text", "box"}`` dict -> ``(id, text, box|None)``."""
    if isinstance(item, dict):
        return str(item["selection_id"]), str(item["text"]), parse_box(item.get("box"))
    selection_id, text, *rest = item
    return str(selection_id), str(text), parse_box(rest[0]) if rest else None


# ---------------------------------------------------------------------------
# Build Plan step 27: person-chosen, text-only multi-object segmentation.
# ---------------------------------------------------------------------------


def segment_selections(
    predictor: Any,
    image_path: Path,
    selections: list[Any],
    *,
    min_area_ratio: float = 0.005,
    max_area_ratio: float = 0.90,
    duplicate_iou: float = 0.85,
    min_box_iou: float | None = None,
) -> dict[str, dict[str, Any]]:
    """One SAM 3.1 pass over every selection's typed name for one photo.

    ``selections`` is ``[(selection_id, text), ...]`` or
    ``[(selection_id, text, box), ...]`` (or the dispatcher's dicts) --
    every pending selection for the upload's `segment` job (skill item 1:
    SAM loads the image once, and every distinct name is a text prompt
    batched into one ``predictor(text=[...])`` call; selections sharing a
    name share its instances). ``predictor`` is any callable that accepts
    ``text=`` and returns either one results-like object per prompt
    (positionally aligned) or, like the real `SAM3SemanticPredictor`, one
    combined result with each instance's prompt index in ``boxes.cls`` (see
    ``candidates_per_prompt``) -- a real predictor on the GPU, or a stub.

    Choosing the instance (docs/WEB_TO_QUEST_PIPELINE.md 7):

    * with a ``box`` (where the vision labeler saw *this* object, stored
      photo pixels): the instance whose mask's box best overlaps it (IoU;
      near-ties broken by score). Box selections are matched greedily
      best-IoU-first and never share an instance, so two "green armchair"
      selections with different boxes get the two different chairs. A box
      nothing overlaps (IoU < ``min_box_iou``) falls back to the best-score
      instance not already taken.
    * without a box: the highest-score instance (unchanged).

    Returns ``{selection_id: {"status", "score", "mask", "alternatives",
    "reason", ...}}`` (box selections also carry ``box_iou`` and
    ``box_match``). A selection with no usable mask -- nothing above the
    area filter, or flagged as a near-duplicate of a better selection -- is
    ``"failed"`` with a reason (Hard Rule 7: it never blocks the others).
    """
    if not selections:
        return {}
    threshold = MIN_BOX_IOU if min_box_iou is None else min_box_iou

    image = Image.open(image_path).convert("RGB")
    width, height = image.size

    parsed = [_normalize_selection(item) for item in selections]
    prompts: list[str] = []
    prompt_index: dict[str, int] = {}
    selection_prompt: list[int] = []
    for _selection_id, text, _box in parsed:
        key = text.strip().casefold()
        if key not in prompt_index:
            prompt_index[key] = len(prompts)
            prompts.append(text.strip())
        selection_prompt.append(prompt_index[key])

    raw_results = predictor(text=prompts)
    per_prompt_candidates = [
        [
            (score, mask)
            for score, mask in candidates
            if min_area_ratio < float(mask.mean()) < max_area_ratio
        ]
        for candidates in candidates_per_prompt(list(raw_results), len(prompts), height, width)
    ]
    candidate_boxes = [[mask_bbox(mask) for _score, mask in candidates] for candidates in per_prompt_candidates]

    def failed(reason: str) -> dict[str, Any]:
        return {"status": "failed", "score": None, "mask": None, "alternatives": [], "reason": reason}

    def alternatives_for(prompt: int, chosen: int) -> list[dict[str, float]]:
        others = [item for index, item in enumerate(per_prompt_candidates[prompt]) if index != chosen]
        others.sort(key=lambda item: item[0], reverse=True)
        return [
            {"score": round(float(score), 4), "area_ratio": round(float(mask.mean()), 4)}
            for score, mask in others
        ]

    # Box selections first: greedy best-IoU-first assignment, one instance
    # per selection, never shared between two box selections of one name.
    chosen: dict[int, tuple[int, float | None, str]] = {}  # selection -> (candidate, box IoU, match)
    taken: set[tuple[int, int]] = set()
    options: dict[int, list[tuple[float, float, int]]] = {}  # selection -> [(IoU, score, candidate)]
    for sel_index, (_selection_id, _text, box) in enumerate(parsed):
        if box is None:
            continue
        prompt = selection_prompt[sel_index]
        for cand_index, (score, _mask) in enumerate(per_prompt_candidates[prompt]):
            cand_box = candidate_boxes[prompt][cand_index]
            iou = box_iou(cand_box, box) if cand_box is not None else 0.0
            if iou >= threshold:
                options.setdefault(sel_index, []).append((iou, float(score), cand_index))
    while True:
        # The selection with the best still-available overlap goes next...
        best: tuple[float, int, list[tuple[float, float, int]]] | None = None
        for sel_index, opts in options.items():
            if sel_index in chosen:
                continue
            prompt = selection_prompt[sel_index]
            available = [opt for opt in opts if (prompt, opt[2]) not in taken]
            if available:
                top = max(opt[0] for opt in available)
                if best is None or top > best[0]:
                    best = (top, sel_index, available)
        if best is None:
            break
        top, sel_index, available = best
        # ...and takes, of its near-tied best overlaps, the highest score.
        near = [opt for opt in available if opt[0] >= top - BOX_IOU_TIE]
        iou, _score, cand_index = max(near, key=lambda opt: (opt[1], opt[0]))
        chosen[sel_index] = (cand_index, iou, "box")
        taken.add((selection_prompt[sel_index], cand_index))

    for sel_index, (_selection_id, _text, box) in enumerate(parsed):
        if sel_index in chosen:
            continue
        prompt = selection_prompt[sel_index]
        candidates = per_prompt_candidates[prompt]
        if not candidates:
            continue
        order = sorted(range(len(candidates)), key=lambda index: candidates[index][0], reverse=True)
        if box is None:
            chosen[sel_index] = (order[0], None, "score")
            continue
        # A box nothing overlaps: best-score instance nobody else took.
        free = [index for index in order if (prompt, index) not in taken] or order
        cand_box = candidate_boxes[prompt][free[0]]
        chosen[sel_index] = (free[0], box_iou(cand_box, box) if cand_box is not None else 0.0, "fallback")
        taken.add((prompt, free[0]))

    outcomes: dict[str, dict[str, Any]] = {}
    chosen_masks: dict[str, np.ndarray] = {}
    rank: dict[str, tuple[float, float]] = {}
    for sel_index, (selection_id, _text, box) in enumerate(parsed):
        if sel_index not in chosen:
            outcomes[selection_id] = failed(_NO_MATCH_REASON)
            continue
        prompt = selection_prompt[sel_index]
        cand_index, iou, match = chosen[sel_index]
        score, mask = per_prompt_candidates[prompt][cand_index]
        outcome: dict[str, Any] = {
            "status": "segmented",
            "score": float(score),
            "mask": mask,
            "alternatives": alternatives_for(prompt, cand_index),
            "reason": None,
        }
        if box is not None:
            outcome["box_iou"] = round(float(iou or 0.0), 4)
            outcome["box_match"] = match
        outcomes[selection_id] = outcome
        chosen_masks[selection_id] = mask
        # Duplicate tie-break: a box-matched pick beats a fallback, then the
        # better box overlap, then SAM's score.
        rank[selection_id] = (
            (2.0 if match == "box" else 1.0 if match == "score" else 0.0) + float(iou or 0.0),
            float(score),
        )

    # Cross-selection duplicate flagging (skill item 1): two selections
    # whose chosen masks overlap heavily are almost certainly the same real
    # object picked twice. Keep the better one, fail the other with a reason
    # instead of reconstructing the same object twice.
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
            loser = id_a if rank[id_a] <= rank[id_b] else id_b
            outcomes[loser] = failed(f"duplicate of another selection (IoU {overlap:.2f})")
            if loser == id_a:
                break
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
    predictor: Any, image_path: Path, output_dir: Path, selections: list[Any]
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
    print(
        "segment_many %s: %s"
        % (
            image_path.name,
            json.dumps(
                {
                    sid: [o.get("status"), o.get("score") and round(o["score"], 3), o.get("box_iou"), o.get("box_match")]
                    for sid, o in report.items()
                }
            ),
        ),
        flush=True,
    )
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
                # Each selection may carry its VLM box (stored-photo pixels);
                # segment_selections uses it to pick that instance.
                selections = [
                    (str(item["selection_id"]), str(item["text"]), item.get("box")) for item in body["selections"]
                ]
            except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
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
