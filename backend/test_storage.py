"""Storage-layer contract tests.

These exercise the backend-selection factory and each store's contract
without requiring real AWS. DynamoDB and S3 are exercised against `moto`'s
in-memory AWS emulation (``mock_aws``) rather than hand-rolled fakes, so the
tests observe real boto3/botocore behavior -- actual `ConditionExpression`
evaluation, real GSI `Query` semantics, and real pagination
(`LastEvaluatedKey`) -- while never making a network call or touching a real
account. Tests that need `moto` (and `boto3`) are skipped when either is
absent from the environment; run with `python -m unittest test_storage.py`.

``StorageContractMixin`` holds the backend-agnostic tests and is run against
both ``LocalJsonStore`` and a moto-backed ``DynamoDbStore`` so the two
backends are proven structurally identical, per AuthoringStore's contract.
"""

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name
# moto's mock_aws still routes through boto3's credential resolution chain;
# without these, a machine with no ~/.aws/credentials can fail before moto
# ever intercepts the call. These are well-known fake values, not secrets.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import main  # noqa: E402
import storage  # noqa: E402

_HAS_BOTO3 = importlib.util.find_spec("boto3") is not None
_HAS_MOTO = importlib.util.find_spec("moto") is not None
_HAS_AWS_MOCKS = _HAS_BOTO3 and _HAS_MOTO

if _HAS_AWS_MOCKS:
    from moto import mock_aws  # noqa: E402


_TEST_REGION = "us-east-1"
_TEST_TABLE_NAME = "sketchscape-authoring-test"


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


