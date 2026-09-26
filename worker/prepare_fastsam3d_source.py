#!/usr/bin/env python3
"""Apply the three narrowly-scoped source fixes proven in the Kaggle run."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    if old in source:
        path.write_text(source.replace(old, new, 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo / "notebook" / "inference.py").is_file():
        raise SystemExit(f"Not a Fast-SAM3D checkout: {repo}")

    # Upstream imports a solver that is absent, although the staged runner never
    # uses it. Remove only that dead mapping/import.
    flow = repo / "sam3d_objects/model/backbone/generator/flow_matching/model.py"
    solver = flow.with_name("solver.py")
    if "class Euler_easy_ss" not in solver.read_text():
        replace_once(flow, "    Euler_easy_ss,\n", "")
        replace_once(flow, '        "euler_easy_ss":Euler_easy_ss,\n', "")

    # The source defaults to the author's personal DINO cache path.
    dino_repo = repo / "third_party/dinov2"
    if not dino_repo.is_dir():
        dino_repo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/facebookresearch/dinov2.git", str(dino_repo)],
            check=True,
        )
    dino_module = repo / "sam3d_objects/model/backbone/dit/embedder/dino.py"
    replace_once(
        dino_module,
        "/data3/wmq/Fast-sam3d-objects/checkpoints/torch-cache/hub/facebookresearch_dinov2_main",
        str(dino_repo),
    )

    # Fast-SAM3D may compute scores on CPU then fuse them with CUDA coordinates.
    utils = repo / "sam3d_objects/pipeline/inference_utils.py"
    replace_once(
        utils,
        "    raw_scores = coords_scores[:, 0].float()",
        "    raw_scores = coords_scores[:, 0].to(device=device, dtype=torch.float32)",
    )
    print(f"Fast-SAM3D source prepared: {repo}")


if __name__ == "__main__":
    main()
