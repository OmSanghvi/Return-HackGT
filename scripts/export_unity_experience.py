#!/usr/bin/env python3
"""Export one published SketchScape project into the Unity authoring folder.

This downloads only public compiled-scene artifacts from the configured API. It
accepts no AWS, worker, Hugging Face, NemoClaw, or Unity credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def download(url: str, destination: Path, *, maximum_bytes: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    total = 0
    try:
        request = Request(url, headers={"User-Agent": "SketchScape-Unity-Exporter/1"})
        with urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                total += len(block)
                if total > maximum_bytes:
                    raise RuntimeError(f"Download exceeded {maximum_bytes} bytes: {url}")
                output.write(block)
        if not total:
            raise RuntimeError(f"Downloaded file was empty: {url}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


ARTIFACT_PATTERNS = ("*.ply", "*.png", "*.jpg")


def export(api_url: str, project_id: str, unity_project: Path) -> None:
    if not SAFE_ID.fullmatch(project_id):
        raise ValueError("project_id contains unsupported characters")

    api_url = api_url.rstrip("/") + "/"
    api_origin = urlparse(api_url)
    if api_origin.scheme not in {"http", "https"} or not api_origin.netloc:
        raise ValueError("api_url must be an absolute HTTP(S) URL")

    endpoint = urljoin(api_url, f"v1/projects/{project_id}/compiled-scene")
    with urlopen(Request(endpoint, headers={"User-Agent": "SketchScape-Unity-Exporter/1"}), timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    scene = payload.get("scene")
    objects = scene.get("objects") if isinstance(scene, dict) else None
    if not isinstance(objects, list):
        raise RuntimeError("Compiled-scene response has no objects array")

    authoring = unity_project / "Assets" / "SketchScape" / "Authoring"
    artifacts = authoring / "Artifacts"
    staging = authoring / ".export-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    for item in objects:
        object_id = item.get("id") if isinstance(item, dict) else None
        asset_url = item.get("asset_url") if isinstance(item, dict) else None
        if not isinstance(object_id, str) or not SAFE_ID.fullmatch(object_id):
            raise RuntimeError(f"Unsafe or missing scene object id: {object_id!r}")
        if not asset_url:
            continue
        resolved = urljoin(api_url, asset_url)
        target_origin = urlparse(resolved)
        if (target_origin.scheme, target_origin.netloc) != (api_origin.scheme, api_origin.netloc):
            raise RuntimeError(f"Refusing cross-origin artifact URL: {resolved}")
        path = target_origin.path.lower()
        if item.get("source") == "sketch_card":
            # Notability page shown as a flat card (Build Plan step 7).
            extension = next((ext for ext in (".png", ".jpg") if path.endswith(ext)), None)
            if extension is None:
                raise RuntimeError(f"Expected a PNG/JPEG sketch card for {object_id}: {resolved}")
            download(resolved, staging / f"{object_id}{extension}", maximum_bytes=16 * 1024 * 1024)
            continue
        if not path.endswith(".ply"):
            raise RuntimeError(f"Expected a PLY artifact for {object_id}: {resolved}")
        download(resolved, staging / f"{object_id}.ply", maximum_bytes=512 * 1024 * 1024)

    artifacts.mkdir(parents=True, exist_ok=True)
    for pattern in ARTIFACT_PATTERNS:
        for old_file in artifacts.glob(pattern):
            old_file.unlink()
        for staged_file in staging.glob(pattern):
            staged_file.replace(artifacts / staged_file.name)
    shutil.rmtree(staging)

    authoring.mkdir(parents=True, exist_ok=True)
    (authoring / "compiled-scene.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Exported project {project_id} to {authoring}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--unity-project", type=Path, default=Path("../HackGTUnity"))
    arguments = parser.parse_args()
    export(arguments.api_url, arguments.project_id, arguments.unity_project.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
