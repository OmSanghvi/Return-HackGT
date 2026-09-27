"""Tests for scene_layout (photo layout from Fast-SAM3D poses).

Run with: python -m unittest test_scene_layout.py
"""

import math
import random
import unittest

import scene_layout as sl


def _pose(translation, rotation=(1.0, 0.0, 0.0, 0.0), scale=(0.5, 0.5, 0.5), floor_y=-0.8):
    pose = {"rotation": list(rotation), "translation": list(translation), "scale": list(scale)}
    if floor_y is not None:
        pose["pointmap"] = {"percentiles": {"y": {"2": floor_y}}}
    return pose


def _unity_matrix(x, y, z):
    """Ry(y) * Rx(x) * Rz(z), matching Unity's Quaternion.Euler."""
    cx, sx = math.cos(math.radians(x)), math.sin(math.radians(x))
    cy, sy = math.cos(math.radians(y)), math.sin(math.radians(y))
    cz, sz = math.cos(math.radians(z)), math.sin(math.radians(z))
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]

    def mul(a, b):
        return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]

    return mul(ry, mul(rx, rz))


class EulerTests(unittest.TestCase):
    def test_round_trips_unity_euler_angles(self) -> None:
        for angles in ((0, 0, 0), (10, 20, 30), (-45, 170, 5), (60, -30, -80), (0, 90, 0)):
            m = _unity_matrix(*angles)
            back = sl.unity_euler_from_matrix(m)
            again = _unity_matrix(*back)
            for i in range(3):
                for j in range(3):
                    self.assertAlmostEqual(m[i][j], again[i][j], places=5, msg=(angles, back))

    def test_gimbal_lock_still_reproduces_the_rotation(self) -> None:
        m = _unity_matrix(90, 30, 0)
        again = _unity_matrix(*sl.unity_euler_from_matrix(m))
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(m[i][j], again[i][j], places=5)


class LayoutTests(unittest.TestCase):
    def test_floor_sets_player_scale_and_objects_keep_their_photo_positions(self) -> None:
        layout = sl.layout_from_poses(
            [
                {"id": "sofa", "pose": _pose([0.0, -0.8, 2.0], scale=[0.9, 0.9, 0.9])},
                {"id": "lamp", "pose": _pose([1.0, -0.5, 2.5], scale=[0.3, 0.3, 0.3])},
            ],
            player_eye_height=1.6,
        )
        self.assertEqual(layout["scale_source"], "floor")
        self.assertAlmostEqual(layout["scene_scale"], 2.0)  # camera 0.8 units above floor = 1.6 m eyes
        sofa, lamp = layout["objects"]["sofa"], layout["objects"]["lamp"]
        self.assertEqual(sofa["position"], [0.0, 0.0, 4.0])  # on the floor, 4 m ahead
        self.assertEqual(lamp["position"], [-2.0, 0.6, 5.0])  # camera-left (+x) is Unity -x
        self.assertAlmostEqual(sofa["scale"], 1.8)
        self.assertAlmostEqual(lamp["scale"], 0.6)  # relative sizes preserved

    def test_player_height_scales_the_whole_scene(self) -> None:
        objs = [{"id": "a", "pose": _pose([0.0, -0.8, 2.0])}]
        tall = sl.layout_from_poses(objs, player_eye_height=1.8)["objects"]["a"]
        short = sl.layout_from_poses(objs, player_eye_height=1.2)["objects"]["a"]
        self.assertGreater(tall["scale"], short["scale"])
        self.assertEqual(tall["position"][1], 0.0)
        self.assertEqual(short["position"][1], 0.0)

    def test_identity_pose_maps_through_camera_and_import_frames(self) -> None:
        rotation = sl.layout_from_poses([{"id": "a", "pose": _pose([0, -0.8, 2])}])["objects"]["a"]["rotation"]
        self.assertEqual(rotation, [0.0, 180.0, 0.0])  # diag(-1, 1, -1): half a turn about up

    def test_label_sizes_scale_the_scene_without_a_floor(self) -> None:
        layout = sl.layout_from_poses(
            [{"id": "cat", "pose": _pose([0, 0, 2], scale=[0.25] * 3, floor_y=None)}],
            label_sizes={"cat": 0.5},
        )
        self.assertEqual(layout["scale_source"], "labels")
        self.assertAlmostEqual(layout["objects"]["cat"]["scale"], 0.5)

    def test_unusable_input_raises(self) -> None:
        with self.assertRaises(sl.LayoutError):
            sl.layout_from_poses([])
        with self.assertRaises(sl.LayoutError):
            sl.layout_from_poses([{"id": "a", "pose": {"translation": [0, 0, 1]}}])
        with self.assertRaises(sl.LayoutError):
            sl.layout_from_poses([{"id": "a", "pose": _pose([0, 0, 1], floor_y=None)}])  # no floor, no labels
        self.assertFalse(sl.has_pose(None))
        self.assertTrue(sl.has_pose(_pose([0, 0, 1])))


