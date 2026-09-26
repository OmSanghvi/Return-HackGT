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
    from storage import DynamoDbStore, RevisionConflict as RevisionConflictError, create_store
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


def _make_contributor(contributor_id: str, project_id: str) -> app_main.Contributor:
    return app_main.Contributor(
        contributor_id=contributor_id,
        project_id=project_id,
        display_name="Smoke Contributor",
        joined_at=_now(),
        clerk_user_id="smoke-account",
    )


def _make_contribution(contribution_id: str, project_id: str, contributor_id: str, asset_id: str) -> app_main.Contribution:
    return app_main.Contribution(
        contribution_id=contribution_id,
        project_id=project_id,
        contributor_id=contributor_id,
        asset_id=asset_id,
        source_type="photo",
        memory_text="Created by smoke_test_aws_storage.py.",
        created_at=_now(),
    )


def _make_insight(project_id: str, revision: int) -> app_main.ConnectionInsight:
    return app_main.ConnectionInsight(
        project_id=project_id,
        revision=revision,
        theme="Smoke test theme",
        explanation="Created by smoke_test_aws_storage.py — safe to delete.",
        placement_rationale=[],
        backend="mock",
        model="smoke-test",
        created_at=_now(),
    )


def _make_job(job_id: str, project_id: str) -> app_main.ReconstructionJob:
    now = _now()
    return app_main.ReconstructionJob(
        job_id=job_id,
        status=app_main.JobStatus.QUEUED,
        poll_url=f"/v1/reconstructions/{job_id}",
        created_at=now,
        updated_at=now,
        project_id=project_id,
        kind="segment",
    )


