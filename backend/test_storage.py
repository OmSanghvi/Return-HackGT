"""Storage-layer contract tests.

These exercise the backend-selection factory and each store's contract without
requiring AWS. DynamoDB CRUD is covered against a small in-memory fake table so
the test stays hermetic; it is skipped only where boto3 itself is needed and
absent. Run with `python -m unittest test_storage.py`.
"""

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

import main  # noqa: E402
import storage  # noqa: E402

_HAS_BOTO3 = importlib.util.find_spec("boto3") is not None


def make_project(project_id: str = "p1") -> "main.ProjectRecord":
    now = main.utc_now()
    return main.ProjectRecord(
        project_id=project_id,
        name="Test",
        description="",
        created_at=now,
        updated_at=now,
    )


def make_asset(asset_id: str = "a1", project_id: str = "p1") -> "main.ProjectAsset":
    return main.ProjectAsset(
        asset_id=asset_id,
        project_id=project_id,
        label="thing",
        status=main.AssetStatus.READY,
        reconstruction_job_id="job1",
    )


def make_contributor(contributor_id: str = "c1", project_id: str = "p1", display_name: str = "Alice") -> "main.Contributor":
    return main.Contributor(
        contributor_id=contributor_id,
        project_id=project_id,
        display_name=display_name,
        joined_at=main.utc_now(),
    )


def make_contribution(
    contribution_id: str = "ctr1",
    project_id: str = "p1",
    contributor_id: str = "c1",
    asset_id: str = "a1",
    source_type: "main.ContributionSourceType" = "photo",
    memory_text: str = "A trip we took together.",
) -> "main.Contribution":
    return main.Contribution(
        contribution_id=contribution_id,
        project_id=project_id,
        contributor_id=contributor_id,
        asset_id=asset_id,
        source_type=source_type,
        memory_text=memory_text,
        created_at=main.utc_now(),
    )


def make_connection_insight(project_id: str = "p1", revision: int = 1) -> "main.ConnectionInsight":
    return main.ConnectionInsight(
        project_id=project_id,
        revision=revision,
        theme="Warm childhood summers",
        explanation="Both objects evoke long summer afternoons together.",
        placement_rationale=[
            main.PlacementRationale(object_id="o1", asset_id="a1", rationale="Placed near the window light."),
        ],
        backend="mock",
        model="mock-v1",
        created_at=main.utc_now(),
    )


class FactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._state = Path(_temp_dir.name) / "factory-state.json"

    def test_defaults_to_local_json_store(self) -> None:
        store = storage.create_store(local_state_path=self._state)
        self.assertIsInstance(store, storage.LocalJsonStore)

    def test_explicit_local_backend(self) -> None:
        store = storage.create_store(local_state_path=self._state, backend="local")
        self.assertIsInstance(store, storage.LocalJsonStore)

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            storage.create_store(local_state_path=self._state, backend="postgres")

    def test_store_alias_points_at_local_json_store(self) -> None:
        self.assertIs(storage.Store, storage.LocalJsonStore)


class LocalJsonStoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._state = Path(_temp_dir.name) / f"contract-{self.id().split('.')[-1]}.json"
        self._state.unlink(missing_ok=True)
        self.store = storage.LocalJsonStore(self._state)
        self.store.load()

    def test_project_and_asset_roundtrip(self) -> None:
        self.store.save_project(make_project())
        self.store.save_asset(make_asset())
        self.assertEqual(self.store.get_project("p1").project_id, "p1")
        self.assertEqual(self.store.get_asset("a1").asset_id, "a1")
        self.assertIsNone(self.store.get_project("missing"))

    def test_reload_rehydrates_state(self) -> None:
        self.store.save_project(make_project())
        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertIsNotNone(reloaded.get_project("p1"))

    def test_corrupt_snapshot_is_quarantined_not_fatal(self) -> None:
        self._state.write_text("{ this is not valid json", encoding="utf-8")
        # load() must not raise; it should quarantine and start empty.
        self.store.load()
        self.assertIsNone(self.store.get_project("p1"))
        quarantined = list(self._state.parent.glob(self._state.name + ".corrupt-*"))
        self.assertTrue(quarantined, "corrupt snapshot should be preserved for inspection")

    def test_contributor_and_contribution_roundtrip(self) -> None:
        self.store.save_project(make_project())
        self.store.save_asset(make_asset())
        self.store.append_contributor(make_contributor())
        self.store.append_contribution(make_contribution())

        contributors = self.store.list_contributors("p1")
        contributions = self.store.list_contributions("p1")
        self.assertEqual([c.contributor_id for c in contributors], ["c1"])
        self.assertEqual([c.contribution_id for c in contributions], ["ctr1"])
        self.assertEqual(contributions[0].source_type, "photo")

    def test_connection_insight_roundtrip(self) -> None:
        self.store.save_project(make_project())
        self.store.append_connection_insight(make_connection_insight())
        insights = self.store.list_connection_insights("p1")
        self.assertEqual(len(insights), 1)
        self.assertEqual(insights[0].backend, "mock")
        self.assertEqual(insights[0].placement_rationale[0].object_id, "o1")

    def test_project_with_three_or_more_contributors_roundtrips(self) -> None:
        """N-ary proof: this must work for 3+ contributors, not just a pair."""
        self.store.save_project(make_project())
        for asset_id in ("a1", "a2", "a3"):
            self.store.save_asset(make_asset(asset_id=asset_id))

        contributor_ids = ["c1", "c2", "c3"]
        for contributor_id in contributor_ids:
            self.store.append_contributor(
                make_contributor(contributor_id=contributor_id, display_name=f"Person {contributor_id}")
            )
        for index, (contributor_id, asset_id) in enumerate(zip(contributor_ids, ("a1", "a2", "a3"))):
            self.store.append_contribution(
                make_contribution(
                    contribution_id=f"ctr{index + 1}",
                    contributor_id=contributor_id,
                    asset_id=asset_id,
                )
            )

        contributors = self.store.list_contributors("p1")
        contributions = self.store.list_contributions("p1")
        self.assertEqual(len(contributors), 3)
        self.assertEqual(len(contributions), 3)
        self.assertEqual(
            {c.contributor_id for c in contributions},
            set(contributor_ids),
        )

    def test_contributor_and_contribution_reload_rehydrates(self) -> None:
        self.store.save_project(make_project())
        self.store.append_contributor(make_contributor())
        self.store.append_contribution(make_contribution())
        self.store.append_connection_insight(make_connection_insight())

        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertEqual(len(reloaded.list_contributors("p1")), 1)
        self.assertEqual(len(reloaded.list_contributions("p1")), 1)
        self.assertEqual(len(reloaded.list_connection_insights("p1")), 1)


class DynamoDbStoreTests(unittest.TestCase):
    def test_missing_table_name_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            storage.DynamoDbStore("")

    def test_seq_key_is_zero_padded_and_ordered(self) -> None:
        first = storage.DynamoDbStore._seq_key("PUBLICATION", 1)
        second = storage.DynamoDbStore._seq_key("PUBLICATION", 2)
        tenth = storage.DynamoDbStore._seq_key("PUBLICATION", 10)
        self.assertLess(first, second)
        self.assertLess(second, tenth)
        self.assertTrue(first.startswith("PUBLICATION#"))

    def test_missing_boto3_gives_actionable_error(self) -> None:
        if _HAS_BOTO3:
            self.skipTest("boto3 is installed; the missing-dependency path cannot be exercised.")
        store = storage.DynamoDbStore("some-table")
        with self.assertRaises(RuntimeError) as ctx:
            store.load()
        self.assertIn("boto3", str(ctx.exception))

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB CRUD test needs boto3 conditions helpers.")
    def test_crud_against_fake_table(self) -> None:
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())
        store.save_asset(make_asset())
        self.assertEqual(store.get_project("p1").project_id, "p1")
        self.assertEqual(store.get_asset("a1").asset_id, "a1")

        blueprint = _make_blueprint("p1", revision=1)
        store.append_blueprint(blueprint)
        store.append_blueprint(_make_blueprint("p1", revision=2))
        revisions = [bp.revision for bp in store.list_blueprints("p1")]
        self.assertEqual(revisions, [1, 2])

        store.append_publication(main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now()))
        store.append_publication(main.PublicationRecord(project_id="p1", revision=2, published_at=main.utc_now()))
        store.append_publication(main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now()))
        published = [rec.revision for rec in store.list_publications("p1")]
        self.assertEqual(published, [1, 2, 1])

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB CRUD test needs boto3 conditions helpers.")
    def test_contributor_and_contribution_roundtrip_against_fake_table(self) -> None:
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())
        store.save_asset(make_asset())

        store.append_contributor(make_contributor())
        store.append_contribution(make_contribution())

        contributors = store.list_contributors("p1")
        contributions = store.list_contributions("p1")
        self.assertEqual([c.contributor_id for c in contributors], ["c1"])
        self.assertEqual([c.contribution_id for c in contributions], ["ctr1"])

        store.append_connection_insight(make_connection_insight(revision=1))
        store.append_connection_insight(make_connection_insight(revision=2))
        insights = [insight.revision for insight in store.list_connection_insights("p1")]
        self.assertEqual(insights, [1, 2])

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB CRUD test needs boto3 conditions helpers.")
    def test_three_or_more_contributors_against_fake_table(self) -> None:
        """N-ary proof against DynamoDbStore too — not just LocalJsonStore."""
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())
        for asset_id in ("a1", "a2", "a3", "a4"):
            store.save_asset(make_asset(asset_id=asset_id))

        contributor_ids = ["c1", "c2", "c3", "c4"]
        for contributor_id in contributor_ids:
            store.append_contributor(make_contributor(contributor_id=contributor_id))
        for index, (contributor_id, asset_id) in enumerate(zip(contributor_ids, ("a1", "a2", "a3", "a4"))):
            store.append_contribution(
                make_contribution(
                    contribution_id=f"ctr{index + 1}",
                    contributor_id=contributor_id,
                    asset_id=asset_id,
                )
            )

        contributors = store.list_contributors("p1")
        contributions = store.list_contributions("p1")
        self.assertEqual(len(contributors), 4)
        self.assertEqual(len(contributions), 4)
        self.assertEqual({c.contributor_id for c in contributions}, set(contributor_ids))


