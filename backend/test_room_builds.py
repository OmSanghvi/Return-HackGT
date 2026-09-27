"""Room builds and the headset's shared view (docs/WEB_TO_QUEST_PIPELINE.md 1, 1b).

Store contract tests run against LocalJsonStore and a moto-mocked
DynamoDbStore (same table shape as test_storage); API tests use the local
store through the real FastAPI app, in mock mode (the web app's offline mode)
and in demo mode (the two hardcoded accounts, where visibility matters).
Run with `python -m unittest test_room_builds.py`.
"""

import importlib.util
import io
import os
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import main  # noqa: E402
import storage  # noqa: E402

_HAS_AWS_MOCKS = importlib.util.find_spec("boto3") is not None and importlib.util.find_spec("moto") is not None
if _HAS_AWS_MOCKS:
    from moto import mock_aws  # noqa: E402

    from test_storage import _TEST_REGION, _TEST_TABLE_NAME, _create_moto_authoring_table  # noqa: E402

TOKEN = "room-runner-test-token-" + "y" * 24  # >= auth.MIN_NEMOCLAW_TOKEN_LENGTH
SERVICE = {"Authorization": f"Bearer {TOKEN}"}
ALICE = {"X-SketchScape-Dev-User": "demo-alice"}
BOB = {"X-SketchScape-Dev-User": "demo-bob"}


