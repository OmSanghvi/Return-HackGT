"""Tests for decimate_splats (the Quest-sized splat copies). Standard library only.

Run with: python -m unittest scripts/test_decimate_splats.py
"""

import math
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decimate_splats as ds  # noqa: E402

PROPS = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
         "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
HEADER_EXTRA = ["comment made by a 3DGS trainer", "obj_info test"]


def _row(i, opacity, log_scale):
    return [i * 0.01, 0.5, -i * 0.02, 0, 0, 1, 0.1, 0.2, 0.3, opacity, log_scale, log_scale, log_scale, 1, 0, 0, 0]


def _write(path, rows, newline="\n", props=PROPS, extra=HEADER_EXTRA):
    header = ["ply", "format binary_little_endian 1.0", *extra, f"element vertex {len(rows)}"]
    header += [f"property float {p}" for p in props] + ["end_header"]
    floats = array("f", [v for r in rows for v in r])
    if sys.byteorder != "little":
        floats.byteswap()
    path.write_bytes((newline.join(header) + newline).encode("ascii") + floats.tobytes())


def _rows_of(path):
    lines, props, count, floats = ds.read_ply(path)
    stride = len(props)
    return lines, [list(floats[i * stride:(i + 1) * stride]) for i in range(count)]


class DecimateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_keeps_the_most_important_splats_and_preserves_the_header(self) -> None:
        # 10 opaque big splats (important) and 90 faint small ones.
        rows = [_row(i, 6.0, -2.0) for i in range(10)] + [_row(10 + i, -4.0, -6.0) for i in range(90)]
        src, dst = self.dir / "in.ply", self.dir / "out.ply"
        _write(src, rows)
        stats = ds.decimate(src, dst, 10, 1.3)
        self.assertEqual((stats["source"], stats["kept"]), (100, 10))
        lines, kept = _rows_of(dst)
        src_lines, _ = _rows_of(src)
        # Every header line is kept in order; only the vertex count changes.
        self.assertEqual([l for l in lines if not l.startswith("element vertex")],
                         [l for l in src_lines if not l.startswith("element vertex")])
        self.assertIn("element vertex 10", lines)
        self.assertEqual(ds.read_header(dst)[2], 10)
        # The opaque ones survive, in their original order, positions untouched.
        self.assertEqual([round(r[0], 4) for r in kept], [round(i * 0.01, 4) for i in range(10)])
        self.assertEqual([r[9] for r in kept], [6.0] * 10)
        self.assertFalse((self.dir / "out.ply.writing").exists())

    def test_scale_up_restores_the_area_share_below_the_cap(self) -> None:
        # Two equally important halves: keeping one keeps half the area -> sqrt(2) = 1.414.
        rows = [_row(i, 8.0, -3.0) for i in range(4)]
        src, dst = self.dir / "in.ply", self.dir / "out.ply"
        _write(src, rows)
        stats = ds.decimate(src, dst, 2, 2.0)
        self.assertAlmostEqual(stats["area_share"], 0.5, places=5)
        self.assertAlmostEqual(stats["scale_up"], math.sqrt(2.0), places=5)
        _, kept = _rows_of(dst)
        for r in kept:  # log scales grow by log(scale_up)
            for k in (10, 11, 12):
                self.assertAlmostEqual(r[k], -3.0 + math.log(math.sqrt(2.0)), places=5)

    def test_scale_up_is_capped(self) -> None:
        rows = [_row(i, 8.0, -3.0) for i in range(100)]
        src, dst = self.dir / "in.ply", self.dir / "out.ply"
        _write(src, rows)
        stats = ds.decimate(src, dst, 1, 1.3)  # 1 % of the area kept: sqrt(100) = 10, capped at 1.3
        self.assertAlmostEqual(stats["scale_up"], 1.3, places=6)
        _, kept = _rows_of(dst)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0][10], -3.0 + math.log(1.3), places=5)
        # A cap below 1 never shrinks splats.
        self.assertEqual(ds.decimate(src, self.dir / "o2.ply", 1, 0.5)["scale_up"], 1.0)

    def test_keep_at_or_above_the_count_keeps_everything_unchanged(self) -> None:
        rows = [_row(i, 1.0 - i, -4.0 + 0.1 * i) for i in range(7)]
        src = self.dir / "in.ply"
        _write(src, rows)
        for keep in (7, 50):
            dst = self.dir / f"out{keep}.ply"
            stats = ds.decimate(src, dst, keep, 1.3)
            self.assertEqual((stats["kept"], stats["scale_up"], stats["area_share"]), (7, 1.0, 1.0))
            self.assertEqual(dst.read_bytes(), src.read_bytes())

    def test_crlf_header_and_bad_files(self) -> None:
        src = self.dir / "crlf.ply"
        _write(src, [_row(i, 2.0, -3.0) for i in range(5)], newline="\r\n")
        self.assertEqual(ds.read_header(src)[2], 5)
        self.assertEqual(ds.decimate(src, self.dir / "o.ply", 3, 1.3)["kept"], 3)
        bad = self.dir / "bad.ply"
        bad.write_bytes(b"not a ply at all")
        with self.assertRaises(ValueError):
            ds.read_header(bad)
        ascii_ply = self.dir / "ascii.ply"
        ascii_ply.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n1\n")
        with self.assertRaises(ValueError):
            ds.read_ply(ascii_ply)
        uchar = self.dir / "uchar.ply"
        uchar.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty uchar red\nend_header\n\x01")
        with self.assertRaises(ValueError):
            ds.read_ply(uchar)
        short = self.dir / "short.ply"
        _write(short, [_row(0, 1.0, -3.0)])
        short.write_bytes(short.read_bytes()[:-8])
        with self.assertRaises(ValueError):
            ds.read_ply(short)
        no_scale = self.dir / "noscale.ply"
        _write(no_scale, [[0.0, 0.0, 0.0, 1.0]], props=["x", "y", "z", "opacity"])
        with self.assertRaises(ValueError):
            ds.decimate(no_scale, self.dir / "o3.ply", 1, 1.3)
        with self.assertRaises(ValueError):
            ds.decimate(src, self.dir / "o4.ply", 0, 1.3)

    def test_command_line(self) -> None:
        src, dst = self.dir / "in.ply", self.dir / "out.ply"
        _write(src, [_row(i, 2.0, -3.0) for i in range(20)])
        self.assertEqual(ds.main([str(src), str(dst), "--keep", "5"]), 0)
        self.assertEqual(ds.read_header(dst)[2], 5)
        bad = self.dir / "bad.ply"
        bad.write_bytes(b"nope")
        self.assertEqual(ds.main([str(bad), str(dst), "--keep", "5"]), 2)


if __name__ == "__main__":
    unittest.main()
