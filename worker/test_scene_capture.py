"""Unit tests for scene_capture's pure functions (numpy only).

    python -m unittest test_scene_capture      # from worker/
"""

from __future__ import annotations

import base64
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

import scene_capture as sc

INTR = {"fx": 500.0, "fy": 500.0, "cx": 320.0, "cy": 240.0}


def pitch_up(deg: float) -> np.ndarray:
    t = math.radians(deg)
    return np.array([0.0, -math.cos(t), -math.sin(t)])


def synthetic_room(pitch_deg: float = 20.0, cam_h: float = 1.5, w: int = 160, h: int = 120,
                   table_h: float = 0.0, table_frac: float = 0.0):
    """Pointmap of a floor (plus back wall) seen by a camera pitched down,
    optionally with a table top at `table_h` covering the lower image."""
    intr = {"fx": 150.0, "fy": 150.0, "cx": w / 2, "cy": h / 2}
    up = pitch_up(pitch_deg)
    u, v = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
    rays = np.stack([(u - intr["cx"]) / intr["fx"], (v - intr["cy"]) / intr["fy"], np.ones_like(u)], -1)
    frame = sc.gravity_frame(up)
    fwd = frame[2]
    pm = np.full((h, w, 3), np.nan)
    normals = np.full((h, w, 3), np.nan)
    # floor: up . p = -cam_h
    d_up = rays @ up
    with np.errstate(divide="ignore", invalid="ignore"):
        t_floor = np.where(d_up < -1e-6, -cam_h / d_up, np.inf)
        # back wall 4 m ahead: fwd . p = 4
        d_f = rays @ fwd
        t_wall = np.where(d_f > 1e-6, 4.0 / d_f, np.inf)
    t = np.minimum(t_floor, t_wall)
    pm = rays * t[..., None]
    normals[:] = np.where((t_floor <= t_wall)[..., None], up, -fwd)
    if table_frac > 0:
        rows = slice(int(h * (1 - table_frac)), h)
        t_tab = np.where(d_up < -1e-6, -(cam_h - table_h) / d_up, np.inf)
        pm[rows] = rays[rows] * t_tab[rows][..., None]
        normals[rows] = up
    return pm, normals, intr, up


class ProjectionTests(unittest.TestCase):
    def test_project_unproject_roundtrip(self):
        rng = np.random.default_rng(1)
        p = rng.uniform([-1, -1, 0.5], [1, 1, 5], size=(100, 3))
        u, v, z = sc.project(p, INTR)
        q = sc.unproject(u, v, z, INTR)
        np.testing.assert_allclose(p, q, atol=1e-9)

    def test_principal_point_projects_to_centre(self):
        u, v, _ = sc.project(np.array([[0.0, 0.0, 2.0]]), INTR)
        self.assertAlmostEqual(u[0], 320.0)
        self.assertAlmostEqual(v[0], 240.0)

    def test_intrinsics_from_normalized(self):
        k = np.array([[0.8, 0, 0.5], [0, 0.8 * 640 / 480, 0.5], [0, 0, 1]])
        d = sc.intrinsics_from_normalized(k, 640, 480)
        self.assertAlmostEqual(d["fx"], 512.0)
        self.assertAlmostEqual(d["fy"], 512.0)
        self.assertEqual((d["cx"], d["cy"]), (320.0, 240.0))

    def test_splat_render_front_most_wins(self):
        xyz = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 2.0]])
        rgb = np.array([[1.0, 0, 0], [0, 1.0, 0]])
        img = sc.splat_render(xyz, rgb, INTR, 640, 480)
        np.testing.assert_allclose(img[240, 320], [1.0, 0, 0])
        self.assertTrue(np.isnan(img[0, 0, 0]))

    def test_front_depth_and_alignment_scale(self):
        pm, _, intr, _ = synthetic_room(w=80, h=60)
        pts = pm.reshape(-1, 3)
        sd = sc.front_depth(pts / 1.7, intr, 80, 60)
        s, mad, n = sc.alignment_scale(sd, pm[..., 2])
        self.assertAlmostEqual(s, 1.7, places=2)
        self.assertLess(mad, 1e-2)
        self.assertGreater(n, 1000)


