"""Unit tests for worker/vlm_server.py JSON extraction and normalization.

No model, torch or PIL needed:  python -m unittest worker/test_vlm_server.py
"""
from __future__ import annotations

import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import vlm_server as v  # noqa: E402


class ExtractJsonTests(unittest.TestCase):
    def test_plain_array(self):
        self.assertEqual(v.extract_json('[{"label": "cat"}]', list), [{"label": "cat"}])

    def test_fenced_with_prose(self):
        text = 'Sure! Here you go:\n```json\n{"caption": "x", "a": [1, 2]}\n```\nHope that helps.'
        self.assertEqual(v.extract_json(text, dict), {"caption": "x", "a": [1, 2]})

    def test_trailing_commas_and_python_literals(self):
        text = '[{"label": "cat", "salient": True,}, {"label": "sofa", "box": None},]'
        self.assertEqual(v.extract_json(text, list),
                         [{"label": "cat", "salient": True}, {"label": "sofa", "box": None}])

    def test_truncated_array_keeps_complete_elements(self):
        text = '```json\n[{"bbox_2d": [1, 2, 3, 4], "label": "cat"}, {"bbox_2d": [5, 6, 7'
        self.assertEqual(v.extract_json(text, list), [{"bbox_2d": [1, 2, 3, 4], "label": "cat"}])

    def test_brackets_inside_strings(self):
        text = '{"caption": "a [weird] {caption}", "room_type": "den"}'
        self.assertEqual(v.extract_json(text, dict)["caption"], "a [weird] {caption}")

    def test_wrapped_array(self):
        text = '{"objects": [{"label": "lamp"}]}'
        self.assertEqual(v.extract_json(text, list), [{"label": "lamp"}])

    def test_prefers_requested_type(self):
        text = 'boxes [1,2] then {"caption": "c"}'
        self.assertEqual(v.extract_json(text, dict), {"caption": "c"})

    def test_garbage_raises(self):
        for text in ("", "   ", "no json here", "[{broken", '{"a": 1'):
            with self.assertRaises(ValueError):
                v.extract_json(text, dict if text.startswith("{") else list)


class NameTests(unittest.TestCase):
    def test_normalize_name(self):
        cases = {
            "A Tabby Cat": "tabby cat",
            "the remote controls": "remote control",
            "Pink blanket on the sofa": "pink blanket",
            "green armchair (left)": "green armchair",
            "2 pillows": "pillow",
            "wooden_side_table": "wooden side table",
            "bookshelves": "bookshelf",
            "glasses": "glasses",
            "people": "person",
            "  ": "",
            None: "",
            "cushions": "cushion",
            "canvas": "canvas",
        }
        for raw, want in cases.items():
            self.assertEqual(v.normalize_name(raw), want, raw)

    def test_exclusions(self):
        for name in ("wall", "white wall", "wood floor", "ceiling", "background", "shadow",
                     "sofa leg", "sky", "room"):
            self.assertTrue(v.is_excluded(v.normalize_name(name)), name)
        for name in ("floor lamp", "wall clock", "ceiling fan", "cat", "rug", "fireplace"):
            self.assertFalse(v.is_excluded(v.normalize_name(name)), name)


class BoxTests(unittest.TestCase):
    def test_rel1000_to_pixels(self):
        self.assertEqual(v.convert_box([0, 0, 500, 1000], 640, 480, "rel1000"), [0, 0, 320, 480])

    def test_abs_swapped_and_clamped(self):
        self.assertEqual(v.convert_box([700, 50, 100, -5], 640, 480, "abs"), [100, 0, 640, 50])

    def test_invalid_boxes(self):
        for raw in (None, [1, 2, 3], ["a", 1, 2, 3], [5, 5, 5, 5], [0, 0, float("nan"), 3]):
            self.assertIsNone(v.convert_box(raw, 640, 480, "abs"), raw)

    def test_iou(self):
        self.assertAlmostEqual(v.box_iou([0, 0, 10, 10], [0, 0, 10, 10]), 1.0)
        self.assertAlmostEqual(v.box_iou([0, 0, 10, 10], [10, 10, 20, 20]), 0.0)
        self.assertAlmostEqual(v.box_iou([0, 0, 10, 10], [5, 0, 15, 10]), 1 / 3)


