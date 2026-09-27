"""Tests for scene_pose (pose.json written beside each reconstruction).

Run with: python -m unittest test_scene_pose.py   (numpy only; no torch)
"""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

import scene_pose


class _FakeTensor:
    """Just enough of a torch tensor: .detach().float().cpu().numpy()."""

    def __init__(self, values):
        self._values = np.asarray(values, dtype=np.float32)

    def detach(self):
        return self

    def float(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class PoseRecordTests(unittest.TestCase):
    def test_keeps_pose_values_and_shapes_from_tensors(self) -> None:
        ss_return = {
            "rotation": _FakeTensor([[1.0, 0.0, 0.0, 0.0]]),
            "translation": _FakeTensor([[0.1, -0.2, 2.5]]),
            "scale": _FakeTensor([[0.4, 0.4, 0.4]]),
            "coords": _FakeTensor([[0, 0, 0]]),  # not a pose key: ignored
        }
        record = scene_pose.pose_record(ss_return, image_size=(640, 480))
        self.assertEqual(record["rotation"], [1.0, 0.0, 0.0, 0.0])
        self.assertEqual(record["translation_shape"], [1, 3])
        self.assertEqual(record["scale"], [0.4, 0.4, 0.4])
        self.assertEqual(record["image_size"], [640, 480])
        self.assertNotIn("coords", record)
        self.assertIn("coords", record["ss_keys"])
        json.dumps(record)  # JSON-safe

    def test_pointmap_stats_handle_layouts_and_invalid_points(self) -> None:
        points = np.zeros((4, 5, 3))
        points[..., 1] = np.linspace(-1.5, 0.5, 20).reshape(4, 5)
        points[0, 0] = np.nan
        for layout in (points, np.moveaxis(points, -1, 0), points[None]):
            stats = scene_pose.pointmap_stats(layout)
            self.assertEqual(stats["valid_points"], 19)
            self.assertLess(stats["percentiles"]["y"]["1"], stats["percentiles"]["y"]["99"])
        self.assertEqual(scene_pose.pointmap_stats(np.full((2, 2, 3), np.nan)), {"valid_points": 0})

    def test_write_pose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = scene_pose.write_pose(Path(tmp) / "pose.json", {"translation": [0, 0, 1]}, np.ones((2, 2, 3)))
            data = json.loads(path.read_text())
        self.assertEqual(data["translation"], [0.0, 0.0, 1.0])
        self.assertEqual(data["pointmap"]["valid_points"], 4)


def _random_rotation(rng):
    q = rng.normal(size=4)
    return q / np.linalg.norm(q)


def _make_scene_p3d(points, q, t, s):
    """Fast-SAM3D make_scene: Transform3d().scale(s).rotate(R).translate(t),
    PyTorch3D row-vector convention, R = quaternion_to_matrix(q)."""
    return s * (points @ scene_pose.quat_wxyz_to_matrix(q)) + t


def _pinhole_pointmap(k, size, depth):
    w, h = size
    v, u = np.mgrid[0:h, 0:w] + 0.5
    x = (u - k["cx"]) / k["fx"] * depth
    y = (v - k["cy"]) / k["fy"] * depth
    return np.stack([x, y, np.broadcast_to(depth, x.shape)], -1)


class TransformTests(unittest.TestCase):
    def test_quaternion_round_trip(self) -> None:
        rng = np.random.default_rng(0)
        for _ in range(50):
            q = _random_rotation(rng)
            q = q if q[0] >= 0 else -q
            back = scene_pose.matrix_to_quat_wxyz(scene_pose.quat_wxyz_to_matrix(q))
            np.testing.assert_allclose(back, q, atol=1e-9)

    def test_splat_to_cam_matches_make_scene_in_opencv_frame(self) -> None:
        rng = np.random.default_rng(1)
        points = rng.uniform(-0.5, 0.5, size=(200, 3))
        q, t, s = _random_rotation(rng), np.array([0.1, -0.3, 2.0]), 0.7
        expected_cv = _make_scene_p3d(points, q, t, s) @ scene_pose.P3D_TO_CV
        sim = scene_pose.sam3d_splat_to_cam(q, t, [s, s, s])
        np.testing.assert_allclose(scene_pose.apply_similarity(points, sim), expected_cv, atol=1e-9)
        rot = scene_pose.quat_wxyz_to_matrix(sim["rotation_wxyz"])
        self.assertAlmostEqual(np.linalg.det(rot), 1.0, places=9)

    def test_p3d_pointmap_to_cv_flips_x_and_y(self) -> None:
        pm = np.zeros((3, 2, 2)); pm[0] = 1; pm[1] = 2; pm[2] = 3
        cv = scene_pose.p3d_pointmap_to_cv(pm)
        np.testing.assert_allclose(cv[0, 0], [-1, -2, 3])


class ProjectionTests(unittest.TestCase):
    K = {"fx": 500.0, "fy": 480.0, "cx": 320.0, "cy": 240.0}

    def test_intrinsics_from_pointmap_and_rescale(self) -> None:
        depth = np.linspace(1, 3, 640 * 480).reshape(480, 640)
        pm = _pinhole_pointmap(self.K, (640, 480), depth)
        pm[0, 0] = np.nan
        k = scene_pose.intrinsics_from_pointmap(pm)
        for key in self.K:
            self.assertAlmostEqual(k[key], self.K[key], places=6)
        k2 = scene_pose.intrinsics_from_pointmap(pm, image_size=(1280, 960))
        self.assertAlmostEqual(k2["fx"], 1000.0, places=5)
        self.assertAlmostEqual(k2["cy"], 480.0, places=5)

    def _blob_and_mask(self, sim):
        rng = np.random.default_rng(2)
        points = rng.uniform(-0.5, 0.5, size=(40000, 3))
        mask = scene_pose.project_silhouette(scene_pose.apply_similarity(points, sim), self.K, (640, 480))
        return points, mask

    def test_reprojection_iou_is_high_for_the_true_pose_and_low_otherwise(self) -> None:
        sim = {"rotation_wxyz": [1, 0, 0, 0], "translation": [0.2, 0.1, 2.5], "scale": 0.6}
        points, mask = self._blob_and_mask(sim)
        self.assertGreater(scene_pose.reprojection_iou(points, sim, self.K, mask), 0.9)
        wrong = dict(sim, translation=[-0.4, 0.1, 2.5])
        self.assertLess(scene_pose.reprojection_iou(points, wrong, self.K, mask), 0.2)

    def test_depth_ratio_and_rebase_keep_the_object_in_place(self) -> None:
        depth = np.full((480, 640), 2.0)
        sam_pm = _pinhole_pointmap(self.K, (640, 480), depth)
        k2 = {"fx": 550.0, "fy": 550.0, "cx": 318.0, "cy": 242.0}
        metric_pm = _pinhole_pointmap(k2, (640, 480), depth * 1.5)
        mask = np.zeros((480, 640), bool); mask[200:300, 250:400] = True
        ratio = scene_pose.depth_ratio(sam_pm, metric_pm, mask)
        self.assertAlmostEqual(ratio, 1.5, places=6)
        sim = {"rotation_wxyz": [1, 0, 0, 0], "translation": [0.2, 0.1, 2.0], "scale": 0.3}
        points, mask = self._blob_and_mask(sim)
        rebased = scene_pose.rebase_similarity(sim, points, self.K, k2, ratio)
        self.assertGreater(scene_pose.reprojection_iou(points, rebased, k2, mask), 0.85)
        centre = scene_pose.apply_similarity(np.median(points, 0)[None], rebased)[0]
        self.assertAlmostEqual(centre[2], 1.5 * scene_pose.apply_similarity(np.median(points, 0)[None], sim)[0][2], places=6)


def _ellipsoid(n, axes, seed=0):
    rng = np.random.default_rng(seed)
    d = rng.normal(size=(n, 3))
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    return d * np.asarray(axes)


def _render(points_cam, k, size, background_z=2.0):
    """Metric pointmap + mask of an object's surface points in front of a flat background."""
    w, h = size
    u = np.floor(k["fx"] * points_cam[:, 0] / points_cam[:, 2] + k["cx"]).astype(int)
    v = np.floor(k["fy"] * points_cam[:, 1] / points_cam[:, 2] + k["cy"]).astype(int)
    ok = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    zbuf = np.full(h * w, np.inf)
    np.minimum.at(zbuf, v[ok] * w + u[ok], points_cam[ok, 2])
    zbuf = zbuf.reshape(h, w)
    mask = np.isfinite(zbuf)
    depth = np.where(mask, zbuf, background_z)
    return _pinhole_pointmap(k, size, depth), mask


class RefineTests(unittest.TestCase):
    K = {"fx": 260.0, "fy": 260.0, "cx": 160.0, "cy": 120.0}
    SIZE = (320, 240)
    TRUE = {"rotation_wxyz": scene_pose.matrix_to_quat_wxyz(
        scene_pose.quat_wxyz_to_matrix([0.9, 0.2, -0.3, 0.25])), "translation": [0.05, 0.08, 1.1], "scale": 0.6}

    def _scene(self):
        surface = _ellipsoid(200000, (0.45, 0.25, 0.12))
        pm, mask = _render(scene_pose.apply_similarity(surface, self.TRUE), self.K, self.SIZE)
        return surface[::10], pm, mask

    def test_umeyama_recovers_a_similarity(self) -> None:
        rng = np.random.default_rng(4)
        src = rng.normal(size=(100, 3))
        dst = scene_pose.apply_similarity(src, self.TRUE)
        for symmetric in (False, True):
            s, rot, t = scene_pose.umeyama(src, dst, symmetric_scale=symmetric)
            self.assertAlmostEqual(s, 0.6, places=9)
            np.testing.assert_allclose(t, self.TRUE["translation"], atol=1e-9)
            np.testing.assert_allclose(rot, scene_pose.quat_wxyz_to_matrix(self.TRUE["rotation_wxyz"]), atol=1e-9)

    def test_front_points_keep_the_camera_facing_side(self) -> None:
        pts = scene_pose.apply_similarity(_ellipsoid(20000, (0.2, 0.2, 0.2)), {"rotation_wxyz": [1, 0, 0, 0], "translation": [0, 0, 1.0], "scale": 1.0})
        front = scene_pose.front_points(pts, self.K, cell_px=4, tol=0.02)
        self.assertGreater(front.sum(), 1000)
        self.assertLess(np.percentile(pts[front, 2], 90), 1.0)  # near hemisphere only

    def test_refine_recovers_a_perturbed_pose(self) -> None:
        points, pm, mask = self._scene()
        rot = scene_pose.quat_wxyz_to_matrix(self.TRUE["rotation_wxyz"])
        tilt = scene_pose.quat_wxyz_to_matrix([np.cos(0.12), np.sin(0.12), 0, 0])  # ~14 deg off
        prior = scene_pose.make_similarity(tilt @ rot, np.add(self.TRUE["translation"], [0.04, -0.03, 0.1]), 0.45)
        self.assertLess(scene_pose.reprojection_iou(points, prior, self.K, mask), 0.6)
        sim, report = scene_pose.refine_pose(points, mask, pm, self.K, prior=prior)
        self.assertGreater(report["iou"], 0.85)
        self.assertLess(report["depth_residual"], 0.02)
        self.assertAlmostEqual(sim["scale"] / 0.6, 1.0, delta=0.1)
        np.testing.assert_allclose(sim["translation"], self.TRUE["translation"], atol=0.04)
        json.dumps(report)

    def test_refine_without_prior_uses_principal_axes(self) -> None:
        points, pm, mask = self._scene()
        sim, report = scene_pose.refine_pose(points, mask, pm, self.K)
        self.assertTrue(report["chosen"].startswith("pca"))
        self.assertGreater(report["iou"], 0.85)

    def test_rotation_helpers(self) -> None:
        up = np.array([0.1, -0.8, -0.6]) / np.linalg.norm([0.1, -0.8, -0.6])
        r = scene_pose.rotation_between(scene_pose.PLY_UP, up)
        np.testing.assert_allclose(r @ scene_pose.PLY_UP, up, atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(r), 1.0, places=12)
        np.testing.assert_allclose(scene_pose.rotation_between(up, -up) @ up, -up, atol=1e-12)
        yaw = scene_pose.axis_angle_matrix(up, 1.1)
        np.testing.assert_allclose(yaw @ up, up, atol=1e-12)
        sim = scene_pose.make_similarity(yaw @ r, [0, 0, 1], 1.0)
        self.assertAlmostEqual(scene_pose.up_alignment(sim, up), 1.0, places=9)
        self.assertIsNone(scene_pose.up_alignment(sim, None))

    def test_refine_with_gravity_stays_upright(self) -> None:
        # A flat object (PLY z = its up, like SAM 3D's canonical frame) lying
        # on a surface seen from above at ~37 deg: with gravity, the
        # alternatives to the prior are upright yaw hypotheses.
        up = np.array([0.0, -0.8, -0.6])
        true_rot = scene_pose.axis_angle_matrix(up, 0.7) @ scene_pose.rotation_between(scene_pose.PLY_UP, up)
        true = scene_pose.make_similarity(true_rot, [0.05, 0.08, 1.1], 0.6)
        surface = _ellipsoid(200000, (0.45, 0.25, 0.12))
        pm, mask = _render(scene_pose.apply_similarity(surface, true), self.K, self.SIZE)
        sim, report = scene_pose.refine_pose(surface[::10], mask, pm, self.K, up=up)
        self.assertTrue(report["chosen"].startswith("yaw"))
        self.assertGreater(report["iou"], 0.85)
        self.assertGreater(report["up_cos"], 0.95)
        self.assertGreater(scene_pose.up_alignment(sim, up), 0.95)

    def test_refine_reports_missing_depth(self) -> None:
        points, pm, mask = self._scene()
        sim, report = scene_pose.refine_pose(points, mask, np.full_like(pm, np.nan), self.K)
        self.assertIsNone(sim)
        self.assertIn("error", report)


class PoseRecordV2Tests(unittest.TestCase):
    def _record(self, iou, placement=None):
        mask = np.zeros((48, 64), bool); mask[10:20, 30:40] = True
        sim = {"rotation_wxyz": [1, 0, 0, 0], "translation": [0, 0, 2], "scale": 0.5}
        pts = np.random.default_rng(3).uniform(-0.2, 0.2, size=(500, 3)) + [0, 0, 2]
        return scene_pose.pose_record_v2(raw={"version": 1}, image_size=(64, 48), intrinsics={"fx": 50, "fy": 50, "cx": 32, "cy": 24},
                                         mask=mask, splat_to_cam=sim, reprojection_iou=iou, placement=placement, points_cam=pts)

    def test_verified_record(self) -> None:
        rec = self._record(0.8)
        json.dumps(rec)
        self.assertEqual(rec["version"], 2)
        self.assertEqual(rec["frame"], "opencv")
        self.assertEqual(rec["object"]["mask_bbox"], [30, 10, 40, 20])
        self.assertIsNotNone(rec["object"]["splat_to_cam"])
        self.assertEqual(rec["object"]["reprojection_iou"], 0.8)
        self.assertEqual(rec["gravity_up_cam"], [0.0, -1.0, 0.0])
        self.assertAlmostEqual(rec["object"]["centroid_cam"][2], 2.0, places=1)
        self.assertFalse(rec["metric"])

    def test_unverified_transform_is_null(self) -> None:
        rec = self._record(0.2)
        self.assertIsNone(rec["object"]["splat_to_cam"])
        self.assertEqual(rec["object"]["reprojection_iou"], 0.2)

    def test_depth_disagreement_is_not_verified(self) -> None:
        mask = np.zeros((48, 64), bool); mask[10:20, 30:40] = True
        sim = {"rotation_wxyz": [1, 0, 0, 0], "translation": [0, 0, 2], "scale": 0.5}
        kw = dict(raw={"version": 1}, image_size=(64, 48), intrinsics={"fx": 50, "fy": 50, "cx": 32, "cy": 24},
                  mask=mask, splat_to_cam=sim, reprojection_iou=0.8)
        self.assertIsNotNone(scene_pose.pose_record_v2(**kw, depth_residual=0.05)["object"]["splat_to_cam"])
        self.assertIsNone(scene_pose.pose_record_v2(**kw, depth_residual=0.3)["object"]["splat_to_cam"])

    def test_placement_values_win(self) -> None:
        placement = {"intrinsics": {"fx": 60, "fy": 61, "cx": 30, "cy": 20}, "gravity_up_cam": [0, -0.9, -0.1],
                     "support_plane": {"kind": "floor", "camera_height": 1.2},
                     "object": {"centroid_cam": [1, 2, 3], "yaw_deg": 12.5}}
        rec = self._record(0.9, placement)
        self.assertEqual(rec["intrinsics"]["fy"], 61)
        self.assertEqual(rec["object"]["centroid_cam"], [1, 2, 3])
        self.assertEqual(rec["object"]["yaw_deg"], 12.5)
        self.assertEqual(rec["support_plane"]["kind"], "floor")
        self.assertTrue(rec["metric"])


if __name__ == "__main__":
    unittest.main()
