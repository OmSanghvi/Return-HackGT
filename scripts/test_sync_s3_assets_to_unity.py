"""Tests for the stdlib pieces of sync_s3_assets_to_unity (PNG masks, PLY I/O,
scene cut-out, catalog merge). No AWS access.

Run with: python -m unittest scripts/test_sync_s3_assets_to_unity.py
"""

import base64
import json
import math
import struct
import sys
import tempfile
import unittest
import zlib
from array import array
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sync_s3_assets_to_unity as sync  # noqa: E402

PROPS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def _png(width, height, rows, ctype, depth=8, filters=(0,), palette=None, trns=None):
    """Encode a PNG; ``rows`` are the unfiltered scanline bytes; each row uses
    the next filter type from ``filters`` (cycled)."""
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = max(1, channels * depth // 8)
    raw = bytearray()
    prev = bytearray(len(rows[0]))
    for y, row in enumerate(rows):
        f = filters[y % len(filters)]
        row = bytearray(row)
        out = bytearray(len(row))
        for i in range(len(row)):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            pred = {0: 0, 1: a, 2: b, 3: (a + b) >> 1, 4: sync._paeth(a, b, c)}[f]
            out[i] = (row[i] - pred) & 0xFF
        raw += bytes([f]) + out
        prev = row

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, ctype, 0, 0, 0))
    if palette:
        data += chunk(b"PLTE", bytes(v for rgb in palette for v in rgb))
    if trns:
        data += chunk(b"tRNS", bytes(trns))
    return data + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


def _pattern(w, h):
    return [[1 if (x - 5) ** 2 + (y - 4) ** 2 < 10 or x == w - 1 else 0 for x in range(w)] for y in range(h)]


def _write_ply(path, rows, props=PROPS):
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(rows)}"]
    header += [f"property float {p}" for p in props] + ["end_header"]
    floats = array("f", [v for r in rows for v in r])
    path.write_bytes(("\n".join(header) + "\n").encode() + floats.tobytes())


def _row(x, y, z, opacity=2.0):
    return [x, y, z, 0.1, 0.2, 0.3, opacity, -3, -3, -3, 1, 0, 0, 0]


