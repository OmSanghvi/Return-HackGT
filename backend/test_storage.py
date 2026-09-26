"""Storage-layer contract tests.

These exercise the backend-selection factory and each store's contract without
requiring AWS. DynamoDB CRUD is covered against a small in-memory fake table so
the test stays hermetic; it is skipped only where boto3 itself is needed and
absent. Run with `python -m unittest test_storage.py`.
"""

import importlib.util
import json
import os
import re
import tempfile
import unittest
from datetime import timedelta
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

    def test_append_blueprint_out_of_sequence_raises_revision_conflict(self) -> None:
        """Build Plan step 15: a duplicate/out-of-order revision must not
        silently overwrite — it raises RevisionConflict so the caller retries.
        """
        self.store.save_project(make_project())
        self.store.append_blueprint(_make_blueprint("p1", revision=1))
        with self.assertRaises(storage.RevisionConflict):
            self.store.append_blueprint(_make_blueprint("p1", revision=1))
        # A skipped number is out of sequence too, not just an exact repeat.
        with self.assertRaises(storage.RevisionConflict):
            self.store.append_blueprint(_make_blueprint("p1", revision=3))
        # The list is unaffected by the rejected appends.
        self.assertEqual([bp.revision for bp in self.store.list_blueprints("p1")], [1])

    def test_live_revision_defaults_to_none_and_roundtrips(self) -> None:
        self.store.save_project(make_project())
        self.assertIsNone(self.store.get_live_revision("p1"))
        self.assertTrue(self.store.set_live_revision("p1", None, 1))
        self.assertEqual(self.store.get_live_revision("p1"), 1)

    def test_set_live_revision_with_wrong_expected_returns_false(self) -> None:
        """Build Plan step 15: a compare-and-set against a stale `expected`
        value must fail closed (return False), not raise and not apply.
        """
        self.store.save_project(make_project())
        self.assertTrue(self.store.set_live_revision("p1", None, 1))
        self.assertFalse(self.store.set_live_revision("p1", 0, 2))
        self.assertFalse(self.store.set_live_revision("p1", None, 2))
        # The pointer must be unchanged by the rejected attempts.
        self.assertEqual(self.store.get_live_revision("p1"), 1)

    def test_live_revision_survives_reload(self) -> None:
        self.store.save_project(make_project())
        self.store.set_live_revision("p1", None, 1)
        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertEqual(reloaded.get_live_revision("p1"), 1)

    def test_old_snapshot_without_live_revisions_field_loads_cleanly(self) -> None:
        """A state file written before this field existed must still load,
        with the pointer defaulting to unset rather than failing to load."""
        self.store.save_project(make_project())
        raw = json.loads(self._state.read_text("utf-8"))
        del raw["live_revisions"]
        self._state.write_text(json.dumps(raw), encoding="utf-8")

        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertIsNotNone(reloaded.get_project("p1"))
        self.assertIsNone(reloaded.get_live_revision("p1"))

    def test_job_and_upload_records_survive_reload(self) -> None:
        self.store.save_project(make_project())
        job = main.ReconstructionJob(
            job_id="j1",
            status=main.JobStatus.QUEUED,
            poll_url="/v1/reconstructions/j1",
            created_at=main.utc_now(),
            updated_at=main.utc_now(),
            project_id="p1",
            kind="segment",
        )
        self.store.save_job(job)
        self.store.link_asset("p1", "a1")
        upload = main.UploadRecord(
            upload_id="u1",
            project_id="p1",
            uploader_user_id="dev-user",
            image_key="uploads/p1/u1/source.png",
            width=10,
            height=10,
            created_at=main.utc_now(),
        )
        self.store.save_upload_record(upload)

        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertEqual(reloaded.get_job("j1").job_id, "j1")
        self.assertEqual(reloaded.list_linked_asset_ids("p1"), ["a1"])
        self.assertEqual(reloaded.get_upload_record("p1", "u1").upload_id, "u1")

    def test_claim_next_job_is_oldest_queued_first_and_filters_kind(self) -> None:
        now = main.utc_now()
        older = main.ReconstructionJob(
            job_id="older", status=main.JobStatus.QUEUED, poll_url="/x",
            created_at=now, updated_at=now, project_id="p1", kind="segment",
        )
        newer = main.ReconstructionJob(
            job_id="newer", status=main.JobStatus.QUEUED, poll_url="/x",
            created_at=now + timedelta(seconds=1),
            updated_at=now, project_id="p1", kind="segment",
        )
        wrong_kind = main.ReconstructionJob(
            job_id="wrong", status=main.JobStatus.QUEUED, poll_url="/x",
            created_at=now, updated_at=now, project_id="p1", kind="reconstruct",
        )
        for job in (newer, older, wrong_kind):
            self.store.save_job(job)

        claimed = self.store.claim_next_job("worker-1", ["segment"], lease_seconds=60)
        self.assertEqual(claimed.job_id, "older")
        self.assertEqual(claimed.status, "running")
        self.assertEqual(claimed.lease_owner, "worker-1")

    def test_release_expired_leases_requeues_then_fails_after_max_attempts(self) -> None:
        os.environ["SKETCHSCAPE_JOB_MAX_ATTEMPTS"] = "2"
        try:
            now = main.utc_now()
            job = main.ReconstructionJob(
                job_id="lease-test", status=main.JobStatus.RUNNING, poll_url="/x",
                created_at=now, updated_at=now, project_id="p1", kind="segment",
                lease_owner="worker-1",
                lease_expires_at=now - timedelta(seconds=1),
                attempts=0,
            )
            self.store.save_job(job)
            released = self.store.release_expired_leases()
            self.assertEqual(released, 1)
            requeued = self.store.get_job("lease-test")
            self.assertEqual(requeued.status, "queued")
            self.assertIsNone(requeued.lease_owner)
            self.assertEqual(requeued.attempts, 1)

            requeued.status = main.JobStatus.RUNNING
            requeued.lease_owner = "worker-2"
            requeued.lease_expires_at = now - timedelta(seconds=1)
            self.store.save_job(requeued)
            released_again = self.store.release_expired_leases()
            self.assertEqual(released_again, 1)
            failed = self.store.get_job("lease-test")
            self.assertEqual(failed.status, "failed")
        finally:
            del os.environ["SKETCHSCAPE_JOB_MAX_ATTEMPTS"]


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

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB conditional-write test needs botocore's ClientError.")
    def test_duplicate_append_blueprint_raises_revision_conflict(self) -> None:
        """Build Plan step 15: the DynamoDB ConditionExpression on `sk` must
        reject a second writer landing the same revision, as RevisionConflict
        — not silently overwrite it with `put_item`.
        """
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())
        store.append_blueprint(_make_blueprint("p1", revision=1))
        with self.assertRaises(storage.RevisionConflict):
            store.append_blueprint(_make_blueprint("p1", revision=1))
        # The original write must be intact.
        self.assertEqual([bp.revision for bp in store.list_blueprints("p1")], [1])

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB conditional-write test needs botocore's ClientError.")
    def test_append_publication_retries_past_a_conflicting_sequence_slot(self) -> None:
        """A racing writer that already grabbed the next sequence slot must not
        stop this append — publications are append-only, so retrying with the
        next number is always correct.
        """
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())
        # Simulate another instance already having written PUBLICATION#1.
        store._table.put_item(
            Item={
                "pk": "PROJECT#p1",
                "sk": storage.DynamoDbStore._seq_key("PUBLICATION", 1),
                "document": main.PublicationRecord(
                    project_id="p1", revision=1, published_at=main.utc_now()
                ).model_dump_json(),
            }
        )
        store.append_publication(
            main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now())
        )
        published = [rec.revision for rec in store.list_publications("p1")]
        self.assertEqual(published, [1, 1])

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB conditional-write test needs botocore's ClientError.")
    def test_live_revision_compare_and_set_against_fake_table(self) -> None:
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())

        self.assertIsNone(store.get_live_revision("p1"))
        self.assertTrue(store.set_live_revision("p1", None, 1))
        self.assertEqual(store.get_live_revision("p1"), 1)

        # A stale `expected` must fail closed, not raise, and not apply.
        self.assertFalse(store.set_live_revision("p1", 0, 2))
        self.assertEqual(store.get_live_revision("p1"), 1)

        self.assertTrue(store.set_live_revision("p1", 1, 2))
        self.assertEqual(store.get_live_revision("p1"), 2)

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB CRUD test needs boto3 conditions helpers.")
    def test_missing_gsi_refuses_to_start(self) -> None:
        store = storage.DynamoDbStore("fake")

        class _Client:
            def describe_table(self, TableName: str) -> dict:  # noqa: N803
                return {"Table": {"GlobalSecondaryIndexes": []}}

        class _Table:
            class meta:  # noqa: N801 - mirrors boto3's Table.meta.client shape
                client = _Client()

        store._table = _Table()
        with self.assertRaises(RuntimeError) as ctx:
            store._check_required_indexes()
        self.assertIn("gsi1", str(ctx.exception))
        self.assertIn("gsi2", str(ctx.exception))

    @unittest.skipUnless(_HAS_BOTO3, "DynamoDB CRUD test needs boto3 conditions helpers.")
    def test_job_lifecycle_against_fake_table(self) -> None:
        store = storage.DynamoDbStore("fake")
        store._table = _FakeTable()
        store.save_project(make_project())

        job = make_job(job_id="j1", project_id="p1", kind="segment")
        store.save_job(job)
        self.assertEqual(store.get_job("j1").job_id, "j1")

        other = make_job(job_id="j2", project_id="p1", kind="reconstruct")
        store.save_job(other)
        project_jobs = [j.job_id for j in store.list_project_jobs("p1")]
        self.assertEqual(set(project_jobs), {"j1", "j2"})

        claimed = store.claim_next_job("worker-1", ["segment"], lease_seconds=60)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.job_id, "j1")
        self.assertEqual(claimed.status, "running")

        # A second worker asking for the same kind finds nothing left queued.
        self.assertIsNone(store.claim_next_job("worker-2", ["segment"], lease_seconds=60))

        self.assertTrue(store.renew_lease("j1", "worker-1", lease_seconds=120))
        self.assertFalse(store.renew_lease("j1", "worker-2", lease_seconds=120))

        self.assertFalse(store.complete_job("j1", "worker-2", {"status": main.JobStatus.COMPLETE}))
        self.assertTrue(store.complete_job("j1", "worker-1", {"status": main.JobStatus.COMPLETE}))
        self.assertEqual(store.get_job("j1").status, "complete")

        store.link_asset("p1", "asset-a")
        store.link_asset("p1", "asset-a")  # idempotent
        store.link_asset("p1", "asset-b")
        self.assertEqual(set(store.list_linked_asset_ids("p1")), {"asset-a", "asset-b"})

        upload = make_upload_record(upload_id="u1", project_id="p1")
        store.save_upload_record(upload)
        self.assertEqual(store.get_upload_record("p1", "u1").upload_id, "u1")
        self.assertEqual(len(store.list_upload_records("p1")), 1)