def _png(color=(200, 180, 150)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _build(project_id: str, created: datetime, status: str = "requested", runner_id: str = "") -> "main.RoomBuild":
    stamp = storage.iso_z(created)
    return main.RoomBuild(
        build_id=uuid.uuid4().hex,
        project_id=project_id,
        requested_by="demo-alice",
        scene_id="u1",
        status=status,
        runner_id=runner_id,
        created_at=stamp,
        updated_at=stamp,
    )


class RoomBuildStoreContract:
    """Backend-agnostic room-build store tests; subclasses set self.store."""

    def test_create_get_list_and_one_active_per_project(self) -> None:
        now = datetime.now(UTC)
        first = _build("p1", now - timedelta(minutes=5))
        self.store.create_room_build(first)
        self.assertEqual(self.store.get_room_build(first.build_id).status, "requested")
        self.assertEqual(self.store.get_room_build(first.build_id, "p1").build_id, first.build_id)
        self.assertIsNone(self.store.get_room_build("nope"))
        with self.assertRaises(storage.RoomBuildConflict) as ctx:
            self.store.create_room_build(_build("p1", now))
        self.assertEqual(ctx.exception.active.build_id, first.build_id)
        self.store.create_room_build(_build("p2", now))  # other projects are independent

        done = first.model_copy(update={"status": "failed", "updated_at": storage.iso_z(now)})
        self.assertTrue(
            self.store.update_room_build(
                done, expected_status="requested", expected_runner_id="", expected_updated_at=first.updated_at
            )
        )
        second = _build("p1", now)
        self.store.create_room_build(second)
        self.assertEqual([b.build_id for b in self.store.list_room_builds("p1")], [second.build_id, first.build_id])

    def test_claim_takes_oldest_requested_across_projects(self) -> None:
        now = datetime.now(UTC)
        newer = _build("p1", now - timedelta(minutes=1))
        older = _build("p2", now - timedelta(minutes=9))
        self.store.create_room_build(newer)
        self.store.create_room_build(older)
        claimed = self.store.claim_next_room_build("runner-a", now)
        self.assertEqual((claimed.build_id, claimed.status, claimed.runner_id), (older.build_id, "claimed", "runner-a"))
        self.assertEqual(self.store.get_room_build(older.build_id).status, "claimed")
        self.assertEqual(self.store.claim_next_room_build("runner-a", now).build_id, newer.build_id)
        self.assertIsNone(self.store.claim_next_room_build("runner-a", now))

    def test_update_is_compare_and_set(self) -> None:
        now = datetime.now(UTC)
        build = _build("p1", now)
        self.store.create_room_build(build)
        claimed = self.store.claim_next_room_build("runner-a", now)
        moved = claimed.model_copy(update={"status": "building", "updated_at": storage.iso_z(now + timedelta(seconds=1))})
        self.assertFalse(
            self.store.update_room_build(
                moved, expected_status="claimed", expected_runner_id="runner-b", expected_updated_at=claimed.updated_at
            )
        )
        self.assertTrue(
            self.store.update_room_build(
                moved, expected_status="claimed", expected_runner_id="runner-a", expected_updated_at=claimed.updated_at
            )
        )
        self.assertFalse(  # a second writer holding the old version loses
            self.store.update_room_build(
                moved, expected_status="claimed", expected_runner_id="runner-a", expected_updated_at=claimed.updated_at
            )
        )
        self.assertEqual(self.store.get_room_build(build.build_id).status, "building")

    def test_stale_leases_go_back_to_requested(self) -> None:
        now = datetime.now(UTC)
        stale = _build("p1", now - timedelta(hours=2), status="building", runner_id="runner-a")
        fresh = _build("p2", now - timedelta(minutes=5), status="syncing", runner_id="runner-b")
        waiting = _build("p3", now - timedelta(hours=3))
        for build in (stale, fresh, waiting):
            self.store.create_room_build(build)
        self.assertEqual(self.store.release_stale_room_builds(1800, now, project_id="p2"), 0)
        self.assertEqual(self.store.release_stale_room_builds(1800, now), 1)
        requeued = self.store.get_room_build(stale.build_id)
        self.assertEqual((requeued.status, requeued.runner_id), ("requested", "runner-a"))
        self.assertEqual(requeued.message, storage.ROOM_BUILD_REQUEUED_MESSAGE)
        self.assertEqual(self.store.get_room_build(fresh.build_id).status, "syncing")
        self.assertEqual(self.store.get_room_build(waiting.build_id).status, "requested")


class LocalRoomBuildStoreTests(RoomBuildStoreContract, unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = storage.LocalJsonStore(Path(self._dir.name) / "state.json")
        self.store.load()

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_room_builds_survive_a_reload(self) -> None:
        build = _build("p1", datetime.now(UTC))
        self.store.create_room_build(build)
        reloaded = storage.LocalJsonStore(Path(self._dir.name) / "state.json")
        reloaded.load()
        self.assertEqual(reloaded.get_room_build(build.build_id), build)


@unittest.skipUnless(_HAS_AWS_MOCKS, "needs boto3 and moto")
class DynamoDbRoomBuildStoreTests(RoomBuildStoreContract, unittest.TestCase):
    def setUp(self) -> None:
        self._mock = mock_aws()
        self._mock.start()
        _create_moto_authoring_table()
        self.store = storage.DynamoDbStore(_TEST_TABLE_NAME, region_name=_TEST_REGION)
        self.store.load()

    def tearDown(self) -> None:
        self._mock.stop()

    def test_claim_uses_the_status_index(self) -> None:
        build = _build("p9", datetime.now(UTC))
        self.store.create_room_build(build)
        table = self.store._require_table()
        item = table.get_item(Key={"pk": "PROJECT#p9", "sk": f"ROOMBUILD#{build.build_id}"})["Item"]
        self.assertEqual(item["gsi2pk"], "ROOMBUILDQ#requested")
        self.assertEqual(table.get_item(Key={"pk": f"ROOMBUILD#{build.build_id}", "sk": "META"})["Item"]["project_id"], "p9")
        self.store.claim_next_room_build("runner-a", datetime.now(UTC))
        item = table.get_item(Key={"pk": "PROJECT#p9", "sk": f"ROOMBUILD#{build.build_id}"})["Item"]
        self.assertEqual(item["gsi2pk"], "ROOMBUILDQ#claimed")


class _ApiCase(unittest.TestCase):
    MODE = "mock"

    def setUp(self) -> None:
        env = {"SKETCHSCAPE_NEMOCLAW_TOKEN": TOKEN}
        if self.MODE == "demo":
            env.update({"SKETCHSCAPE_AUTH_MODE": "demo", "SKETCHSCAPE_WEB_ORIGINS": "https://app.example.com"})
        else:
            env.update({"SKETCHSCAPE_AUTH_MODE": "mock"})
        self._patches = [
            patch.dict(os.environ, env),
            patch.object(main, "_ROOM_STATE_RATE_LIMIT_MAX_CALLS", 10_000),
        ]
        for item in self._patches:
            item.start()
        main.store.room_builds.clear()  # claim is global: no builds leak between tests
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for item in reversed(self._patches):
            item.stop()

    def _project(self, headers=ALICE, name="Cabin") -> str:
        response = self.client.post("/v1/projects", json={"name": name, "creator_display_name": "Alice"}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["project_id"]

    def _scene_upload(self, project_id: str, uploader: str, minutes_ago: float, with_scene: bool = True) -> str:
        upload_id = uuid.uuid4().hex
        main.store.save_upload_record(
            main.UploadRecord(
                upload_id=upload_id,
                project_id=project_id,
                uploader_user_id=uploader,
                image_key=f"uploads/{project_id}/{upload_id}/source.png",
                width=8,
                height=6,
                created_at=main.utc_now() - timedelta(minutes=minutes_ago),
                scene_key=f"artifacts/scenes/{upload_id}/scene.json" if with_scene else None,
            )
        )
        return upload_id


class RoomBuildApiTests(_ApiCase):
    def test_create_defaults_to_newest_scene_and_allows_one_active(self) -> None:
        pid = self._project()
        response = self.client.post(f"/v1/projects/{pid}/room-builds", json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("scene", response.json()["detail"])
        self._scene_upload(pid, "dev-user", 30)
        newest_scene = self._scene_upload(pid, "dev-user", 10)
        self._scene_upload(pid, "dev-user", 1, with_scene=False)
        response = self.client.post(f"/v1/projects/{pid}/room-builds", json={"prompt": "  cozy evening  "})
        self.assertEqual(response.status_code, 201, response.text)
        build = response.json()
        self.assertEqual(build["scene_id"], newest_scene)
        self.assertEqual((build["status"], build["prompt"], build["requested_by"]), ("requested", "cozy evening", "dev-user"))
        self.assertEqual(
            set(build),
            {"build_id", "project_id", "requested_by", "prompt", "scene_id", "status", "message", "slug",
             "scene_path", "apk_path", "runner_id", "created_at", "updated_at"},
        )
        self.assertTrue(all(isinstance(value, str) for value in build.values()))
        again = self.client.post(f"/v1/projects/{pid}/room-builds")  # no body at all
        self.assertEqual(again.status_code, 409)
        self.assertIn(build["build_id"], again.json()["detail"])
        listed = self.client.get(f"/v1/projects/{pid}/room-builds").json()
        self.assertEqual([item["build_id"] for item in listed], [build["build_id"]])
        one = self.client.get(f"/v1/projects/{pid}/room-builds/{build['build_id']}")
        self.assertEqual(one.json(), build)
        self.assertEqual(self.client.get(f"/v1/projects/{pid}/room-builds/nope").status_code, 404)

    def test_explicit_scene_id_is_validated(self) -> None:
        pid = self._project()
        no_scene = self._scene_upload(pid, "dev-user", 5, with_scene=False)
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={"scene_id": "missing"}).status_code, 422)
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={"scene_id": no_scene}).status_code, 409)
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={"prompt": "x" * 1001}).status_code, 422)
        chosen = self._scene_upload(pid, "dev-user", 60)
        self._scene_upload(pid, "dev-user", 1)
        response = self.client.post(f"/v1/projects/{pid}/room-builds", json={"scene_id": chosen})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["scene_id"], chosen)

    def test_runner_lifecycle(self) -> None:
        pid = self._project()
        self._scene_upload(pid, "dev-user", 5)
        build = self.client.post(f"/v1/projects/{pid}/room-builds", json={}).json()
        bid = build["build_id"]
        # Runner routes need the service token.
        self.assertEqual(self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}).status_code, 403)
        wrong = {"Authorization": "Bearer " + "z" * len(TOKEN)}
        self.assertEqual(self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=wrong).status_code, 403)
        claimed = self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=SERVICE)
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual((claimed.json()["build_id"], claimed.json()["status"], claimed.json()["runner_id"]), (bid, "claimed", "r1"))
        self.assertEqual(self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r2"}, headers=SERVICE).status_code, 204)

        def report(body, headers=SERVICE):
            return self.client.post(f"/v1/internal/room-builds/{bid}/status", json=body, headers=headers)

        self.assertEqual(report({"runner_id": "r1", "status": "syncing"}, headers={}).status_code, 403)
        self.assertEqual(report({"runner_id": "r2", "status": "syncing"}).status_code, 409)
        self.assertEqual(report({"runner_id": "r1", "status": "requested"}).status_code, 422)
        self.assertEqual(self.client.post("/v1/internal/room-builds/nope/status", json={"runner_id": "r1", "status": "syncing"}, headers=SERVICE).status_code, 404)
        syncing = report({"runner_id": "r1", "status": "syncing", "message": "Syncing scans"})
        self.assertEqual((syncing.status_code, syncing.json()["message"]), (200, "Syncing scans"))
        building = report({"runner_id": "r1", "status": "building"})
        self.assertEqual((building.json()["status"], building.json()["message"]), ("building", ""))
        heartbeat = report({"runner_id": "r1", "status": "building", "message": "Agent placing objects"})
        self.assertEqual(heartbeat.status_code, 200)
        self.assertGreaterEqual(heartbeat.json()["updated_at"], building.json()["updated_at"])
        self.assertEqual(report({"runner_id": "r1", "status": "syncing"}).status_code, 409)  # no going back
        ready_body = {
            "runner_id": "r1", "status": "ready", "slug": "cabin-living-room",
            "scene_path": "Assets/SketchScape/AgentRooms/cabin-living-room.unity",
            "apk_path": "build/quest/cabin-living-room.apk",
        }
        ready = report(ready_body)  # packaging may be skipped (--no-apk runs)
        self.assertEqual(ready.status_code, 200, ready.text)
        self.assertEqual((ready.json()["status"], ready.json()["slug"]), ("ready", "cabin-living-room"))
        self.assertEqual(report(ready_body).json(), ready.json())  # a retried final report is a no-op
        self.assertEqual(report({"runner_id": "r1", "status": "failed"}).status_code, 409)
        self.assertEqual(report({"runner_id": "r1", "status": "packaging"}).status_code, 409)
        # Terminal: a new build may be requested.
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={}).status_code, 201)

    def test_failed_from_any_active_status_and_member_cancel(self) -> None:
        pid = self._project()
        self._scene_upload(pid, "dev-user", 5)
        first = self.client.post(f"/v1/projects/{pid}/room-builds", json={}).json()
        self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=SERVICE)
        failed = self.client.post(
            f"/v1/internal/room-builds/{first['build_id']}/status",
            json={"runner_id": "r1", "status": "failed", "message": "Unity MCP not reachable"},
            headers=SERVICE,
        )
        self.assertEqual((failed.status_code, failed.json()["status"]), (200, "failed"))
        second = self.client.post(f"/v1/projects/{pid}/room-builds", json={}).json()
        cancelled = self.client.post(f"/v1/projects/{pid}/room-builds/{second['build_id']}/cancel")
        self.assertEqual((cancelled.status_code, cancelled.json()["status"]), (200, "failed"))
        self.assertIn("Cancelled", cancelled.json()["message"])
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds/{second['build_id']}/cancel").status_code, 409)
        self.assertEqual(self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=SERVICE).status_code, 204)

    def test_silent_runner_loses_the_build_after_the_lease(self) -> None:
        pid = self._project()
        self._scene_upload(pid, "dev-user", 5)
        bid = self.client.post(f"/v1/projects/{pid}/room-builds", json={}).json()["build_id"]
        self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=SERVICE)
        self.client.post(f"/v1/internal/room-builds/{bid}/status", json={"runner_id": "r1", "status": "building"}, headers=SERVICE)
        stored = main.store.get_room_build(bid)
        old = stored.model_copy(update={"updated_at": storage.iso_z(main.utc_now() - timedelta(minutes=31))})
        self.assertTrue(main.store.update_room_build(old, expected_status="building", expected_runner_id="r1", expected_updated_at=stored.updated_at))
        polled = self.client.get(f"/v1/projects/{pid}/room-builds").json()[0]
        self.assertEqual(polled["status"], "requested")
        self.assertIn("stopped reporting", polled["message"])
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={}).status_code, 409)  # still active
        self.assertEqual(  # a stranger can't report on it
            self.client.post(f"/v1/internal/room-builds/{bid}/status", json={"runner_id": "r9", "status": "packaging"}, headers=SERVICE).status_code,
            409,
        )
        reclaimed = self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r2"}, headers=SERVICE)
        self.assertEqual((reclaimed.json()["build_id"], reclaimed.json()["runner_id"]), (bid, "r2"))
        self.assertEqual(  # the silent runner lost it to r2
            self.client.post(f"/v1/internal/room-builds/{bid}/status", json={"runner_id": "r1", "status": "building"}, headers=SERVICE).status_code,
            409,
        )

    def test_slow_runner_reattaches_if_nobody_claimed_its_build(self) -> None:
        pid = self._project()
        self._scene_upload(pid, "dev-user", 5)
        bid = self.client.post(f"/v1/projects/{pid}/room-builds", json={}).json()["build_id"]
        self.client.post("/v1/internal/room-builds/claim", json={"runner_id": "r1"}, headers=SERVICE)
        self.client.post(f"/v1/internal/room-builds/{bid}/status", json={"runner_id": "r1", "status": "packaging"}, headers=SERVICE)
        stored = main.store.get_room_build(bid)
        old = stored.model_copy(update={"updated_at": storage.iso_z(main.utc_now() - timedelta(minutes=45))})
        main.store.update_room_build(old, expected_status="packaging", expected_runner_id="r1", expected_updated_at=stored.updated_at)
        self.assertEqual(self.client.get(f"/v1/projects/{pid}/room-builds").json()[0]["status"], "requested")
        ready = self.client.post(
            f"/v1/internal/room-builds/{bid}/status",
            json={"runner_id": "r1", "status": "ready", "apk_path": "build/quest/cabin.apk"},
            headers=SERVICE,
        )
        self.assertEqual((ready.status_code, ready.json()["status"], ready.json()["apk_path"]), (200, "ready", "build/quest/cabin.apk"))

    def test_shared_view_works_in_mock_mode(self) -> None:
        pid = self._project()
        response = self.client.get(f"/v1/rooms/{pid}/shared")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["viewer"], "dev-user")
        self.assertEqual(body["viewer_label"], "")
        self.assertEqual([a["label"] for a in body["accounts"]], ["Account 1", "Account 2"])
        self.assertEqual(body["latest_build"], {"build_id": "", "status": "", "slug": "", "scene_path": "", "apk_path": ""})
        self.assertEqual(self.client.get("/v1/rooms/nope/shared").status_code, 404)