def _make_blueprint(project_id: str, revision: int, based_on_revision: int | None = None) -> "main.ExperienceBlueprint":
    return main.ExperienceBlueprint(
        project_id=project_id,
        revision=revision,
        created_at=main.utc_now(),
        based_on_revision=based_on_revision,
        experience=main.ExperienceSettings(mode="desktop", theme="t", units="meters"),
        objects=[
            main.BlueprintObject(id="o1", asset_id="a1", position=[0, 0, 0])
        ],
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


# ---------------------------------------------------------------------------
# Shared AuthoringStore contract -- run against every backend.
#
# Every method here uses only the abstract AuthoringStore surface (never a
# backend-specific attribute), so the exact same test bodies prove
# LocalJsonStore and DynamoDbStore behave identically -- the property the
# contributor-data-model and durable-jobs skills both require ("mock mode and
# cloud mode are structurally identical").
# ---------------------------------------------------------------------------


class StorageContractMixin:
    """Mixin of backend-agnostic ``AuthoringStore`` tests.

    Concrete subclasses provide ``self.store`` in ``setUp`` and mix this in
    alongside ``unittest.TestCase``.
    """

    store: "storage.AuthoringStore"

    def test_project_and_asset_roundtrip(self) -> None:
        self.store.save_project(make_project())
        self.store.save_asset(make_asset())
        self.assertEqual(self.store.get_project("p1").project_id, "p1")
        self.assertEqual(self.store.get_asset("a1").asset_id, "a1")
        self.assertIsNone(self.store.get_project("missing"))

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

    def test_connection_insight_revisions_are_ordered(self) -> None:
        """Insights are revisioned like blueprints (append-only, in order)."""
        self.store.save_project(make_project())
        self.store.append_connection_insight(make_connection_insight(revision=1))
        self.store.append_connection_insight(make_connection_insight(revision=2))
        insights = [insight.revision for insight in self.store.list_connection_insights("p1")]
        self.assertEqual(insights, [1, 2])

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

    def test_contributions_are_queryable_per_project_and_filterable_per_user(self) -> None:
        """Both hardcoded demo accounts' contributions in one project: list by
        project (the only index either backend needs), then filter by the
        contributor's bound account id -- exactly what main.py's route
        handlers do (see ``owned_object_ids``)."""
        self.store.save_project(make_project())
        for asset_id in ("a1", "a2"):
            self.store.save_asset(make_asset(asset_id=asset_id))
        self.store.append_contributor(
            make_contributor(contributor_id="c-alice", display_name="Alice")
        )
        # Bind a second contributor to the second hardcoded demo account.
        alice_bound = main.Contributor(
            contributor_id="c-alice", project_id="p1", display_name="Alice",
            joined_at=main.utc_now(), clerk_user_id="demo-account-1",
        )
        bob_bound = main.Contributor(
            contributor_id="c-bob", project_id="p1", display_name="Bob",
            joined_at=main.utc_now(), clerk_user_id="demo-account-2",
        )
        self.store.append_contributor(alice_bound)
        self.store.append_contributor(bob_bound)
        self.store.append_contribution(
            make_contribution(contribution_id="ctr-a", contributor_id="c-alice", asset_id="a1")
        )
        self.store.append_contribution(
            make_contribution(contribution_id="ctr-b", contributor_id="c-bob", asset_id="a2")
        )

        contributions = self.store.list_contributions("p1")
        contributors_by_id = {c.contributor_id: c for c in self.store.list_contributors("p1")}
        bob_contributions = [
            c for c in contributions
            if contributors_by_id[c.contributor_id].clerk_user_id == "demo-account-2"
        ]
        self.assertEqual([c.contribution_id for c in bob_contributions], ["ctr-b"])

    def test_append_blueprint_then_duplicate_raises_revision_conflict(self) -> None:
        """Build Plan step 15: a duplicate revision must not silently
        overwrite -- it raises RevisionConflict so the caller retries."""
        self.store.save_project(make_project())
        self.store.append_blueprint(_make_blueprint("p1", revision=1))
        with self.assertRaises(storage.RevisionConflict):
            self.store.append_blueprint(_make_blueprint("p1", revision=1))
        self.assertEqual([bp.revision for bp in self.store.list_blueprints("p1")], [1])

    def test_blueprints_and_publications_are_ordered(self) -> None:
        self.store.save_project(make_project())
        self.store.append_blueprint(_make_blueprint("p1", revision=1))
        self.store.append_blueprint(_make_blueprint("p1", revision=2))
        self.assertEqual([bp.revision for bp in self.store.list_blueprints("p1")], [1, 2])

        self.store.append_publication(main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now()))
        self.store.append_publication(main.PublicationRecord(project_id="p1", revision=2, published_at=main.utc_now()))
        self.store.append_publication(main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now()))
        self.assertEqual([rec.revision for rec in self.store.list_publications("p1")], [1, 2, 1])

    def test_live_revision_defaults_to_none_and_roundtrips(self) -> None:
        self.store.save_project(make_project())
        self.assertIsNone(self.store.get_live_revision("p1"))
        self.assertTrue(self.store.set_live_revision("p1", None, 1))
        self.assertEqual(self.store.get_live_revision("p1"), 1)

    def test_set_live_revision_with_wrong_expected_returns_false(self) -> None:
        """Build Plan step 15: a compare-and-set against a stale `expected`
        value must fail closed (return False), not raise and not apply."""
        self.store.save_project(make_project())
        self.assertTrue(self.store.set_live_revision("p1", None, 1))
        self.assertFalse(self.store.set_live_revision("p1", 0, 2))
        self.assertFalse(self.store.set_live_revision("p1", None, 2))
        self.assertEqual(self.store.get_live_revision("p1"), 1)

        self.assertTrue(self.store.set_live_revision("p1", 1, 2))
        self.assertEqual(self.store.get_live_revision("p1"), 2)

    def test_job_lifecycle_round_trip(self) -> None:
        self.store.save_project(make_project())

        job = make_job(job_id="j1", project_id="p1", kind="segment")
        self.store.save_job(job)
        self.assertEqual(self.store.get_job("j1").job_id, "j1")

        other = make_job(job_id="j2", project_id="p1", kind="reconstruct")
        self.store.save_job(other)
        project_jobs = [j.job_id for j in self.store.list_project_jobs("p1")]
        self.assertEqual(set(project_jobs), {"j1", "j2"})

        claimed = self.store.claim_next_job("worker-1", ["segment"], lease_seconds=60)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.job_id, "j1")
        self.assertEqual(claimed.status, "running")

        # A second worker asking for the same kind finds nothing left queued.
        self.assertIsNone(self.store.claim_next_job("worker-2", ["segment"], lease_seconds=60))

        self.assertTrue(self.store.renew_lease("j1", "worker-1", lease_seconds=120))
        self.assertFalse(self.store.renew_lease("j1", "worker-2", lease_seconds=120))

        self.assertFalse(self.store.complete_job("j1", "worker-2", {"status": main.JobStatus.COMPLETE}))
        self.assertTrue(self.store.complete_job("j1", "worker-1", {"status": main.JobStatus.COMPLETE}))
        self.assertEqual(self.store.get_job("j1").status, "complete")

        self.store.link_asset("p1", "asset-a")
        self.store.link_asset("p1", "asset-a")  # idempotent
        self.store.link_asset("p1", "asset-b")
        self.assertEqual(set(self.store.list_linked_asset_ids("p1")), {"asset-a", "asset-b"})

        upload = make_upload_record(upload_id="u1", project_id="p1")
        self.store.save_upload_record(upload)
        self.assertEqual(self.store.get_upload_record("p1", "u1").upload_id, "u1")
        self.assertEqual(len(self.store.list_upload_records("p1")), 1)

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

    def test_upload_records_are_queryable_per_project_and_filterable_per_user(self) -> None:
        """Both hardcoded demo accounts' uploads in one project: list by
        project, then filter by ``uploader_user_id`` -- the same pattern as
        contributions above."""
        self.store.save_project(make_project())
        self.store.save_upload_record(make_upload_record(upload_id="u1", uploader_user_id="demo-account-1"))
        self.store.save_upload_record(make_upload_record(upload_id="u2", uploader_user_id="demo-account-2"))

        uploads = self.store.list_upload_records("p1")
        self.assertEqual(len(uploads), 2)
        account_2_uploads = [u for u in uploads if u.uploader_user_id == "demo-account-2"]
        self.assertEqual([u.upload_id for u in account_2_uploads], ["u2"])


