"""Tests for the room composer v2 (compose_room -> room spec -> RoomKit).

Run with: python -m unittest test_unity_room.py

These check the room spec against docs/IMMERSIVE_SCENE_PIPELINE.md section 5
(shape, JsonUtility safety, defaults from the scene analysis), the generated
C# (a few reflection lines around the spec), the no-scene fallback and the
CLI. ``scene_layout.photo_room_layout`` (sync-layout stream) is replaced by a
stub with its contract signature, so these run without it.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import scene_tools as st
import unity_room as ur

_INSIGHT = {"theme": "Evenings at home", "explanation": "They all lived in the corner where the family gathered."}
_SCENE_ID = "b0949bf0e9f540229b92411d42843db4"
_ANALYSIS = {
    "room_type": "living room", "setting": "indoor", "time_of_day": "evening", "mood": "cozy, quiet",
    "lighting": {"key_direction": "from window at left", "color_temperature_k": 3200,
                 "sources": ["window left", "floor lamp right"], "brightness": "dim"},
    "materials": {"floor": "light oak wood", "walls": "white plaster", "other": ["pink fleece"]},
    "palette": ["#c2185b", "#f8bbd0"],
    "search_terms": {"hdri": ["cozy living room"], "sounds": ["room tone", "rain on window"], "images": ["family photos"]},
    "caption": "Two tabby cats asleep on a pink blanket on a red sofa.",
}
_CATALOG = {
    "assets": [
        {"label": "cat", "asset_id": "cat1", "upload_id": _SCENE_ID, "unity_path": "Assets/SketchScape/AssetLibrary/cat_1.ply",
         "native_extent": [0.6, 1.0, 0.3], "pose": {"version": 2}},
        {"label": "pink blanket", "asset_id": "blanket1", "upload_id": _SCENE_ID, "unity_path": "Assets/SketchScape/AssetLibrary/blanket_1.ply",
         "native_extent": [1.0, 0.58, 0.02], "pose": {"version": 2}},
        {"label": "remote control", "asset_id": "remote1", "upload_id": _SCENE_ID, "unity_path": "Assets/SketchScape/AssetLibrary/remote_1.ply",
         "native_extent": [0.35, 1.0, 0.19], "pose": {"version": 2}},
        {"label": "tomato", "asset_id": "tomato1", "upload_id": "other", "unity_path": "Assets/SketchScape/AssetLibrary/tomato_1.ply"},
        {"label": "reading lamp", "asset_id": "lamp1", "upload_id": "other2", "unity_path": ""},
    ],
    "scenes": [{
        "scene_id": _SCENE_ID, "project_id": "p1", "photo": "uploads/p1/u/source.jpg",
        "unity_path": "Assets/SketchScape/Scenes/b0949bf0/scene.ply",
        "scene": {"version": 1, "frame": "opencv", "image_size": [640, 480]},
        "analysis": _ANALYSIS,
        "asset_ids": ["cat1", "blanket1", "remote1"],
        "cut_asset_ids": ["cat1", "remote1"],
    }],
}


def _stub_layout(calls):
    def photo_room_layout(scene, objects, *, player_eye_height=1.6):
        calls.append({"scene": scene, "objects": objects, "eye": player_eye_height})
        placed = {}
        for i, o in enumerate(objects):
            placed[o["id"]] = {"mode": "transform", "position": [-0.4 + 0.8 * i, 0.55, 2.2], "rotation": [0.0, 0.0, 0.0, 1.0],
                               "scale": [0.4, 0.4, 0.4], "size_m": 0.45}
        return {
            "scene_transform": {"position": [0.0, player_eye_height, 0.0], "rotation": [1.0, 0.0, 0.0, 0.0], "scale": [1.2, 1.2, 1.2]},
            "objects": placed,
            "spawn": {"position": [0.0, 0.0, 0.0], "yaw": 0.0},
            "support": {"kind": "floor", "height": 0.0},
            "camera_world": [0.0, player_eye_height, 0.0],
            "bounds": {"min": [-1.5, 0.0, 1.2], "max": [1.5, 1.4, 4.0]},
            "notes": ["scale from floor"],
        }
    return photo_room_layout


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list = []
        stub = types.SimpleNamespace(photo_room_layout=_stub_layout(self.calls))
        patcher = mock.patch.object(ur, "_scene_layout", stub)
        patcher.start()
        self.addCleanup(patcher.stop)

    def compose(self, **request):
        return ur.compose_room(request, catalog=_CATALOG)


def _walk(value, path="spec"):
    yield path, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}[{i}]")


class SpecShapeTests(_Base):
    def test_spec_matches_contract_and_is_jsonutility_safe(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="Lazy Sunday")["spec"]
        self.assertEqual(set(spec), {"version", "slug", "scene_path", "root", "player", "photo_scene", "objects", "environment",
                                     "lights", "images", "audio", "particles", "staging", "teleport", "credits"})
        self.assertEqual(spec["slug"], "Lazy_Sunday")
        self.assertEqual(spec["scene_path"], "Assets/SketchScape/AgentRooms/Lazy_Sunday.unity")
        self.assertEqual(spec["root"], "SharedRoom_Lazy_Sunday")
        for path, value in _walk(spec):
            self.assertIsNotNone(value, path)
            if isinstance(value, list):
                self.assertFalse(any(isinstance(v, list) for v in value), f"nested array at {path}")
            if isinstance(value, float):
                self.assertTrue(math.isfinite(value), path)
        env = spec["environment"]
        self.assertEqual(set(env), {"hdri_url", "hdri_rotation", "hdri_exposure", "sky_tint", "ambient_mode", "ambient_color",
                                    "ambient_intensity", "fog", "floor", "shell"})
        self.assertEqual(set(env["floor"]), {"enabled", "size", "height", "texture_url", "color", "tiling"})
        self.assertEqual(set(env["shell"]), {"enabled", "center", "size", "wall_texture_url", "wall_color", "ceiling"})
        for obj in spec["objects"]:
            self.assertEqual(set(obj), {"id", "label", "asset_id", "splat_path", "mode", "position", "rotation", "scale", "size_m",
                                        "tint", "grabbable", "light"})
            self.assertEqual(len(obj["rotation"]), 4)
            self.assertEqual(set(obj["light"]), {"enabled", "type", "color", "intensity", "range", "offset"})
        for light in spec["lights"]:
            self.assertEqual(set(light), {"type", "color", "intensity", "position", "rotation", "range", "spot_angle", "shadows", "name"})
            self.assertAlmostEqual(sum(q * q for q in light["rotation"]), 1.0, places=3)
        self.assertEqual(len(spec["teleport"]["hotspots"]) % 3, 0)
        self.assertEqual(set(spec["staging"]), {"enabled", "mood_color", "glow_position", "motif_xz", "reveal_order", "reveal_seconds",
                                                "narration", "narration_audio_url"})

    def test_photo_scene_places_cut_objects_and_lists_the_rest_as_in_photo(self) -> None:
        result = self.compose(scene_id=_SCENE_ID, room_name="Lazy Sunday")
        spec, plan = result["spec"], result["plan"]
        self.assertTrue(spec["photo_scene"]["enabled"])
        self.assertEqual(spec["photo_scene"]["splat_path"], "Assets/SketchScape/Scenes/b0949bf0/scene.ply")
        self.assertEqual(spec["photo_scene"]["scale"], [1.2, 1.2, 1.2])
        self.assertEqual([o["label"] for o in spec["objects"]], ["cat", "remote control"])  # cut objects only
        self.assertTrue(all(o["mode"] == "transform" and o["grabbable"] for o in spec["objects"]))
        self.assertEqual(plan["in_photo_scene"], ["pink blanket"])
        # The layout got the contract's object fields and the eye height.
        self.assertEqual(self.calls[0]["eye"], 1.6)
        self.assertEqual(set(self.calls[0]["objects"][0]), {"id", "pose", "native_extent", "bounds_min", "bounds_max", "label_size_m"})
        grabs = [s["args"]["NameOrID"] for s in plan["unity_steps"] if s["tool"].endswith("meta_add_grabbable")]
        self.assertEqual(grabs, [o["id"] for o in spec["objects"]])

    def test_prefix_scene_id_and_eye_height(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID[:8], room_name="R", player_eye_height=1.2)["spec"]
        self.assertEqual(spec["player"]["eye_height"], 1.2)
        self.assertEqual(self.calls[-1]["eye"], 1.2)
        with self.assertRaises(st.SceneToolError):
            self.compose(scene_id="nope", room_name="R")
        with self.assertRaises(st.SceneToolError):
            self.compose(scene_id=_SCENE_ID, player_eye_height=5)

    def test_objects_from_a_scene_bring_the_scene_automatically(self) -> None:
        result = self.compose(objects=[{"label": "our cat Miso"}], room_name="R")
        self.assertTrue(result["spec"]["photo_scene"]["enabled"])
        self.assertEqual([o["label"] for o in result["spec"]["objects"]], ["cat", "remote control"])  # not duplicated
        no_scene = self.compose(objects=[{"label": "our cat Miso"}], room_name="R", scene_id="none")
        self.assertFalse(no_scene["spec"]["photo_scene"]["enabled"])

    def test_extra_objects_sit_beside_the_photo_not_in_front(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, objects=[{"label": "tomato"}, {"label": "guitar"}], room_name="R")["spec"]
        extras = [o for o in spec["objects"] if o["label"] in ("tomato", "guitar")]
        self.assertEqual(len(extras), 2)
        for o in extras:
            self.assertEqual(o["mode"], "upright")
            self.assertEqual(o["position"][1], 0.0)
            bearing = math.degrees(math.atan2(o["position"][0], o["position"][2]))
            self.assertGreater(abs(bearing), 40)  # outside the photo's view cone
        self.assertEqual({o["label"]: bool(o["splat_path"]) for o in extras}, {"tomato": True, "guitar": False})


class AnalysisDefaultsTests(_Base):
    def test_environment_follows_the_analysis(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R")["spec"]
        env = spec["environment"]
        self.assertTrue(env["hdri_url"].startswith("https://dl.polyhaven.org/") and env["hdri_url"].endswith("_2k.hdr"))
        self.assertIn("fireplace", env["hdri_url"])  # indoor + evening + cozy
        self.assertIn("laminate_floor_02", env["floor"]["texture_url"])  # "light oak wood"
        self.assertTrue(env["fog"]["enabled"])
        self.assertEqual(env["floor"]["height"], -0.02)  # splat floor stays visible
        self.assertFalse(env["shell"]["enabled"])
        key = next(l for l in spec["lights"] if l["name"] == "Key Light")
        self.assertEqual(key["type"], "directional")
        self.assertGreater(key["color"][0], key["color"][2])  # 3200 K is warm
        self.assertLess(key["intensity"], 1.0)  # "dim"
        # Light from the left travels toward +x: forward = q * (0,0,1).
        x, y, z, w = key["rotation"]
        fwd_x = 2 * (x * z + w * y)
        fwd_y = 2 * (y * z - w * x)
        self.assertGreater(fwd_x, 0.3)
        self.assertLess(fwd_y, 0)  # pointing down
        names = [l["name"] for l in spec["lights"]]
        self.assertIn("Fill Light", names)
        self.assertIn("Rim Light", names)
        self.assertTrue(any(n.startswith("Practical floor lamp") for n in names))
        self.assertFalse(any("window" in n for n in names))
        self.assertEqual([p["kind"] for p in spec["particles"]], ["dust"])
        titles = [a["title"] for a in spec["audio"]]
        self.assertIn("rain on window", titles)
        rain = next(a for a in spec["audio"] if a["title"] == "rain on window")
        self.assertTrue(rain["spatial"])
        self.assertLess(rain["position"][0], 0)  # from the window at the left
        self.assertTrue(any(a["title"] == "Cat purring" and a["spatial"] for a in spec["audio"]))
        self.assertTrue(any("Poly Haven" in c for c in spec["credits"]))
        self.assertTrue(any("Freesound" in c for c in spec["credits"]))

    def test_kelvin_to_rgb(self) -> None:
        warm, daylight, cool = ur.kelvin_to_rgb(2700), ur.kelvin_to_rgb(6600), ur.kelvin_to_rgb(10000)
        self.assertGreater(warm[0], warm[2])
        self.assertTrue(all(c > 0.95 for c in daylight))
        self.assertGreater(cool[2], cool[0])

    def test_overrides(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R", particles="none",
                            environment={"hdri": "satara_night", "floor_texture": "marble", "wall_texture": "red_brick_03", "fog": False})["spec"]
        env = spec["environment"]
        self.assertIn("satara_night_2k.hdr", env["hdri_url"])
        self.assertIn("marble_01", env["floor"]["texture_url"])
        self.assertTrue(env["shell"]["enabled"])
        self.assertIn("red_brick_03", env["shell"]["wall_texture_url"])
        self.assertFalse(env["fog"]["enabled"])
        self.assertEqual(spec["particles"], [])

    def test_images_form_a_gallery_facing_spawn_away_from_the_photo(self) -> None:
        imgs = [{"url": f"https://example.org/{i}.jpg", "title": f"Photo {i}", "attribution": f"'Photo {i}' by A, CC BY 4.0"} for i in range(4)]
        spec = self.compose(scene_id=_SCENE_ID, room_name="R", images=imgs)["spec"]
        self.assertEqual(len(spec["images"]), 4)
        seen = set()
        for img in spec["images"]:
            x, y, z = img["position"]
            self.assertAlmostEqual(y, 1.5, places=2)  # eye height - 0.1
            bearing = math.degrees(math.atan2(x, z))
            self.assertGreater(abs(bearing), 60)  # never in front of the photo scene
            qx, qy, qz, qw = img["rotation"]
            fwd = (2 * (qx * qz + qw * qy), 1 - 2 * (qx * qx + qy * qy))
            dot = (fwd[0] * x + fwd[1] * z) / math.hypot(x, z)
            self.assertGreater(dot, 0.99)  # +Z points away from the viewer: the Quad faces spawn
            seen.add((round(x, 2), round(z, 2)))
            self.assertIn(img["attribution"], spec["credits"])
        self.assertEqual(len(seen), 4)

    def test_requested_sounds_attach_to_objects(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R", sounds=[
            {"url": "https://cdn.example/amb.mp3", "title": "Amb", "attribution": "A", "kind": "ambient"},
            {"url": "https://cdn.example/purr.mp3", "title": "Purr", "attribution": "B", "kind": "object", "attach_to": "cat"},
        ])["spec"]
        by_title = {a["title"]: a for a in spec["audio"]}
        self.assertFalse(by_title["Amb"]["spatial"])
        self.assertTrue(by_title["Purr"]["spatial"])
        cat = next(o for o in spec["objects"] if o["label"] == "cat")
        self.assertAlmostEqual(by_title["Purr"]["position"][0], cat["position"][0])
        self.assertNotIn("room_tone", json.dumps(spec["audio"]))  # the agent's ambience replaces the default bed

    def test_hotspots_include_spawn_and_both_sides_of_the_scene(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R")["spec"]
        flat = spec["teleport"]["hotspots"]
        pts = [flat[i:i + 3] for i in range(0, len(flat), 3)]
        self.assertIn([0.0, 0.0, 0.0], pts)
        self.assertTrue(any(p[0] < -1.5 for p in pts) and any(p[0] > 1.5 for p in pts))
        self.assertTrue(all(p[1] == 0.0 for p in pts))
        steps = [s["args"]["Position"] for s in self.compose(scene_id=_SCENE_ID, room_name="R")["plan"]["unity_steps"]
                 if s["tool"].endswith("teleport_hotspot")]
        self.assertEqual(steps, pts)

    def test_staging_from_connection_insight(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R", connection_insight=_INSIGHT)["spec"]
        self.assertEqual(spec["staging"]["narration"], _INSIGHT["explanation"])
        self.assertEqual(sorted(spec["staging"]["reveal_order"]), sorted(o["id"] for o in spec["objects"]))
        self.assertGreater(len(spec["staging"]["motif_xz"]), 2)
        plain = self.compose(scene_id=_SCENE_ID, room_name="R")["spec"]
        self.assertEqual(plain["staging"]["narration"], "")
        self.assertEqual(plain["staging"]["motif_xz"], [])


class PhotoAnchorTests(unittest.TestCase):
    """Fire, embers, hearth light and window sounds sit where the analysis boxed
    the fireplace / window in the photo (real scene_layout, synthetic scene)."""

    def _catalog(self):
        fx = fy = 500.0
        cx, cy, cam_h, wall = 320.0, 240.0, 1.5, 4.0
        pts = []
        for v in range(10, 480, 40):
            for u in range(10, 640, 40):
                z = wall if v <= cy else min(wall, cam_h * fy / (v - cy))  # level camera: floor below, a wall 4 m ahead
                pts += [(u - cx) / fx * z, (v - cy) / fy * z, z]
        scene = {"version": 1, "frame": "opencv", "image_size": [640, 480],
                 "intrinsics": {"fx": fx, "fy": fy, "cx": cx, "cy": cy}, "gravity_up_cam": [0.0, -1.0, 0.0],
                 "support_plane": {"normal_cam": [0.0, -1.0, 0.0], "offset": cam_h, "camera_height": cam_h, "kind": "floor"},
                 "depth_grid": {"w": len(pts) // 3, "h": 1, "points_cam": pts}, "depth_grid_valid": []}
        analysis = {
            "room_type": "cabin living room", "setting": "indoor", "time_of_day": "afternoon", "mood": "cozy, rustic",
            "lighting": {"key_direction": "left, window light", "color_temperature_k": 5500, "sources": ["window on left"], "brightness": "medium"},
            "objects": [{"name": "stone fireplace", "box": [480, 250, 600, 400], "salient": True},
                        {"name": "window", "box": [0, 40, 120, 250], "salient": False}],
            "search_terms": {"sounds": ["fireplace crackling", "birds outside"]},
            "caption": "A cozy cabin living room with a stone fireplace.", "image_size": [640, 480],
        }
        return {"assets": [], "scenes": [{"scene_id": "cabin0001", "project_id": "", "photo": "x.jpg",
                                          "unity_path": "Assets/SketchScape/Scenes/cabin000/scene.ply",
                                          "scene": scene, "analysis": analysis, "asset_ids": [], "cut_asset_ids": []}]}

    def test_fire_and_window_sounds_are_anchored_to_the_photo(self) -> None:
        import scene_layout
        with mock.patch.object(ur, "_scene_layout", scene_layout):
            result = ur.compose_room({"scene_id": "cabin0001", "room_name": "Cabin"}, catalog=self._catalog())
        spec = result["spec"]
        # The fireplace box centre (u 540, v 325) on the wall 4 m away: world ~(1.76, 0.82, 4.0).
        embers = next(p for p in spec["particles"] if p["kind"] == "embers")
        self.assertGreater(embers["position"][0], 1.4)
        self.assertGreater(embers["position"][2], 3.4)
        fire = next(a for a in spec["audio"] if "fire" in a["title"].lower())
        self.assertTrue(fire["spatial"])
        self.assertAlmostEqual(fire["position"][0], 1.76, delta=0.1)
        self.assertAlmostEqual(fire["position"][2], 4.0, delta=0.1)
        glow = next(l for l in spec["lights"] if l["name"].startswith("Hearth glow"))
        self.assertGreater(glow["position"][0], 1.4)
        self.assertLess(glow["position"][2], 4.0)  # pulled into the room, not inside the stone
        self.assertGreater(glow["color"][0], glow["color"][2])  # warm
        outside = [a for a in spec["audio"] if a["spatial"] and "fire" not in a["title"].lower()]
        self.assertTrue(any("bird" in a["title"].lower() for a in outside))  # the analysis asked for birds outside
        for a in outside:  # birdsong comes in through the window at the left
            self.assertLess(a["position"][0], -1.0)
        beds = [a for a in spec["audio"] if not a["spatial"]]
        self.assertEqual(len(beds), 1)  # one room bed, and it belongs indoors
        self.assertNotIn("bird", beds[0]["title"].lower())
        self.assertFalse(any("rain" in a["title"].lower() for a in spec["audio"]))  # "cozy" must not pull rain in
        self.assertTrue(any("anchored to the photo" in n for n in result["plan"]["notes"]))

    def test_agent_fire_sound_asked_as_ambient_still_crackles_at_the_fireplace(self) -> None:
        # What Muse Spark did live: its own Openverse fire sound, kind "ambient", no attach_to.
        import scene_layout
        with mock.patch.object(ur, "_scene_layout", scene_layout):
            spec = ur.compose_room({"scene_id": "cabin0001", "room_name": "Cabin", "sounds": [
                {"url": "https://cdn.freesound.org/previews/346/346321_6290213-hq.mp3", "title": "Crackling fireplace",
                 "attribution": "'Crackling fireplace' by nielstii, CC0 1.0, via Freesound", "kind": "ambient"}]},
                catalog=self._catalog())["spec"]
        fire = next(a for a in spec["audio"] if a["title"] == "Crackling fireplace")
        self.assertTrue(fire["spatial"])
        self.assertAlmostEqual(fire["position"][0], 1.76, delta=0.1)
        self.assertEqual(sum(1 for a in spec["audio"] if "fire" in a["title"].lower()), 1)  # no curated duplicate
        beds = [a for a in spec["audio"] if not a["spatial"]]
        self.assertEqual(len(beds), 1)  # the room still gets its indoor bed
        self.assertNotIn("fire", beds[0]["title"].lower())
        self.assertTrue(any("bird" in a["title"].lower() and a["position"][0] < -1.0 for a in spec["audio"]))
        self.assertIn("'Crackling fireplace' by nielstii, CC0 1.0, via Freesound", spec["credits"])

    def test_no_anchor_without_boxes_keeps_the_old_placement(self) -> None:
        import scene_layout
        catalog = self._catalog()
        for obj in catalog["scenes"][0]["analysis"]["objects"]:
            obj.pop("box")
        with mock.patch.object(ur, "_scene_layout", scene_layout):
            spec = ur.compose_room({"scene_id": "cabin0001", "room_name": "Cabin"}, catalog=catalog)["spec"]
        self.assertFalse(any(l["name"].startswith("Hearth glow") for l in spec["lights"]))


class NoSceneFallbackTests(_Base):
    def test_objects_stand_upright_on_an_arc_with_label_sizes(self) -> None:
        result = ur.compose_room({"objects": [{"label": "tomato"}, {"label": "family sofa"}, {"label": "reading lamp"}],
                                  "room_name": "Arc", "connection_insight": _INSIGHT}, catalog={"assets": _CATALOG["assets"][3:], "scenes": []})
        spec = result["spec"]
        self.assertFalse(spec["photo_scene"]["enabled"])
        self.assertEqual(self.calls, [])
        self.assertEqual([o["mode"] for o in spec["objects"]], ["upright"] * 3)
        self.assertEqual([o["size_m"] for o in spec["objects"]], [0.35, 2.0, 0.35])
        self.assertTrue(all(o["position"][1] == 0.0 and o["position"][2] > 0.5 for o in spec["objects"]))
        self.assertEqual([bool(o["splat_path"]) for o in spec["objects"]], [True, False, False])
        lamp = spec["objects"][2]
        self.assertTrue(lamp["light"]["enabled"])  # practical light on the lamp
        self.assertEqual(spec["player"]["spawn"], [0.0, 0.0, 0.0])
        self.assertTrue(spec["environment"]["hdri_url"])
        self.assertTrue(spec["audio"])  # a default ambient bed
        self.assertIn("warm-amber", result["plan"]["staging"]["lighting_preset"])

    def test_missing_layout_function_degrades_to_the_arc(self) -> None:
        with mock.patch.object(ur, "_scene_layout", types.SimpleNamespace()):
            result = self.compose(scene_id=_SCENE_ID, room_name="R")
        self.assertFalse(result["spec"]["photo_scene"]["enabled"])
        self.assertTrue(any("photo_room_layout" in n for n in result["plan"]["notes"]))

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(st.SceneToolError):
            ur.compose_room({"room_name": "R"}, catalog={"assets": [], "scenes": []})
        with self.assertRaises(st.SceneToolError):
            ur.compose_room({"objects": [{}]}, catalog={"assets": [], "scenes": []})
        with self.assertRaises(st.SceneToolError):
            ur.room_finalize_command("../escape")


class CSharpTests(_Base):
    def test_build_code_is_a_few_lines_calling_roomkit_by_reflection(self) -> None:
        result = self.compose(scene_id=_SCENE_ID, room_name="Grandma's \"Quiet\" Room", connection_insight=_INSIGHT)
        code = result["build_code"]
        self.assertIn("internal class CommandScript : IRunCommand", code)
        self.assertIn('System.Type.GetType("SketchScape.RoomKit, Assembly-CSharp-Editor")', code)
        self.assertIn('GetMethod("Build", new[] { typeof(string) })', code)
        self.assertIn("python scripts/install_hackgt_roomkit.py", code)
        self.assertLess(len([l for l in code.splitlines() if l.strip()]), 25)
        # The spec round-trips out of the C# verbatim literal.
        start = code.index('const string Spec = @"') + len('const string Spec = @"')
        end = code.index('";\n', start)
        spec = json.loads(code[start:end].replace('""', '"'))
        self.assertEqual(spec, json.loads(json.dumps(result["spec"])))
        body = code.replace(code[start:end], "")
        self.assertEqual(body.count("{"), body.count("}"))

    def test_finalize_code_passes_spawn(self) -> None:
        spec = self.compose(scene_id=_SCENE_ID, room_name="R")["spec"]
        code = ur.room_finalize_command("R", spec)
        self.assertIn('GetMethod("Finalize"', code)
        self.assertIn('new object[] { "R", 0.0f, 0.0f, 0.0f }', code)
        self.assertEqual(code.count("{"), code.count("}"))


class CliTests(unittest.TestCase):
    MAX_OUTPUT_CHARS = 12_000

    def setUp(self) -> None:
        self._state = tempfile.TemporaryDirectory()
        self.addCleanup(self._state.cleanup)
        self.catalog = Path(self._state.name) / "catalog.json"
        self.catalog.write_text(json.dumps(_CATALOG))

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(Path(__file__).with_name("unity_room_cli.py")), *args],
            capture_output=True, text=True, check=False,
            env={**os.environ, "SKETCHSCAPE_ROOM_STATE_DIR": self._state.name, "SKETCHSCAPE_ASSET_CATALOG": str(self.catalog)},
        )

    def test_compose_then_build_and_finalize_code(self) -> None:
        objects = [{"label": w} for w in ("tomato", "guitar", "mug", "bookshelf", "photo frame", "oak table", "armchair", "candle")]
        out = self._run("compose_room", json.dumps({"objects": objects, "connection_insight": _INSIGHT, "room_name": "Cli Room", "scene_id": "none"}))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertLess(len(out.stdout), self.MAX_OUTPUT_CHARS)
        self.assertEqual(json.loads(out.stdout)["room"]["slug"], "Cli_Room")
        build = self._run("build_code", "Cli_Room")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertLess(len(build.stdout), self.MAX_OUTPUT_CHARS)
        self.assertTrue("=== END BUILD CODE ===" in build.stdout or "=== END BUILD CODE PART " in build.stdout)
        self.assertTrue((Path(self._state.name) / "Cli_Room.spec.json").is_file())
        fin = self._run("finalize_code", "Cli_Room")
        self.assertIn('"Cli_Room"', fin.stdout)

    def test_big_room_builds_in_verified_parts(self) -> None:
        objects = [{"label": w} for w in ("tomato", "guitar", "mug", "bookshelf", "photo frame", "oak table", "armchair", "candle")]
        images = [{"url": f"https://example.org/very/long/path/to/an/image/number/{i}.jpg", "title": f"Family photo {i}",
                   "attribution": f"'Family photo {i}' by Somebody With A Long Name, CC BY 4.0, via Openverse"} for i in range(6)]
        out = self._run("compose_room", json.dumps({"objects": objects, "images": images, "connection_insight": _INSIGHT,
                                                    "room_name": "Big Room", "scene_id": "none"}))
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        steps = [s["args"]["Title"] for s in json.loads(out.stdout)["unity_steps"] if s["tool"] == "unity-mcp__Unity_RunCommand"]
        self.assertTrue(steps[0].startswith("Build room Big_Room (part 1/"))
        build = self._run("build_code", "Big_Room")
        self.assertEqual(build.returncode, 0, build.stderr)
        self.assertIn("=== BUILD CODE PART 1/", build.stdout)
        n = int(build.stdout.split("=== BUILD CODE PART 1/")[1].split(":")[0])
        self.assertGreaterEqual(n, 3)
        two = self._run("build_code", "Big_Room", "2")
        self.assertIn(f"=== BUILD CODE PART 2/{n}:", two.stdout)
        self.assertNotIn(f"PART 1/{n}", two.stdout)


    def test_list_scenes_and_assets(self) -> None:
        scenes = json.loads(self._run("list_scenes", "all").stdout)["scenes"]
        self.assertEqual(scenes[0]["scene_id"], _SCENE_ID)
        self.assertEqual(scenes[0]["separate_objects"], ["cat", "remote control"])
        self.assertEqual(scenes[0]["mood"], "cozy, quiet")
        assets = json.loads(self._run("list_assets", "all").stdout)["real_assets"]
        self.assertEqual(len(assets), 5)

    def test_errors_are_json(self) -> None:
        for args in (("compose_room", '{"objects": []}'), ("build_code", "Never_Composed"), ("search_images", '{"query": ""}'), ("nope", "x")):
            bad = self._run(*args)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("error", json.loads(bad.stdout))


class BuildPartsTests(_Base):
    def test_small_spec_is_one_snippet_and_big_spec_round_trips_through_parts(self) -> None:
        small = self.compose(scene_id=_SCENE_ID, room_name="R")
        if len(json.dumps(small["spec"], separators=(",", ":"), ensure_ascii=False)) <= ur.BUILD_SINGLE_MAX_CHARS:
            self.assertEqual(small["build_parts"], [small["build_code"]])
        imgs = [{"url": f"https://example.org/a/long/image/path/{i}.jpg", "title": f"Photo \"{i}\" of us",
                 "attribution": f"'Photo {i}' by Ann Émile O'Brien, CC BY 4.0"} for i in range(6)]
        big = self.compose(scene_id=_SCENE_ID, room_name="Big", images=imgs, connection_insight=_INSIGHT)
        parts = big["build_parts"]
        self.assertGreater(len(parts), 2)
        text = json.dumps(big["spec"], separators=(",", ":"), ensure_ascii=False)
        pieces = []
        for k, code in enumerate(parts[:-1], start=1):
            self.assertIn("internal class CommandScript : IRunCommand", code)
            self.assertIn(f'SessionState.SetString("SketchScape.RoomSpec.Big.{k}", Part)', code)
            self.assertNotIn("System.IO", code)  # file I/O in a snippet needs a user prompt MCP can't answer
            self.assertLess(len(code), 3400)  # each part stays short enough to copy verbatim
            start = code.index('const string Part = @"') + len('const string Part = @"')
            end = code.index('";\n', start)
            pieces.append(code[start:end].replace('""', '"'))
            body = code.replace(code[start:end], "")
            self.assertEqual(body.count("{"), body.count("}"))
        self.assertEqual("".join(pieces), text)
        last = parts[-1]
        self.assertNotIn("System.IO", last)
        # The same FNV-1a over UTF-16 code units that the C# loop computes (the text has non-ASCII chars).
        units = text.encode("utf-16-le")
        h = 2166136261
        for i in range(0, len(units), 2):
            h = ((h ^ (units[i] | units[i + 1] << 8)) * 16777619) & 0xFFFFFFFF
        self.assertIn(f"spec.Length != {len(units) // 2} || h != {h}u", last)
        self.assertIn(f"i <= {len(parts) - 1}", last)
        self.assertIn('SessionState.EraseString("SketchScape.RoomSpec.Big." + i)', last)
        self.assertIn('GetMethod("Build", new[] { typeof(string) })', last)
        self.assertEqual(last.count("{"), last.count("}"))


if __name__ == "__main__":
    unittest.main()