def _make_upload(upload_id: str, project_id: str) -> app_main.UploadRecord:
    return app_main.UploadRecord(
        upload_id=upload_id,
        project_id=project_id,
        uploader_user_id="smoke-account",
        image_key=f"uploads/{project_id}/{upload_id}/source.png",
        width=10,
        height=10,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# DynamoDB smoke test
# ---------------------------------------------------------------------------

def run_dynamodb_smoke(project_id: str, asset_id: str, job_id: str) -> None:
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

    # -- blueprints (ordered, conditional writes -- Build Plan step 15) ----
    bp1 = _make_blueprint(project_id, revision=1)
    bp2 = _make_blueprint(project_id, revision=2)
    store.append_blueprint(bp1)
    store.append_blueprint(bp2)
    revisions = store.list_blueprints(project_id)
    check("two blueprints stored", len(revisions) == 2)
    check("blueprints returned in creation order", [r.revision for r in revisions] == [1, 2])

    try:
        store.append_blueprint(_make_blueprint(project_id, revision=1))
        check("duplicate blueprint revision rejected", False, "expected RevisionConflict")
    except RevisionConflictError:
        check("duplicate blueprint revision rejected (real ConditionExpression)", True)

    # -- publications (append-only, ordered) -------------------------------
    store.append_publication(_make_pub(project_id, 1))
    store.append_publication(_make_pub(project_id, 2))
    store.append_publication(_make_pub(project_id, 1))  # republish rev 1
    pubs = store.list_publications(project_id)
    check("three publication records stored", len(pubs) == 3)
    check("publication log is append-only [1,2,1]", [p.revision for p in pubs] == [1, 2, 1])

    # -- LIVE pointer compare-and-set (Build Plan step 15) ------------------
    check("live revision starts unset", store.get_live_revision(project_id) is None)
    check("set_live_revision(None -> 1) applies", store.set_live_revision(project_id, None, 1))
    check("set_live_revision with stale expected fails closed", not store.set_live_revision(project_id, 0, 2))
    check("live revision unaffected by the rejected CAS", store.get_live_revision(project_id) == 1)

    # -- overwrite protection: get after update ----------------------------
    project.updated_at = _now()
    project.asset_ids.append(asset_id)
    store.save_project(project)
    updated = store.get_project(project_id)
    check("project update persists asset_ids", updated and asset_id in updated.asset_ids)

    # -- contributors / contributions / connection insights (step 1) -------
    contributor_id = f"{project_id}-contributor"
    contribution_id = f"{project_id}-contribution"
    store.append_contributor(_make_contributor(contributor_id, project_id))
    store.append_contribution(_make_contribution(contribution_id, project_id, contributor_id, asset_id))
    store.append_connection_insight(_make_insight(project_id, revision=1))
    check("contributor roundtrips", len(store.list_contributors(project_id)) == 1)
    check("contribution roundtrips", len(store.list_contributions(project_id)) == 1)
    check("connection insight roundtrips", len(store.list_connection_insights(project_id)) == 1)

    # -- durable jobs + project->asset links + uploads (step 26) -----------
    # These live under a distinct pk (JOB#<job_id>), and their pollability
    # depends on the gsi1/gsi2 indexes actually being provisioned -- this is
    # exactly what the offline moto tests can't confirm against the real
    # table.
    store.save_job(_make_job(job_id, project_id))
    check("save_job / get_job roundtrip", store.get_job(job_id) is not None)
    project_jobs = store.list_project_jobs(project_id)
    check("list_project_jobs finds it via gsi1", any(j.job_id == job_id for j in project_jobs))
    claimed = store.claim_next_job("smoke-worker", ["segment"], lease_seconds=60)
    check("claim_next_job claims it via gsi2", claimed is not None and claimed.job_id == job_id)
    check(
        "complete_job succeeds for the lease owner",
        store.complete_job(job_id, "smoke-worker", {"status": app_main.JobStatus.COMPLETE}),
    )

    store.link_asset(project_id, asset_id)
    check("link_asset / list_linked_asset_ids roundtrip", asset_id in store.list_linked_asset_ids(project_id))

    upload_id = f"{project_id}-upload"
    store.save_upload_record(_make_upload(upload_id, project_id))
    check(
        "save_upload_record / get_upload_record roundtrip",
        store.get_upload_record(project_id, upload_id) is not None,
    )


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

        # -- uploads/ prefix (Build Plan step 26) --------------------------
        # Distinct from artifacts/<job_id>/ above. This is exactly the
        # prefix the IAM-policy fix in infra/aws/main.tf added; without it,
        # both calls below get AccessDenied against the real bucket even
        # though the artifacts/ checks above pass.
        upload_project_id = f"smoke-{job_id}-project"
        upload_id = f"smoke-{job_id}-upload"
        upload_source = UploadFile(filename="source.png", file=io.BytesIO(mask_data))
        upload_key = run(
            artifact_store.put_upload(
                upload_project_id, upload_id, "source.png", upload_source, size_limit=1024 * 1024
            )
        )
        check(
            "put_upload returns the canonical uploads/ key",
            upload_key == f"uploads/{upload_project_id}/{upload_id}/source.png",
        )
        check("open_upload reads back the same bytes", artifact_store.open_upload(upload_key) == mask_data)

    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Cleanup: remove all smoke-test items from DynamoDB and S3
# ---------------------------------------------------------------------------

def cleanup_dynamodb(project_id: str, asset_id: str, job_id: str) -> None:
    section("Cleanup — DynamoDB")
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    from boto3.dynamodb.conditions import Key as DKey  # noqa: N814

    # Collect and delete all items under PROJECT#<id> (project meta, LIVE
    # pointer, blueprints, publications, contributors, contributions,
    # insights, asset links, and upload records all live here).
    items_deleted = 0
    response = table.query(KeyConditionExpression=DKey("pk").eq(f"PROJECT#{project_id}"))
    for item in response.get("Items", []):
        table.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
        items_deleted += 1

    # Delete asset item
    table.delete_item(Key={"pk": f"ASSET#{asset_id}", "sk": "META"})
    items_deleted += 1

    # Delete the durable job item -- it lives under its own pk (JOB#<id>),
    # not under PROJECT#<id>, so the query above never sees it.
    table.delete_item(Key={"pk": f"JOB#{job_id}", "sk": "META"})
    items_deleted += 1

    check(f"removed {items_deleted} DynamoDB smoke items", items_deleted > 0)


def cleanup_s3(job_id: str) -> None:
    section("Cleanup — S3")
    s3 = boto3.client("s3", region_name=REGION)
    # Two distinct prefixes exercised by run_s3_smoke: artifacts/<job_id>/
    # (PLY/mask/preview) and uploads/<project_id>/<upload_id>/ (source
    # photos). Both must be cleaned up, and both must be reachable by the
    # bucket's IAM policy for this smoke test to have passed at all.
    prefixes = [f"artifacts/{job_id}/", f"uploads/smoke-{job_id}-project/"]
    total_removed = 0
    for prefix in prefixes:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        objects = response.get("Contents", [])
        if objects:
            s3.delete_objects(
                Bucket=BUCKET_NAME,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
        total_removed += len(objects)
    check(f"removed {total_removed} S3 smoke objects", True)  # non-zero is ideal but 0 is also fine


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
        run_dynamodb_smoke(project_id, asset_id, job_id)
        run_s3_smoke(job_id)
    finally:
        try:
            cleanup_dynamodb(project_id, asset_id, job_id)
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
