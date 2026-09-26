"""worker/gaussian_ply_safety.py. Pure numpy, no torch/plyfile/GPU needed --
run with: python -m unittest test_gaussian_ply_safety.py
"""

import unittest

import numpy as np

from gaussian_ply_safety import SAFE_LOGIT, sanitize_opacity_array


class SanitizeOpacityArrayTests(unittest.TestCase):
    def test_all_finite_input_is_unchanged_and_reports_zero(self) -> None:
        opacities = np.array([-3.0, 0.0, 2.5, 9.9], dtype=np.float32)
        fixed, count = sanitize_opacity_array(opacities)
        np.testing.assert_array_equal(fixed, opacities)
        self.assertEqual(count, 0)

    def test_positive_infinity_becomes_safe_positive_logit(self) -> None:
        fixed, count = sanitize_opacity_array(np.array([1.0, np.inf], dtype=np.float32))
        self.assertEqual(count, 1)
        self.assertEqual(fixed[1], SAFE_LOGIT)
        self.assertTrue(np.isfinite(fixed).all())

    def test_negative_infinity_becomes_safe_negative_logit(self) -> None:
        fixed, count = sanitize_opacity_array(np.array([-np.inf, 1.0], dtype=np.float32))
        self.assertEqual(count, 1)
        self.assertEqual(fixed[0], -SAFE_LOGIT)

    def test_nan_becomes_safe_negative_logit_not_opaque(self) -> None:
        fixed, count = sanitize_opacity_array(np.array([np.nan], dtype=np.float32))
        self.assertEqual(count, 1)
        self.assertEqual(fixed[0], -SAFE_LOGIT)

    def test_mixed_array_fixes_only_the_bad_entries(self) -> None:
        opacities = np.array([2.0, np.inf, -np.inf, np.nan, -5.0], dtype=np.float32)
        fixed, count = sanitize_opacity_array(opacities)
        self.assertEqual(count, 3)
        np.testing.assert_array_equal(fixed, [2.0, SAFE_LOGIT, -SAFE_LOGIT, -SAFE_LOGIT, -5.0])
        self.assertTrue(np.isfinite(fixed).all())

    def test_dtype_is_preserved(self) -> None:
        opacities = np.array([np.inf], dtype=np.float32)
        fixed, _ = sanitize_opacity_array(opacities)
        self.assertEqual(fixed.dtype, np.float32)


try:
    import plyfile
except ImportError:  # only installed in the Fast-SAM3D GPU env
    plyfile = None


@unittest.skipIf(plyfile is None, "plyfile not installed")
class SanitizePlyOpacityFileTests(unittest.TestCase):
    def _write_ply(self, path, opacities) -> np.ndarray:
        data = np.zeros(len(opacities), dtype=[("x", "f4"), ("opacity", "f4"), ("scale_0", "f4")])
        data["x"] = np.arange(len(opacities))
        data["opacity"] = opacities
        data["scale_0"] = -1.5
        plyfile.PlyData([plyfile.PlyElement.describe(data, "vertex")]).write(str(path))
        return data

    def test_repairs_file_in_place_and_keeps_other_columns(self) -> None:
        import tempfile
        from pathlib import Path

        from gaussian_ply_safety import sanitize_ply_opacity_file

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reconstruction.ply"
            original = self._write_ply(path, [1.0, np.inf, np.nan, -2.0])
            self.assertEqual(sanitize_ply_opacity_file(path), 2)
            out = plyfile.PlyData.read(str(path), mmap=False)["vertex"].data
            np.testing.assert_array_equal(out["opacity"], [1.0, SAFE_LOGIT, -SAFE_LOGIT, -2.0])
            np.testing.assert_array_equal(out["x"], original["x"])
            np.testing.assert_array_equal(out["scale_0"], original["scale_0"])
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["reconstruction.ply"])
            self.assertEqual(sanitize_ply_opacity_file(path), 0)


if __name__ == "__main__":
    unittest.main()
