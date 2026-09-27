#!/usr/bin/env python3
"""Re-run Fast-SAM3D for existing ready object jobs so they get pose.json v2.

Runs ON the GPU host, next to the resident worker (worker_server.py): it
hands each job's photo + mask to the worker's loopback ``POST /worker/local``
(no second copy of the models), then publishes the results:

  artifacts/<job_id>/reconstruction.orig.ply   backup of the old PLY (once)
  artifacts/<job_id>/reconstruction.ply        new PLY (same pipeline, pose-verified)
  artifacts/<job_id>/pose.json                 pose.json v2 (contract section 1a)

and stores the pose on the DynamoDB JOB item and on its ASSET item (top level
+ the matching view), like the backend's result callback does.

Usage (host, as root or ubuntu, with /etc/sketchscape.env loaded):
  /opt/sketchscape/backend/.venv/bin/python backfill_objects.py --project-id <p> --upload-id <u> [--dry-run]
  /opt/sketchscape/backend/.venv/bin/python backfill_objects.py --job-id <id> [--job-id <id> ...]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import boto3
from boto3.dynamodb.conditions import Key

BUCKET = os.environ.get("SKETCHSCAPE_ARTIFACTS_BUCKET", "sketchscape-artifacts-20260922133334256700000003")
TABLE = os.environ.get("SKETCHSCAPE_DYNAMODB_TABLE", "sketchscape-authoring")
REGION = os.environ.get("AWS_REGION", "us-east-1")
WORKER_URL = os.environ.get("SKETCHSCAPE_WORKER_URL",
                            f"http://127.0.0.1:{os.environ.get('SKETCHSCAPE_WORKER_SERVER_PORT', '8001')}")
GSI1 = os.environ.get("SKETCHSCAPE_DYNAMODB_GSI1", "gsi1")
WORK = Path(os.environ.get("SKETCHSCAPE_BACKFILL_DIR", "/opt/sketchscape/data/backfill"))


def _json(url: str, body: dict | None = None, timeout: float = 30) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {},
                  method="POST" if data is not None else "GET")
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def wait_for_worker(timeout: float = 900) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            health = _json(f"{WORKER_URL}/worker/health", timeout=5)
            if health.get("status") == "ready":
                return
        except Exception:
            pass
        time.sleep(10)
    raise SystemExit("worker not ready")


def jobs_for_upload(table, upload_id: str, project_id: str | None) -> list[dict]:
    """Ready reconstruct jobs of an upload, via the project's job index
    (gsi1: PROJECTJOBS#<project_id>; the host role may not Scan)."""
    if not project_id:
        raise SystemExit("--upload-id needs --project-id (or pass --job-id)")
    items, kwargs = [], {"IndexName": GSI1, "KeyConditionExpression": Key("gsi1pk").eq(f"PROJECTJOBS#{project_id}")}
    while True:
        page = table.query(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    docs = [json.loads(i["document"]) for i in items if "document" in i]
    if docs and not all("job_id" in d for d in docs):  # index projects keys only
        docs = [get_doc(table, i["pk"]) for i in items]
    return [d for d in docs if d and d.get("upload_id") == upload_id and d.get("kind") == "reconstruct"
            and d.get("status") == "complete"]


def get_doc(table, pk: str) -> dict | None:
    item = table.get_item(Key={"pk": pk, "sk": "META"}).get("Item")
    return json.loads(item["document"]) if item else None


def put_doc(table, pk: str, doc: dict) -> None:
    table.update_item(Key={"pk": pk, "sk": "META"}, UpdateExpression="SET #d = :d",
                      ExpressionAttributeNames={"#d": "document"},
                      ExpressionAttributeValues={":d": json.dumps(doc, separators=(",", ":"))})


def reconstruct(image: Path, mask: Path, out: Path, debug: bool) -> dict:
    wait_for_worker()
    for attempt in range(60):
        try:
            job = _json(f"{WORKER_URL}/worker/local",
                        {"image_path": str(image), "mask_path": str(mask), "output_dir": str(out), "debug": debug})
            break
        except Exception as exc:  # 429 while the worker is busy with a live job
            print(f"  worker busy ({exc}); retrying", flush=True)
            time.sleep(10)
    else:
        raise RuntimeError("worker never accepted the job")
    local_id = job["job_id"]
    deadline = time.time() + 900
    while time.time() < deadline:
        status = _json(f"{WORKER_URL}/worker/status/{local_id}", timeout=10)
        if status.get("status") in ("complete", "failed"):
            return status
        time.sleep(3)
    raise RuntimeError(f"{local_id} timed out")


def scene_check(s3, upload_id: str | None, pose: dict | None, mask_path: Path) -> dict:
    """Is pose.json in the same geometry as the stored scene.json? Same image
    size and intrinsics, and the same depth scale: the scene's depth grid
    inside the mask vs the pose's visible-surface centroid depth (a v1/v2
    scale mix-up shows up as a ratio of ~1.5)."""
    if not upload_id or not pose or pose.get("version") != 2:
        return {"ok": None, "reason": "no upload id or no v2 pose"}
    try:
        scene = json.loads(s3.get_object(Bucket=BUCKET, Key=f"artifacts/scenes/{upload_id}/scene.json")["Body"].read())
    except Exception as exc:
        return {"ok": None, "reason": f"no scene.json ({str(exc)[:120]})"}
    out = {"metric_source": ((scene.get("splat") or {}).get("metric_scale") or {}).get("source"),
           "scene_fx": (scene.get("intrinsics") or {}).get("fx"), "pose_fx": (pose.get("intrinsics") or {}).get("fx")}
    same_k = (list(scene.get("image_size") or []) == list(pose.get("image_size") or [])
              and out["scene_fx"] and out["pose_fx"] and abs(out["scene_fx"] - out["pose_fx"]) <= 0.005 * out["scene_fx"])
    grid = scene.get("depth_grid") or {}
    pts, gw, gh = grid.get("points_cam") or [], int(grid.get("w") or 0), int(grid.get("h") or 0)
    centroid = (pose.get("object") or {}).get("centroid_cam")
    ratio = None
    if gw and gh and len(pts) == 3 * gw * gh and centroid:
        try:
            from PIL import Image
            import numpy as np
            m = np.asarray(Image.open(mask_path).convert("L").resize((gw, gh), Image.Resampling.NEAREST)) > 127
            z = np.asarray(pts, dtype=float).reshape(gh, gw, 3)[..., 2][m]
            z = z[np.isfinite(z) & (z > 0)]
            if len(z):
                ratio = round(float(np.median(z)) / float(centroid[2]), 4)
        except Exception as exc:
            out["grid_error"] = str(exc)[:120]
    out["grid_depth_over_pose_depth"] = ratio
    out["ok"] = bool(same_k) and (ratio is None or 0.85 <= ratio <= 1.15)
    return out


def backfill(job: dict, *, s3, table, dry_run: bool, debug: bool) -> dict:
    job_id = job["job_id"]
    work = WORK / job_id
    work.mkdir(parents=True, exist_ok=True)
    image = work / ("source" + (Path(job["image_key"]).suffix or ".png"))
    mask = work / "mask.png"
    s3.download_file(BUCKET, job["image_key"], str(image))
    s3.download_file(BUCKET, f"artifacts/{job_id}/mask.png", str(mask))
    os.system(f"chown -R ubuntu:ubuntu {work} 2>/dev/null")
    status = reconstruct(image, mask, work / "output", debug)
    if status.get("status") != "complete":
        raise RuntimeError(f"reconstruction failed: {status}")
    ply, pose_path = Path(status["ply"]), Path(status["pose"]) if status.get("pose") else None
    pose = json.loads(pose_path.read_text()) if pose_path else None
    obj = (pose or {}).get("object", {})
    summary = {"job_id": job_id, "label": job.get("subject_hint"), "pose_version": (pose or {}).get("version"),
               "reprojection_iou": obj.get("reprojection_iou"), "metric": (pose or {}).get("metric"),
               "verified": obj.get("splat_to_cam") is not None,
               "verification": (pose or {}).get("verification"), "ply_bytes": ply.stat().st_size}
    summary["scene_check"] = scene_check(s3, job.get("upload_id"), pose, mask)
    if dry_run:
        summary["dry_run"] = True
        return summary

    if summary["scene_check"].get("ok") is False:
        raise RuntimeError(f"pose and scene.json disagree; nothing written: {summary['scene_check']}")
    orig_key = f"artifacts/{job_id}/reconstruction.orig.ply"
    try:
        s3.head_object(Bucket=BUCKET, Key=orig_key)
    except s3.exceptions.ClientError:
        s3.copy_object(Bucket=BUCKET, Key=orig_key, CopySource={"Bucket": BUCKET, "Key": f"artifacts/{job_id}/reconstruction.ply"})
    s3.upload_file(str(ply), BUCKET, f"artifacts/{job_id}/reconstruction.ply",
                   ExtraArgs={"ContentType": "application/octet-stream"})
    if pose is not None:
        s3.upload_file(str(pose_path), BUCKET, f"artifacts/{job_id}/pose.json", ExtraArgs={"ContentType": "application/json"})
        doc = get_doc(table, f"JOB#{job_id}")
        if doc is not None:
            doc["pose"] = pose
            put_doc(table, f"JOB#{job_id}", doc)
        asset_id = job.get("asset_id")
        asset = get_doc(table, f"ASSET#{asset_id}") if asset_id else None
        if asset is not None:
            for view in asset.get("views") or []:
                if view.get("reconstruction_job_id") == job_id:
                    view["pose"] = pose
            ready = [v for v in asset.get("views") or [] if v.get("status") == "ready"]
            if not ready or ready[0].get("reconstruction_job_id") == job_id:
                asset["pose"] = pose
            put_doc(table, f"ASSET#{asset_id}", asset)
            summary["asset_id"] = asset_id
    summary["s3"] = {"ply": f"artifacts/{job_id}/reconstruction.ply", "orig": orig_key,
                     "pose": f"artifacts/{job_id}/pose.json" if pose else None}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--upload-id")
    parser.add_argument("--project-id")
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true", help="reconstruct only; no S3/DynamoDB writes")
    parser.add_argument("--debug", action="store_true", help="also keep pose_debug.npz beside the outputs")
    args = parser.parse_args()
    s3 = boto3.client("s3", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    jobs = jobs_for_upload(table, args.upload_id, args.project_id) if args.upload_id else []
    for job_id in args.job_id:
        doc = get_doc(table, f"JOB#{job_id}")
        if doc is None:
            print(f"no such job {job_id}", file=sys.stderr)
            return 2
        jobs.append(doc)
    if not jobs:
        print("no jobs", file=sys.stderr)
        return 2
    failures = 0
    for job in jobs:
        print(f"== {job['job_id']} ({job.get('subject_hint')})", flush=True)
        try:
            print(json.dumps(backfill(job, s3=s3, table=table, dry_run=args.dry_run, debug=args.debug)), flush=True)
        except Exception as exc:
            failures += 1
            print(f"  FAILED: {exc}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
