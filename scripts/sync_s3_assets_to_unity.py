#!/usr/bin/env python3
"""Pull real Fast-SAM3D reconstructions from AWS into the Unity project.

For every catalog asset in DynamoDB (``ASSET#<id>``) that is ``ready``, is a
``reconstruction``, and has a real label (not the placeholder ``object``),
this picks the newest asset per label, downloads its ``reconstruction.ply``
from the artifacts bucket, repairs non-finite opacity values (the same
repair as ``worker/gaussian_ply_safety.py``; Unity's Gsplat importer rejects
the whole file on the first one), and writes it into the Unity project at
``Assets/SketchScape/AssetLibrary/<label>_<id8>.ply``, where the Gsplat
importer picks it up. It also writes ``config/nemoclaw/asset-catalog.json``,
which ``backend/unity_room.py`` uses to swap placeholder cubes for real
splats by label.

Standard library only (plus the AWS CLI, already logged in via
``aws login``), so it runs from any Python 3.10+ on this machine.

    python scripts/sync_s3_assets_to_unity.py [--unity-project ../HackGTUnity]
        [--bucket NAME] [--table NAME] [--region us-east-1] [--labels cat tomato]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_BUCKET = "sketchscape-artifacts-20260922133334256700000003"
DEFAULT_TABLE = "sketchscape-authoring"
LIBRARY_DIR = "Assets/SketchScape/AssetLibrary"
CATALOG_PATH = REPO / "config" / "nemoclaw" / "asset-catalog.json"
PLACEHOLDER_LABELS = {"", "object"}
SAFE_LOGIT = 10.0  # matches worker/gaussian_ply_safety.SAFE_LOGIT


def _aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"aws {' '.join(args[:3])} failed: {result.stderr.strip()}")
    return result.stdout


def _plain(value: dict):
    kind, inner = next(iter(value.items()))
    if kind == "M":
        return {k: _plain(v) for k, v in inner.items()}
    if kind == "L":
        return [_plain(v) for v in inner]
    return inner


def load_assets(table: str, region: str) -> list[dict]:
    raw = json.loads(
        _aws(
            "dynamodb", "scan", "--table-name", table, "--region", region, "--output", "json",
            "--filter-expression", "begins_with(pk, :a)",
            "--expression-attribute-values", json.dumps({":a": {"S": "ASSET#"}}),
        )
    )
    return [json.loads(_plain(item["document"])) for item in raw.get("Items", [])]


def pick_newest_per_label(assets: list[dict], labels: set[str] | None) -> list[dict]:
    newest: dict[str, dict] = {}
    for asset in assets:
        label = (asset.get("label") or "").strip().lower()
        if (
            asset.get("status") != "ready"
            or asset.get("kind") != "reconstruction"
            or label in PLACEHOLDER_LABELS
            or not asset.get("reconstruction_job_id")
            or (labels and label not in labels)
        ):
            continue
        stamp = asset.get("updated_at") or asset.get("created_at") or ""
        if label not in newest or stamp > (newest[label].get("updated_at") or newest[label].get("created_at") or ""):
            newest[label] = asset
    return [newest[k] for k in sorted(newest)]


def repair_ply(path: Path) -> dict:
    """Validate a float-only binary little-endian Gaussian PLY and repair
    non-finite opacity in place. Returns vertex count, repair count and the
    position bounds of splats that are not fully transparent."""
    data = path.read_bytes()
    end = data.index(b"end_header") + len(b"end_header")
    end += 2 if data[end:end + 2] == b"\r\n" else 1
    header = data[:end].decode("ascii").splitlines()
    if "format binary_little_endian 1.0" not in header:
        raise ValueError(f"{path.name}: expected binary_little_endian PLY")
    props = [line.split() for line in header if line.startswith("property")]
    if any(p[1] != "float" for p in props):
        raise ValueError(f"{path.name}: expected float-only vertex properties")
    names = [p[2] for p in props]
    count = int(next(line for line in header if line.startswith("element vertex")).split()[2])
    stride = len(names)
    floats = array("f")
    floats.frombytes(data[end:end + 4 * stride * count])
    if sys.byteorder != "little":
        floats.byteswap()

    o = names.index("opacity")
    repaired = 0
    for i in range(o, len(floats), stride):
        v = floats[i]
        if not math.isfinite(v):
            floats[i] = SAFE_LOGIT if v == math.inf else -SAFE_LOGIT
            repaired += 1
    if repaired:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data[:end] + floats.tobytes() + data[end + 4 * stride * count:])
        tmp.replace(path)

    lo, hi = [math.inf] * 3, [-math.inf] * 3
    x = names.index("x")
    for i in range(0, len(floats), stride):
        if floats[i + o] < -4.0:  # sigmoid < ~2%: effectively invisible
            continue
        for k in range(3):
            v = floats[i + x + k]
            if math.isfinite(v):
                lo[k] = min(lo[k], v)
                hi[k] = max(hi[k], v)
    return {"vertices": count, "repaired_opacity": repaired, "bounds_min": lo, "bounds_max": hi}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "asset"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--unity-project", default=str(REPO.parent / "HackGTUnity"))
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--labels", nargs="*", help="only these labels (default: every real label)")
    args = parser.parse_args()

    library = Path(args.unity_project) / LIBRARY_DIR
    library.mkdir(parents=True, exist_ok=True)
    chosen = pick_newest_per_label(load_assets(args.table, args.region), {l.lower() for l in args.labels or []} or None)
    if not chosen:
        print("No ready, labeled reconstructions found.")
        return 1

    catalog = []
    with tempfile.TemporaryDirectory() as tmp:
        for asset in chosen:
            job = asset["reconstruction_job_id"]
            label = asset["label"].strip()
            name = f"{_slug(label)}_{asset['asset_id'][:8]}.ply"
            local = Path(tmp) / name
            key = f"artifacts/{job}/reconstruction.ply"
            _aws("s3", "cp", f"s3://{args.bucket}/{key}", str(local), "--only-show-errors")
            info = repair_ply(local)
            shutil.copyfile(local, library / name)
            size = [round(info["bounds_max"][k] - info["bounds_min"][k], 4) for k in range(3)]
            print(f"{label:16} {name:34} {info['vertices']:>8} splats, repaired {info['repaired_opacity']}, extent {size}")
            catalog.append(
                {
                    "label": label,
                    "asset_id": asset["asset_id"],
                    "project_id": asset.get("project_id"),
                    "unity_path": f"{LIBRARY_DIR}/{name}",
                    "source": f"s3://{args.bucket}/{key}",
                    "vertices": info["vertices"],
                    "repaired_opacity": info["repaired_opacity"],
                    "native_extent": size,
                }
            )

    CATALOG_PATH.write_text(json.dumps({"assets": catalog}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(catalog)} asset(s) to {library} and {CATALOG_PATH.relative_to(REPO)}.")
    print("Next: refresh the Unity Editor's AssetDatabase so the Gsplat importer imports them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
