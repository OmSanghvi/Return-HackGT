"""Build Plan step 27: unit tests for the testable half of
`segment_sam31_local.py` -- everything above its "adapter boundary" comment.

These never import torch or ultralytics (both lazily imported only inside
the GPU-only functions below that boundary) and never touch a GPU, so they
run on any CPU machine with `numpy` and `Pillow` installed:

    pip install numpy Pillow   # or just use backend/.venv, which has both

Run with `python -m unittest test_segment_sam31_local.py` from this
directory (or `python -m unittest worker.test_segment_sam31_local` from the
repo root).
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import segment_sam31_local as sam31  # noqa: E402


def _circle_mask(height: int, width: int, cx: int, cy: int, radius: int) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    return ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius * radius


def _fake_result(masks: list[np.ndarray], scores: list[float]) -> types.SimpleNamespace:
    """A duck-typed stand-in for one Ultralytics `Results` object. Real
    results carry torch tensors; these are plain numpy arrays, which is
    exactly the seam `_to_numpy` exists for (no `.detach`, so it falls
    straight to `np.asarray`).
    """
    boxes = types.SimpleNamespace(conf=np.asarray(scores, dtype=float))
    masks_obj = types.SimpleNamespace(data=np.asarray(masks, dtype=float))
    return types.SimpleNamespace(masks=masks_obj, boxes=boxes)


class StubPredictor:
    """Fakes `SAM3SemanticPredictor(text=[...])`: one fake Results per
    prompt, positionally aligned, per the skill's documented Ultralytics
    batching contract."""

    def __init__(self, by_prompt: dict[str, types.SimpleNamespace]) -> None:
        self._by_prompt = by_prompt
        self.calls: list[list[str]] = []

    def set_image(self, _path: str) -> None:
        pass

    def __call__(self, text: list[str]) -> list[types.SimpleNamespace]:
        self.calls.append(list(text))
        return [self._by_prompt.get(prompt, _fake_result([], [])) for prompt in text]


class _TempImage:
    """A real PNG on disk (`segment_selections` opens the image by path).

    Uses a directory rather than `NamedTemporaryFile` -- on Windows, a
    still-open `NamedTemporaryFile` handle blocks its own later deletion
    even after the image bytes are flushed via a separate PIL handle.
    """

    def __init__(self, width: int = 40, height: int = 40):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "image.png"
        Image.new("RGB", (width, height), (5, 5, 5)).save(self.path)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc) -> None:
        self._dir.cleanup()


class ResizeMaskTests(unittest.TestCase):
    def test_same_shape_is_returned_unchanged(self) -> None:
        mask = _circle_mask(20, 20, 10, 10, 5)
        result = sam31.resize_mask(mask, 20, 20)
        np.testing.assert_array_equal(result, mask)

    def test_resizes_to_target_dimensions(self) -> None:
        mask = _circle_mask(10, 10, 5, 5, 3)
        result = sam31.resize_mask(mask, 20, 30)
        self.assertEqual(result.shape, (20, 30))


class MaskIouTests(unittest.TestCase):
    def test_identical_masks_have_iou_one(self) -> None:
        mask = _circle_mask(30, 30, 15, 15, 8)
        self.assertAlmostEqual(sam31.mask_iou(mask, mask), 1.0)

    def test_disjoint_masks_have_iou_zero(self) -> None:
        a = _circle_mask(30, 30, 5, 5, 3)
        b = _circle_mask(30, 30, 25, 25, 3)
        self.assertEqual(sam31.mask_iou(a, b), 0.0)

    def test_two_empty_masks_have_iou_zero(self) -> None:
        empty = np.zeros((10, 10), dtype=bool)
        self.assertEqual(sam31.mask_iou(empty, empty.copy()), 0.0)


class SegmentSelectionsTests(unittest.TestCase):
    """Skill's required scenarios for `segment_selections`."""

    def test_batches_every_selection_into_one_predictor_call(self) -> None:
        with _TempImage() as path:
            vase = _circle_mask(40, 40, 10, 10, 5)
            lamp = _circle_mask(40, 40, 30, 30, 5)
            predictor = StubPredictor(
                {"vase": _fake_result([vase], [0.9]), "lamp": _fake_result([lamp], [0.8])}
            )
            outcomes = sam31.segment_selections(predictor, path, [("s1", "vase"), ("s2", "lamp")])
            self.assertEqual(len(predictor.calls), 1)
            self.assertEqual(predictor.calls[0], ["vase", "lamp"])
            self.assertEqual(outcomes["s1"]["status"], "segmented")
            self.assertEqual(outcomes["s2"]["status"], "segmented")
            self.assertAlmostEqual(outcomes["s1"]["score"], 0.9)
            np.testing.assert_array_equal(outcomes["s1"]["mask"], vase)

    def test_returns_alternatives_for_the_runner_up_instances(self) -> None:
        with _TempImage() as path:
            best = _circle_mask(40, 40, 10, 10, 6)
            second = _circle_mask(40, 40, 30, 10, 4)
            predictor = StubPredictor({"vase": _fake_result([best, second], [0.9, 0.6])})
            outcomes = sam31.segment_selections(predictor, path, [("s1", "vase")])
            self.assertEqual(outcomes["s1"]["status"], "segmented")
            self.assertEqual(len(outcomes["s1"]["alternatives"]), 1)
            self.assertAlmostEqual(outcomes["s1"]["alternatives"][0]["score"], 0.6)

    def test_area_filter_rejects_too_small_and_too_large_masks(self) -> None:
        with _TempImage() as path:
            tiny = _circle_mask(40, 40, 2, 2, 1)  # far under 0.5% of the image
            huge = np.ones((40, 40), dtype=bool)  # 100% of the image
            predictor = StubPredictor(
                {
                    "tiny": _fake_result([tiny], [0.9]),
                    "huge": _fake_result([huge], [0.9]),
                }
            )
            outcomes = sam31.segment_selections(predictor, path, [("s1", "tiny"), ("s2", "huge")])
            self.assertEqual(outcomes["s1"]["status"], "failed")
            self.assertEqual(outcomes["s2"]["status"], "failed")

    def test_no_usable_mask_fails_with_a_reason(self) -> None:
        with _TempImage() as path:
            predictor = StubPredictor({})  # "chair" matches nothing
            outcomes = sam31.segment_selections(predictor, path, [("s1", "chair")])
            self.assertEqual(outcomes["s1"]["status"], "failed")
            self.assertIn("nothing found", outcomes["s1"]["reason"])
            self.assertIsNone(outcomes["s1"]["mask"])

    def test_duplicate_across_selections_is_flagged_keeping_the_higher_score(self) -> None:
        with _TempImage() as path:
            same_mask = _circle_mask(40, 40, 20, 20, 8)
            predictor = StubPredictor(
                {
                    "vase": _fake_result([same_mask], [0.7]),
                    "ceramic vase": _fake_result([same_mask], [0.95]),
                }
            )
            outcomes = sam31.segment_selections(
                predictor, path, [("s1", "vase"), ("s2", "ceramic vase")]
            )
            self.assertEqual(outcomes["s1"]["status"], "failed")
            self.assertIn("duplicate", outcomes["s1"]["reason"])
            self.assertEqual(outcomes["s2"]["status"], "segmented")

    def test_empty_selection_list_returns_empty_dict(self) -> None:
        with _TempImage() as path:
            self.assertEqual(sam31.segment_selections(StubPredictor({}), path, []), {})