def _make_blueprint(project_id: str, revision: int) -> "main.ExperienceBlueprint":
    return main.ExperienceBlueprint(
        project_id=project_id,
        revision=revision,
        created_at=main.utc_now(),
        experience=main.ExperienceSettings(mode="desktop", theme="t", units="meters"),
        objects=[
            main.BlueprintObject(id="o1", asset_id="a1", position=[0, 0, 0])
        ],
    )


class _FakeTable:
    """A tiny in-memory stand-in for a boto3 DynamoDB Table.

    It supports only the operations DynamoDbStore uses: get_item, put_item, and
    a begins_with/eq Query with ScanIndexForward. Keys are (pk, sk) tuples.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict] = {}

    def get_item(self, Key: dict) -> dict:  # noqa: N803 - boto3 API name
        item = self._items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def put_item(self, Item: dict) -> None:  # noqa: N803 - boto3 API name
        self._items[(Item["pk"], Item["sk"])] = dict(Item)

    def query(self, **kwargs) -> dict:
        # DynamoDbStore builds the condition with boto3's Key helper; rather
        # than parse it, re-derive the pk/sk-prefix filter it always uses.
        condition = kwargs["KeyConditionExpression"]
        pk_value, sk_prefix = _extract_pk_and_prefix(condition)
        matches = [
            item
            for (pk, sk), item in self._items.items()
            if pk == pk_value and sk.startswith(sk_prefix)
        ]
        matches.sort(key=lambda item: item["sk"])
        if not kwargs.get("ScanIndexForward", True):
            matches.reverse()
        return {"Items": matches}


def _extract_pk_and_prefix(condition) -> tuple[str, str]:
    """Pull the pk value and sk prefix out of a boto3 And(condition) tree."""
    from boto3.dynamodb.conditions import And, BeginsWith, Equals  # noqa: PLC0415

    pk_value = ""
    sk_prefix = ""
    parts = condition._values if isinstance(condition, And) else [condition]
    for part in parts:
        values = part._values
        attr, operand = values[0], values[1]
        if isinstance(part, Equals):
            pk_value = operand
        elif isinstance(part, BeginsWith):
            sk_prefix = operand
    return pk_value, sk_prefix


# ---------------------------------------------------------------------------
# Artifact store tests
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import io
import shutil

import artifact_store as artifact_store_module
from artifact_store import (
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
    create_artifact_store,
)
from fastapi import UploadFile


def _upload_file(data: bytes, filename: str = "test.ply") -> UploadFile:
    """Construct a minimal UploadFile from in-memory bytes."""
    return UploadFile(filename=filename, file=io.BytesIO(data))


def _run(coro):
    """Run a coroutine synchronously inside the test suite."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ArtifactStoreFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = Path(_temp_dir.name) / "artifact-factory"

    def test_defaults_to_local(self) -> None:
        store = create_artifact_store(local_artifact_root=self._root)
        self.assertIsInstance(store, LocalArtifactStore)

    def test_explicit_local_backend(self) -> None:
        store = create_artifact_store(local_artifact_root=self._root, backend="local")
        self.assertIsInstance(store, LocalArtifactStore)

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            create_artifact_store(local_artifact_root=self._root, backend="gcs")

    def test_s3_missing_bucket_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            create_artifact_store(local_artifact_root=self._root, backend="s3")

    def test_canonical_url_is_backend_agnostic(self) -> None:
        url = ArtifactStore.artifact_url("job42", "reconstruction.ply")
        self.assertEqual(url, "/v1/artifacts/job42/reconstruction.ply")


class LocalArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._root = Path(_temp_dir.name) / f"local-artifacts-{self.id().split('.')[-1]}"
        shutil.rmtree(self._root, ignore_errors=True)
        self.store = LocalArtifactStore(self._root)

    def test_put_returns_canonical_url(self) -> None:
        url = _run(
            self.store.put("j1", "out.ply", _upload_file(b"PLYDATA"), size_limit=1024)
        )
        self.assertEqual(url, "/v1/artifacts/j1/out.ply")

    def test_put_writes_bytes_to_disk(self) -> None:
        _run(self.store.put("j2", "mask.png", _upload_file(b"\x89PNG"), size_limit=1024))
        self.assertEqual((self._root / "j2" / "mask.png").read_bytes(), b"\x89PNG")

    def test_exists_true_after_put(self) -> None:
        _run(self.store.put("j3", "a.ply", _upload_file(b"X"), size_limit=1024))
        self.assertTrue(self.store.exists("j3", "a.ply"))

    def test_exists_false_for_missing(self) -> None:
        self.assertFalse(self.store.exists("j3", "nope.ply"))

    def test_copy_local_roundtrips(self) -> None:
        src = Path(_temp_dir.name) / "source.ply"
        src.write_bytes(b"LOCALPLY")
        url = _run(self.store.copy_local("j4", "copy.ply", src))
        self.assertEqual(url, "/v1/artifacts/j4/copy.ply")
        self.assertEqual((self._root / "j4" / "copy.ply").read_bytes(), b"LOCALPLY")

    def test_serve_returns_200_for_existing_artifact(self) -> None:
        _run(self.store.put("j5", "file.ply", _upload_file(b"DATA"), size_limit=1024))
        response = _run(self.store.serve("j5", "file.ply"))
        self.assertEqual(response.status_code, 200)

    def test_serve_raises_404_for_missing(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            _run(self.store.serve("j5", "missing.ply"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_put_rejects_oversized_upload(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            _run(
                self.store.put(
                    "j6", "big.ply", _upload_file(b"A" * 10), size_limit=5
                )
            )
        self.assertEqual(ctx.exception.status_code, 413)

    def test_put_rejects_empty_upload(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            _run(self.store.put("j7", "empty.ply", _upload_file(b""), size_limit=1024))
        self.assertEqual(ctx.exception.status_code, 400)


class S3ArtifactStoreTests(unittest.TestCase):
    def test_missing_bucket_raises_at_construction(self) -> None:
        with self.assertRaises(RuntimeError):
            S3ArtifactStore("")

    def test_missing_boto3_gives_actionable_error(self) -> None:
        if _HAS_BOTO3:
            self.skipTest("boto3 is installed; the missing-dependency path is not exercisable.")
        store = S3ArtifactStore("some-bucket")
        with self.assertRaises(RuntimeError) as ctx:
            store._boto_client()
        self.assertIn("boto3", str(ctx.exception))
        self.assertIn("local", str(ctx.exception))

    @unittest.skipUnless(_HAS_BOTO3, "S3 CRUD test needs boto3.")
    def test_put_and_serve_against_fake_s3(self) -> None:
        store = S3ArtifactStore("fake-bucket")
        store._client = _FakeS3Client()

        url = _run(
            store.put("j1", "reconstruction.ply", _upload_file(b"PLYDATA"), size_limit=1024)
        )
        self.assertEqual(url, "/v1/artifacts/j1/reconstruction.ply")
        self.assertTrue(store.exists("j1", "reconstruction.ply"))

        response = _run(store.serve("j1", "reconstruction.ply"))
        # S3 backend issues a 302 redirect to the presigned URL.
        self.assertEqual(response.status_code, 302)
        self.assertIn("presigned", response.headers["location"])


class _FakeS3Client:
    """Minimal in-memory stand-in for a boto3 S3 client.

    Supports only the operations S3ArtifactStore uses: upload_file,
    head_object, and generate_presigned_url.
    """

    def __init__(self) -> None:
        self._objects: set[tuple[str, str]] = set()

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs) -> None:
        self._objects.add((bucket, key))

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if (Bucket, Key) not in self._objects:
            raise Exception("NoSuchKey")
        return {}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int = 300
    ) -> str:  # noqa: N803
        key = Params.get("Key", "")
        return f"https://fake-bucket.s3.amazonaws.com/{key}?presigned=1"


if __name__ == "__main__":
    unittest.main()