class PlaneTests(unittest.TestCase):
    def test_fit_plane_orients_toward_camera(self):
        rng = np.random.default_rng(0)
        xz = rng.uniform(-2, 2, size=(500, 2))
        p = np.stack([xz[:, 0], np.full(500, 1.5), xz[:, 1] + 3], 1)  # y down: floor 1.5 below
        n, d = sc.fit_plane(p)
        np.testing.assert_allclose(n, [0, -1, 0], atol=1e-9)
        self.assertAlmostEqual(d, 1.5)

    def test_ransac_plane_rejects_outliers(self):
        rng = np.random.default_rng(0)
        xz = rng.uniform(-2, 2, size=(800, 2))
        p = np.stack([xz[:, 0], 1.2 + rng.normal(0, 0.003, 800), xz[:, 1] + 3], 1)
        out = rng.uniform(-2, 2, size=(300, 3)) + [0, 0, 3]
        n, d, inl = sc.ransac_plane(np.concatenate([p, out]), threshold=0.02)
        self.assertLess(sc.angle_deg(n, [0, -1, 0]), 1.0)
        self.assertAlmostEqual(d, 1.2, places=2)
        self.assertGreater(inl[:800].mean(), 0.95)

    def test_gravity_frame_is_right_handed_to_unity(self):
        f = sc.gravity_frame([0, -1, 0])
        np.testing.assert_allclose(f[0], [1, 0, 0], atol=1e-12)   # right
        np.testing.assert_allclose(f[1], [0, -1, 0], atol=1e-12)  # up
        np.testing.assert_allclose(f[2], [0, 0, 1], atol=1e-12)   # forward
        f2 = sc.gravity_frame([0, 0, -1])  # straight down
        self.assertTrue(np.all(np.isfinite(f2)))

    def _run(self, **kw):
        pm, nm, intr, up = synthetic_room(**kw)
        ok = np.all(np.isfinite(pm), -1)
        P, N = pm[ok], nm[ok]
        A = sc.pixel_area_weights(P, N, intr)
        return P, N, A, up

    def test_refine_gravity_from_noisy_prior(self):
        P, N, A, up = self._run(pitch_deg=25)
        prior = sc._unit(up + [0.1, 0.05, 0.1])
        g, frac = sc.refine_gravity(N, A, prior)
        self.assertLess(sc.angle_deg(g, up), 0.5)
        self.assertGreater(frac, 0.1)

    def test_gravity_without_prior_eye_level_and_top_down(self):
        for pitch in (15.0, 70.0):
            P, N, A, up = self._run(pitch_deg=pitch, cam_h=1.4)
            g, info = sc.gravity_from_normals(N, A, P)
            self.assertLess(sc.angle_deg(g, up), 1.0, (pitch, info))

    def test_support_plane_floor_eye_level(self):
        P, N, A, up = self._run(pitch_deg=20, cam_h=1.55)
        plane, u = sc.support_plane(P, N, A, up)
        self.assertEqual(plane["kind"], "floor")
        self.assertAlmostEqual(plane["camera_height"], 1.55, places=2)
        self.assertEqual(plane["offset"], plane["camera_height"])
        # plane equation: normal . p + offset = 0 on the floor
        floor_pt = -1.55 * np.asarray(plane["normal_cam"])
        self.assertAlmostEqual(float(np.dot(plane["normal_cam"], floor_pt) + plane["offset"]), 0.0, places=3)

    def test_support_prefers_lowest_substantial_plane(self):
        P, N, A, up = self._run(pitch_deg=30, cam_h=1.6, table_h=0.75, table_frac=0.35)
        plane, _ = sc.support_plane(P, N, A, up)
        self.assertAlmostEqual(plane["camera_height"], 1.6, places=2)
        self.assertEqual(plane["kind"], "floor")

    def test_close_up_from_above_is_surface(self):
        # top-down shot of a sofa seat 1.1 m below: in floor range but a close-up
        P, N, A, up = self._run(pitch_deg=70, cam_h=1.1)
        near = P @ up > -1.2
        plane, _ = sc.support_plane(P[near], N[near], A[near], up)
        self.assertEqual(plane["kind"], "surface")
        self.assertIn("close-up", plane["kind_reason"])

    def test_high_camera_is_surface(self):
        P, N, A, up = self._run(pitch_deg=20, cam_h=3.0)
        plane, _ = sc.support_plane(P, N, A, up)
        self.assertEqual(plane["kind"], "surface")