class SegmentManyAutoDetectTests(unittest.TestCase):
    """Skill's required scenarios for the optional auto-detect helper."""

    def test_threshold_drops_low_confidence_instances(self) -> None:
        with _TempImage() as path:
            mask = _circle_mask(40, 40, 20, 20, 6)
            predictor = StubPredictor({"mug": _fake_result([mask], [0.2])})
            result = sam31.segment_many(predictor, path, ["mug"], confidence=0.35)
            self.assertEqual(result, [])

    def test_area_bounds_are_applied(self) -> None:
        with _TempImage() as path:
            tiny = _circle_mask(40, 40, 2, 2, 1)
            predictor = StubPredictor({"mug": _fake_result([tiny], [0.9])})
            result = sam31.segment_many(predictor, path, ["mug"])
            self.assertEqual(result, [])

    def test_dedupes_overlapping_instances_across_prompts(self) -> None:
        with _TempImage() as path:
            mask = _circle_mask(40, 40, 20, 20, 6)
            predictor = StubPredictor(
                {"mug": _fake_result([mask], [0.9]), "cup": _fake_result([mask], [0.8])}
            )
            result = sam31.segment_many(predictor, path, ["mug", "cup"])
            self.assertEqual(len(result), 1)
            self.assertAlmostEqual(result[0]["score"], 0.9)

    def test_cap_limits_how_many_are_returned(self) -> None:
        with _TempImage() as path:
            masks = [_circle_mask(60, 60, 5 + i * 8, 5 + i * 8, 3) for i in range(5)]
            predictor = StubPredictor({"thing": _fake_result(masks, [0.9 - i * 0.05 for i in range(5)])})
            result = sam31.segment_many(predictor, path, ["thing"], cap=2)
            self.assertEqual(len(result), 2)

    def test_sorted_by_score_descending(self) -> None:
        with _TempImage() as path:
            low = _circle_mask(60, 60, 10, 10, 3)
            high = _circle_mask(60, 60, 40, 40, 3)
            predictor = StubPredictor({"thing": _fake_result([low, high], [0.4, 0.9])})
            result = sam31.segment_many(predictor, path, ["thing"])
            self.assertEqual([round(r["score"], 2) for r in result], [0.9, 0.4])

    def test_empty_prompt_list_returns_empty(self) -> None:
        with _TempImage() as path:
            self.assertEqual(sam31.segment_many(StubPredictor({}), path, []), [])


class LegacyChooseOneUnaffectedByRefactorTests(unittest.TestCase):
    """`choose_one`/`candidate_masks` are unchanged by step 27 except for
    the torch/numpy duck-typing seam (`_to_numpy`); this pins the existing
    single-object behavior."""

    def test_choose_one_picks_the_centered_confident_instance(self) -> None:
        centered = _circle_mask(40, 40, 20, 20, 6)
        edge = _circle_mask(40, 40, 2, 2, 2)
        candidates = sam31.candidate_masks(
            [_fake_result([centered, edge], [0.9, 0.3])], 40, 40
        )
        chosen = sam31.choose_one(candidates, 40, 40)
        np.testing.assert_array_equal(chosen, centered)

    def test_choose_one_returns_none_for_two_similarly_good_separated_instances(self) -> None:
        left = _circle_mask(40, 40, 10, 20, 5)
        right = _circle_mask(40, 40, 30, 20, 5)
        candidates = sam31.candidate_masks([_fake_result([left, right], [0.9, 0.85])], 40, 40)
        self.assertIsNone(sam31.choose_one(candidates, 40, 40))


if __name__ == "__main__":
    unittest.main()
