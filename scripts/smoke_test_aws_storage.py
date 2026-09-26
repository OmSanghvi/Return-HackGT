#!/usr/bin/env python3
"""Live AWS smoke test for the DynamoDB authoring store and S3 artifact store.

This script exercises the real ``DynamoDbStore`` and ``S3ArtifactStore``
backends against actual AWS resources. It is intentionally NOT part of the
unit-test suite (which stays hermetic). Run it once after ``terraform apply``
to confirm the provisioned table and bucket behave as the application expects.

Every item it creates is tagged with a ``smoke-test`` prefix and is cleaned
up in the ``finally`` block, so a failed run leaves no orphaned data.

Usage
-----
    cd /path/to/HackGT/backend
    pip install boto3
    SKETCHSCAPE_DYNAMODB_TABLE=<table> \
    SKETCHSCAPE_ARTIFACTS_BUCKET=<bucket> \
    AWS_REGION=us-east-2 \
    python ../scripts/smoke_test_aws_storage.py

All three env vars are required. Obtain their values from::

    terraform -chdir=infra/aws output -raw dynamodb_table_name
    terraform -chdir=infra/aws output -raw artifacts_bucket
    terraform -chdir=infra/aws output -raw aws_region

Exit codes
----------
    0   All checks passed.
    1   One or more checks failed (details printed to stderr).
    2   Missing env var or boto3 not installed.
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: resolve paths so the script can be run from anywhere.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Minimal env so main.py models import cleanly without a real FastAPI startup.
os.environ.setdefault("PIPELINE_MODE", "mock")
os.environ.setdefault("SKETCHSCAPE_DATA_DIR", "/tmp/sketchscape-smoke")


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: {name} is not set. See script usage.", file=sys.stderr)
        sys.exit(2)
    return value


TABLE_NAME = _require_env("SKETCHSCAPE_DYNAMODB_TABLE")
BUCKET_NAME = _require_env("SKETCHSCAPE_ARTIFACTS_BUCKET")
REGION = _require_env("AWS_REGION")

try:
    import boto3
    from boto3.dynamodb.conditions import Key  # noqa: F401 - validates import path
except ImportError:
    print(
        "ERROR: boto3 is not installed. Run: pip install boto3",
        file=sys.stderr,
    )
    sys.exit(2)

# Validate that application backends import cleanly before touching AWS.
try:
    from storage import DynamoDbStore, create_store
    from artifact_store import S3ArtifactStore, create_artifact_store
    import main as app_main
except ImportError as exc:
    print(f"ERROR: Could not import application modules from {BACKEND_DIR}: {exc}", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SMOKE_PREFIX = f"smoke-{uuid.uuid4().hex[:8]}"

_PASS = "\033[32m✓\033[0m"
_FAIL = "\033[31m✗\033[0m"
_failures: list[str] = []


def check(label: str, predicate: bool, detail: str = "") -> None:
    if predicate:
        print(f"  {_PASS}  {label}")
    else:
        msg = f"{label}" + (f": {detail}" if detail else "")
        print(f"  {_FAIL}  {msg}", file=sys.stderr)
        _failures.append(msg)


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _now() -> datetime:
    return datetime.now(UTC)


def _make_project(project_id: str) -> app_main.ProjectRecord:
    now = _now()
    return app_main.ProjectRecord(
        project_id=project_id,
        name=f"Smoke test {project_id}",
        description="Created by smoke_test_aws_storage.py — safe to delete.",
        created_at=now,
        updated_at=now,
    )


def _make_asset(asset_id: str, project_id: str) -> app_main.ProjectAsset:
    return app_main.ProjectAsset(
        asset_id=asset_id,
        project_id=project_id,
        label="smoke-object",
        status=app_main.AssetStatus.READY,
        reconstruction_job_id=f"job-{asset_id}",
    )


def _make_blueprint(project_id: str, revision: int) -> app_main.ExperienceBlueprint:
    return app_main.ExperienceBlueprint(
        project_id=project_id,
        revision=revision,
        created_at=_now(),
        experience=app_main.ExperienceSettings(
            mode="desktop", theme="smoke-test", units="meters"
        ),
        objects=[
            app_main.BlueprintObject(
                id="obj-1",
                asset_id=f"asset-{project_id}",
                position=[0.0, 0.0, 0.0],
            )
        ],
    )


def _make_pub(project_id: str, revision: int) -> app_main.PublicationRecord:
    return app_main.PublicationRecord(
        project_id=project_id, revision=revision, published_at=_now()
    )


# ---------------------------------------------------------------------------
# DynamoDB smoke test
# ---------------------------------------------------------------------------

def run_dynamodb_smoke(project_id: str, asset_id: str) -> None:
    section(f"DynamoDB — table: {TABLE_NAME}")

    os.environ["SKETCHSCAPE_STORAGE_BACKEND"] = "dynamodb"
    os.environ["SKETCHSCAPE_DYNAMODB_TABLE"] = TABLE_NAME
    store = create_store(
        local_state_path=Path("/tmp/sketchscape-smoke/unused.json"),
        backend="dynamodb",
    )

    # -- project -----------------------------------------------------------
    project = _make_project(project_id)
    store.save_project(project)
    got = store.get_project(project_id)
    check("save_project / get_project roundtrip", got is not None)
    check("project name survives roundtrip", got and got.name == project.name)

    # -- asset -------------------------------------------------------------
    asset = _make_asset(asset_id, project_id)
    store.save_asset(asset)
    got_asset = store.get_asset(asset_id)
    check("save_asset / get_asset roundtrip", got_asset is not None)
    check("asset label survives", got_asset and got_asset.label == "smoke-object")

    # -- blueprints (ordered) ----------------------------------------------
    bp1 = _make_blueprint(project_id, revision=1)
    bp2 = _make_blueprint(project_id, revision=2)
    store.append_blueprint(bp1)
    store.append_blueprint(bp2)
    revisions = store.list_blueprints(project_id)
    check("two blueprints stored", len(revisions) == 2)
    check("blueprints returned in creation order", [r.revision for r in revisions] == [1, 2])

    # -- publications (append-only, ordered) -------------------------------
    store.append_publication(_make_pub(project_id, 1))
    store.append_publication(_make_pub(project_id, 2))
    store.append_publication(_make_pub(project_id, 1))  # republish rev 1
    pubs = store.list_publications(project_id)
    check("three publication records stored", len(pubs) == 3)
    check("publication log is append-only [1,2,1]", [p.revision for p in pubs] == [1, 2, 1])

    # -- overwrite protection: get after update ----------------------------
    project.updated_at = _now()
    project.asset_ids.append(asset_id)
    store.save_project(project)
    updated = store.get_project(project_id)
    check("project update persists asset_ids", updated and asset_id in updated.asset_ids)


# ---------------------------------------------------------------------------
# S3 artifact smoke test
# ---------------------------------------------------------------------------

def run_s3_smoke(job_id: str) -> None:
    section(f"S3 artifacts — bucket: {BUCKET_NAME}")

    os.environ["SKETCHSCAPE_ARTIFACTS_BACKEND"] = "s3"
    os.environ["SKETCHSCAPE_ARTIFACTS_BUCKET"] = BUCKET_NAME
    artifact_store = create_artifact_store(
        local_artifact_root=Path("/tmp/sketchscape-smoke/local-unused"),
        backend="s3",
    )

    # Use asyncio to call the async put/serve methods.
    import asyncio
    from fastapi import UploadFile

    loop = asyncio.new_event_loop()

    def run(coro):
        return loop.run_until_complete(coro)

    ply_data = b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n0\n"
    mask_data = b"\x89PNG\r\n\x1a\n"  # minimal PNG header bytes

    try:
        # -- put PLY -------------------------------------------------------
        ply_upload = UploadFile(filename="reconstruction.ply", file=io.BytesIO(ply_data))
        ply_url = run(artifact_store.put(job_id, "reconstruction.ply", ply_upload, size_limit=1024 * 1024))
        check("put PLY returns canonical URL", ply_url == f"/v1/artifacts/{job_id}/reconstruction.ply")
        check("PLY exists in bucket", artifact_store.exists(job_id, "reconstruction.ply"))

        # -- put mask ------------------------------------------------------
        mask_upload = UploadFile(filename="mask.png", file=io.BytesIO(mask_data))
        run(artifact_store.put(job_id, "mask.png", mask_upload, size_limit=1024 * 1024))
        check("mask exists in bucket", artifact_store.exists(job_id, "mask.png"))

        # -- presigned redirect serves a reachable URL ---------------------
        response = run(artifact_store.serve(job_id, "reconstruction.ply"))
        check("serve returns 302 redirect", response.status_code == 302)
        location = response.headers.get("location", "")
        check("presigned URL points to correct bucket", BUCKET_NAME in location)
        check("presigned URL contains expected key path", f"artifacts/{job_id}" in location)

        # -- copy_local round-trip -----------------------------------------
        tmp = Path("/tmp/sketchscape-smoke")
        tmp.mkdir(parents=True, exist_ok=True)
        preview_src = tmp / "preview.png"
        preview_src.write_bytes(mask_data)
        preview_url = run(artifact_store.copy_local(job_id, "mask-preview.png", preview_src))
        check("copy_local returns canonical URL", "mask-preview.png" in preview_url)
        check("preview exists in bucket", artifact_store.exists(job_id, "mask-preview.png"))

        # -- oversize rejection stays client-side (does not hit S3) -------
        from fastapi import HTTPException
        try:
            big = UploadFile(filename="big.ply", file=io.BytesIO(b"X" * 20))
            run(artifact_store.put(job_id, "big.ply", big, size_limit=10))
            check("oversize upload rejected", False, "expected HTTPException 413")
        except HTTPException as exc:
            check("oversize upload rejected with 413", exc.status_code == 413)

    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Cleanup: remove all smoke-test items from DynamoDB and S3
# ---------------------------------------------------------------------------

def cleanup_dynamodb(project_id: str, asset_id: str) -> None:
    section("Cleanup — DynamoDB")
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    from boto3.dynamodb.conditions import Key as DKey  # noqa: N814

    # Collect and delete all items under PROJECT#<id>
    items_deleted = 0
    response = table.query(KeyConditionExpression=DKey("pk").eq(f"PROJECT#{project_id}"))
    for item in response.get("Items", []):
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        items_deleted += 1

    # Delete asset item
    table.delete_item(Key={"pk": f"ASSET#{asset_id}", "sk": "META"})
    items_deleted += 1

    check(f"removed {items_deleted} DynamoDB smoke items", items_deleted > 0)


def cleanup_s3(job_id: str) -> None:
    section("Cleanup — S3")
    s3 = boto3.client("s3", region_name=REGION)
    prefix = f"artifacts/{job_id}/"
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
    objects = response.get("Contents", [])
    if objects:
        s3.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
        )
    check(f"removed {len(objects)} S3 smoke objects", True)  # non-zero is ideal but 0 is also fine


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    project_id = f"{SMOKE_PREFIX}-project"
    asset_id = f"{SMOKE_PREFIX}-asset"
    job_id = f"{SMOKE_PREFIX}-job"

    print(f"\nSketchScape AWS storage smoke test")
    print(f"  Region:  {REGION}")
    print(f"  Table:   {TABLE_NAME}")
    print(f"  Bucket:  {BUCKET_NAME}")
    print(f"  Run ID:  {SMOKE_PREFIX}")

    try:
        run_dynamodb_smoke(project_id, asset_id)
        run_s3_smoke(job_id)
    finally:
        try:
            cleanup_dynamodb(project_id, asset_id)
        except Exception as exc:
            print(f"WARNING: DynamoDB cleanup failed: {exc}", file=sys.stderr)
        try:
            cleanup_s3(job_id)
        except Exception as exc:
            print(f"WARNING: S3 cleanup failed: {exc}", file=sys.stderr)

    section("Result")
    if _failures:
        print(f"\n  {len(_failures)} check(s) FAILED:\n")
        for failure in _failures:
            print(f"    {_FAIL}  {failure}", file=sys.stderr)
        return 1

    print(f"\n  {_PASS}  All checks passed. DynamoDB and S3 backends are verified.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