class PlacementTests(unittest.TestCase):
    def test_erode_and_resize(self):
        m = np.zeros((10, 10), bool)
        m[2:8, 2:8] = True
        e = sc.erode(m, 1)
        self.assertEqual(int(e.sum()), 16)
        r = sc.resize_nearest(m, 20, 20)
        self.assertEqual(r.shape, (20, 20))
        self.assertEqual(int(r.sum()), 144)

    def test_box_on_floor(self):
        # a 0.8 (w) x 0.4 (h) x 0.5 (d) box on a floor 1.5 m below a level camera,
        # 3 m ahead; the pointmap holds its visible front/top faces.
        W, H = 320, 320
        intr = {"fx": 250.0, "fy": 250.0, "cx": 160.0, "cy": 160.0}
        pts = []
        for x in np.linspace(-0.4, 0.4, 200):
            for y in np.linspace(1.1, 1.5, 100):
                pts.append([x, y, 3.0])       # front face (y down: 1.5 = floor)
            for z in np.linspace(3.0, 3.5, 60):
                pts.append([x, 1.1, z])       # top face
        pts = np.array(pts)
        u, v, z = sc.project(pts, intr)
        pm = np.full((H, W, 3), np.nan)
        ui, vi = u.astype(int), v.astype(int)
        order = np.argsort(-z)
        pm[vi[order], ui[order]] = pts[order]
        mask = np.all(np.isfinite(pm), -1)
        # fill holes so the mask is solid
        obj = sc.object_placement(pm, mask, [0, -1, 0], image_size=(W, H), pointmap_intrinsics=intr)
        self.assertAlmostEqual(obj["extent_m"]["width"], 0.8, delta=0.08)
        self.assertAlmostEqual(obj["extent_m"]["height"], 0.4, delta=0.06)
        self.assertAlmostEqual(obj["base_cam"][1], 1.5, delta=0.03)  # on the floor
        self.assertAlmostEqual(obj["base_cam"][2], obj["centroid_cam"][2], places=6)
        # the visible footprint (front face + top) is nearly isotropic -> yaw may be null
        if obj["yaw_deg"] is not None:
            self.assertLess(abs(obj["yaw_deg"]), 5.0)  # long side faces the camera
        self.assertGreater(obj["mask_area_frac"], 0)
        x0, y0, x1, y1 = obj["mask_bbox"]
        self.assertTrue(0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H)

    def test_yaw_sign_matches_unity(self):
        # long axis rotated so its right end is farther away -> Unity yaw < 0
        W, H = 320, 320
        intr = {"fx": 250.0, "fy": 250.0, "cx": 160.0, "cy": 160.0}
        a = math.radians(30)
        pts = []
        for s in np.linspace(-0.5, 0.5, 80):
            for t in np.linspace(-0.1, 0.1, 10):
                for y in (1.3, 1.5):
                    pts.append([s * math.cos(a) - t * math.sin(a), y, 3 + s * math.sin(a) + t * math.cos(a)])
        pts = np.array(pts)
        u, v, z = sc.project(pts, intr)
        pm = np.full((H, W, 3), np.nan)
        pm[v.astype(int), u.astype(int)] = pts
        obj = sc.object_placement(pm, np.all(np.isfinite(pm), -1), [0, -1, 0], image_size=(W, H))
        self.assertAlmostEqual(obj["yaw_deg"], -30.0, delta=4.0)


class GaussianTests(unittest.TestCase):
    def _gaussians(self, n=1000, seed=0):
        rng = np.random.default_rng(seed)
        return {
            "xyz": rng.uniform([-1, -1, 0.5], [1, 1, 4], size=(n, 3)),
            "f_dc": rng.normal(size=(n, 3)),
            "opacity_logit": rng.normal(size=n),
            "scale_log": rng.normal(-4, 0.5, size=(n, 3)),
            "rot": rng.normal(size=(n, 4)),
        }

    def test_prune_keeps_most_important_and_filters(self):
        g = self._gaussians()
        g["xyz"][0] = [0, 0, -1]              # behind the camera
        g["f_dc"][1, 0] = np.nan              # non-finite
        g["opacity_logit"][2] = -10           # transparent
        g["opacity_logit"][3] = 10            # opaque and huge -> must survive
        g["scale_log"][3] = [0, 0, 0]
        out, stats = sc.sanitize_and_prune(g, max_count=100)
        self.assertEqual(stats["output"], 100)
        self.assertEqual(stats["nonfinite"], 1)
        self.assertEqual(len(out["xyz"]), 100)
        self.assertTrue(np.any(np.all(np.isclose(out["xyz"], g["xyz"][3]), axis=1)))
        self.assertTrue(np.all(out["xyz"][:, 2] > 0))
        np.testing.assert_allclose(np.linalg.norm(out["rot"], axis=1), 1.0, atol=1e-9)
        imp = sc.importance(out)
        self.assertTrue(np.all(np.isfinite(imp)))

    def test_apply_scale(self):
        g = self._gaussians(10)
        s = sc.apply_scale(g, 2.0)
        np.testing.assert_allclose(s["xyz"], g["xyz"] * 2)
        np.testing.assert_allclose(s["scale_log"], g["scale_log"] + math.log(2))

    def test_ply_roundtrip_and_header(self):
        g, _ = sc.sanitize_and_prune(self._gaussians(50), max_count=50)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.ply"
            n = sc.write_ply(path, g)
            raw = path.read_bytes()
            header = raw[: raw.index(b"end_header\n")].decode()
            self.assertIn("format binary_little_endian 1.0", header)
            self.assertIn(f"element vertex {n}", header)
            self.assertEqual(header.count("element"), 1)
            back = sc.read_ply(path)
            self.assertEqual(back["names"], list(sc.PLY_PROPERTIES))
            self.assertEqual(back["count"], n)
            np.testing.assert_allclose(back["data"]["x"], g["xyz"][:, 0].astype(np.float32))
            np.testing.assert_allclose(back["data"]["rot_3"], g["rot"][:, 3].astype(np.float32))
            self.assertEqual(len(raw) - (raw.index(b"end_header\n") + 11), n * 14 * 4)

    def test_write_ply_refuses_nonfinite(self):
        g, _ = sc.sanitize_and_prune(self._gaussians(5), max_count=5)
        g["xyz"][0, 0] = np.inf
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sc.write_ply(Path(tmp) / "x.ply", g)

    def test_color_conversions(self):
        self.assertAlmostEqual(float(sc.linear_to_srgb(np.array([1.0]))[0]), 1.0)
        self.assertAlmostEqual(float(sc.linear_to_srgb(np.array([0.0]))[0]), 0.0)
        rgb = np.array([[0.2, 0.5, 0.9]])
        np.testing.assert_allclose(sc.sh0_to_rgb(sc.rgb_to_sh0(rgb)), rgb)


