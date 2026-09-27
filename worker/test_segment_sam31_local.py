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

    def test_splits_one_combined_result_by_prompt_class(self) -> None:
        # The real SAM3SemanticPredictor returns ONE Results for a text batch,
        # each mask tagged with its prompt index in boxes.cls (verified on the
        # L40S host 2026-09-26: only the first prompt got masks before this).
        with _TempImage() as path:
            cat = _circle_mask(40, 40, 10, 10, 5)
            remote = _circle_mask(40, 40, 30, 30, 5)
            combined = _fake_result([cat, remote], [0.9, 0.8])
            combined.boxes.cls = np.asarray([0.0, 1.0])
            outcomes = sam31.segment_selections(
                lambda text: [combined], path, [("s1", "cat"), ("s2", "remote")]
            )
            self.assertEqual(outcomes["s1"]["status"], "segmented")
            self.assertEqual(outcomes["s2"]["status"], "segmented")
            np.testing.assert_array_equal(outcomes["s2"]["mask"], remote)
            self.assertEqual(outcomes["s1"]["alternatives"], [])

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


def _rect_mask(height: int, width: int, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask


class BoxAwareSelectionTests(unittest.TestCase):
    """docs/WEB_TO_QUEST_PIPELINE.md 7: a selection's VLM box picks the SAM
    3.1 instance whose mask best overlaps it, so same-kind objects in one
    photo (two green armchairs, several wooden chairs) get distinct masks."""

    H, W = 60, 100

    def test_two_same_name_selections_get_the_two_different_instances(self) -> None:
        with _TempImage(self.W, self.H) as path:
            left = _rect_mask(self.H, self.W, 5, 10, 35, 50)
            right = _rect_mask(self.H, self.W, 60, 12, 90, 48)
            # The right chair scores higher: without boxes both selections
            # would pick it and one would be failed as a duplicate.
            predictor = StubPredictor({"green armchair": _fake_result([left, right], [0.70, 0.95])})
            outcomes = sam31.segment_selections(
                predictor,
                path,
                [
                    ("s-left", "green armchair", [4, 9, 36, 51]),
                    ("s-right", "green armchair", [59, 11, 91, 49]),
                ],
            )
            self.assertEqual(outcomes["s-left"]["status"], "segmented")
            self.assertEqual(outcomes["s-right"]["status"], "segmented")
            np.testing.assert_array_equal(outcomes["s-left"]["mask"], left)
            np.testing.assert_array_equal(outcomes["s-right"]["mask"], right)
            self.assertEqual(outcomes["s-left"]["box_match"], "box")
            self.assertGreater(outcomes["s-left"]["box_iou"], 0.8)
            self.assertAlmostEqual(outcomes["s-left"]["score"], 0.70)
            # One text prompt for both selections (same name, sent once).
            self.assertEqual(predictor.calls, [["green armchair"]])

    def test_without_boxes_the_old_highest_score_behaviour_is_kept(self) -> None:
        with _TempImage(self.W, self.H) as path:
            left = _rect_mask(self.H, self.W, 5, 10, 35, 50)
            right = _rect_mask(self.H, self.W, 60, 12, 90, 48)
            predictor = StubPredictor({"green armchair": _fake_result([left, right], [0.70, 0.95])})
            outcomes = sam31.segment_selections(predictor, path, [("s1", "green armchair")])
            np.testing.assert_array_equal(outcomes["s1"]["mask"], right)
            self.assertNotIn("box_iou", outcomes["s1"])

    def test_box_overlap_beats_a_higher_score_and_near_ties_go_to_the_score(self) -> None:
        with _TempImage(self.W, self.H) as path:
            target = _rect_mask(self.H, self.W, 10, 5, 60, 55)
            nearly_same = _rect_mask(self.H, self.W, 10, 5, 60, 56)  # box IoU 0.980: inside the tie band
            elsewhere = _rect_mask(self.H, self.W, 65, 10, 95, 40)
            predictor = StubPredictor(
                {"chair": _fake_result([elsewhere, target, nearly_same], [0.99, 0.60, 0.80])}
            )
            outcomes = sam31.segment_selections(predictor, path, [("s1", "chair", [10, 5, 60, 55])])
            # `elsewhere` scores best but doesn't overlap the box; of the two
            # overlapping near-ties, the higher-score one wins.
            np.testing.assert_array_equal(outcomes["s1"]["mask"], nearly_same)
            self.assertAlmostEqual(outcomes["s1"]["score"], 0.80)

    def test_box_selections_never_share_an_instance(self) -> None:
        with _TempImage(self.W, self.H) as path:
            a = _rect_mask(self.H, self.W, 20, 10, 50, 50)
            b = _rect_mask(self.H, self.W, 52, 10, 80, 50)
            predictor = StubPredictor({"wooden chair": _fake_result([a, b], [0.9, 0.9])})
            # Both boxes overlap `a` best, but the second also overlaps `b`.
            outcomes = sam31.segment_selections(
                predictor,
                path,
                [("s1", "wooden chair", [20, 10, 50, 50]), ("s2", "wooden chair", [35, 10, 75, 50])],
            )
            np.testing.assert_array_equal(outcomes["s1"]["mask"], a)
            np.testing.assert_array_equal(outcomes["s2"]["mask"], b)
            self.assertEqual(outcomes["s2"]["status"], "segmented")

    def test_a_box_that_overlaps_nothing_falls_back_to_the_best_free_instance(self) -> None:
        with _TempImage(self.W, self.H) as path:
            left = _rect_mask(self.H, self.W, 5, 10, 35, 50)
            right = _rect_mask(self.H, self.W, 60, 12, 90, 48)
            predictor = StubPredictor({"armchair": _fake_result([left, right], [0.9, 0.8])})
            outcomes = sam31.segment_selections(
                predictor,
                path,
                [("s1", "armchair", [4, 9, 36, 51]), ("s2", "armchair", [40, 52, 58, 59])],
            )
            np.testing.assert_array_equal(outcomes["s1"]["mask"], left)
            np.testing.assert_array_equal(outcomes["s2"]["mask"], right)  # the one s1 didn't take
            self.assertEqual(outcomes["s2"]["box_match"], "fallback")

    def test_only_one_instance_for_two_boxes_keeps_the_better_overlap(self) -> None:
        with _TempImage(self.W, self.H) as path:
            only = _rect_mask(self.H, self.W, 60, 12, 90, 48)
            predictor = StubPredictor({"armchair": _fake_result([only], [0.9])})
            outcomes = sam31.segment_selections(
                predictor,
                path,
                [("s-left", "armchair", [5, 10, 35, 50]), ("s-right", "armchair", [59, 11, 91, 49])],
            )
            self.assertEqual(outcomes["s-right"]["status"], "segmented")
            self.assertEqual(outcomes["s-left"]["status"], "failed")
            self.assertIn("duplicate", outcomes["s-left"]["reason"])

    def test_combined_result_by_prompt_class_with_boxes(self) -> None:
        # The real predictor's shape: ONE Results, prompt index in boxes.cls.
        with _TempImage(self.W, self.H) as path:
            chair_l = _rect_mask(self.H, self.W, 0, 30, 30, 58)
            chair_r = _rect_mask(self.H, self.W, 70, 30, 99, 58)
            lamp = _rect_mask(self.H, self.W, 40, 2, 55, 25)
            combined = _fake_result([chair_r, lamp, chair_l], [0.9, 0.8, 0.7])
            combined.boxes.cls = np.asarray([0.0, 1.0, 0.0])
            calls: list[list[str]] = []

            def predictor(text):
                calls.append(list(text))
                return [combined]

            outcomes = sam31.segment_selections(
                predictor,
                path,
                [
                    {"selection_id": "c1", "text": "wooden chair", "box": [0, 30, 30, 58]},
                    {"selection_id": "l1", "text": "lamp", "box": None},
                    {"selection_id": "c2", "text": "Wooden chair ", "box": [70, 30, 99, 58]},
                ],
            )
            self.assertEqual(calls, [["wooden chair", "lamp"]])  # case/space-insensitive dedupe
            np.testing.assert_array_equal(outcomes["c1"]["mask"], chair_l)
            np.testing.assert_array_equal(outcomes["c2"]["mask"], chair_r)
            np.testing.assert_array_equal(outcomes["l1"]["mask"], lamp)

    def test_a_clearly_better_overlap_wins_over_a_higher_score(self) -> None:
        with _TempImage(self.W, self.H) as path:
            target = _rect_mask(self.H, self.W, 10, 10, 40, 40)
            looser = _rect_mask(self.H, self.W, 10, 10, 48, 50)  # box IoU 0.59
            predictor = StubPredictor({"chair": _fake_result([looser, target], [0.95, 0.50])})
            outcomes = sam31.segment_selections(predictor, path, [("s1", "chair", [10, 10, 40, 40])])
            np.testing.assert_array_equal(outcomes["s1"]["mask"], target)
            self.assertEqual(len(outcomes["s1"]["alternatives"]), 1)

    def test_invalid_boxes_are_ignored(self) -> None:
        for raw in ([1, 2, 3], [10, 10, 5, 20], ["a", 1, 2, 3], "0,0,1,1", [0, 0, float("nan"), 4]):
            self.assertIsNone(sam31.parse_box(raw), raw)
        self.assertEqual(sam31.parse_box([1, 2, 3.5, 4]), [1.0, 2.0, 3.5, 4.0])

    def test_box_iou_and_mask_bbox(self) -> None:
        self.assertAlmostEqual(sam31.box_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        self.assertAlmostEqual(sam31.box_iou([0, 0, 10, 10], [5, 0, 15, 10]), 50 / 150)
        self.assertEqual(sam31.box_iou([0, 0, 1, 1], [2, 2, 3, 3]), 0.0)
        self.assertEqual(sam31.mask_bbox(_rect_mask(20, 20, 3, 4, 8, 9)), (3.0, 4.0, 8.0, 9.0))
        self.assertIsNone(sam31.mask_bbox(np.zeros((5, 5), dtype=bool)))


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
