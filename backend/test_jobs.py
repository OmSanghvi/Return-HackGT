"""Build Plan step 26: durable jobs + multi-object upload API contract tests.

Run with `python -m unittest test_jobs.py`. See the storage-layer lease/claim
tests in test_storage.py (LocalJsonStoreContractTests, DynamoDbStoreTests) for
the lower-level durable-job store contract; this file exercises the HTTP
surface built on top of it.
"""

import io
import json
import os
import tempfile
import unittest

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

from PIL import Image  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

app = main.app


def _png_bytes(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _exif_rotated_jpeg_bytes(width: int = 40, height: int = 20) -> bytes:
    """A genuine JPEG whose EXIF orientation tag (6) requires a 90 deg rotation."""
    image = Image.new("RGB", (width, height), color=(200, 0, 0))
    image.putpixel((0, 0), (0, 200, 0))  # a marker corner, for future visual debugging
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW to display upright
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


class UploadSelectionGenerateFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        with TestClient(app) as client:
            self.project_id = client.post(
                "/v1/projects", json={"name": "Upload flow", "description": "step 26"}
            ).json()["project_id"]

    def _create_upload(self, client: "TestClient") -> dict:
        response = client.post(
            f"/v1/projects/{self.project_id}/uploads",
            files={"image": ("photo.png", io.BytesIO(_png_bytes()), "image/png")},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_three_selections_segment_then_refine_then_generate_two(self) -> None:
        with TestClient(app) as client:
            upload = self._create_upload(client)
            upload_id = upload["upload_id"]
            self.assertEqual(upload["width"], 40)
            self.assertEqual(upload["height"], 30)

            image_response = client.get(upload["image_url"])
            self.assertEqual(image_response.status_code, 200)

            selections = {
                "selections": [
                    {
                        "selection_id": "sel-points",
                        "prompt": {"type": "points", "points": [[0.5, 0.5, 1]]},
                        "label": "vase",
                        "memory_text": "Grandma's vase.",
                    },
                    {
                        "selection_id": "sel-box",
                        "prompt": {"type": "box", "box": [0.1, 0.1, 0.4, 0.4]},
                        "label": "lamp",
                        "memory_text": "The reading lamp.",
                    },
                    {
                        "selection_id": "sel-text",
                        "prompt": {"type": "text", "text": "blue chair"},
                        "label": "chair",
                    },
                ]
            }
            create_response = client.post(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/selections",
                json=selections,
            )
            self.assertEqual(create_response.status_code, 202)
            self.assertTrue(create_response.json()["job_id"])

            record = client.get(f"/v1/projects/{self.project_id}/uploads/{upload_id}").json()
            statuses = {item["selection_id"]: item["status"] for item in record["selections"]}
            self.assertEqual(statuses, {"sel-points": "segmented", "sel-box": "segmented", "sel-text": "segmented"})
            for item in record["selections"]:
                self.assertIsNotNone(item["mask_preview_url"])
                mask_response = client.get(item["mask_preview_url"])
                self.assertEqual(mask_response.status_code, 200)
                mask_image = Image.open(io.BytesIO(mask_response.content))
                self.assertEqual(mask_image.size, (upload["width"], upload["height"]))

            # Resending the same selection_id creates nothing new.
            resend = client.post(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/selections",
                json={"selections": [selections["selections"][0]]},
            )
            self.assertEqual(resend.status_code, 202)
            self.assertIsNone(resend.json()["job_id"])
            after_resend = client.get(f"/v1/projects/{self.project_id}/uploads/{upload_id}").json()
            self.assertEqual(len(after_resend["selections"]), 3)

            # Refine one selection with an exclude point; only it re-segments.
            refine = client.post(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/selections/sel-points/refine",
                json={"points": [[0.5, 0.5, 1], [0.9, 0.9, 0]]},
            )
            self.assertEqual(refine.status_code, 202)
            refined = client.get(f"/v1/projects/{self.project_id}/uploads/{upload_id}").json()
            refined_selection = next(s for s in refined["selections"] if s["selection_id"] == "sel-points")
            self.assertEqual(refined_selection["prompt"]["type"], "points")
            self.assertEqual(refined_selection["status"], "segmented")

            generate = client.post(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/generate",
                json={"selection_ids": ["sel-points", "sel-box"]},
            )
            self.assertEqual(generate.status_code, 202)
            body = generate.json()
            self.assertEqual(len(body["assets"]), 2)
            self.assertEqual(len(body["jobs"]), 2)

            contributions = client.get(f"/v1/projects/{self.project_id}/contributions").json()
            self.assertEqual(len(contributions), 2)
            memory_texts = {c["memory_text"] for c in contributions}
            self.assertEqual(memory_texts, {"Grandma's vase.", "The reading lamp."})

            # A follow-up GET (not the POST response body, which reflects
            # pre-background-task state) shows the mock reconstruct jobs done.
            assets_listed = client.get(f"/v1/projects/{self.project_id}/assets").json()
            self.assertEqual(len(assets_listed), 2)
            for asset in assets_listed:
                self.assertEqual(asset["status"], "ready")

    def test_delete_selection(self) -> None:
        with TestClient(app) as client:
            upload = self._create_upload(client)
            upload_id = upload["upload_id"]
            client.post(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/selections",
                json={"selections": [{"selection_id": "a", "prompt": {"type": "box", "box": [0, 0, 1, 1]}}]},
            )
            deleted = client.delete(
                f"/v1/projects/{self.project_id}/uploads/{upload_id}/selections/a"
            )
            self.assertEqual(deleted.status_code, 204)
            record = client.get(f"/v1/projects/{self.project_id}/uploads/{upload_id}").json()
            self.assertEqual(record["selections"], [])


class SelectionValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        with TestClient(app) as client:
            self.project_id = client.post(
                "/v1/projects", json={"name": "Validation", "description": ""}
            ).json()["project_id"]
            self.upload_id = client.post(
                f"/v1/projects/{self.project_id}/uploads",
                files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
            ).json()["upload_id"]

    def _post_selection(self, client: "TestClient", prompt: dict) -> "object":
        return client.post(
            f"/v1/projects/{self.project_id}/uploads/{self.upload_id}/selections",
            json={"selections": [{"selection_id": "s1", "prompt": prompt}]},
        )

    def test_coordinates_outside_0_1_are_422(self) -> None:
        with TestClient(app) as client:
            response = self._post_selection(client, {"type": "box", "box": [0, 0, 1.5, 1]})
            self.assertEqual(response.status_code, 422)

    def test_empty_prompt_is_422(self) -> None:
        with TestClient(app) as client:
            response = self._post_selection(client, {"type": "points", "points": []})
            self.assertEqual(response.status_code, 422)

    def test_two_prompt_types_at_once_is_422(self) -> None:
        with TestClient(app) as client:
            response = self._post_selection(
                client, {"type": "box", "box": [0, 0, 1, 1], "text": "also text"}
            )
            self.assertEqual(response.status_code, 422)

    def test_generating_an_unsegmented_selection_is_409(self) -> None:
        with TestClient(app) as client:
            client.post(
                f"/v1/projects/{self.project_id}/uploads/{self.upload_id}/selections",
                json={"selections": [{"selection_id": "s1", "prompt": {"type": "box", "box": [0, 0, 1, 1]}}]},
            )
            # Mock segmentation runs synchronously via TestClient's background
            # tasks, so force it back to "pending" to exercise the 409 path.
            record = main.store.get_upload_record(self.project_id, self.upload_id)
            record.selections[0].status = "pending"
            main.store.save_upload_record(record)

            response = client.post(
                f"/v1/projects/{self.project_id}/uploads/{self.upload_id}/generate",
                json={"selection_ids": ["s1"]},
            )
            self.assertEqual(response.status_code, 409)

    def test_unknown_selection_id_on_generate_is_422(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                f"/v1/projects/{self.project_id}/uploads/{self.upload_id}/generate",
                json={"selection_ids": ["nope"]},
            )
            self.assertEqual(response.status_code, 422)

    def test_object_cap_is_enforced(self) -> None:
        with TestClient(app) as client:
            os.environ["SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD"] = "2"
            try:
                selections = {
                    "selections": [
                        {"selection_id": f"s{i}", "prompt": {"type": "box", "box": [0, 0, 0.1, 0.1]}}
                        for i in range(3)
                    ]
                }
                response = client.post(
                    f"/v1/projects/{self.project_id}/uploads/{self.upload_id}/selections",
                    json=selections,
                )
                self.assertEqual(response.status_code, 422)
            finally:
                del os.environ["SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD"]


class ExifOrientationTests(unittest.TestCase):
    def test_exif_rotated_upload_is_stored_upright(self) -> None:
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Exif", "description": ""}
            ).json()["project_id"]
            raw = _exif_rotated_jpeg_bytes(width=40, height=20)
            upload = client.post(
                f"/v1/projects/{project_id}/uploads",
                files={"image": ("rotated.jpg", io.BytesIO(raw), "image/jpeg")},
            ).json()
            # Orientation 6 on a 40x20 source displays upright at 20x40.
            self.assertEqual((upload["width"], upload["height"]), (20, 40))

            stored = client.get(upload["image_url"])
            stored_image = Image.open(io.BytesIO(stored.content))
            self.assertEqual(stored_image.size, (20, 40))
            self.assertNotIn(0x0112, stored_image.getexif())

            # A selection normalized against the corrected canvas produces a
            # mask sized to that same corrected canvas -- i.e. it lines up.
            client.post(
                f"/v1/projects/{project_id}/uploads/{upload['upload_id']}/selections",
                json={
                    "selections": [
                        {"selection_id": "s1", "prompt": {"type": "box", "box": [0.1, 0.1, 0.5, 0.5]}}
                    ]
                },
            )
            record = client.get(f"/v1/projects/{project_id}/uploads/{upload['upload_id']}").json()
            mask = client.get(record["selections"][0]["mask_preview_url"])
            mask_image = Image.open(io.BytesIO(mask.content))
            self.assertEqual(mask_image.size, (20, 40))


class ConcurrentUploadAssetLinkTests(unittest.TestCase):
    def test_two_uploads_racing_both_assets_survive(self) -> None:
        """The old `project.asset_ids.append` + whole-blob save lost one asset
        under concurrent writers; child-item links (store.link_asset) fix it."""
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Race", "description": ""}
            ).json()["project_id"]

        project = main.store.get_project(project_id)
        asset_a = main.ProjectAsset(
            asset_id="asset-a", project_id=project_id, label="a",
            status=main.AssetStatus.READY, reconstruction_job_id="job-a",
        )
        asset_b = main.ProjectAsset(
            asset_id="asset-b", project_id=project_id, label="b",
            status=main.AssetStatus.READY, reconstruction_job_id="job-b",
        )
        main.store.save_asset(asset_a)
        main.store.save_asset(asset_b)
        # Two "concurrent" writers linking against the same stale in-memory
        # `project` snapshot -- the scenario that dropped an asset before
        # step 26's child-item links replaced `project.asset_ids.append`.
        main.store.link_asset(project_id, "asset-a")
        main.store.link_asset(project_id, "asset-b")

        with TestClient(app) as client:
            listed = client.get(f"/v1/projects/{project_id}/assets").json()
        self.assertEqual({item["asset_id"] for item in listed}, {"asset-a", "asset-b"})