class DepthGridTests(unittest.TestCase):
    def test_all_valid(self):
        pm, _, _, _ = synthetic_room(w=128, h=96)
        d = sc.depth_grid(pm, width=16)
        self.assertEqual((d["grid"]["w"], d["grid"]["h"]), (16, 12))
        self.assertEqual(len(d["grid"]["points_cam"]), 16 * 12 * 3)
        self.assertEqual(d["valid"], [])
        self.assertTrue(all(math.isfinite(x) for x in d["grid"]["points_cam"]))

    def test_invalid_cells_bitmask(self):
        pm, _, _, _ = synthetic_room(w=128, h=96)
        pm[:8, :8] = np.nan  # first cell (8x8 px) invalid
        d = sc.depth_grid(pm, width=16)
        bits = np.frombuffer(base64.b64decode(d["valid"]), dtype=np.uint8)
        valid = [int((bits[i // 8] >> (i % 8)) & 1) for i in range(16 * 12)]
        self.assertEqual(valid[0], 0)
        self.assertEqual(sum(valid), 16 * 12 - 1)
        self.assertEqual(len(d["grid"]["points_cam"]), sum(valid) * 3)


try:  # backfill_scenes needs boto3 (host venv, WSL backend venv); skipped elsewhere
    import boto3 as _boto3  # noqa: F401
    import backfill_scenes as bf
except ImportError:  # pragma: no cover
    bf = None


class _FakeS3:
    def __init__(self, keys):
        self.keys, self.heads = set(keys), []

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key not in self.keys:
            raise KeyError(Key)
        return {}


class _FakeDdb:
    def __init__(self, item=None, error=None):
        self.item, self.error, self.calls = item, error, []

    def get_item(self, TableName, Key):
        self.calls.append(Key)
        if self.error:
            raise self.error
        return {"Item": self.item} if self.item else {}

    def scan(self, **_):  # the instance role may not Scan
        raise AssertionError("dynamodb:Scan must never be called")


@unittest.skipIf(bf is None, "boto3 not installed")
class FindPhotoKeyTest(unittest.TestCase):
    P, U = "proj1", "up1"

    def _find(self, s3, ddb, project):
        orig = bf.boto3.client
        bf.boto3.client = lambda service, **_: ddb
        try:
            return bf.find_photo_key(s3, self.U, project)
        finally:
            bf.boto3.client = orig

    def test_upload_record_image_key(self):
        key = f"uploads/{self.P}/{self.U}/source.jpg"
        ddb = _FakeDdb({"document": {"S": '{"image_key": "%s"}' % key}})
        self.assertEqual(self._find(_FakeS3([key]), ddb, self.P), key)
        self.assertEqual(ddb.calls, [{"pk": {"S": f"PROJECT#{self.P}"}, "sk": {"S": f"UPLOAD#{self.U}"}}])

    def test_head_object_fallback_when_get_item_denied(self):
        key = f"uploads/{self.P}/{self.U}/source.png"
        s3 = _FakeS3([key])
        self.assertEqual(self._find(s3, _FakeDdb(error=RuntimeError("AccessDenied")), self.P), key)
        self.assertEqual(s3.heads[-1], key)

    def test_bare_upload_id_needs_project(self):
        with self.assertRaisesRegex(ValueError, "--project-id"):
            self._find(_FakeS3([]), _FakeDdb(), None)

    def test_missing_photo_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "cannot find the photo of upload up1.*no upload record"):
            self._find(_FakeS3([]), _FakeDdb(), self.P)


if __name__ == "__main__":
    unittest.main()