class NormalizeObjectsTests(unittest.TestCase):
    W, H = 640, 480

    def norm(self, raw, **kw):
        return v.normalize_objects(raw, self.W, self.H, box_format=kw.pop("box_format", "rel1000"), **kw)

    def test_cats_photo_shape(self):
        raw = [
            {"bbox_2d": [20, 110, 490, 980], "label": "tabby cat", "salient": True},
            {"bbox_2d": [545, 50, 995, 770], "label": "tabby cat", "salient": True},
            {"bbox_2d": [0, 0, 1000, 1000], "label": "pink blanket", "salient": True},
            {"bbox_2d": [60, 150, 275, 245], "label": "remote control", "salient": True},
            {"bbox_2d": [520, 160, 580, 390], "label": "Remote Controls", "salient": "yes"},
            {"bbox_2d": [0, 0, 1000, 300], "label": "red sofa"},
            {"bbox_2d": [0, 0, 1000, 1000], "label": "background"},
            {"bbox_2d": [100, 100, 200, 200], "label": "wall"},
        ]
        out = self.norm(raw)
        names = [o["name"] for o in out]
        self.assertIn("left tabby cat", names)
        self.assertIn("right tabby cat", names)
        self.assertIn("left remote control", names)
        self.assertIn("right remote control", names)
        self.assertIn("red sofa", names)
        self.assertNotIn("background", names)
        self.assertNotIn("wall", names)
        self.assertNotIn("pink blanket", names)  # whole-frame box is a surface
        for o in out:
            self.assertEqual(set(o), {"name", "box", "salient", "prompt"})
            x0, y0, x1, y1 = o["box"]
            self.assertTrue(0 <= x0 < x1 <= self.W and 0 <= y0 < y1 <= self.H)
        cat = next(o for o in out if o["name"] == "left tabby cat")
        self.assertEqual(cat["prompt"], "tabby cat")
        self.assertEqual(cat["box"], [13, 53, 314, 470])
        self.assertEqual(len(set(names)), len(names))

    def test_duplicate_boxes_merged_and_salient_first(self):
        raw = [
            {"bbox_2d": [10, 10, 20, 20], "label": "cup", "salient": False},
            {"bbox_2d": [100, 100, 900, 900], "label": "sofa", "salient": True},
            {"bbox_2d": [102, 101, 899, 902], "label": "couch", "salient": True},
        ]
        out = self.norm(raw)
        self.assertEqual([o["name"] for o in out], ["sofa", "cup"])

    def test_cap_and_three_instances(self):
        raw = [{"bbox_2d": [x, 400, x + 100, 600], "label": "chair", "salient": True}
               for x in (700, 100, 400)]
        out = self.norm(raw)
        self.assertEqual(sorted(o["name"] for o in out), ["left chair", "middle chair", "right chair"])
        self.assertEqual(len(self.norm(raw * 5, max_objects=4)), 3)  # dupes merge first
        many = [{"bbox_2d": [i * 60, 0, i * 60 + 50, 500], "label": f"thing{i}"} for i in range(16)]
        self.assertEqual(len(self.norm(many, max_objects=5)), 5)

    def test_structural_not_salient_and_no_box(self):
        out = self.norm([{"label": "window", "salient": True, "bbox_2d": [0, 0, 200, 500]},
                         {"label": "lamp"}, {"label": "lamp"}, "plant"])
        by = {o["name"]: o for o in out}
        self.assertFalse(by["window"]["salient"])
        self.assertIsNone(by["lamp"]["box"])
        self.assertIn("plant", by)
        self.assertEqual(len(out), 3)

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            self.norm("cat")