def make_job(
    job_id: str = "job1",
    project_id: str | None = "p1",
    kind: "main.JobKind" = "reconstruct",
    status: "main.JobStatus" = None,
) -> "main.ReconstructionJob":
    now = main.utc_now()
    return main.ReconstructionJob(
        job_id=job_id,
        status=status if status is not None else main.JobStatus.QUEUED,
        poll_url=f"/v1/reconstructions/{job_id}",
        created_at=now,
        updated_at=now,
        project_id=project_id,
        kind=kind,
    )


def make_upload_record(
    upload_id: str = "u1", project_id: str = "p1", uploader_user_id: str = "dev-user"
) -> "main.UploadRecord":
    return main.UploadRecord(
        upload_id=upload_id,
        project_id=project_id,
        uploader_user_id=uploader_user_id,
        image_key=f"uploads/{project_id}/{upload_id}/source.png",
        width=100,
        height=100,
        created_at=main.utc_now(),
    )


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

    It supports only the operations DynamoDbStore uses: get_item, put_item
    (with a ``ConditionExpression`` for the step-15 conditional writes), and a
    begins_with/eq Query with ScanIndexForward. Keys are (pk, sk) tuples.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict] = {}

    def get_item(self, Key: dict) -> dict:  # noqa: N803 - boto3 API name
        item = self._items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def put_item(  # noqa: N803 - boto3 API names
        self,
        Item: dict,
        ConditionExpression: str | None = None,
        ExpressionAttributeNames: dict | None = None,
        ExpressionAttributeValues: dict | None = None,
    ) -> None:
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None:
            existing = self._items.get(key)
            if not self._condition_holds(
                ConditionExpression,
                ExpressionAttributeNames or {},
                ExpressionAttributeValues or {},
                existing,
            ):
                from botocore.exceptions import ClientError  # noqa: PLC0415

                raise ClientError(
                    {
                        "Error": {
                            "Code": "ConditionalCheckFailedException",
                            "Message": "The conditional request failed",
                        }
                    },
                    "PutItem",
                )
        self._items[key] = dict(Item)

    @staticmethod
    def _condition_holds(
        expression: str, names: dict, values: dict, existing: dict | None
    ) -> bool:
        """Evaluate the small subset of DynamoDB condition expressions that
        ``DynamoDbStore`` actually issues: ``attribute_not_exists(x)``,
        optionally OR'd with an equality check such as ``#r = :expected``.
        """
        for clause in (part.strip() for part in expression.split(" OR ")):
            if re.fullmatch(r"attribute_not_exists\(\w+\)", clause):
                if existing is None:
                    return True
                continue
            match = re.fullmatch(r"(\S+)\s*=\s*(\S+)", clause)
            if match and existing is not None:
                attr = names.get(match.group(1), match.group(1))
                expected = values.get(match.group(2), match.group(2))
                if existing.get(attr) == expected:
                    return True
        return False

    def query(self, IndexName: str | None = None, **kwargs) -> dict:  # noqa: N803 - boto3 API name
        # DynamoDbStore builds the condition with boto3's Key helper; rather
        # than parse it, re-derive the attribute-name-aware pk/sk-prefix filter
        # it always uses. Attribute names come straight from the condition
        # (Key("gsi1pk") etc.), so this works the same for the table's own
        # pk/sk and for a GSI's gsi1pk/gsi1sk or gsi2pk/gsi2sk. `IndexName` is
        # accepted (matching the real boto3 signature) but unused: this fake
        # table has no separate index storage, so attribute-based filtering
        # alone is enough to emulate one.
        condition = kwargs["KeyConditionExpression"]
        pk_attr, pk_value, sk_attr, sk_prefix = _extract_pk_and_prefix(condition)
        matches = [
            item
            for item in self._items.values()
            if item.get(pk_attr) == pk_value
            and (sk_attr is None or str(item.get(sk_attr, "")).startswith(sk_prefix))
        ]
        # Ordering follows the queried index's own sort key (gsi1sk/gsi2sk),
        # not necessarily the attribute named in the KeyConditionExpression --
        # a GSI2 claim query has no sort-key condition at all but must still
        # come back oldest-first.
        sort_attr = f"{IndexName}sk" if IndexName else (sk_attr or "sk")
        matches.sort(key=lambda item: item.get(sort_attr, ""))
        if not kwargs.get("ScanIndexForward", True):
            matches.reverse()
        return {"Items": matches}