def _walk_no_nulls(test: unittest.TestCase, value, path="$") -> None:
    test.assertIsNotNone(value, path)
    if isinstance(value, dict):
        for key, item in value.items():
            _walk_no_nulls(test, item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            test.assertNotIsInstance(item, list, f"{path}[{index}] is a nested array")
            _walk_no_nulls(test, item, f"{path}[{index}]")


class SharedViewDemoTests(_ApiCase):
    MODE = "demo"

    def _two_person_room(self) -> dict:
        created = self.client.post(
            "/v1/projects", json={"name": "Cabin living room", "creator_display_name": "Alice"}, headers=ALICE
        ).json()
        pid = created["project_id"]
        alice_cid = self.client.get(f"/v1/projects/{pid}/contributors", headers=ALICE).json()[0]["contributor_id"]
        joined = self.client.post(
            f"/v1/projects/{pid}/contributors",
            json={"display_name": "Bob", "invite_code": created["invite_code"]},
            headers=BOB,
        )
        self.assertEqual(joined.status_code, 201, joined.text)
        bob_cid = joined.json()["contributor_id"]

        def upload(headers, note):
            response = self.client.post(
                f"/v1/projects/{pid}/uploads",
                data={"detect": "false", "note": note},
                files={"image": ("photo.png", io.BytesIO(_png()), "image/png")},
                headers=headers,
            )
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()["upload_id"]

        alice_upload = upload(ALICE, "  Grandma's cabin, every winter.  ")
        bob_upload = upload(BOB, "The armchair where I read.")

        def letter(headers, author, recipient, note):
            response = self.client.post(
                f"/v1/projects/{pid}/letters",
                data={"author_contributor_id": author, "recipient_contributor_ids": [recipient], "note_text": note},
                files={"page": ("page.png", io.BytesIO(_png((250, 245, 230))), "image/png")},
                headers=headers,
            )
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()["letter_id"]

        to_bob = letter(ALICE, alice_cid, bob_cid, "Dear Bob, remember the snow?")
        to_alice = letter(BOB, bob_cid, alice_cid, "Dear Alice, thank you.")

        asset = self.client.post(
            f"/v1/projects/{pid}/assets",
            data={"subject_hint": "lamp"},
            files={"image": ("lamp.png", io.BytesIO(_png()), "image/png")},
            headers=ALICE,
        )
        self.assertEqual(asset.status_code, 202, asset.text)
        asset_id = asset.json()["asset_id"]
        contribution = self.client.post(
            f"/v1/projects/{pid}/contributions",
            json={"contributor_id": alice_cid, "asset_id": asset_id, "source_type": "photo", "memory_text": "Her reading lamp."},
            headers=ALICE,
        )
        self.assertEqual(contribution.status_code, 201, contribution.text)
        return {
            "pid": pid, "alice_cid": alice_cid, "bob_cid": bob_cid, "alice_upload": alice_upload,
            "bob_upload": bob_upload, "to_bob": to_bob, "to_alice": to_alice, "asset_id": asset_id,
        }

    def _shared(self, pid, headers) -> dict:
        response = self.client.get(f"/v1/rooms/{pid}/shared", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        _walk_no_nulls(self, body)
        return body

    def test_each_account_sees_its_own_letter_fields(self) -> None:
        room = self._two_person_room()
        pid = room["pid"]
        alice = self._shared(pid, ALICE)
        self.assertEqual(
            set(alice), {"project_id", "title", "viewer", "viewer_label", "accounts", "notes", "letters", "objects", "latest_build"}
        )
        self.assertEqual((alice["project_id"], alice["title"], alice["viewer"], alice["viewer_label"]), (pid, "Cabin living room", "demo-alice", "Account 1"))
        self.assertEqual(
            alice["accounts"],
            [
                {"id": "demo-alice", "label": "Account 1", "display_name": "Alice", "color": "#e8a33d"},
                {"id": "demo-bob", "label": "Account 2", "display_name": "Bob", "color": "#4aa3df"},
            ],
        )
        letters = {item["letter_id"]: item for item in alice["letters"]}
        texture = f"/v1/projects/{pid}/letters/{room['to_bob']}/texture"
        self.assertEqual(
            letters[room["to_bob"]],
            {"letter_id": room["to_bob"], "author": "demo-alice", "recipients": ["demo-bob"], "title": "From Alice to Bob",
             "sealed": True, "can_open": False, "opened": False, "body": "Dear Bob, remember the snow?", "texture_url": texture},
        )
        self.assertEqual(
            letters[room["to_alice"]],
            {"letter_id": room["to_alice"], "author": "demo-bob", "recipients": ["demo-alice"], "title": "From Bob to Alice",
             "sealed": True, "can_open": True, "opened": False, "body": "", "texture_url": ""},
        )

        bob = self._shared(pid, BOB)
        self.assertEqual((bob["viewer"], bob["viewer_label"]), ("demo-bob", "Account 2"))
        bob_letters = {item["letter_id"]: item for item in bob["letters"]}
        self.assertEqual((bob_letters[room["to_bob"]]["body"], bob_letters[room["to_bob"]]["texture_url"]), ("", ""))
        self.assertTrue(bob_letters[room["to_bob"]]["can_open"])
        self.assertEqual(bob_letters[room["to_alice"]]["body"], "Dear Alice, thank you.")
        self.assertFalse(bob_letters[room["to_alice"]]["can_open"])

        # Only a recipient opens; then its body shows for them, and the author keeps theirs.
        self.assertEqual(self.client.post(f"/v1/rooms/{pid}/letters/{room['to_bob']}/open", headers=ALICE).status_code, 403)
        self.assertEqual(self.client.post(f"/v1/rooms/{pid}/letters/{room['to_bob']}/open", headers=BOB).status_code, 200)
        opened = {item["letter_id"]: item for item in self._shared(pid, BOB)["letters"]}[room["to_bob"]]
        self.assertEqual(
            (opened["sealed"], opened["opened"], opened["can_open"], opened["body"], opened["texture_url"]),
            (False, True, False, "Dear Bob, remember the snow?", texture),
        )
        author_view = {item["letter_id"]: item for item in self._shared(pid, ALICE)["letters"]}[room["to_bob"]]
        self.assertEqual((author_view["opened"], author_view["can_open"], author_view["body"]), (True, False, "Dear Bob, remember the snow?"))
        # The texture route agrees with the view for the recipient who opened it.
        self.assertEqual(self.client.get(texture, headers=BOB).status_code, 200)

    def test_notes_objects_and_latest_build(self) -> None:
        room = self._two_person_room()
        pid = room["pid"]
        alice = self._shared(pid, ALICE)
        notes = {(item["author"], item["text"]): item for item in alice["notes"]}
        self.assertIn(("demo-alice", "Grandma's cabin, every winter."), notes)
        self.assertIn(("demo-bob", "The armchair where I read."), notes)
        self.assertEqual(notes[("demo-bob", "The armchair where I read.")]["upload_id"], room["bob_upload"])
        self.assertEqual(notes[("demo-alice", "Grandma's cabin, every winter.")]["note_id"], f"upload-{room['alice_upload']}")
        lamp_note = notes[("demo-alice", "Her reading lamp.")]
        self.assertEqual(lamp_note["asset_ids"], [room["asset_id"]])
        self.assertFalse(any("Dear" in item["text"] for item in alice["notes"]))  # sealed letter notes never leak
        self.assertEqual(alice["notes"], self._shared(pid, BOB)["notes"])  # notes are the same for both

        objects = {item["asset_id"]: item for item in alice["objects"]}
        self.assertNotIn(room["to_bob"], objects)  # letters are envelopes, not objects
        self.assertEqual(objects[room["asset_id"]], {"asset_id": room["asset_id"], "label": "lamp", "contributor": "demo-alice", "editable_by_me": True})
        bob_objects = {item["asset_id"]: item for item in self._shared(pid, BOB)["objects"]}
        self.assertFalse(bob_objects[room["asset_id"]]["editable_by_me"])

        main.store.save_upload_record(
            main.store.get_upload_record(pid, room["alice_upload"]).model_copy(
                update={"scene_key": f"artifacts/scenes/{room['alice_upload']}/scene.json"}
            )
        )
        build = self.client.post(f"/v1/projects/{pid}/room-builds", json={}, headers=BOB)
        self.assertEqual(build.status_code, 201, build.text)
        self.assertEqual(build.json()["scene_id"], room["alice_upload"])
        latest = self._shared(pid, ALICE)["latest_build"]
        self.assertEqual(latest, {"build_id": build.json()["build_id"], "status": "requested", "slug": "", "scene_path": "", "apk_path": ""})

    def test_service_views_as_a_named_account_for_the_snapshot(self) -> None:
        room = self._two_person_room()
        pid = room["pid"]
        as_bob = self._shared(pid, {**SERVICE, **BOB})
        self.assertEqual((as_bob["viewer"], as_bob["viewer_label"]), ("demo-bob", "Account 2"))
        self.assertEqual(as_bob["letters"], self._shared(pid, BOB)["letters"])
        anonymous = self._shared(pid, SERVICE)
        self.assertEqual((anonymous["viewer"], anonymous["viewer_label"]), ("", ""))
        self.assertTrue(all(item["body"] == "" and not item["can_open"] for item in anonymous["letters"]))

    def test_members_only(self) -> None:
        pid = self._project(ALICE, name="Alice only")
        self.assertEqual(self.client.get(f"/v1/rooms/{pid}/shared", headers=BOB).status_code, 403)
        self.assertEqual(self.client.get(f"/v1/projects/{pid}/room-builds", headers=BOB).status_code, 403)
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={}, headers=BOB).status_code, 403)
        self.assertEqual(self.client.get("/v1/rooms/does-not-exist/shared", headers=ALICE).status_code, 404)
        self.assertEqual(self.client.get(f"/v1/rooms/{pid}/shared").status_code, 401)
        # The runner (service) reads builds but can't request one.
        self.assertEqual(self.client.get(f"/v1/projects/{pid}/room-builds", headers=SERVICE).status_code, 200)
        self.assertEqual(self.client.post(f"/v1/projects/{pid}/room-builds", json={}, headers=SERVICE).status_code, 403)

    def test_upload_note_is_uploader_editable(self) -> None:
        room = self._two_person_room()
        pid, upload_id = room["pid"], room["alice_upload"]
        self.assertEqual(self.client.get(f"/v1/projects/{pid}/uploads/{upload_id}", headers=BOB).json()["note"], "Grandma's cabin, every winter.")
        self.assertEqual(self.client.patch(f"/v1/projects/{pid}/uploads/{upload_id}", json={"note": "hijack"}, headers=BOB).status_code, 403)
        edited = self.client.patch(f"/v1/projects/{pid}/uploads/{upload_id}", json={"note": " Winters at the cabin. "}, headers=ALICE)
        self.assertEqual((edited.status_code, edited.json()["note"]), (200, "Winters at the cabin."))
        texts = [item["text"] for item in self._shared(pid, BOB)["notes"]]
        self.assertIn("Winters at the cabin.", texts)
        self.assertNotIn("Grandma's cabin, every winter.", texts)


if __name__ == "__main__":
    unittest.main()