# ---------------------------------------------------------------------------
# Version 2: photo_room_layout
# ---------------------------------------------------------------------------


def _mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _mv(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _tr(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


def _rot_axis(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == "y":
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _quat_wxyz(m):
    x, y, z, w = sl.quaternion_xyzw_from_matrix(m)
    return [w, x, y, z]


def _camera(pitch_down=0.0, roll=0.0):
    """(camera -> level-OpenCV rotation, gravity-up in the camera frame) for a
    camera pitched down / rolled. Level OpenCV: x right, y down, z ahead."""
    c2l = _mm(_rot_axis("x", -pitch_down), _rot_axis("z", roll))  # tips +z toward +y (down)
    return c2l, _mv(_tr(c2l), [0.0, -1.0, 0.0])


def _scene(gravity, camera_height, kind="floor", grid=None):
    scene = {
        "version": 1, "frame": "opencv", "image_size": [640, 480],
        "intrinsics": {"fx": 500, "fy": 500, "cx": 320, "cy": 240},
        "gravity_up_cam": list(gravity),
        "support_plane": {"normal_cam": list(gravity), "offset": camera_height, "camera_height": camera_height, "kind": kind},
    }
    if grid is not None:
        scene["depth_grid"] = {"w": len(grid), "h": 1, "points_cam": [v for p in grid for v in p]}
        scene["depth_grid_valid"] = []
    return scene


def _pose_v2(scene, *, base, centroid=None, extent=(0.5, 0.25, 0.3), splat_to_cam=None, yaw=None):
    pose = {k: scene[k] for k in ("image_size", "intrinsics", "gravity_up_cam", "support_plane")}
    pose.update({"version": 2, "frame": "opencv", "raw": {}})
    pose["object"] = {
        "mask_bbox": [0, 0, 10, 10], "mask_area_frac": 0.05,
        "centroid_cam": list(centroid or base), "base_cam": list(base),
        "extent_m": dict(zip(("width", "height", "depth"), extent)),
        "yaw_deg": yaw, "splat_to_cam": splat_to_cam, "reprojection_iou": None,
    }
    return pose


def _unity_apply(t, local):
    """What Unity does with a Transform: world = position + R(rotation) * (scale * local)."""
    r = sl.matrix_from_quaternion_xyzw(t["rotation"])
    return [t["position"][i] + v for i, v in enumerate(_mv(r, [t["scale"][i] * local[i] for i in range(3)]))]


def _gsplat_import(ply_point):
    return _mv(sl.GSPLAT_IMPORT_MAP, ply_point)


class QuaternionTests(unittest.TestCase):
    def test_round_trips_random_rotations(self) -> None:
        rng = random.Random(3)
        for _ in range(200):
            m = _mm(_rot_axis("y", rng.uniform(-180, 180)), _mm(_rot_axis("x", rng.uniform(-180, 180)), _rot_axis("z", rng.uniform(-180, 180))))
            q = sl.quaternion_xyzw_from_matrix(m)
            self.assertAlmostEqual(sum(c * c for c in q), 1.0, places=9)
            self.assertGreaterEqual(q[3], 0.0)
            back = sl.matrix_from_quaternion_xyzw(q)
            for i in range(3):
                for j in range(3):
                    self.assertAlmostEqual(m[i][j], back[i][j], places=9)

    def test_unity_yaw_quaternion(self) -> None:
        # Unity: Quaternion.Euler(0, 90, 0) = (0, 0.7071, 0, 0.7071) turns +Z to +X.
        q = sl.quaternion_xyzw_from_matrix(_rot_axis("y", 90))
        self.assertEqual([round(c, 4) for c in q], [0.0, 0.7071, 0.0, 0.7071])
        self.assertEqual([round(v, 6) + 0 for v in _mv(sl.matrix_from_quaternion_xyzw(q), [0, 0, 1])], [1.0, 0.0, 0.0])

    def test_decompose_handles_reflections_with_one_negative_axis(self) -> None:
        _, scale, notes = sl.decompose_linear([[2.0, 0, 0], [0, 2.0, 0], [0, 0, -2.0]])
        self.assertEqual([round(v, 6) for v in scale], [2.0, 2.0, -2.0])
        self.assertTrue(notes)
        with self.assertRaises(sl.LayoutError):
            sl.decompose_linear([[0, 0, 0], [0, 1, 0], [0, 0, 1]])


class PhotoRoomLayoutTests(unittest.TestCase):
    def _check_splat(self, transform, ply_points, expected_world, places=4):
        for p, want in zip(ply_points, expected_world):
            got = _unity_apply(transform, _gsplat_import(p))
            for i in range(3):
                self.assertAlmostEqual(got[i], want[i], places=places, msg=(p, got, want))

    def test_level_camera_on_the_floor(self) -> None:
        out = sl.photo_room_layout(_scene([0, -1, 0], 1.5), [])
        self.assertEqual(out["support"], {"kind": "floor", "height": 0.0, "camera_height": 1.5})
        self.assertEqual(out["camera_world"], [0.0, 1.5, 0.0])
        self.assertEqual(out["spawn"], {"position": [0.0, 0.0, 0.0], "yaw": 0.0})
        # Floor 2 m ahead -> y 0; right stays right, up is up.
        self._check_splat(out["scene_transform"], [[0, 1.5, 2], [1, -0.5, 3], [0, 0, 0]], [[0, 0, 2], [1, 2.0, 3], [0, 1.5, 0]])
        # With the default import map (flip z) the scene transform needs no mirror.
        self.assertTrue(all(v > 0 for v in out["scene_transform"]["scale"]))

    def test_tilted_rolled_camera_round_trips(self) -> None:
        for pitch, roll in ((30, 0), (55, 8), (10, -12), (80, 3), (-15, 5)):
            c2l, gravity = _camera(pitch, roll)
            h = 1.3
            out = sl.photo_room_layout(_scene(gravity, h), [])
            t = out["scene_transform"]
            # A floor point lands on y = 0 at its true distance from the camera's foot.
            got = _unity_apply(t, _gsplat_import(_mv(_tr(c2l), [0.4, h, 2.5])))
            self.assertAlmostEqual(got[1], 0.0, places=4)
            self.assertAlmostEqual(math.hypot(got[0], got[2]), math.hypot(0.4, 2.5), places=4)
            if roll == 0:
                self.assertAlmostEqual(got[0], 0.4, places=4)
                self.assertAlmostEqual(got[2], 2.5, places=4)
            cam = out["camera_world"]
            fwd = [a - b for a, b in zip(_unity_apply(t, _gsplat_import([0, 0, 1])), cam)]
            if roll == 0:
                self.assertAlmostEqual(fwd[0], 0.0, places=6)  # heading exactly the camera's
            self.assertGreater(fwd[2], 0.0)
            self.assertAlmostEqual(fwd[1], -math.sin(math.radians(pitch)), places=6)
            # Handedness: the camera's right stays on the player's right.
            right = [a - b for a, b in zip(_unity_apply(t, _gsplat_import([1, 0, 0])), cam)]
            self.assertGreater(right[0], 0.9)

    def test_top_down_camera_uses_the_top_of_the_photo_as_forward(self) -> None:
        out = sl.photo_room_layout(_scene([0.0, 0.0, -1.0], 0.6), [])  # looking straight down
        t = out["scene_transform"]
        self._check_splat(t, [[0, 0, 0.6]], [[0, 0, 0]])  # straight below -> right under it
        top = _unity_apply(t, _gsplat_import([0, -0.3, 0.6]))
        right = _unity_apply(t, _gsplat_import([0.3, 0, 0.6]))
        self.assertAlmostEqual(top[2], 0.3, places=6)  # top of the image is ahead
        self.assertAlmostEqual(top[1], 0.0, places=6)
        self.assertAlmostEqual(right[0], 0.3, places=6)  # image right is the player's right

    def test_nearly_top_down_is_continuous(self) -> None:
        a = sl.camera_alignment(_camera(89.0)[1])
        b = sl.camera_alignment(_camera(90.0)[1])
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(a[i][j], b[i][j], places=1)

    def test_surface_is_raised_so_the_eyes_meet_the_camera(self) -> None:
        c2l, gravity = _camera(70)
        grid = [_mv(_tr(c2l), [x, 0.5, z]) for x in (-0.4, 0.0, 0.4) for z in (-0.1, 0.3, 0.6)]
        out = sl.photo_room_layout(_scene(gravity, 0.5, kind="surface", grid=grid), [], player_eye_height=1.6)
        self.assertEqual(out["support"]["kind"], "surface")
        self.assertAlmostEqual(out["support"]["height"], 1.1)
        self.assertEqual(out["camera_world"], [0.0, 1.6, 0.0])
        self._check_splat(out["scene_transform"], [grid[0]], [[-0.4, 1.1, -0.1]])
        # The player stands (feet on the real floor) just behind the nearest content.
        self.assertAlmostEqual(out["spawn"]["position"][2], -0.1 - sl.SPAWN_BACKOFF_M, places=4)
        self.assertEqual(out["spawn"]["position"][1], 0.0)
        self.assertLessEqual(out["bounds"]["min"][2], out["spawn"]["position"][2])
        low = sl.photo_room_layout(_scene(gravity, 1.5, kind="surface"), [])
        self.assertAlmostEqual(low["support"]["height"], 0.35)
        self.assertAlmostEqual(low["camera_world"][1], 1.85)
        self.assertTrue(any("clamped" in n for n in low["notes"]))
        high = sl.photo_room_layout(_scene(gravity, 0.1, kind="surface"), [])
        self.assertAlmostEqual(high["support"]["height"], 1.2)

    def test_object_splat_to_cam_round_trips(self) -> None:
        _, gravity = _camera(40, 4)
        scene = _scene(gravity, 1.2)
        rng = random.Random(7)
        for _ in range(20):
            r = _mm(_rot_axis("y", rng.uniform(-180, 180)), _rot_axis("x", rng.uniform(-90, 90)))
            s = rng.uniform(0.1, 0.8)
            tr = [rng.uniform(-1, 1), rng.uniform(-0.5, 1.2), rng.uniform(1, 4)]
            pose = _pose_v2(scene, base=tr, splat_to_cam={"rotation_wxyz": _quat_wxyz(r), "translation": tr, "scale": s})
            out = sl.photo_room_layout(
                scene,
                [{"id": "obj", "pose": pose, "native_extent": [1.0, 0.6, 0.4], "bounds_min": [-0.5, -0.3, -0.2], "bounds_max": [0.5, 0.3, 0.2]}],
            )
            obj = out["objects"]["obj"]
            self.assertEqual(obj["mode"], "transform")
            self.assertAlmostEqual(obj["size_m"], s, places=3)
            self.assertAlmostEqual(abs(obj["scale"][0]), s, places=5)
            pts = [[0.5, 0.3, -0.2], [-0.1, 0.2, 0.15], [0, 0, 0]]
            cam = [[s * v + tr[i] for i, v in enumerate(_mv(r, p))] for p in pts]
            # The object lands exactly where the scene splat puts those camera points.
            expected = [_unity_apply(out["scene_transform"], _gsplat_import(c)) for c in cam]
            self._check_splat(obj, pts, expected)

    def test_other_import_maps_stay_consistent(self) -> None:
        saved = sl.GSPLAT_IMPORT_MAP
        try:
            for g in (((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, 1, 0), (0, 0, 1)), ((1, 0, 0), (0, 0, 1), (0, 1, 0))):
                sl.GSPLAT_IMPORT_MAP = tuple(tuple(float(v) for v in row) for row in g)
                out = sl.photo_room_layout(_scene([0, -1, 0], 1.5), [])
                self._check_splat(out["scene_transform"], [[0, 1.5, 2], [1, -0.5, 3]], [[0, 0, 2], [1, 2.0, 3]])
                if sl._det(g) > 0:  # F has det -1, so a det +1 import map needs a mirror
                    self.assertLess(out["scene_transform"]["scale"][2], 0)
                    self.assertTrue(any("reflection" in n for n in out["notes"]))
                # The version-1 path follows the same constant.
                sl.layout_from_poses([{"id": "a", "pose": _pose([0, -0.8, 2])}])
        finally:
            sl.GSPLAT_IMPORT_MAP = saved

    def test_upright_objects_face_the_camera(self) -> None:
        scene = _scene([0, -1, 0], 1.5)
        cat = _pose_v2(scene, base=[1.0, 1.5, 2.0], extent=(0.5, 0.25, 0.3))
        remote = _pose_v2(scene, base=[0.0, 1.5, 3.0], extent=(0.2, 0.03, 0.05), yaw=90.0)
        out = sl.photo_room_layout(scene, [{"id": "cat", "pose": cat}, {"id": "remote", "pose": remote}])
        c = out["objects"]["cat"]
        self.assertEqual((c["mode"], c["position"], c["size_m"], c["scale"]), ("upright", [1.0, 0.0, 2.0], 0.5, [1.0, 1.0, 1.0]))
        fwd = _mv(sl.matrix_from_quaternion_xyzw(c["rotation"]), [0, 0, 1])
        to_cam = [-1.0 / math.hypot(1, 2), 0.0, -2.0 / math.hypot(1, 2)]
        for i in range(3):
            self.assertAlmostEqual(fwd[i], to_cam[i], places=5)
        r = out["objects"]["remote"]
        # Facing the camera is -Z; yaw_deg 90 more (clockwise from above) -> -X.
        self.assertAlmostEqual(_mv(sl.matrix_from_quaternion_xyzw(r["rotation"]), [0, 0, 1])[0], -1.0, places=5)
        self.assertEqual(r["size_m"], 0.2)

    def test_upright_yaw_follows_the_workers_long_axis_under_roll(self) -> None:
        for pitch, roll, yaw_deg in ((40, 8, 0.0), (75, -6, 30.0), (0, 10, -45.0), (90, 0, 60.0)):
            c2l, gravity = _camera(pitch, roll)
            scene = _scene(gravity, 1.0)
            pose = _pose_v2(scene, base=_mv(_tr(c2l), [0.2, 1.0, 1.5]), extent=(0.6, 0.2, 0.2), yaw=yaw_deg)
            out = sl.photo_room_layout(scene, [{"id": "sofa", "pose": pose}])
            rot = sl.matrix_from_quaternion_xyzw(out["objects"]["sofa"]["rotation"])
            # The worker's long axis: its camera "right" (forward x up, flattened), turned
            # yaw_deg clockwise from above about up (Rodrigues about the camera-frame up).
            u = sl._unit(gravity)
            f = [-u[2] * u[0], -u[2] * u[1], 1.0 - u[2] * u[2]]
            if sl._norm(f) < 1e-6:
                f = [u[1] * u[0], -1.0 + u[1] * u[1], u[1] * u[2]]
            right = sl._unit(sl._cross(sl._unit(f), u))
            fwd = sl._cross(u, right)  # right-handed camera frame: forward = up x right
            a = math.radians(yaw_deg)
            long_cam = [math.cos(a) * right[i] - math.sin(a) * fwd[i] for i in range(3)]  # clockwise from above
            long_world = _mv(sl.camera_alignment(gravity), long_cam)
            local_x = _mv(rot, [1, 0, 0])
            self.assertAlmostEqual(abs(sum(local_x[i] * long_world[i] for i in range(3))), 1.0, places=5)
            # +Z faces the camera's side: back toward the viewer.
            self.assertLess(_mv(rot, [0, 0, 1])[2] * math.cos(a), 1e-9)

    def test_v1_or_missing_poses_are_left_to_the_caller(self) -> None:
        v1 = {"version": 1, "rotation": [1, 0, 0, 0], "translation": [0, 0, 2], "scale": [1, 1, 1]}
        out = sl.photo_room_layout(_scene([0, -1, 0], 1.5), [{"id": "a", "pose": v1}, {"id": "b", "pose": None}, {"id": "c"}])
        self.assertEqual(out["objects"], {})
        self.assertTrue(any("a, b, c" in n for n in out["notes"]))

    def test_without_a_scene_the_frame_comes_from_the_poses(self) -> None:
        scene = _scene(_camera(35)[1], 1.1)
        out = sl.photo_room_layout(None, [{"id": "x", "pose": _pose_v2(scene, base=[0.0, 1.0, 2.0]), "label_size_m": 0.3}])
        self.assertIsNone(out["scene_transform"])
        self.assertEqual(out["camera_world"], [0.0, 1.1, 0.0])
        self.assertIn("x", out["objects"])
        self.assertTrue(any("object pose" in n for n in out["notes"]))

    def test_malformed_splat_to_cam_falls_back_to_upright(self) -> None:
        scene = _scene([0, -1, 0], 1.5)
        pose = _pose_v2(scene, base=[0, 1.5, 2], splat_to_cam={"rotation_wxyz": [0, 0, 0, 0], "translation": [0, 0, 2], "scale": 1})
        self.assertEqual(sl.photo_room_layout(scene, [{"id": "x", "pose": pose}])["objects"]["x"]["mode"], "upright")

    def test_nothing_known_still_returns_a_usable_layout(self) -> None:
        out = sl.photo_room_layout(None, [])
        self.assertIsNone(out["scene_transform"])
        self.assertEqual(out["objects"], {})
        self.assertEqual(out["camera_world"], [0.0, 1.6, 0.0])
        self.assertTrue(out["notes"])


class GeometryVersionTests(unittest.TestCase):
    """A pose v2 is only laid out against the scene.json geometry it was made in."""

    def setUp(self) -> None:
        g = _camera(65)[1]
        self.v2 = _scene(g, 0.7633, kind="surface")
        self.v2["splat"] = {"file": "scene.ply", "aligned_scale": 1.0, "metric_scale": {"source": "sharp"}}
        self.v1 = _scene(g, 1.1786, kind="surface")  # the same photo at MoGe-2's 1.56x scale
        self.v1["splat"] = {"file": "scene.ply", "aligned_scale": 1.55829}

    def test_scene_geometry_version(self) -> None:
        self.assertEqual(sl.scene_geometry(self.v2), "v2")
        self.assertEqual(sl.scene_geometry(self.v1), "v1")
        self.assertEqual(sl.scene_geometry(None), "")

    def test_matching_pose_passes_and_rescaled_pose_is_rejected(self) -> None:
        pose = _pose_v2(self.v2, base=[0.0, 0.1, 0.8])
        self.assertIsNone(sl.pose_frame_mismatch(self.v2, pose))
        why = sl.pose_frame_mismatch(self.v1, pose)
        self.assertIn("camera height", why)
        self.assertIn("different geometry versions", why)
        self.assertIn("camera height", sl.pose_frame_mismatch(self.v2, _pose_v2(self.v1, base=[0.0, 0.1, 1.2])))
        # Not decidable -> accepted: no scene, no v2 pose, or no support plane in the pose.
        self.assertIsNone(sl.pose_frame_mismatch(None, pose))
        self.assertIsNone(sl.pose_frame_mismatch(self.v1, {"version": 1}))
        bare = dict(pose, support_plane=None)
        self.assertIsNone(sl.pose_frame_mismatch(self.v2, bare))

    def test_focal_gravity_and_non_metric_poses_are_rejected(self) -> None:
        pose = _pose_v2(self.v2, base=[0.0, 0.1, 0.8])
        other_focal = dict(pose, intrinsics={"fx": 560, "fy": 560, "cx": 320, "cy": 240})
        self.assertIn("focal", sl.pose_frame_mismatch(self.v2, other_focal))
        # The same focal at twice the resolution is the same camera.
        hires = dict(pose, image_size=[1280, 960], intrinsics={"fx": 1000, "fy": 1000, "cx": 640, "cy": 480})
        self.assertIsNone(sl.pose_frame_mismatch(self.v2, hires))
        tilted = dict(pose, gravity_up_cam=_camera(58)[1])
        self.assertIn("gravity", sl.pose_frame_mismatch(self.v2, tilted))
        self.assertIsNone(sl.pose_frame_mismatch(self.v2, dict(pose, gravity_up_cam=_camera(66)[1])))
        self.assertIn("not metric", sl.pose_frame_mismatch(self.v2, dict(pose, metric=False)))
        self.assertIsNone(sl.pose_frame_mismatch(self.v2, dict(pose, metric=True)))

    def test_layout_leaves_mismatched_poses_to_the_caller(self) -> None:
        good = _pose_v2(self.v2, base=[0.0, 0.1, 0.8])
        stale = _pose_v2(self.v1, base=[0.0, 0.1, 1.2])
        out = sl.photo_room_layout(self.v2, [{"id": "cat", "pose": good}, {"id": "remote", "pose": stale}])
        self.assertEqual(set(out["objects"]), {"cat"})
        self.assertTrue(any(n.startswith("remote: pose not in this scene's geometry") for n in out["notes"]))
        self.assertIsNotNone(out["scene_transform"])
        # Without a scene there is nothing to mismatch: both are laid out.
        self.assertEqual(set(sl.photo_room_layout(None, [{"id": "cat", "pose": good}])["objects"]), {"cat"})


if __name__ == "__main__":
    unittest.main()
