"""Tests for the blueprint -> Unity Editor write bridge (Build Plan step 4/6).

Run with: python -m unittest test_blueprint_to_unity.py

These test the generated C# text deterministically -- they don't compile or
execute it (that needs a live Unity Editor via the Unity MCP connection).
A 4-object shape and a differently-sized shape were both manually verified
end to end against a live Editor; see docs/BUILD_PLAN.md step 4 for that
record. What's tested here is that arbitrary, schema-valid blueprints of
varying object counts produce well-formed, correctly-scaled generation
output -- not just the one shape that happened to be checked by hand.
"""

import unittest

import scene_tools as st
from blueprint_to_unity import blueprint_to_unity_command


def _objects(n: int) -> list[dict]:
    labels = [
        "reading lamp",
        "wicker armchair",
        "oak table",
        "family sofa",
        "ceramic vase",
        "bookshelf",
        "guitar",
        "mug",
    ]
    return [{"asset_id": f"asset_{i}", "label": labels[i % len(labels)]} for i in range(n)]


class BlueprintToUnityCommandTests(unittest.TestCase):
    def test_generates_one_place_call_per_object_for_varying_counts(self) -> None:
        for n in (1, 2, 5, 8):
            blueprint = st.place_objects_in_scene(_objects(n))
            code = blueprint_to_unity_command(blueprint)
            self.assertEqual(code.count("Place(result, root,"), n)

    def test_includes_every_object_id_and_asset_id(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(4))
        code = blueprint_to_unity_command(blueprint)
        for obj in blueprint["objects"]:
            self.assertIn(obj["id"], code)
            self.assertIn(obj["asset_id"], code)

    def test_scale_is_multiplied_by_the_shared_reference_footprint(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(1))
        obj = blueprint["objects"][0]
        code = blueprint_to_unity_command(blueprint)
        expected = obj["scale"][0] * st._DEFAULT_SIZE[0]
        self.assertIn(repr(float(expected)), code)

    def test_wants_floor_flag_reflects_environment_floor(self) -> None:
        # The floor-creation block is always emitted, gated by a runtime
        # "wantsFloor" bool -- only the literal's value should change.
        blueprint = st.place_objects_in_scene(_objects(2))
        blueprint["environment"]["floor"] = True
        self.assertIn("bool wantsFloor = true;", blueprint_to_unity_command(blueprint))
        blueprint["environment"]["floor"] = False
        self.assertIn("bool wantsFloor = false;", blueprint_to_unity_command(blueprint))

    def test_rejects_a_blueprint_with_no_objects(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(1))
        blueprint["objects"] = []
        with self.assertRaises(st.SceneToolError):
            blueprint_to_unity_command(blueprint)

    def test_theme_with_special_characters_is_safely_escaped(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(1), theme='Grandma\'s "Quiet" Room')
        code = blueprint_to_unity_command(blueprint)
        # Must land as an escaped literal, not break out of the C# string.
        self.assertIn('\\"Quiet\\"', code)

    def test_output_is_syntactically_plausible_csharp(self) -> None:
        blueprint = st.place_objects_in_scene(_objects(3))
        code = blueprint_to_unity_command(blueprint)
        self.assertEqual(code.count("{"), code.count("}"))
        self.assertIn("internal class CommandScript : IRunCommand", code)


if __name__ == "__main__":
    unittest.main()