class NormalizeAnalysisTests(unittest.TestCase):
    RAW = {
        "caption": "Two tabby cats asleep on a pink blanket.",
        "room_type": "Living Room", "setting": "Indoor", "camera_view": "top down",
        "time_of_day": "Afternoon", "mood": "Cozy, Quiet",
        "lighting": {"key_direction": "from the upper left window", "key_description": "window light",
                     "color_temperature_k": "5200", "sources": ["window at left", "Window at left"],
                     "brightness": "Bright", "shadows": "soft"},
        "materials": {"floor": "Pink fleece", "walls": "not visible", "other": "red fabric, plastic"},
        "palette": ["#C2185B", "f8bbd0", "bad"],
        "search_terms": {"hdri": ["cozy living room"], "sounds": ["cat purring", "room tone"],
                         "images": ["cat portrait"]},
    }

    def test_full_document(self):
        doc = v.normalize_analysis(self.RAW, [{"name": "cat", "box": [1, 2, 3, 4], "salient": True,
                                               "prompt": "cat"}])
        self.assertEqual(doc["room_type"], "living room")
        self.assertEqual(doc["setting"], "indoor")
        self.assertEqual(doc["camera_view"], "top-down")
        self.assertEqual(doc["time_of_day"], "afternoon")
        self.assertEqual(doc["lighting"]["key_direction_code"], "left")
        self.assertEqual(doc["lighting"]["key_direction"], "left, window light")
        self.assertEqual(doc["lighting"]["key_azimuth_deg"], 270)
        self.assertEqual(doc["materials"]["floor"], "pink fleece")
        self.assertEqual(doc["materials"]["walls"], "white painted plaster")  # "not visible" -> likely
        self.assertEqual(doc["lighting"]["color_temperature_k"], 5200)
        self.assertEqual(doc["lighting"]["sources"], ["window at left"])
        self.assertEqual(doc["lighting"]["brightness"], "bright")
        self.assertEqual(doc["materials"]["other"], ["red fabric", "plastic"])
        self.assertEqual(doc["palette"], ["#c2185b", "#f8bbd0"])
        self.assertEqual(doc["objects"], [{"name": "cat", "box": [1, 2, 3, 4], "salient": True}])
        for key in ("room_type", "setting", "time_of_day", "mood", "lighting", "materials",
                    "palette", "objects", "search_terms", "caption"):
            self.assertIn(key, doc)

    def test_measured_palette_wins_and_defaults(self):
        raw = {"caption": "c", "room_type": "x", "lighting": {"color_temperature_k": 99999}}
        doc = v.normalize_analysis(raw, None, ["#000000"])
        self.assertEqual(doc["palette"], ["#000000"])
        self.assertEqual(doc["lighting"]["color_temperature_k"], 10000)
        self.assertEqual(doc["lighting"]["key_direction_code"], "camera-left")
        self.assertEqual(doc["lighting"]["key_direction"], "behind camera left")
        self.assertEqual(doc["lighting"]["key_azimuth_deg"], 315)
        self.assertEqual(doc["materials"]["floor"], "wooden floor")  # missing -> likely floor
        self.assertFalse(doc["materials"]["floor_visible"])
        self.assertEqual(doc["time_of_day"], "unknown")
        self.assertEqual(doc["objects"], [])

    def test_missing_core_keys_raise(self):
        for raw in ([], {"caption": "c"}, {"caption": "", "room_type": "x", "lighting": {}}):
            with self.assertRaises(ValueError):
                v.normalize_analysis(raw)

    def test_key_direction_phrases(self):
        cases = {"left": "left", "Right side": "right", "overhead": "above",
                 "backlight from window": "backlight", "backlight-left": "backlight-left",
                 "front-left": "camera-left", "camera": "camera", "camera-right": "camera-right",
                 "camera flash": "camera", "behind the camera": "camera",
                 "from behind, right": "backlight-right", "window at left": "left",
                 "shining toward the camera": "backlight", "bright": "camera-left",
                 None: "camera-left", "": "camera-left", "ceiling lights": "above"}
        for raw, want in cases.items():
            self.assertEqual(v.normalize_key_direction(raw), want, raw)
        for code in v.KEY_CODES:
            self.assertIn(code, v.KEY_PHRASES)
            self.assertIn(code, v.KEY_AZIMUTH_DEG)

    def test_key_phrases_read_right_by_compose_room(self):
        """backend/unity_room.py _key_direction parses words: camera side must
        say behind/camera, far side ahead/backlit, never the other way round."""
        def compose_parse(text):  # the rules of unity_room._key_direction
            w = text.lower()
            x = (-1 if "left" in w else 0) + (1 if "right" in w else 0)
            z = 0
            if "behind" in w or "back" in w.split() or "camera" in w:
                z -= 1
            if any(k in w for k in ("front", "ahead", "backlit", "facing", "opposite")):
                z += 1
            overhead = any(k in w for k in ("above", "overhead", "ceiling", "top"))
            return x, z, overhead, "window" in w
        want = {"left": (-1, 0), "right": (1, 0), "camera": (0, -1), "camera-left": (-1, -1),
                "camera-right": (1, -1), "backlight": (0, 1), "backlight-left": (-1, 1),
                "backlight-right": (1, 1), "above": (0, 0)}
        for code, (x, z) in want.items():
            got = compose_parse(v.key_direction_phrase(code))
            self.assertEqual(got[:2], (x, z), code)
            self.assertEqual(got[2], code == "above", code)
        self.assertTrue(compose_parse(v.key_direction_phrase("left", "window"))[3])
        self.assertEqual(v.key_direction_phrase("above", "window"), "above")

    def test_hex(self):
        self.assertEqual(v.normalize_hex("#ABC"), "#aabbcc")
        self.assertEqual(v.normalize_hex("zzzzzz"), "")


