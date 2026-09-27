#!/usr/bin/env python3
"""Install the SketchScape RoomKit (Editor) + RoomDirector (runtime) into HackGTUnity.

Canonical source lives in this repo under ``unity-hackgt/Assets/SketchScape/``;
this copies every file (scripts and their fixed-GUID ``.meta`` files) into the
Unity project's ``Assets/SketchScape/`` tree. Idempotent: files whose bytes are
already identical are left alone, nothing else in the project is touched or
deleted. Standard library only.

    python scripts/install_hackgt_roomkit.py [--unity-project PATH] [--dry-run]

Unity recompiles on its next focus/refresh (or call
``AssetDatabase.Refresh()`` through the Unity MCP).
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "unity-hackgt" / "Assets" / "SketchScape"
DEFAULT_PROJECT = Path(os.environ.get("HACKGT_UNITY_PROJECT", r"C:\Users\kriva\Desktop\HackGTUnity"))
SKIP_SUFFIXES = {".pyc", ".orig", ".swp"}


def plan(source: Path, dest: Path) -> list[tuple[Path, Path, str]]:
    """(src, dst, action) for every canonical file; action is 'new', 'update' or 'same'."""
    out = []
    for src in sorted(source.rglob("*")):
        if not src.is_file() or src.suffix in SKIP_SUFFIXES or src.name.startswith("."):
            continue
        dst = dest / src.relative_to(source)
        if not dst.exists():
            action = "new"
        elif filecmp.cmp(src, dst, shallow=False):
            action = "same"
        else:
            action = "update"
        out.append((src, dst, action))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--unity-project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    project = args.unity_project
    if not (project / "Assets").is_dir() or not (project / "ProjectSettings").is_dir():
        print(f"error: {project} is not a Unity project (no Assets/ProjectSettings)", file=sys.stderr)
        return 2
    if not SOURCE.is_dir():
        print(f"error: canonical source {SOURCE} is missing", file=sys.stderr)
        return 2

    dest = project / "Assets" / "SketchScape"
    steps = plan(SOURCE, dest)
    changed = 0
    for src, dst, action in steps:
        rel = dst.relative_to(project)
        if action == "same":
            continue
        changed += 1
        print(f"{action:6} {rel}")
        if not args.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".installing")
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
    print(f"{changed} file(s) {'would change' if args.dry_run else 'installed'}, "
          f"{len(steps) - changed} already current -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