class LocalJsonStoreContractTests(StorageContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._state = Path(_temp_dir.name) / f"contract-{self.id().split('.')[-1]}.json"
        self._state.unlink(missing_ok=True)
        self.store = storage.LocalJsonStore(self._state)
        self.store.load()

    # -- LocalJsonStore-specific behavior (disk persistence) ----------------

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
        self.store.save_job(make_job(job_id="j1", project_id="p1", kind="segment"))
        self.store.link_asset("p1", "a1")
        self.store.save_upload_record(make_upload_record(upload_id="u1", project_id="p1"))

        reloaded = storage.LocalJsonStore(self._state)
        reloaded.load()
        self.assertEqual(reloaded.get_job("j1").job_id, "j1")
        self.assertEqual(reloaded.list_linked_asset_ids("p1"), ["a1"])
        self.assertEqual(reloaded.get_upload_record("p1", "u1").upload_id, "u1")


# ---------------------------------------------------------------------------
# DynamoDB: unit-level tests that don't need a real (or moto) table.
# ---------------------------------------------------------------------------


class DynamoDbStoreUnitTests(unittest.TestCase):
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

    @unittest.skipUnless(_HAS_BOTO3, "needs boto3's describe_table response shape.")
    def test_missing_gsi_refuses_to_start(self) -> None:
        """Unit-level version of the check, without a real/moto table: proves
        the parsing of describe_table's response, independent of moto."""
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


# ---------------------------------------------------------------------------
# DynamoDB: real (moto-mocked) table, matching infra/aws/main.tf exactly.
# ---------------------------------------------------------------------------


def _create_moto_authoring_table(table_name: str = _TEST_TABLE_NAME, *, with_gsis: bool = True):
    """Create a table with the same pk/sk + GSI1/GSI2 shape as
    ``infra/aws/main.tf``'s ``aws_dynamodb_table.authoring`` resource, inside
    an active moto ``mock_aws`` context. Keeping this in one place means the
    test schema can't silently drift from what Terraform actually declares.
    """
    import boto3  # noqa: PLC0415

    attribute_definitions = [
        {"AttributeName": "pk", "AttributeType": "S"},
        {"AttributeName": "sk", "AttributeType": "S"},
    ]
    kwargs: dict = {
        "TableName": table_name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    }
    if with_gsis:
        attribute_definitions += [
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "gsi1sk", "AttributeType": "S"},
            {"AttributeName": "gsi2pk", "AttributeType": "S"},
            {"AttributeName": "gsi2sk", "AttributeType": "S"},
        ]
        kwargs["GlobalSecondaryIndexes"] = [
            {
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "gsi2",
                "KeySchema": [
                    {"AttributeName": "gsi2pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi2sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ]
    kwargs["AttributeDefinitions"] = attribute_definitions
    dynamodb = boto3.resource("dynamodb", region_name=_TEST_REGION)
    table = dynamodb.create_table(**kwargs)
    table.wait_until_exists()
    return table


class _ForcedPageSizeTable:
    """Wraps a real (moto-mocked) boto3 ``Table`` and forces ``Limit=1`` on
    every ``Query`` unless the caller already set one.

    A hermetic test can't make a real DynamoDB response exceed a 1 MB page
    (that would need thousands of items), so without this, the pagination
    loop in ``DynamoDbStore._query_index``/``_query_children`` never actually
    pages during a test even if the loop itself were missing entirely. This
    forces genuine multi-page traversal at trivial item counts, so a
    regression in the ``LastEvaluatedKey`` loop shows up as a failed
    assertion instead of silently passing.
    """

    def __init__(self, table) -> None:
        self._table = table

    def query(self, **kwargs):
        kwargs.setdefault("Limit", 1)
        return self._table.query(**kwargs)

    def __getattr__(self, name):
        return getattr(self._table, name)


@unittest.skipUnless(_HAS_AWS_MOCKS, "needs both boto3 and moto for a mocked DynamoDB table.")
class DynamoDbStoreContractTests(StorageContractMixin, unittest.TestCase):
    """Runs the exact same contract tests as LocalJsonStoreContractTests
    against a moto-mocked table shaped like the real Terraform resource."""

    def setUp(self) -> None:
        self._mock = mock_aws()
        self._mock.start()
        _create_moto_authoring_table()
        self.store = storage.DynamoDbStore(_TEST_TABLE_NAME, region_name=_TEST_REGION)
        self.store.load()  # exercises the real _check_required_indexes() path too.

    def tearDown(self) -> None:
        self._mock.stop()

    # -- DynamoDB-specific behavior not shared with LocalJsonStore ----------

    def test_missing_gsi_refuses_to_start_against_real_table(self) -> None:
        """End-to-end proof that a table provisioned without GSI1/GSI2 (i.e.
        the Terraform change in DATA_ARCHITECTURE.md not yet applied) is
        refused, using a real describe_table response instead of a stub."""
        self._mock.stop()
        self._mock = mock_aws()
        self._mock.start()
        _create_moto_authoring_table("no-gsi-table", with_gsis=False)
        store = storage.DynamoDbStore("no-gsi-table", region_name=_TEST_REGION)
        with self.assertRaises(RuntimeError) as ctx:
            store.load()
        self.assertIn("gsi1", str(ctx.exception))
        self.assertIn("gsi2", str(ctx.exception))

    def test_duplicate_append_blueprint_rejected_by_real_condition_expression(self) -> None:
        """The DynamoDB `ConditionExpression` on `sk` must reject a second
        writer landing the same revision -- not silently overwrite it."""
        self.store.save_project(make_project())
        self.store.append_blueprint(_make_blueprint("p1", revision=1))
        with self.assertRaises(storage.RevisionConflict):
            self.store.append_blueprint(_make_blueprint("p1", revision=1))
        self.assertEqual([bp.revision for bp in self.store.list_blueprints("p1")], [1])

    def test_append_publication_retries_past_a_conflicting_sequence_slot(self) -> None:
        """A racing writer that already grabbed the next sequence slot must
        not stop this append -- publications are append-only, so retrying
        with the next number is always correct."""
        self.store.save_project(make_project())
        # Simulate another instance already having written PUBLICATION#1.
        self.store._table.put_item(
            Item={
                "pk": "PROJECT#p1",
                "sk": storage.DynamoDbStore._seq_key("PUBLICATION", 1),
                "document": main.PublicationRecord(
                    project_id="p1", revision=1, published_at=main.utc_now()
                ).model_dump_json(),
            }
        )
        self.store.append_publication(
            main.PublicationRecord(project_id="p1", revision=1, published_at=main.utc_now())
        )
        published = [rec.revision for rec in self.store.list_publications("p1")]
        self.assertEqual(published, [1, 1])

    def test_list_project_jobs_paginates_beyond_one_page(self) -> None:
        """A project with more jobs than fit on one Query page must still
        return all of them (storage.DynamoDbStore._query_index's loop)."""
        self.store.save_project(make_project())
        for index in range(5):
            self.store.save_job(make_job(job_id=f"job-{index}", project_id="p1", kind="segment"))
        self.store._table = _ForcedPageSizeTable(self.store._table)

        jobs = self.store.list_project_jobs("p1")
        self.assertEqual({j.job_id for j in jobs}, {f"job-{i}" for i in range(5)})

    def test_claim_next_job_finds_job_beyond_first_page(self) -> None:
        """The only matching-kind job sits behind several wrong-kind queued
        jobs; claim_next_job must keep paging until it finds it, not give up
        after the first (forced-to-size-1) page."""
        self.store.save_project(make_project())
        for index in range(4):
            self.store.save_job(make_job(job_id=f"wrong-{index}", project_id="p1", kind="segment"))
        self.store.save_job(make_job(job_id="right", project_id="p1", kind="reconstruct"))
        self.store._table = _ForcedPageSizeTable(self.store._table)

        claimed = self.store.claim_next_job("worker-1", ["reconstruct"], lease_seconds=60)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.job_id, "right")

    def test_release_expired_leases_paginates_beyond_one_page(self) -> None:
        self.store.save_project(make_project())
        now = main.utc_now()
        for index in range(4):
            job = main.ReconstructionJob(
                job_id=f"lease-{index}", status=main.JobStatus.RUNNING, poll_url="/x",
                created_at=now, updated_at=now, project_id="p1", kind="segment",
                lease_owner="worker-1", lease_expires_at=now - timedelta(seconds=1), attempts=0,
            )
            self.store.save_job(job)
        self.store._table = _ForcedPageSizeTable(self.store._table)

        released = self.store.release_expired_leases()
        self.assertEqual(released, 4)
        for index in range(4):
            self.assertEqual(self.store.get_job(f"lease-{index}").status, "queued")


# ---------------------------------------------------------------------------
# Artifact store tests
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import io  # noqa: E402
import shutil  # noqa: E402

from artifact_store import (  # noqa: E402
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
    create_artifact_store,
)
from fastapi import UploadFile  # noqa: E402


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


class ArtifactStoreContractMixin:
    """Backend-agnostic ``ArtifactStore`` tests. Concrete subclasses provide
    ``self.store`` in ``setUp``."""

    store: "ArtifactStore"

    def test_put_returns_canonical_url(self) -> None:
        url = _run(
            self.store.put("j1", "out.ply", _upload_file(b"PLYDATA"), size_limit=1024)
        )
        self.assertEqual(url, "/v1/artifacts/j1/out.ply")

    def test_exists_true_after_put_false_before(self) -> None:
        self.assertFalse(self.store.exists("j3", "nope.ply"))
        _run(self.store.put("j3", "a.ply", _upload_file(b"X"), size_limit=1024))
        self.assertTrue(self.store.exists("j3", "a.ply"))

    def test_copy_local_roundtrips(self) -> None:
        src = Path(_temp_dir.name) / f"source-{id(self)}.ply"
        src.write_bytes(b"LOCALPLY")
        url = _run(self.store.copy_local("j4", "copy.ply", src))
        self.assertEqual(url, "/v1/artifacts/j4/copy.ply")

    def test_put_rejects_oversized_upload(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            _run(self.store.put("j6", "big.ply", _upload_file(b"A" * 10), size_limit=5))
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


class LocalArtifactStoreTests(ArtifactStoreContractMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._root = Path(_temp_dir.name) / f"local-artifacts-{self.id().split('.')[-1]}"
        shutil.rmtree(self._root, ignore_errors=True)
        self.store = LocalArtifactStore(self._root)

    # -- local-specific behavior (disk layout) -------------------------------

    def test_put_writes_bytes_to_disk(self) -> None:
        _run(self.store.put("j2", "mask.png", _upload_file(b"\x89PNG"), size_limit=1024))
        self.assertEqual((self._root / "j2" / "mask.png").read_bytes(), b"\x89PNG")

    def test_copy_local_writes_bytes_to_disk(self) -> None:
        src = Path(_temp_dir.name) / "source.ply"
        src.write_bytes(b"LOCALPLY")
        _run(self.store.copy_local("j4", "copy.ply", src))
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

    def test_open_upload_missing_raises_404(self) -> None:
        from fastapi import HTTPException  # noqa: PLC0415

        with self.assertRaises(HTTPException) as ctx:
            self.store.open_upload("uploads/proj1/nope/source.png")
        self.assertEqual(ctx.exception.status_code, 404)


class S3ArtifactStoreUnitTests(unittest.TestCase):
    """Tests that don't need a real/moto bucket."""

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


_TEST_BUCKET_NAME = "sketchscape-artifacts-test"


@unittest.skipUnless(_HAS_AWS_MOCKS, "needs both boto3 and moto for a mocked S3 bucket.")
class S3ArtifactStoreContractTests(ArtifactStoreContractMixin, unittest.TestCase):
    """Runs the exact same contract tests as LocalArtifactStoreTests against
    a moto-mocked S3 bucket, so both ArtifactStore backends are proven
    structurally identical."""

    def setUp(self) -> None:
        import boto3  # noqa: PLC0415

        self._mock = mock_aws()
        self._mock.start()
        boto3.client("s3", region_name=_TEST_REGION).create_bucket(Bucket=_TEST_BUCKET_NAME)
        self.store = S3ArtifactStore(_TEST_BUCKET_NAME, region_name=_TEST_REGION)

    def tearDown(self) -> None:
        self._mock.stop()

    # -- S3-specific behavior ------------------------------------------------

    def test_serve_redirects_to_presigned_url_under_the_artifacts_prefix(self) -> None:
        _run(self.store.put("j1", "reconstruction.ply", _upload_file(b"PLYDATA"), size_limit=1024))
        response = _run(self.store.serve("j1", "reconstruction.ply"))
        self.assertEqual(response.status_code, 302)
        location = response.headers["location"]
        self.assertIn(_TEST_BUCKET_NAME, location)
        self.assertIn("artifacts/j1", location)

    def test_serve_streams_png_images_instead_of_redirecting(self) -> None:
        # Browsers can't follow the cross-origin S3 redirect with the auth
        # header (the bucket has no CORS), so masks/previews come back inline.
        _run(self.store.put("j1", "mask.png", _upload_file(b"PNGDATA", "mask.png"), size_limit=1024))
        response = _run(self.store.serve("j1", "mask.png"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.body, b"PNGDATA")
        self.assertEqual(response.media_type, "image/png")

    def test_put_upload_lands_under_the_uploads_prefix_not_artifacts(self) -> None:
        """Regression guard for the IAM-policy bug this task fixed in
        infra/aws/main.tf: uploads/ and artifacts/ are two distinct prefixes,
        and a policy scoped to only one of them would 403 the other in real
        S3 (moto does not enforce IAM, so this only checks the *key layout*,
        not the permission -- see infra/aws/main.tf's artifacts_bucket policy
        comment for the permission side)."""
        key = _run(
            self.store.put_upload(
                "proj1", "up1", "source.png", _upload_file(b"PNGDATA", "source.png"), size_limit=1024
            )
        )
        self.assertTrue(key.startswith("uploads/"))
        self.assertFalse(key.startswith("artifacts/"))


if __name__ == "__main__":
    unittest.main()
