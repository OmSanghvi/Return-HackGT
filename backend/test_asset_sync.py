"""Tests for scripts/sync_s3_assets_to_unity.py's pure parts (PLY repair and
asset selection). The AWS and Unity sides were run for real on 2026-09-26.

Run with: python -m unittest test_asset_sync.py
"""

import math
import struct
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import sync_s3_assets_to_unity as sync  # noqa: E402

_PROPS = ["x", "y", "z", "opacity"]


def _write_ply(path: Path, rows: list[tuple[float, ...]]) -> None:
    header = "ply\nformat binary_little_endian 1.0\nelement vertex {}\n{}end_header\n".format(
        len(rows), "".join(f"property float {p}\n" for p in _PROPS)
    )
    body = b"".join(struct.pack("<4f", *row) for row in rows)
    path.write_bytes(header.encode("ascii") + body)


class RepairPlyTests(unittest.TestCase):
    def test_repairs_non_finite_opacity_and_measures_visible_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.ply"
            _write_ply(path, [
                (0.0, 0.0, 0.0, 1.0),
                (1.0, 2.0, 3.0, math.inf),
                (-1.0, -1.0, -1.0, math.nan),
                (9.0, 9.0, 9.0, -8.0),  # effectively invisible: excluded from bounds
            ])
            info = sync.repair_ply(path)
            self.assertEqual(info["vertices"], 4)
            self.assertEqual(info["repaired_opacity"], 2)
            self.assertEqual(info["bounds_max"], [1.0, 2.0, 3.0])
            self.assertEqual(info["bounds_min"], [0.0, 0.0, 0.0])
            data = path.read_bytes()
            floats = array("f")
            floats.frombytes(data[data.index(b"end_header") + 11:])
            self.assertEqual([floats[i] for i in range(3, 16, 4)], [1.0, sync.SAFE_LOGIT, -sync.SAFE_LOGIT, -8.0])

    def test_clean_file_is_left_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.ply"
            _write_ply(path, [(0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0, 2.0)])
            before = path.read_bytes()
            self.assertEqual(sync.repair_ply(path)["repaired_opacity"], 0)
            self.assertEqual(path.read_bytes(), before)


class PickAssetsTests(unittest.TestCase):
    def test_newest_ready_real_label_per_label(self) -> None:
        def asset(asset_id, label, status="ready", updated="2026-09-26T10:00", kind="reconstruction"):
            return {"asset_id": asset_id, "label": label, "status": status, "kind": kind,
                    "reconstruction_job_id": "j" + asset_id, "updated_at": updated}

        chosen = sync.pick_newest_per_label([
            asset("1", "cat", updated="2026-09-26T09:00"),
            asset("2", "Cat", updated="2026-09-26T11:00"),
            asset("3", "cat", status="failed", updated="2026-09-26T12:00"),
            asset("4", "object"),
            asset("5", "tomato", kind="upload"),
            asset("6", "pink blanket"),
        ], None)
        self.assertEqual([a["asset_id"] for a in chosen], ["2", "6"])
        only = sync.pick_newest_per_label([asset("6", "pink blanket"), asset("2", "cat")], {"cat"})
        self.assertEqual([a["asset_id"] for a in only], ["2"])


if __name__ == "__main__":
    unittest.main()
