"""Backfill whole-photo scenes (docs/IMMERSIVE_SCENE_PIPELINE.md 1b) on the GPU host.

For each upload: download its source photo, run scene capture, upload
``artifacts/scenes/<upload_id>/{scene.ply,scene.json}``.

    python backfill_scenes.py --project-id 02b682878bc045d5a5eadc9837f01865 b0949bf0e9f540229b92411d42843db4
    python backfill_scenes.py b0949bf0e9f540229b92411d42843db4=uploads/02b682878bc045d5a5eadc9837f01865/b0949bf0e9f540229b92411d42843db4/source.jpg
    python backfill_scenes.py testroom1=artifacts/_deploy/testphotos/room1.jpg
    python backfill_scenes.py --skip-existing --project-id P U1 U2 ...

``UPLOAD_ID=KEY`` uses that S3 key as the photo. A bare ``UPLOAD_ID`` needs
``--project-id``: the photo key comes from the upload record (DynamoDB GetItem
``PROJECT#<p>`` / ``UPLOAD#<u>``, field ``image_key``), else from HeadObject on
``uploads/<p>/<u>/source.{jpg,jpeg,png,webp}``. Never scans the table or lists
the bucket (the instance role may do neither). Uses the warm
sketchscape-scene server (127.0.0.1:8004) when it is up, else loads the models
in-process (run with /opt/sketchscape/runtime/scene/venv/bin/python then).
Credentials: the instance role (boto3 default chain).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

import boto3

BUCKET = os.environ.get("SKETCHSCAPE_ARTIFACTS_BUCKET", "sketchscape-artifacts-20260922133334256700000003")
REGION = os.environ.get("AWS_REGION", "us-east-1")
SCENE_URL = os.environ.get("SKETCHSCAPE_SCENE_URL", "http://127.0.0.1:8004")
WORK = Path(os.environ.get("SKETCHSCAPE_SCENE_BACKFILL_DIR", "/opt/sketchscape/data/scene-backfill"))


PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG", ".PNG")


def _s3_exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def find_photo_key(s3, upload_id: str, project_id: str | None) -> str:
    """S3 key of an upload's source photo, via GetItem/HeadObject only (the
    instance role has neither dynamodb:Scan nor s3:ListBucket)."""
    if not project_id:
        raise ValueError(f"no photo key for {upload_id}: pass --project-id <project_id> "
                         f"or {upload_id}=uploads/<project_id>/{upload_id}/source.jpg")
    notes = []
    table = os.environ.get("SKETCHSCAPE_DYNAMODB_TABLE", "sketchscape-authoring")
    try:
        ddb = boto3.client("dynamodb", region_name=REGION)
        item = ddb.get_item(TableName=table, Key={"pk": {"S": f"PROJECT#{project_id}"},
                                                  "sk": {"S": f"UPLOAD#{upload_id}"}}).get("Item")
        if item and "document" in item:
            key = json.loads(item["document"]["S"]).get("image_key")
            if key and _s3_exists(s3, key):
                return key
            notes.append(f"upload record image_key {key!r} not in S3")
        else:
            notes.append(f"no upload record PROJECT#{project_id}/UPLOAD#{upload_id} in {table}")
    except Exception as exc:  # no dynamodb:GetItem etc.: fall back to S3 probing
        notes.append(f"GetItem failed ({type(exc).__name__}: {exc})")
    for suffix in PHOTO_SUFFIXES:
        key = f"uploads/{project_id}/{upload_id}/source{suffix}"
        if _s3_exists(s3, key):
            return key
    notes.append(f"no uploads/{project_id}/{upload_id}/source.{{jpg,jpeg,png,webp}} in s3://{BUCKET}")
    raise ValueError(f"cannot find the photo of upload {upload_id}: " + "; ".join(notes)
                     + f". Pass {upload_id}=<s3 key of the photo>.")


def server_up() -> bool:
    try:
        with urlopen(f"{SCENE_URL}/health", timeout=3) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


def run_scene(image: Path, out_dir: Path, upload_id: str, photo: str) -> dict:
    if server_up():
        body = json.dumps({"image_path": str(image), "out_dir": str(out_dir), "upload_id": upload_id, "photo": photo}).encode()
        req = Request(f"{SCENE_URL}/v1/scene", data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=900) as r:
            return json.loads(r.read())["scene_json"]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import scene_capture
    return scene_capture.SceneCapture(keep_resident=True).scene(image, out_dir, upload_id, photo)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("uploads", nargs="+", help="UPLOAD_ID or UPLOAD_ID=S3_KEY_OF_PHOTO")
    ap.add_argument("--project-id", help="project of the bare UPLOAD_IDs (photo key via GetItem/HeadObject)")
    ap.add_argument("--skip-existing", action="store_true")
    args = ap.parse_args()
    s3 = boto3.client("s3", region_name=REGION)
    failures = 0
    for spec in args.uploads:
        upload_id, _, key = spec.partition("=")
        prefix = f"artifacts/scenes/{upload_id}/"
        if args.skip_existing:
            try:
                s3.head_object(Bucket=BUCKET, Key=prefix + "scene.json")
                print(f"{upload_id}: exists, skipped")
                continue
            except s3.exceptions.ClientError:
                pass
        try:
            key = key or find_photo_key(s3, upload_id, args.project_id)
            work = WORK / upload_id
            work.mkdir(parents=True, exist_ok=True)
            image = work / ("source" + (Path(key).suffix or ".jpg"))
            s3.download_file(BUCKET, key, str(image))
            t = time.time()
            doc = run_scene(image, work / "out", upload_id, key)
            dt = time.time() - t
            s3.upload_file(str(work / "out" / "scene.ply"), BUCKET, prefix + "scene.ply",
                           ExtraArgs={"ContentType": "application/octet-stream"})
            s3.upload_file(str(work / "out" / "scene.json"), BUCKET, prefix + "scene.json",
                           ExtraArgs={"ContentType": "application/json"})
            sp = doc["support_plane"]
            metric = (doc["splat"].get("metric_scale") or {}).get("source", "moge (v1)")
            print(f"{upload_id}: {doc['splat']['count']} gaussians, camera {sp['camera_height']} m above {sp['kind']}, "
                  f"aligned_scale {doc['splat']['aligned_scale']}, metric {metric}, {dt:.1f}s "
                  f"<- s3://{BUCKET}/{key} -> s3://{BUCKET}/{prefix}")
        except Exception as exc:  # keep going with the others
            failures += 1
            print(f"{upload_id}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
