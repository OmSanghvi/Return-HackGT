"""NemoClaw scene-layout and immersive-staging tools (Build Plan steps 4, 6).

Run with: python -m unittest test_scene_tools.py

Pure-reasoning tests only -- no live LLM call, matching the mock philosophy
used throughout this repo (see test_subject_labeler.py).
"""

import unittest

import jsonschema

import scene_tools as st


def _objects(n: int) -> list[dict]:
    labels = ["reading lamp", "wicker armchair", "oak table", "family sofa", "ceramic vase", "bookshelf"]
    return [{"asset_id": f"asset_{i}", "label": labels[i % len(labels)]} for i in range(n)]


class PlaceObjectsInSceneTests(unittest.TestCase):
    def test_two_and_five_objects_both_schema_valid_same_run(self) -> None:
        for n in (2, 5):
            blueprint = st.place_objects_in_scene(_objects(n), project_id="proj-1")
            self.assertEqual(len(blueprint["objects"]), n)
            envelope = {
                "project_id": "proj-1",
                "revision": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                **blueprint,
            }
            jsonschema.validate(envelope, st._load_schema())

    def test_accepts_a_list_not_a_hard_coded_pair(self) -> None:
        for n in (1, 2, 3, 5, 8):
            blueprint = st.place_objects_in_scene(_objects(n))
            self.assertEqual(len(blueprint["objects"]), n)

    def test_object_ids_are_unique_and_pattern_valid(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(5))
        ids = [o["id"] for o in blueprint["objects"]]
        self.assertEqual(len(ids), len(set(ids)))
        for object_id in ids:
            self.assertRegex(object_id, st.ID_PATTERN.pattern)

    def test_positions_and_rotations_are_three_floats(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(4))
        for obj in blueprint["objects"]:
            self.assertEqual(len(obj["position"]), 3)
            self.assertEqual(len(obj["rotation"]), 3)
            self.assertEqual(len(obj["scale"]), 3)

    def test_objects_do_not_collapse_onto_the_same_point(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(5))
        positions = [tuple(o["position"]) for o in blueprint["objects"]]
        self.assertEqual(len(positions), len(set(positions)))

    def test_never_publishes_and_never_assigns_real_project_metadata(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(2))
        self.assertNotIn("project_id", blueprint)
        self.assertNotIn("revision", blueprint)

    def test_relative_scale_reflects_label_semantics(self) -> None:
        blueprint = st.place_objects_in_scene(
            [{"asset_id": "a1", "label": "reading lamp"}, {"asset_id": "a2", "label": "family sofa"}]
        )
        lamp = next(o for o in blueprint["objects"] if o["asset_id"] == "a1")
        sofa = next(o for o in blueprint["objects"] if o["asset_id"] == "a2")
        self.assertLess(lamp["scale"][0], sofa["scale"][0])

    def test_invalid_asset_id_is_rejected(self) -> None:
        with self.assertRaises(st.SceneToolError):
            st.place_objects_in_scene([{"asset_id": "not a valid id!", "label": "lamp"}])

    def test_empty_object_list_is_rejected(self) -> None:
        with self.assertRaises(st.SceneToolError):
            st.place_objects_in_scene([])

    def test_layout_hint_left_of_reorders_objects(self) -> None:
        objects = [{"asset_id": "a1", "label": "lamp"}, {"asset_id": "a2", "label": "chair"}]
        default_blueprint = st.place_objects_in_scene(objects)
        default_lamp_x = next(o for o in default_blueprint["objects"] if o["asset_id"] == "a1")["position"][0]

        hint = st.LayoutHint(relations=["chair left_of lamp"])
        hinted_blueprint = st.place_objects_in_scene(objects, sketch_layout_hint=hint)
        chair_x = next(o for o in hinted_blueprint["objects"] if o["asset_id"] == "a2")["position"][0]
        lamp_x = next(o for o in hinted_blueprint["objects"] if o["asset_id"] == "a1")["position"][0]
        self.assertLess(chair_x, lamp_x)
        self.assertNotEqual(default_lamp_x, lamp_x)

    def test_unparseable_hint_relations_are_ignored_not_raised(self) -> None:
        hint = st.LayoutHint(relations=["this is not a relation sentence"])
        blueprint = st.place_objects_in_scene(_objects(2), sketch_layout_hint=hint)
        self.assertEqual(len(blueprint["objects"]), 2)


class ReadSketchLayoutTests(unittest.TestCase):
    def test_mock_backend_returns_empty_hint(self) -> None:
        hint = st.read_sketch_layout(None, backend="mock")
        self.assertEqual(hint.relations, [])
        self.assertEqual(hint.backend, "mock")

    def test_default_backend_is_mock(self) -> None:
        hint = st.read_sketch_layout(None)
        self.assertEqual(hint.backend, "mock")

    def test_nemoclaw_backend_needs_runtime(self) -> None:
        with self.assertRaises(st.SceneToolError):
            st.read_sketch_layout(None, backend="nemoclaw")

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(st.SceneToolError):
            st.read_sketch_layout(None, backend="gpt")


class StageImmersiveRevealTests(unittest.TestCase):
    def _staged_objects(self, n: int) -> list[dict]:
        blueprint = st.place_objects_in_scene(_objects(n))
        return blueprint["objects"]

    def test_two_and_five_objects_in_same_run(self) -> None:
        insight = {"theme": "warm family reunion", "explanation": "Two memories of home, side by side."}
        for n in (2, 5):
            objects = self._staged_objects(n)
            plan = st.stage_immersive_reveal(insight, objects)
            self.assertEqual(len(plan["reveal_order"]), n)
            self.assertEqual(len(plan["haptic_signatures"]), n)

    def test_narration_text_comes_from_explanation_never_empty(self) -> None:
        insight = {"theme": "cool ocean calm", "explanation": "A shared love of the sea."}
        plan = st.stage_immersive_reveal(insight, self._staged_objects(3))
        self.assertEqual(plan["narration"]["text"], "A shared love of the sea.")

    def test_lighting_preset_keyed_to_theme(self) -> None:
        warm = st.stage_immersive_reveal({"theme": "warm family home", "explanation": "x"}, self._staged_objects(2))
        cool = st.stage_immersive_reveal({"theme": "cool ocean water", "explanation": "x"}, self._staged_objects(2))
        self.assertEqual(warm["lighting_preset"], "warm-amber")
        self.assertEqual(cool["lighting_preset"], "cool-teal")
        self.assertNotEqual(warm["lighting_preset"], cool["lighting_preset"])

    def test_unrecognized_theme_falls_back_to_neutral(self) -> None:
        plan = st.stage_immersive_reveal({"theme": "xyzzy", "explanation": "x"}, self._staged_objects(2))
        self.assertEqual(plan["lighting_preset"], "neutral-glow")

    def test_connecting_motif_references_every_object(self) -> None:
        objects = self._staged_objects(5)
        plan = st.stage_immersive_reveal({"theme": "joyful celebration", "explanation": "x"}, objects)
        # One control point per object plus the shared center.
        self.assertEqual(len(plan["connecting_motif"]["control_points"]), len(objects) + 1)

    def test_empty_object_list_is_rejected(self) -> None:
        with self.assertRaises(st.SceneToolError):
            st.stage_immersive_reveal({"theme": "x", "explanation": "x"}, [])


if __name__ == "__main__":
    unittest.main()