class InventoryAndLightTests(unittest.TestCase):
    def test_names_from_inventory(self):
        raw = ["Green Armchair", "green armchair", "wall", "the rugs", {"label": "microwave"},
               "sofa leg", 7, "stone fireplace"]
        self.assertEqual(v.names_from_inventory(raw),
                         ["green armchair", "rug", "microwave", "stone fireplace"])
        self.assertEqual(v.names_from_inventory({"objects": ["cat", "cat"]}), ["cat"])
        self.assertEqual(len(v.names_from_inventory([f"thing{i}" for i in range(50)], 5)), 5)
        with self.assertRaises(ValueError):
            v.names_from_inventory("cat")

    def test_cct(self):
        self.assertTrue(6000 <= v.cct_from_linear_rgb(1.0, 1.0, 1.0) <= 6700)   # D65 white
        warm = v.cct_from_linear_rgb(1.0, 0.45, 0.12)
        self.assertTrue(1800 <= warm <= 3200, warm)
        cool = v.cct_from_linear_rgb(0.7, 0.85, 1.0)
        self.assertGreater(cool, 7500)
        self.assertEqual(v.cct_from_linear_rgb(0, 0, 0), 6500)

    def test_measured_temperature_overrides_model(self):
        raw = {"caption": "c", "room_type": "den", "lighting": {"color_temperature_k": 6500}}
        doc = v.normalize_analysis(raw, [], None, {"color_temperature_k": 3100, "mean_luminance": 0.2})
        self.assertEqual(doc["lighting"]["color_temperature_k"], 3100)
        self.assertEqual(doc["lighting"]["color_temperature_model_k"], 6500)
        self.assertEqual(doc["lighting"]["measured"]["mean_luminance"], 0.2)