class RestartDurabilityTests(unittest.TestCase):
    def test_segment_job_survives_a_restart(self) -> None:
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Restart", "description": ""}
            ).json()["project_id"]
            upload_id = client.post(
                f"/v1/projects/{project_id}/uploads",
                files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
            ).json()["upload_id"]
            create = client.post(
                f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
                json={"selections": [{"selection_id": "s1", "prompt": {"type": "box", "box": [0, 0, 1, 1]}}]},
            )
            job_id = create.json()["job_id"]

        from storage import Store  # noqa: E402

        reloaded = Store(main.store._state_path)
        reloaded.load()
        job = reloaded.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.status, "complete")
        self.assertEqual(reloaded.get_upload_record(project_id, upload_id).selections[0].status, "segmented")


class JobsPollingEndpointTests(unittest.TestCase):
    def test_etag_returns_304_when_unchanged_and_lists_every_job(self) -> None:
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Polling", "description": ""}
            ).json()["project_id"]
            client.post(
                f"/v1/projects/{project_id}/assets",
                data={"subject_hint": "thing"},
                files={"image": ("t.png", io.BytesIO(b"not-a-real-png"), "image/png")},
            )
            first = client.get(f"/v1/projects/{project_id}/jobs")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(len(first.json()), 1)
            etag = first.headers["etag"]

            second = client.get(
                f"/v1/projects/{project_id}/jobs", headers={"If-None-Match": etag}
            )
            self.assertEqual(second.status_code, 304)

            upload_id = client.post(
                f"/v1/projects/{project_id}/uploads",
                files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
            ).json()["upload_id"]
            client.post(
                f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
                json={"selections": [{"selection_id": "s1", "prompt": {"type": "box", "box": [0, 0, 1, 1]}}]},
            )
            changed = client.get(
                f"/v1/projects/{project_id}/jobs", headers={"If-None-Match": etag}
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(len(changed.json()), 2)


class WorkerResultLeaseOwnershipTests(unittest.TestCase):
    def test_result_callback_rejected_from_a_non_owner_and_accepted_from_the_owner(self) -> None:
        with TestClient(app) as client:
            now = main.utc_now()
            job_id = "leased-job-1"
            job = main.ReconstructionJob(
                job_id=job_id,
                status=main.JobStatus.RUNNING,
                poll_url=f"/v1/reconstructions/{job_id}",
                created_at=now,
                updated_at=now,
                kind="reconstruct",
                lease_owner="worker-1",
            )
            main.store.save_job(job)

            rejected = client.post(
                f"/v1/internal/reconstructions/{job_id}/result",
                data={"result": json.dumps({"status": "failed", "error": "boom"}), "worker_id": "worker-2"},
            )
            self.assertEqual(rejected.status_code, 401)

            accepted = client.post(
                f"/v1/internal/reconstructions/{job_id}/result",
                data={"result": json.dumps({"status": "failed", "error": "boom"}), "worker_id": "worker-1"},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