class PngTests(unittest.TestCase):
    def test_every_filter_and_color_type_round_trips(self) -> None:
        w, h = 13, 9
        pat = _pattern(w, h)
        cases = {
            0: [bytes(255 * v for v in r) for r in pat],
            2: [bytes(c for v in r for c in (200 * v, 30, 10 * v)) for r in pat],
            4: [bytes(c for v in r for c in (255, 255 * v)) for r in pat],  # white; alpha is the mask
            6: [bytes(c for v in r for c in (255 * v, 255 * v, 255 * v, 255)) for r in pat],
        }
        for ctype, rows in cases.items():
            png = _png(w, h, rows, ctype, filters=(0, 1, 2, 3, 4))
            ww, hh, bits = sync.decode_png_mask(png)
            self.assertEqual((ww, hh), (w, h))
            self.assertEqual(list(bits), [v for r in pat for v in r], msg=ctype)

    def test_one_bit_grayscale_and_palette(self) -> None:
        w, h = 11, 5
        pat = _pattern(w, h)

        def pack(r):
            out = bytearray((w + 7) // 8)
            for x, v in enumerate(r):
                out[x // 8] |= v << (7 - x % 8)
            return bytes(out)

        png = _png(w, h, [pack(r) for r in pat], 0, depth=1, filters=(0, 2))
        self.assertEqual(list(sync.decode_png_mask(png)[2]), [v for r in pat for v in r])
        pal = _png(w, h, [bytes(r) for r in pat], 3, palette=[(0, 0, 0), (255, 255, 255)], filters=(1, 4))
        self.assertEqual(list(sync.decode_png_mask(pal)[2]), [v for r in pat for v in r])

    def test_real_worker_mask_if_present(self) -> None:
        # Masks from artifacts/<job>/mask.png are 8-bit grayscale at the photo's size.
        png = _png(4, 2, [bytes([0, 255, 255, 0]), bytes([0, 0, 255, 0])], 0, filters=(4, 1))
        self.assertEqual(sync.decode_png_mask(png), (4, 2, bytearray([0, 1, 1, 0, 0, 0, 1, 0])))

    def test_dilate(self) -> None:
        w, h = 7, 5
        m = bytearray(w * h)
        m[2 * w + 3] = 1
        d = sync.dilate(m, w, h, 1)
        self.assertEqual(sum(d), 9)
        self.assertEqual(d[1 * w + 2], 1)
        self.assertEqual(d[0 * w + 3], 0)


class PlyAndCutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _scene(self):
        return {"image_size": [40, 30], "intrinsics": {"fx": 40.0, "fy": 40.0, "cx": 20.0, "cy": 15.0}}

    def test_cut_removes_the_object_but_keeps_background_behind_it(self) -> None:
        # A 20x15 mask (half resolution) covering pixels 16..23 x 12..17 of the 40x30 photo.
        mw, mh = 20, 15
        mask = bytearray(mw * mh)
        for y in range(6, 9):
            for x in range(8, 12):
                mask[y * mw + x] = 1
        rows = [
            _row(0.0, 0.0, 1.0),  # centre pixel (20, 15), object depth -> removed
            _row(0.0, 0.0, 0.5),  # in front of the object -> removed (floater)
            _row(0.0, 0.0, 3.0),  # far behind -> kept (background)
            _row(0.5, 0.0, 1.0),  # projects to u = 40: outside the mask -> kept
            _row(0.0, 0.0, -1.0),  # behind the camera -> kept
            _row(float("nan"), 0.0, 2.0),  # non-finite -> dropped
            _row(0.0, 0.0, 2.0, opacity=float("inf")),  # opacity repaired, behind -> kept
        ]
        path = self.dir / "scene.ply"
        _write_ply(path, rows)
        ply = sync.GaussianPly.read(path)
        self.assertEqual(ply.count, 7)
        self.assertEqual(ply.repair_opacity(), 1)
        pose = {"version": 2, "object": {"centroid_cam": [0, 0, 1.0], "base_cam": [0, 0.1, 1.05], "extent_m": {"width": 0.4, "height": 0.2, "depth": 0.3}}}
        z_limit = sync.object_depth_limit(pose)
        self.assertAlmostEqual(z_limit, 1.05 + 0.1)
        stats = sync.cut_scene(ply, self._scene(), [{"asset_id": "cat", "mask": (mw, mh, mask), "z_limit": z_limit}])
        self.assertEqual((stats["before"], stats["after"]), (7, 4))
        self.assertEqual(stats["removed"], {"cat": 2})
        self.assertEqual(stats["dropped_nonfinite"], 1)
        out = self.dir / "cut.ply"
        ply.write(out)
        again = sync.GaussianPly.read(out)
        self.assertEqual(again.count, 4)
        self.assertEqual(list(again.column("z")), [3.0, 1.0, -1.0, 2.0])
        self.assertEqual(again.column("opacity")[3], sync.SAFE_LOGIT)
        self.assertTrue(all(math.isfinite(v) for v in again.floats))
        text = out.read_bytes()[:400].decode("ascii", "replace")
        self.assertIn("element vertex 4\n", text)
        self.assertEqual(len(out.read_bytes()) - text.index("end_header\n") - len("end_header\n"), 4 * 14 * 4)

    def test_verified_pose_extends_the_cut_to_the_far_side_of_the_object(self) -> None:
        obj = {"centroid_cam": [0, 0, 2.0], "base_cam": [0, 0.1, 2.05], "extent_m": {"width": 1.0, "height": 0.5, "depth": 0.8}}
        pose = {"version": 2, "object": dict(obj, splat_to_cam=None)}
        bounds = ([-0.5, -0.5, -0.5], [0.5, 0.5, 1.0])
        self.assertAlmostEqual(sync.object_depth_limit(pose, bounds), 2.05 + 0.2)  # no verified pose: surface + margin
        s2c = {"rotation_wxyz": [1, 0, 0, 0], "translation": [0, 0, 2.0], "scale": 1.0}
        pose = {"version": 2, "object": dict(obj, splat_to_cam=s2c)}
        self.assertAlmostEqual(sync.object_depth_limit(pose), 2.25)  # no bounds: unchanged
        self.assertAlmostEqual(sync.object_depth_limit(pose, bounds), 3.0 + 0.04)  # far face at z = 3
        turned = dict(s2c, rotation_wxyz=[0, 0, 1, 0])  # 180 deg about y: the box's -z side faces away
        self.assertAlmostEqual(sync.object_depth_limit({"version": 2, "object": dict(obj, splat_to_cam=turned)}, bounds), 2.5 + 0.04)
        huge = ([-0.5, -0.5, -0.5], [0.5, 0.5, 20.0])
        self.assertAlmostEqual(sync.object_depth_limit(pose, huge), 2.05 + 1.5 * 1.0)  # capped
        scaled = dict(s2c, scale=0.1)  # a small box never shrinks the limit
        self.assertAlmostEqual(sync.object_depth_limit({"version": 2, "object": dict(obj, splat_to_cam=scaled)}, bounds), 2.25)

    def test_reader_rejects_non_float_or_extra_elements(self) -> None:
        bad = self.dir / "bad.ply"
        bad.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty double x\nend_header\n" + b"\0" * 8)
        with self.assertRaises(ValueError):
            sync.GaussianPly.read(bad)
        bad.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 0\nproperty float x\nend_header\n")
        with self.assertRaises(ValueError):
            sync.GaussianPly.read(bad)


class SyncSceneOfflineTests(unittest.TestCase):
    """sync_scene end to end against a fake S3 (a local folder)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.s3 = self.root / "s3"
        self.saved = (sync._aws, sync._s3_get, sync._s3_list)

        def s3_path(uri_or_key):
            return self.s3 / uri_or_key.split(f"s3://{sync.DEFAULT_BUCKET}/")[-1]

        def fake_aws(*args):
            assert args[:2] == ("s3", "cp"), args
            Path(args[3]).write_bytes(s3_path(args[2]).read_bytes())
            return ""

        def fake_get(bucket, key, dest):
            src = self.s3 / key
            if not src.exists():
                return False
            Path(dest).write_bytes(src.read_bytes())
            return True

        sync._aws, sync._s3_get = fake_aws, fake_get
        sync._s3_list = lambda bucket, prefix: {p.name for p in (self.s3 / prefix).glob("*")}

    def tearDown(self) -> None:
        sync._aws, sync._s3_get, sync._s3_list = self.saved
        self.tmp.cleanup()

    def _put(self, key, data):
        path = self.s3 / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    def test_small_objects_are_cut_and_large_ones_stay(self) -> None:
        upload = "u" * 32
        scene = {
            "version": 1, "upload_id": upload, "photo": f"uploads/p/{upload}/source.jpg", "frame": "opencv",
            "image_size": [40, 30], "intrinsics": {"fx": 40.0, "fy": 40.0, "cx": 20.0, "cy": 15.0},
            "gravity_up_cam": [0, -1, 0], "support_plane": {"normal_cam": [0, -1, 0], "offset": 1.2, "camera_height": 1.2, "kind": "floor"},
            "splat": {"file": "scene.ply", "count": 3},
            "depth_grid": {"w": 2, "h": 1, "points_cam": [0, 1, 2, 0.5, 1, 3]}, "depth_grid_valid": [],
        }
        self._put(f"artifacts/scenes/{upload}/scene.json", scene)
        self._put(f"artifacts/scenes/{upload}/analysis.json", {"room_type": "living room"})
        ply = self.root / "src.ply"
        _write_ply(ply, [_row(0, 0, 1.0), _row(0, 0, 4.0), _row(-0.4, -0.3, 1.0)])
        self._put(f"artifacts/scenes/{upload}/scene.ply", ply.read_bytes())
        full = bytearray(40 * 30)
        full[15 * 40 + 20] = 1
        big = bytearray(b"\x01") * (40 * 30)

        def member(aid, mask, area, pose_v):
            pose = {"version": pose_v, "object": {"centroid_cam": [0, 0, 1.0], "base_cam": [0, 0, 1.0], "extent_m": {"width": 0.3}}}
            return {"entry": {"asset_id": aid, "label": aid, "upload_id": upload, "photo": scene["photo"], "pose": pose, "mask_area_frac": area}, "mask": (40, 30, mask)}

        unity = self.root / "unity"
        synced = [member("cat", full, 0.05, 2), member("blanket", big, 0.6, 2), member("old", full, 0.05, 1)]
        work = self.root / "work"
        work.mkdir()
        with mock.patch.object(sync, "CUT_UNVERIFIED", True):  # the size rule on its own (these poses carry no splat_to_cam)
            entry = sync.sync_scene(upload, synced, bucket=sync.DEFAULT_BUCKET, project_id="p", unity=unity, tmp=work)
        self.assertEqual(entry["cut_asset_ids"], ["cat"])
        self.assertEqual(entry["asset_ids"], ["cat", "blanket", "old"])
        self.assertEqual(entry["unity_path"], f"Assets/SketchScape/Scenes/{upload[:8]}/scene.ply")
        self.assertEqual(entry["cut"], {"before": 3, "after": 2, "removed": {"cat": 1}, "below_support_pruned": 0})
        self.assertEqual(entry["analysis"], {"room_type": "living room"})
        self.assertNotIn("depth_grid_valid", entry["scene"])
        out = sync.GaussianPly.read(unity / entry["unity_path"])
        self.assertEqual(list(out.column("z")), [4.0, 1.0])
        # No scene.json -> nothing.
        self.assertIsNone(sync.sync_scene("v" * 32, synced, bucket=sync.DEFAULT_BUCKET, project_id="p", unity=unity, tmp=work))

    def _room_scene(self, scene_id, camera_height=1.2, metric=True):
        scene = {
            "version": 1, "upload_id": scene_id, "photo": "artifacts/_deploy/testphotos/room1.jpg", "frame": "opencv",
            "image_size": [40, 30], "intrinsics": {"fx": 40.0, "fy": 40.0, "cx": 20.0, "cy": 15.0},
            "gravity_up_cam": [0, -1, 0],
            "support_plane": {"normal_cam": [0, -1, 0], "offset": camera_height, "camera_height": camera_height, "kind": "floor"},
            "splat": {"file": "scene.ply", "count": 2, "aligned_scale": 1.0},
            "depth_grid": {"w": 2, "h": 1, "points_cam": [0, 1, 2, 0.5, 1, 3]}, "depth_grid_valid": [],
        }
        if metric:
            scene["splat"]["metric_scale"] = {"source": "sharp"}
        return scene

    def test_standalone_scene_has_no_objects_and_an_empty_project(self) -> None:
        self._put("artifacts/scenes/testroom1/scene.json", self._room_scene("testroom1"))
        ply = self.root / "room.ply"
        _write_ply(ply, [_row(0, 0, 2.0), _row(0.3, 0.2, 3.0)])
        self._put("artifacts/scenes/testroom1/scene.ply", ply.read_bytes())
        unity, work = self.root / "unity", self.root / "work"
        work.mkdir()
        entry = sync.sync_standalone_scene("testroom1", bucket=sync.DEFAULT_BUCKET, unity=unity, tmp=work, existing={"scenes": []})
        self.assertEqual(entry["scene_id"], "testroom1")
        self.assertEqual(entry["project_id"], "")
        self.assertEqual(entry["photo"], "artifacts/_deploy/testphotos/room1.jpg")
        self.assertEqual(entry["unity_path"], "Assets/SketchScape/Scenes/testroom/scene.ply")
        self.assertEqual((entry["asset_ids"], entry["cut_asset_ids"]), ([], []))
        self.assertEqual(entry["analysis"], {})
        self.assertEqual(sync.GaussianPly.read(unity / entry["unity_path"]).count, 2)
        # The preview is what compose_room gets: the scene at the camera, floor at 0.
        layout = sync.layout_preview(entry, [])
        self.assertEqual(layout["support"]["kind"], "floor")
        self.assertEqual(layout["scene_transform"]["position"], [0.0, 1.2, 0.0])
        # A scene the catalog knows as a project upload is refused (its objects must be cut).
        known = {"scenes": [{"scene_id": "testroom1", "project_id": "p", "asset_ids": ["a"]}]}
        self.assertIsNone(sync.sync_standalone_scene("testroom1", bucket=sync.DEFAULT_BUCKET, unity=unity, tmp=work, existing=known))
        self.assertIsNone(sync.sync_standalone_scene("nothere", bucket=sync.DEFAULT_BUCKET, unity=unity, tmp=work, existing={"scenes": []}))

    def test_verified_pose_is_checked_against_the_photo_before_the_cut(self) -> None:
        # Photo 40x30, f = 40: the photo's visible surface (a cat) is a plane at z = 1.0 over
        # pixels x 10..29, y 10..19 (the mask). The GPU pose puts the scan 10 % too deep and the
        # scan covers only the mask's left half (x 10..19): the right half (a tail it missed)
        # must stay in the scene, and the depth must be pulled onto the photo's surface.
        upload = "r" * 32
        scene = self._room_scene(upload, camera_height=1.2)
        self._put(f"artifacts/scenes/{upload}/scene.json", scene)
        rows = []
        for v in range(10, 20):
            for u in range(10, 30):
                rows.append(_row((u - 20) / 40.0, (v - 15) / 40.0, 1.0))
        rows.append(_row(0.0, 0.0, 3.0))  # background far behind the object: kept
        ply = self.root / "src.ply"
        _write_ply(ply, rows)
        self._put(f"artifacts/scenes/{upload}/scene.ply", ply.read_bytes())
        mask = bytearray(40 * 30)
        for v in range(10, 20):
            for u in range(10, 30):
                mask[v * 40 + u] = 1
        # The scan in its own PLY coordinates = camera coordinates at z = 1.1 (identity rotation,
        # scale 1): a dense patch over the mask's left half.
        unity = self.root / "unity"
        scan = unity / "Assets/SketchScape/AssetLibrary/cat_aaaaaaaa.ply"
        scan.parent.mkdir(parents=True)
        pts = []
        for v in range(10, 20):
            for u in range(10, 20):
                for du in (-0.25, 0.25):
                    pts.append(_row((u + du - 20) * 1.1 / 40.0, (v - 15) * 1.1 / 40.0, 1.1))
        _write_ply(scan, pts)
        pose = {
            "version": 2, "metric": True, "image_size": [40, 30], "intrinsics": scene["intrinsics"],
            "gravity_up_cam": [0, -1, 0], "support_plane": scene["support_plane"],
            "object": {"centroid_cam": [0, 0, 1.05], "base_cam": [0, 0, 1.05], "extent_m": {"width": 0.5},
                       "splat_to_cam": {"rotation_wxyz": [1, 0, 0, 0], "translation": [0.0, 0.0, 0.0], "scale": 1.0}},
        }
        member = {"entry": {"asset_id": "cat", "label": "cat", "upload_id": upload, "photo": scene["photo"], "pose": pose,
                            "mask_area_frac": 0.05, "unity_path": "Assets/SketchScape/AssetLibrary/cat_aaaaaaaa.ply",
                            "native_extent": [0.3, 0.3, 0.01], "bounds_min": [-0.3, -0.15, 1.1], "bounds_max": [0.0, 0.15, 1.1]},
                  "mask": (40, 30, mask)}
        work = self.root / "work"
        work.mkdir()
        saved, sync.REFINE_MIN_PIXELS = sync.REFINE_MIN_PIXELS, 50  # a 40x30 photo has 100 cat pixels
        try:
            entry = sync.sync_scene(upload, [member], bucket=sync.DEFAULT_BUCKET, project_id="p", unity=unity, tmp=work)
        finally:
            sync.REFINE_MIN_PIXELS = saved
        check = entry["cut"]["photo_check"]["cat"]
        self.assertAlmostEqual(check["depth_factor"], round(1.0 / 1.1, 4))
        self.assertAlmostEqual(check["gap_m_before"], 0.1, places=4)
        self.assertAlmostEqual(check["gap_m_after"], 0.0, places=4)
        self.assertAlmostEqual(check["coverage"], 0.6, places=2)  # left half + the 2 px gap closing
        s2c = pose["object"]["splat_to_cam"]
        self.assertAlmostEqual(s2c["scale"], round(1.0 / 1.1, 6))
        self.assertEqual(pose["object"]["splat_to_cam_gpu"]["scale"], 1.0)
        self.assertEqual(pose["sync_refine"], check)
        # The covered part (+ margin) is cut, the uncovered right side and the background stay.
        out = sync.GaussianPly.read(unity / entry["unity_path"])
        kept_u = sorted({round(x * 40 + 20) for x, z in zip(out.column("x"), out.column("z")) if z < 2})
        self.assertEqual(kept_u, list(range(23, 30)))  # x 10..20 covered, +2 px margin (radius 1 at 50 px diagonal)
        self.assertIn(3.0, list(out.column("z")))
        self.assertEqual(entry["cut_asset_ids"], ["cat"])
        # The layout uses the refined pose: the scan's surface lands on the photo's (z = 1.0 -> y 0.2 m... below the camera).
        layout = sync.layout_preview(entry, [member["entry"]])
        self.assertEqual(layout["objects"]["cat_cat"]["mode"], "transform")
        self.assertAlmostEqual(layout["objects"]["cat_cat"]["scale"][0], 1.0 / 1.1, places=5)

    def test_floaters_below_the_support_are_pruned(self) -> None:
        scene = self._room_scene("x", camera_height=1.2)  # floor 1.2 m below a level camera (y down)
        rows = [_row(0.1 * i, 1.2 + 0.001 * (i % 7 - 3), 2.0 + 0.01 * i) for i in range(200)]  # the floor, 3 mm noise
        rows += [_row(0.0, 0.2, 2.0), _row(0.3, 1.25, 2.0)]  # content above; 5 cm below the floor: kept (< 12 cm)
        rows += [_row(0.0, 1.5, 2.5), _row(0.2, 2.4, 3.0)]  # 30 cm / 1.2 m under the floor: floaters
        path = self.root / "floor.ply"
        _write_ply(path, rows)
        ply = sync.GaussianPly.read(path)
        out = sync.prune_below_support(ply, scene)
        self.assertEqual((out["removed"], out["kind"], out["margin_m"]), (2, "floor", 0.12))
        self.assertEqual(ply.count, 202)
        self.assertLess(max(ply.column("y")), 1.3)
        # A surface-kind scene uses the tighter margin (5 cm, or 3x the plane noise if larger).
        scene["support_plane"]["kind"] = "surface"
        ply = sync.GaussianPly.read(path)
        self.assertEqual(sync.prune_below_support(ply, scene)["removed"], 3)
        self.assertEqual(sync.prune_below_support(ply, {"support_plane": {}})["removed"], 0)

    def test_the_surface_under_a_cut_object_is_patched_with_its_surroundings(self) -> None:
        # Level camera 1.2 m above a floor (y = 1.2 in the camera frame), f = 40, 40x30 photo.
        # The floor is pink on the left half of the image and blue on the right half; an object
        # (cut region = pixels x 14..25, y 20..25) rests on it. After the cut, the patch lies on
        # the floor plane, under the object, coloured from the floor around it.
        scene = self._room_scene("x", camera_height=1.2)
        fx = cx = 40.0
        rows = []
        for v in range(16, 30):
            for u in range(40):
                dy = (v - 15) / fx
                t = 1.2 / dy  # ray meets y = 1.2 at depth t
                pink = u < 20
                rows.append(struct.unpack("<14f", struct.pack(
                    "<14f", (u - 20) / fx * t, 1.2, t, 1.0 if pink else -1.0, -1.0, -1.0 if pink else 1.0,
                    2.0, -5.0, -5.0, -5.0, 1.0, 0.0, 0.0, 0.0)))
        path = self.root / "floor.ply"
        _write_ply(path, [list(r) for r in rows])
        ply = sync.GaussianPly.read(path)
        mask = bytearray(40 * 30)
        for v in range(20, 26):
            for u in range(14, 26):
                mask[v * 40 + u] = 1
        cutter = {"asset_id": "box", "mask": (40, 30, mask), "z_limit": 20.0, "base": [0.0, 1.2, 1.2 / (5 / fx)], "radius": 0}
        stats = sync.cut_scene(ply, scene, [cutter])
        self.assertEqual(stats["removed"], {"box": 72})
        added = sync.fill_under_cut(ply, scene, [cutter], stats["keep"])
        self.assertEqual(added, {"box": 72})
        self.assertEqual(ply.count, 14 * 40)
        new = ply.floats[-72 * 14:]
        patch = [new[i * 14:(i + 1) * 14] for i in range(72)]
        self.assertTrue(all(abs(p[1] - 1.2) < 1e-4 for p in patch))  # on the floor plane
        self.assertTrue(all(p[6] == sync.FILL_OPACITY for p in patch))
        left = [p for p in patch if p[0] < -0.05]
        right = [p for p in patch if p[0] > 0.05]
        self.assertGreater(min(p[3] for p in left), max(p[3] for p in right))  # pink side stays pinker
        self.assertTrue(all(-1.0 <= p[3] <= 1.0 and -1.0 <= p[5] <= 1.0 for p in patch))
        # Rays that miss the surface under the object (beyond its depth limit) are not patched.
        ply = sync.GaussianPly.read(path)
        cutter["z_limit"] = 6.2  # rows v 23..25 (depth 6.0, 5.3, 4.8 m) are within it
        stats = sync.cut_scene(ply, scene, [cutter])
        self.assertEqual(sync.fill_under_cut(ply, scene, [cutter], stats["keep"]), {"box": 36})

    def test_colour_gain_matches_the_scan_to_the_photo(self) -> None:
        c0 = sync.SH_C0
        f = lambda colour: (colour - 0.5) / c0  # noqa: E731  colour -> f_dc
        # Scan: 300 front Gaussians of colour (0.4, 0.4, 0.2); photo there: (0.6, 0.5, 0.5).
        rows = [struct.unpack("<14f", struct.pack("<14f", 0, 0, 1, f(0.4), f(0.4), f(0.2), 2, -5, -5, -5, 1, 0, 0, 0))
                for _ in range(300)]
        path = self.root / "scan.ply"
        _write_ply(path, [list(r) for r in rows])
        scan = sync.GaussianPly.read(path)
        w, h = 30, 10
        front = {k: 1.0 for k in range(300)}
        rows_at = {k: k for k in range(300)}
        photo = {k: (0.6, 0.5, 0.5) for k in range(300)}
        bits = bytearray(b"\x01") * 300
        gain = sync.colour_gain(front, rows_at, scan, photo, bits, (w, h), (w, h))
        self.assertEqual(gain, [1.5, 1.25, 1.6])  # blue wanted 2.5x: clamped to 1.6
        sync.apply_colour_gain(scan, gain)
        got = [0.5 + c0 * scan.column(f"f_dc_{j}")[0] for j in range(3)]
        for a, b in zip(got, [0.6, 0.5, 0.32]):
            self.assertAlmostEqual(a, b, places=5)
        self.assertIsNone(sync.colour_gain(front, rows_at, scan, {}, bits, (w, h), (w, h)))  # no photo colours
        few = {k: v for k, v in list(photo.items())[:50]}
        self.assertIsNone(sync.colour_gain(front, rows_at, scan, few, bits, (w, h), (w, h)))  # too few pixels

    def test_box_blur_only_averages_given_pixels(self) -> None:
        pts = [(1, 1, [1.0, 0.0, 0.0]), (2, 1, [0.0, 1.0, 0.0]), (9, 9, [0.0, 0.0, 1.0])]
        out = sync._box_blur_colours(pts, 10, 10, 1)
        self.assertEqual(out[0], [0.5, 0.5, 0.0])
        self.assertEqual(out[1], [0.5, 0.5, 0.0])
        self.assertEqual(out[2], [0.0, 0.0, 1.0])
        self.assertEqual(sync._box_blur_colours(pts, 10, 10, 0)[0], [1.0, 0.0, 0.0])

    def test_poses_from_another_geometry_are_never_cut(self) -> None:
        upload = "w" * 32
        scene = self._room_scene(upload, camera_height=0.76)
        self._put(f"artifacts/scenes/{upload}/scene.json", scene)
        ply = self.root / "src.ply"
        _write_ply(ply, [_row(0, 0, 1.0), _row(0, 0, 4.0)])
        self._put(f"artifacts/scenes/{upload}/scene.ply", ply.read_bytes())
        mask = bytearray(40 * 30)
        mask[15 * 40 + 20] = 1

        def member(aid, camera_height, metric=True):
            pose = {
                "version": 2, "metric": metric, "image_size": [40, 30], "intrinsics": scene["intrinsics"],
                "gravity_up_cam": [0, -1, 0], "support_plane": dict(scene["support_plane"], camera_height=camera_height, offset=camera_height),
                "object": {"centroid_cam": [0, 0, 1.0], "base_cam": [0, 0, 1.0], "extent_m": {"width": 0.3}, "splat_to_cam": None},
            }
            return {"entry": {"asset_id": aid, "label": aid, "upload_id": upload, "photo": scene["photo"], "pose": pose,
                              "mask_area_frac": 0.05, "native_extent": [1, 1, 1], "bounds_min": [-0.5] * 3, "bounds_max": [0.5] * 3},
                    "mask": (40, 30, mask)}

        synced = [member("same", 0.76), member("stale", 1.19), member("nonmetric", 0.76, metric=False)]
        work = self.root / "work"
        work.mkdir()
        # The geometry guard on its own (these poses are unverified, which by default also keeps them).
        with mock.patch.object(sync, "CUT_UNVERIFIED", True):
            entry = sync.sync_scene(upload, synced, bucket=sync.DEFAULT_BUCKET, project_id="p", unity=self.root / "unity", tmp=work)
        self.assertEqual(entry["cut_asset_ids"], ["same"])
        self.assertEqual(entry["cut"]["removed"], {"same": 1})
        layout = sync.layout_preview(entry, [s["entry"] for s in synced])
        self.assertEqual(list(layout["objects"]), ["same_same"])
        self.assertEqual(layout["objects"]["same_same"]["mode"], "upright")
        # Default: an unverified pose is never cut; the photo splat keeps showing the object.
        work2 = self.root / "work2"
        work2.mkdir()
        entry = sync.sync_scene(upload, synced[:1], bucket=sync.DEFAULT_BUCKET, project_id="p", unity=self.root / "unity", tmp=work2)
        self.assertEqual(entry["cut_asset_ids"], [])
        self.assertEqual(entry["cut"]["removed"], {})


class CatalogTests(unittest.TestCase):
    def test_merge_keeps_old_entries_and_replaces_by_id(self) -> None:
        old = {"assets": [{"asset_id": "a", "label": "old"}, {"asset_id": "b"}], "scenes": [{"scene_id": "u1", "x": 1}]}
        merged = sync.merge_catalog(old, [{"asset_id": "a", "label": "new"}], [{"scene_id": "u2"}, {"scene_id": "u1", "x": 2}])
        self.assertEqual({a["asset_id"]: a.get("label") for a in merged["assets"]}, {"a": "new", "b": None})
        self.assertEqual({s["scene_id"]: s.get("x") for s in merged["scenes"]}, {"u1": 2, "u2": None})
        json.dumps(merged)

    def test_upload_id_and_pose_version(self) -> None:
        self.assertEqual(sync.upload_id_of("uploads/p1/u1/source.jpg"), "u1")
        self.assertIsNone(sync.upload_id_of("artifacts/x.png"))
        self.assertTrue(sync.is_pose_v2({"version": 2, "object": {}}))
        self.assertFalse(sync.is_pose_v2({"version": 1, "rotation": [1, 0, 0, 0]}))

    def test_coarse_depth_grid_follows_the_valid_bitmask(self) -> None:
        w, h = 32, 24
        cells = [(x, y) for y in range(h) for x in range(w)]
        valid = bytearray((w * h + 7) // 8)
        pts = []
        for i, (x, y) in enumerate(cells):
            if x % 2 == 0:  # even columns valid; the list holds valid cells only
                valid[i >> 3] |= 1 << (i & 7)  # LSB first
                pts += [x * 0.1, y * 0.1, 1.0 + y * 0.01]
        scene = {"depth_grid": {"w": w, "h": h, "points_cam": pts}, "depth_grid_valid": base64.b64encode(bytes(valid)).decode()}
        # 16 x 12 samples land on odd columns (x = 1, 3, ...): all invalid.
        self.assertEqual(sync.coarse_depth_grid(scene, (16, 12))["w"], 0)
        coarse = sync.coarse_depth_grid(scene, (8, 6))  # x = 2, 6, ... even: valid
        self.assertEqual(coarse["w"], 48)
        self.assertEqual(coarse["points_cam"][:3], [0.2, 0.2, 1.02])
        # All valid ([]): every sample kept.
        full = {"depth_grid": {"w": 4, "h": 2, "points_cam": [float(i) for i in range(24)]}, "depth_grid_valid": []}
        self.assertEqual(sync.coarse_depth_grid(full, (2, 1))["w"], 2)
        # A bitmask that doesn't match the points -> None (don't guess).
        scene["depth_grid_valid"] = base64.b64encode(bytes(len(valid))).decode()
        self.assertIsNone(sync.coarse_depth_grid(scene, (8, 6)))

if __name__ == "__main__":
    unittest.main()