class MiscTests(unittest.TestCase):
    def test_decode_b64(self):
        data = base64.b64encode(b"\xff\xd8jpeg").decode()
        self.assertEqual(v.decode_image_b64(data), b"\xff\xd8jpeg")
        self.assertEqual(v.decode_image_b64("data:image/jpeg;base64," + data), b"\xff\xd8jpeg")
        with self.assertRaises(ValueError):
            v.decode_image_b64("")

    def test_box_format(self):
        self.assertEqual(v.box_format_for("Qwen3-VL-4B-Instruct"), "rel1000")
        self.assertEqual(v.box_format_for("Qwen2.5-VL-7B-Instruct"), "abs")

    def test_chunk_names(self):
        names = [f"n{i}" for i in range(16)]
        groups = v.chunk_names(names, 4)
        self.assertEqual(len(groups), 4)
        self.assertEqual(sum(groups, []), names)  # order kept, nothing lost
        self.assertEqual(v.chunk_names(names[:3], 4), [names[:3]])
        self.assertEqual([len(g) for g in v.chunk_names(names[:5], 4)], [3, 2])
        self.assertEqual(len(v.chunk_names(names + names, 4)), 4)
        self.assertEqual(v.chunk_names([], 4), [])
        self.assertEqual(v.chunk_names(names, 1), [names])

    def test_merge_group_outputs(self):
        texts = ['[{"bbox_2d": [1, 2, 30, 40], "label": "cat"}]',
                 "sorry, no json here",
                 '```json\n[{"bbox_2d": [5, 5, 50, 50], "label": "sofa"}, {"bbox_2d": [6, 6',
                 "[]"]
        items, failed = v.merge_group_outputs(texts)
        self.assertEqual([i["label"] for i in items], ["cat", "sofa"])
        self.assertEqual(failed, [1])

    def test_fingerprints_match(self):
        base = bytes(range(0, 256, 1))
        noisy = bytes(min(255, b + (2 if i % 3 else 0)) for i, b in enumerate(base))  # re-encode noise
        other = bytes(reversed(base))
        self.assertTrue(v.fingerprints_match((1.5, base), (1.5, noisy)))
        self.assertTrue(v.fingerprints_match((1.5, base), (1.505, base)))  # resize rounding
        self.assertFalse(v.fingerprints_match((1.5, base), (1.5, other)))
        self.assertFalse(v.fingerprints_match((1.5, base), (1.33, base)))
        self.assertFalse(v.fingerprints_match(None, (1.5, base)))

    def test_rescale_objects(self):
        objs = [{"name": "cat", "box": [100, 50, 200, 150], "salient": True}, {"name": "x", "box": None}]
        out = v.rescale_objects(objs, [1280, 960], [640, 480])
        self.assertEqual(out[0]["box"], [50, 25, 100, 75])
        self.assertIsNone(out[1]["box"])
        self.assertEqual(objs[0]["box"], [100, 50, 200, 150])  # input untouched
        self.assertEqual(v.rescale_objects(objs, [640, 480], [640, 480])[0]["box"], [100, 50, 200, 150])
        self.assertEqual(v.rescale_objects(objs, [10, 10], [1000, 1000])[0]["box"], [1000, 1000, 1000, 1000])

    def test_merge_analysis_parts(self):
        scene = {"caption": "c", "room_type": "den", "lighting": {"key_direction": "left"}}
        design = {"materials": {"floor": "oak"}, "search_terms": {"hdri": ["den"]}, "caption": "x"}
        raw = v.merge_analysis_parts(scene, design)
        self.assertEqual(raw["caption"], "c")  # the scene part wins on overlap
        self.assertEqual(raw["materials"]["floor"], "oak")
        doc = v.normalize_analysis(v.merge_analysis_parts(scene, None))
        self.assertEqual(doc["search_terms"], {"hdri": [], "sounds": [], "images": []})

    def test_prompt_formats(self):
        self.assertIn("At most 12 entries", v.DETECT_PROMPT.format(max_objects=12))
        self.assertIn("at most 20 entries", v.INVENTORY_PROMPT.format(max_objects=20))
        self.assertIn("sofa, cat.", v.GROUND_PROMPT.format(names="sofa, cat"))
        self.assertIn('"bbox_2d"', v.DETECT_PROMPT.format(max_objects=3))
        for prompt in (v.ANALYZE_SCENE_PROMPT, v.ANALYZE_DESIGN_PROMPT):
            self.assertNotIn("{{", prompt)  # used verbatim, never .format()ed
        self.assertIn('"key_direction"', v.ANALYZE_SCENE_PROMPT)
        self.assertIn('"search_terms"', v.ANALYZE_DESIGN_PROMPT)


if __name__ == "__main__":
    unittest.main()