def _extract_pk_and_prefix(condition) -> tuple[str, str, str | None, str]:
    """Pull the (pk attr, pk value, sk attr, sk prefix) out of a boto3 condition.

    Handles a lone ``Key(x).eq(v)`` (e.g. a GSI2 claim query with no sort-key
    condition) as well as an ``And`` of an equality and a ``begins_with``.
    """
    from boto3.dynamodb.conditions import And, BeginsWith, Equals  # noqa: PLC0415

    pk_attr, pk_value = "pk", ""
    sk_attr: str | None = None
    sk_prefix = ""
    parts = condition._values if isinstance(condition, And) else [condition]
    for part in parts:
        values = part._values
        attr, operand = values[0], values[1]
        if isinstance(part, Equals):
            pk_attr, pk_value = attr.name, operand
        elif isinstance(part, BeginsWith):
            sk_attr, sk_prefix = attr.name, operand
    return pk_attr, pk_value, sk_attr, sk_prefix


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

    def test_put_upload_roundtrips_by_key(self) -> None:
        key = _run(
            self.store.put_upload(
                "proj1", "up1", "source.png", _upload_file(b"PNGDATA", "source.png"), size_limit=1024
            )
        )
        self.assertEqual(key, "uploads/proj1/up1/source.png")
        self.assertEqual(self.store.open_upload(key), b"PNGDATA")

    def test_open_upload_missing_raises_404(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            self.store.open_upload("uploads/proj1/nope/source.png")
        self.assertEqual(ctx.exception.status_code, 404)


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

    @unittest.skipUnless(_HAS_BOTO3, "S3 CRUD test needs boto3.")
    def test_put_upload_and_open_upload_against_fake_s3(self) -> None:
        store = S3ArtifactStore("fake-bucket")
        store._client = _FakeS3Client()

        key = _run(
            store.put_upload(
                "proj1", "up1", "source.png", _upload_file(b"PNGDATA", "source.png"), size_limit=1024
            )
        )
        self.assertEqual(key, "uploads/proj1/up1/source.png")
        self.assertEqual(store.open_upload(key), b"PNGDATA")


class _FakeS3Client:
    """Minimal in-memory stand-in for a boto3 S3 client.

    Supports only the operations S3ArtifactStore uses: upload_file,
    head_object, get_object, and generate_presigned_url.
    """

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], bytes] = {}

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs) -> None:
        self._objects[(bucket, key)] = Path(filename).read_bytes()

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if (Bucket, Key) not in self._objects:
            raise Exception("NoSuchKey")
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        try:
            data = self._objects[(Bucket, Key)]
        except KeyError as error:
            raise Exception("NoSuchKey") from error
        return {"Body": io.BytesIO(data)}

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int = 300
    ) -> str:  # noqa: N803
        key = Params.get("Key", "")
        return f"https://fake-bucket.s3.amazonaws.com/{key}?presigned=1"


if __name__ == "__main__":
    unittest.main()
