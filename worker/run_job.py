#!/usr/bin/env python3
"""Run one staged Fast-SAM3D job and return its artifacts to SketchScape.

This lives in the GPU image, not in Unity or the public FastAPI container. It
uses only the private worker token to pull its input and post the finished PLY.

The image must already contain the patched, staged runner that was validated in
the Kaggle notebook. Building SAM 3D dependencies on a live hackathon request
would make latency and failures unpredictable, so this script refuses to do it.
"""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_URL = required("SKETCHSCAPE_API_URL").rstrip("/")
JOB_ID = required("SKETCHSCAPE_JOB_ID")
WORKER_TOKEN = required("SKETCHSCAPE_WORKER_TOKEN")
WORK_DIR = Path(os.environ.get("SKETCHSCAPE_WORK_DIR", "/tmp/sketchscape-job")) / JOB_ID
RUNNER = Path(required("FASTSAM3D_STAGED_RUNNER"))


def private_url(path: str) -> str:
    return f"{API_URL}{path}"


def download(path: str, destination: Path) -> bool:
    request = Request(private_url(path), headers={"X-SketchScape-Worker-Token": WORKER_TOKEN})
    try:
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        return True
    except Exception as error:  # HTTP 404 means the optional mask was absent.
        print(f"Could not download {path}: {error}", file=sys.stderr)
        return False


def get_task() -> dict[str, object]:
    request = Request(
        private_url(f"/v1/internal/reconstructions/{JOB_ID}/task"),
        headers={"X-SketchScape-Worker-Token": WORKER_TOKEN},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Worker task response was not an object.")
    return payload


def stream_multipart(path: str, fields: dict[str, str], files: dict[str, Path]) -> None:
    """Post files without loading a potentially large splat PLY into memory."""
    target = urlparse(path)
    if target.scheme not in {"http", "https"} or not target.hostname:
        raise RuntimeError(f"Invalid API URL: {path}")
    boundary = f"----SketchScape{uuid.uuid4().hex}"

    def header(name: str, value: str) -> bytes:
        return f"--{boundary}\r\n{name}: {value}\r\n\r\n".encode()

    pieces: list[tuple[bytes, Path | None]] = []
    for name, value in fields.items():
        pieces.append((header("Content-Disposition", f'form-data; name="{name}"') + value.encode() + b"\r\n", None))
    for name, file_path in files.items():
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        lead = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        pieces.append((lead, file_path))
    closing = f"--{boundary}--\r\n".encode()
    content_length = sum(len(prefix) + (file_path.stat().st_size if file_path else 0) + (2 if file_path else 0) for prefix, file_path in pieces) + len(closing)
    connection_type = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(target.hostname, target.port, timeout=180)
    try:
        connection.putrequest("POST", target.path or "/")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(content_length))
        connection.endheaders()
        for prefix, file_path in pieces:
            connection.send(prefix)
            if file_path:
                with file_path.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        connection.send(block)
                connection.send(b"\r\n")
        connection.send(closing)
        response = connection.getresponse()
        body = response.read().decode(errors="replace")
        if response.status >= 300:
            raise RuntimeError(f"Worker callback failed ({response.status}): {body}")
    finally:
        connection.close()


def report(status: str, *, label: str = "gaussian_splat", error: str | None = None, files: dict[str, Path] | None = None) -> None:
    payload = {"status": status, "object_label": label}
    if error:
        payload["error"] = error[-500:]
    stream_multipart(
        private_url(f"/v1/internal/reconstructions/{JOB_ID}/result"),
        {"worker_token": WORKER_TOKEN, "result": json.dumps(payload)},
        files or {},
    )


def generate_mask(image: Path, mask: Path, prompt: str) -> bool:
    """Run the pre-baked automatic segmentation command, if one was configured.

    It receives a centred-object photo and must write an aligned white-on-black
    PNG to ``mask``. No shell is used, and a missing/ambiguous result becomes a
    safe ``mask_review`` state rather than a wrong 3D reconstruction.
    """
    template = os.environ.get("SKETCHSCAPE_AUTO_MASK_COMMAND")
    # SAM 3.1 concept segmentation is deliberately not asked to invent an
    # object name. An absent/ambiguous hint becomes a product-level review.
    if not template or not prompt.strip():
        return False
    command = [
        part.format(image=str(image), mask=str(mask), prompt=prompt.strip())
        for part in shlex.split(template)
    ]
    completed = subprocess.run(command, timeout=120)
    # Exit code 2 is the segmentation command's explicit "ask the user" path.
    if completed.returncode == 2:
        return False
    if completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, command)
    return mask.is_file() and mask.stat().st_size > 0


def main() -> int:
    if not RUNNER.is_file():
        raise RuntimeError(f"Staged runner not found: {RUNNER}")
    input_dir, output_dir = WORK_DIR / "input", WORK_DIR / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    image, mask = input_dir / "image.png", input_dir / "mask.png"
    if not download(f"/v1/internal/reconstructions/{JOB_ID}/input/image", image):
        raise RuntimeError("The image input could not be fetched.")
    task = get_task()
    subject_hint = str(task.get("subject_hint") or "").strip()
    if not download(f"/v1/internal/reconstructions/{JOB_ID}/input/mask", mask):
        try:
            has_mask = generate_mask(image, mask, subject_hint)
        except Exception as error:
            report("failed", error=f"Automatic segmentation failed: {error}")
            return 1
        if not has_mask:
            report("mask_review", label="unknown")
            return 0

    runner_env = os.environ.copy()
    runner_env.update(
        {
            "FASTSAM3D_INPUT_IMAGE": str(image),
            "FASTSAM3D_INPUT_MASK": str(mask),
            "FASTSAM3D_OUTPUT_DIR": str(output_dir),
            "FASTSAM3D_MAX_INPUT_SIDE": os.environ.get("FASTSAM3D_MAX_INPUT_SIDE", "768"),
            "FASTSAM3D_STAGE1_STEPS": os.environ.get("FASTSAM3D_STAGE1_STEPS", "12"),
            "FASTSAM3D_STAGE2_STEPS": os.environ.get("FASTSAM3D_STAGE2_STEPS", "12"),
            "FASTSAM3D_SEED": os.environ.get("FASTSAM3D_SEED", "42"),
            "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "0"),
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
    )
    try:
        subprocess.run([sys.executable, str(RUNNER)], check=True, env=runner_env, timeout=900)
        ply = output_dir / "fastsam3d_reconstruction.ply"
        if not ply.is_file() or not ply.stat().st_size:
            raise RuntimeError("Fast-SAM3D exited without producing a PLY.")
        report("complete", label=subject_hint or "gaussian_splat", files={"ply": ply, "mask": mask})
    except Exception as error:
        report("failed", error=f"Fast-SAM3D failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Fatal worker error: {error}", file=sys.stderr)
        raise
