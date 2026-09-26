"""Tests for the Unity room composer (Build Plan steps 4 + 6, Unity write path).

Run with: python -m unittest test_unity_room.py

These check the plan and the generated C# text deterministically. The C#
itself was compiled and run against the live HackGTUnity Editor (build,
Meta camera rig, interaction rig, grabbable, teleport hotspot, finalize) on
2026-09-26; see docs/BUILD_PLAN.md step 4.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import scene_tools as st
import unity_room as ur

_LABELS = ["reading lamp", "leather armchair", "photo frame", "acoustic guitar", "oak table", "family sofa", "mug", "bookshelf"]
_INSIGHT = {"theme": "Evenings at home", "explanation": "They all lived in the corner where the family gathered."}


def _objects(n: int) -> list[dict]:
    return [{"asset_id": f"asset_{i}", "label": _LABELS[i % len(_LABELS)]} for i in range(n)]


class ComposeRoomTests(unittest.TestCase):
    def test_accepts_varying_object_counts(self) -> None:
        for n in (1, 2, 5, 8):
            plan = ur.compose_room(_objects(n), connection_insight=_INSIGHT, room_name="Room")
            self.assertEqual(len(plan["objects"]), n)
            self.assertEqual(plan["build_code"].count("Place(result, root,"), n)
            grabs = [s for s in plan["unity_steps"] if s["tool"] == "unity-mcp__meta_add_grabbable"]
            self.assertEqual([g["args"]["NameOrID"] for g in grabs], [o["id"] for o in plan["objects"]])

    def test_steps_are_ordered_build_rig_interactions_finalize(self) -> None:
        tools = [s["tool"] for s in ur.compose_room(_objects(3), room_name="Room")["unity_steps"]]
        self.assertEqual(tools[0], "unity-mcp__Unity_RunCommand")
        self.assertEqual(tools[1:4], [
            "unity-mcp__meta_get_config_information",
            "unity-mcp__meta_add_camerarig",
            "unity-mcp__meta_add_interactionrig",
        ])
        self.assertEqual(tools[-1], "unity-mcp__Unity_RunCommand")

    def test_room_lives_in_its_own_scene_file(self) -> None:
        plan = ur.compose_room(_objects(2), room_name="Evenings at Home!")
        self.assertEqual(plan["room"]["slug"], "Evenings_at_Home")
        self.assertEqual(plan["room"]["scene_path"], "Assets/SketchScape/AgentRooms/Evenings_at_Home.unity")
        self.assertIn("NewSceneSetup.EmptyScene", plan["build_code"])
        self.assertIn('"Assets/SketchScape/AgentRooms/Evenings_at_Home.unity"', plan["build_code"])

    def test_refuses_to_discard_unsaved_team_scenes(self) -> None:
        code = ur.compose_room(_objects(1), room_name="Room")["build_code"]
        guard = code.index("has unsaved changes")
        self.assertLess(guard, code.index("EditorSceneManager.NewScene"))

    def test_staging_adds_mood_glow_and_motif_only_with_an_insight(self) -> None:
        staged = ur.compose_room(_objects(3), connection_insight=_INSIGHT, room_name="Room")
        self.assertIn("Connecting Motif", staged["build_code"])
        self.assertIn("new Color(1.0f, 0.72f, 0.42f)", staged["build_code"])  # warm-amber
        self.assertEqual(staged["staging"]["lighting_preset"], "warm-amber")
        plain = ur.compose_room(_objects(3), room_name="Room")
        self.assertNotIn("Connecting Motif", plain["build_code"])
        self.assertIsNone(plain["staging"])

    def test_hotspots_stand_in_front_of_objects_toward_the_entry(self) -> None:
        plan = ur.compose_room(_objects(4), room_name="Room")
        hotspots = [s["args"]["Position"] for s in plan["unity_steps"] if s["tool"].endswith("teleport_hotspot")]
        self.assertEqual(len(hotspots), 4)
        for spot, obj in zip(hotspots, plan["objects"]):
            self.assertEqual(spot[1], 0.0)
            self.assertLess(abs(spot[0]) + abs(spot[2]), abs(obj["position"][0]) + abs(obj["position"][2]))

    def test_sizes_match_the_blueprint_scale_times_reference_footprint(self) -> None:
        plan = ur.compose_room([{"asset_id": "a1", "label": "family sofa"}], room_name="Room")
        self.assertEqual(plan["objects"][0]["size_m"], [2.0, 0.9, 0.9])

    def test_generated_csharp_is_balanced_and_escaped(self) -> None:
        plan = ur.compose_room(_objects(3), connection_insight=_INSIGHT, theme='Grandma\'s "Quiet" Room')
        for code in (plan["build_code"], ur.room_finalize_command(plan["room"]["slug"])):
            self.assertEqual(code.count("{"), code.count("}"))
            self.assertIn("internal class CommandScript : IRunCommand", code)

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(st.SceneToolError):
            ur.compose_room([], room_name="Room")
        with self.assertRaises(st.SceneToolError):
            ur.room_finalize_command("../escape")


class CliTests(unittest.TestCase):
    # OpenClaw truncates tool results at 16k characters (including its own
    # wrapper), so every CLI output must stay well under that for 8 objects.
    MAX_OUTPUT_CHARS = 10_000

    def setUp(self) -> None:
        self._state = tempfile.TemporaryDirectory()
        self.addCleanup(self._state.cleanup)

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("unity_room_cli.py")), *args],
            capture_output=True, text=True, check=False,
            env={**os.environ, "SKETCHSCAPE_ROOM_STATE_DIR": self._state.name},
        )

    def test_compose_then_build_code_round_trip(self) -> None:
        payload = {"objects": _objects(8), "connection_insight": _INSIGHT, "room_name": "Cli Room"}
        out = self._run("compose_room", json.dumps(payload))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertLess(len(out.stdout), self.MAX_OUTPUT_CHARS)
        self.assertEqual(json.loads(out.stdout)["room"]["slug"], "Cli_Room")
        build = self._run("build_code", "Cli_Room")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertLess(len(build.stdout), self.MAX_OUTPUT_CHARS)
        self.assertIn("=== END BUILD CODE ===", build.stdout)
        self.assertEqual(build.stdout.count("Place(result, root,"), 8)

    def test_finalize_and_errors(self) -> None:
        self.assertIn("SharedRoom_Cli_Room", self._run("finalize_code", "Cli_Room").stdout)
        for args in (("compose_room", '{"objects": []}'), ("build_code", "Never_Composed")):
            bad = self._run(*args)
            self.assertEqual(bad.returncode, 1)
            self.assertIn("error", json.loads(bad.stdout))


if __name__ == "__main__":
    unittest.main()
