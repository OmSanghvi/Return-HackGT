"""Build Plan step 27: GPU-worker dispatcher API contract tests.

Covers the pieces `worker/gpu_dispatcher.py` depends on that step 26 did not
yet exercise over HTTP: the internal claim/lease routes, the new per-segment-
job selections task route, and the new per-selection result callback route
that lets one SAM 3.1 pass over several typed names report back one
selection at a time (Hard Rule 7: a failed selection never blocks the
others). Also covers `dispatch_job` leaving a `segment` job queued for the
dispatcher under `PIPELINE_MODE=aws-local`, instead of the old auto-fail.

Run with `python -m unittest test_gpu_worker.py`. Never touches a real GPU,
AWS, or the network -- see worker/test_gpu_dispatcher.py and
worker/test_segment_sam31_local.py for the worker-side unit tests.
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


def _mask_bytes(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("L", (width, height), color=255).save(buffer, format="PNG")
    return buffer.getvalue()


def _drain_queue(client: "TestClient", kinds: list[str] = ["segment", "reconstruct"]) -> None:
    """`main.store` is one process-wide global, so a `segment` job another
    test method left `queued` (Build Plan step 27's whole point -- it no
    longer runs to completion inline) would otherwise be claimed ahead of
    the job a test just created, since `claim_next_job` picks the oldest
    queued job across every project. Call this before any test that expects
    claim() to hand back one specific job."""
    while True:
        response = client.post("/v1/internal/jobs/claim", json={"worker_id": "drain", "kinds": kinds})
        if response.status_code == 204:
            return


class _AwsLocalMode:
    """Temporarily switch PIPELINE_MODE so a segment job is left `queued`
    for the dispatcher instead of running the mock segmenter inline."""

    def __enter__(self):
        self._previous = os.environ.get("PIPELINE_MODE")
        os.environ["PIPELINE_MODE"] = "aws-local"
        return self

    def __exit__(self, *exc):
        if self._previous is None:
            os.environ.pop("PIPELINE_MODE", None)
        else:
            os.environ["PIPELINE_MODE"] = self._previous


class SegmentJobLeftQueuedUnderAwsLocalTests(unittest.TestCase):
    def test_segment_job_stays_queued_instead_of_auto_failing(self) -> None:
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "aws-local", "description": ""}
            ).json()["project_id"]
            upload_id = client.post(
                f"/v1/projects/{project_id}/uploads",
                files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
            ).json()["upload_id"]

            with _AwsLocalMode():
                create = client.post(
                    f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
                    json={"selections": [{"selection_id": "s1", "prompt": {"text": "vase"}}]},
                )
                self.assertEqual(create.status_code, 202)
                job_id = create.json()["job_id"]

            job = main.store.get_job(job_id)
            self.assertEqual(job.status, "queued")
            self.assertIsNone(job.error)

    def test_reconstruct_job_is_left_for_the_dispatcher_not_pushed_by_the_api(self) -> None:
        # Pushing from the API raced the dispatcher: three objects from one
        # photo were submitted back to back and the worker 429'd the third.
        from types import SimpleNamespace

        from fastapi import BackgroundTasks

        tasks = BackgroundTasks()
        with _AwsLocalMode():
            main.dispatch_job(SimpleNamespace(kind="reconstruct", job_id="j1"), tasks)
        self.assertEqual(tasks.tasks, [])


class InternalClaimAndLeaseRouteTests(unittest.TestCase):
    def _queued_segment_job(self, client: "TestClient") -> tuple[str, str, str]:
        _drain_queue(client)
        project_id = client.post("/v1/projects", json={"name": "claim", "description": ""}).json()["project_id"]
        upload_id = client.post(
            f"/v1/projects/{project_id}/uploads",
            files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
        ).json()["upload_id"]
        with _AwsLocalMode():
            job_id = client.post(
                f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
                json={"selections": [{"selection_id": "s1", "prompt": {"text": "vase"}}]},
            ).json()["job_id"]
        return project_id, upload_id, job_id

    def test_claim_returns_queued_job_then_204_when_idle(self) -> None:
        with TestClient(app) as client:
            _project_id, _upload_id, job_id = self._queued_segment_job(client)

            claimed = client.post(
                "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]}
            )
            self.assertEqual(claimed.status_code, 200)
            body = claimed.json()
            self.assertEqual(body["job_id"], job_id)
            self.assertEqual(body["status"], "running")

            job = main.store.get_job(job_id)
            self.assertEqual(job.lease_owner, "gpu-1")

            idle = client.post(
                "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]}
            )
            self.assertEqual(idle.status_code, 204)

    def test_claim_filters_by_kind(self) -> None:
        with TestClient(app) as client:
            self._queued_segment_job(client)
            reconstruct_claim = client.post(
                "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["reconstruct"]}
            )
            self.assertEqual(reconstruct_claim.status_code, 204)

    def test_renew_lease(self) -> None:
        with TestClient(app) as client:
            _project_id, _upload_id, job_id = self._queued_segment_job(client)
            client.post("/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]})

            renewed = client.post(
                f"/v1/internal/jobs/{job_id}/lease", data={"worker_id": "gpu-1"}
            )
            self.assertTrue(renewed.json()["renewed"])

            rejected = client.post(
                f"/v1/internal/jobs/{job_id}/lease", data={"worker_id": "someone-else"}
            )
            self.assertFalse(rejected.json()["renewed"])

    def test_claim_requires_a_valid_worker_token(self) -> None:
        with TestClient(app) as client:
            self._queued_segment_job(client)
        os.environ["SKETCHSCAPE_WORKER_TOKEN"] = "correct-token"
        try:
            with TestClient(app) as client:
                unauthorized = client.post(
                    "/v1/internal/jobs/claim",
                    json={"worker_id": "gpu-1", "kinds": ["segment"]},
                    headers={"X-SketchScape-Worker-Token": "wrong-token"},
                )
                self.assertEqual(unauthorized.status_code, 401)

                authorized = client.post(
                    "/v1/internal/jobs/claim",
                    json={"worker_id": "gpu-1", "kinds": ["segment"]},
                    headers={"X-SketchScape-Worker-Token": "correct-token"},
                )
                self.assertEqual(authorized.status_code, 200)
        finally:
            del os.environ["SKETCHSCAPE_WORKER_TOKEN"]


class SegmentTaskAndSelectionResultTests(unittest.TestCase):
    def _three_selections(self, client: "TestClient") -> dict:
        _drain_queue(client)
        project_id = client.post("/v1/projects", json={"name": "multi", "description": ""}).json()["project_id"]
        upload = client.post(
            f"/v1/projects/{project_id}/uploads",
            files={"image": ("p.png", io.BytesIO(_png_bytes()), "image/png")},
        ).json()
        upload_id = upload["upload_id"]
        with _AwsLocalMode():
            job_id = client.post(
                f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
                json={
                    "selections": [
                        {"selection_id": "sel-vase", "prompt": {"text": "vase"}, "label": "vase"},
                        {"selection_id": "sel-lamp", "prompt": {"text": "lamp"}, "label": "lamp"},
                        {"selection_id": "sel-chair", "prompt": {"text": "blue chair"}, "label": "chair"},
                    ]
                },
            ).json()["job_id"]
        return {"project_id": project_id, "upload_id": upload_id, "job_id": job_id, "width": upload["width"], "height": upload["height"]}

    def test_task_route_lists_pending_selection_prompts(self) -> None:
        with TestClient(app) as client:
            ctx = self._three_selections(client)
            client.post("/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]})

            task = client.get(f"/v1/internal/reconstructions/{ctx['job_id']}/selections")
            self.assertEqual(task.status_code, 200)
            body = task.json()
            self.assertEqual(
                {item["selection_id"]: item["text"] for item in body["selections"]},
                {"sel-vase": "vase", "sel-lamp": "lamp", "sel-chair": "blue chair"},
            )

    def test_task_route_404_for_non_segment_job(self) -> None:
        with TestClient(app) as client:
            job_id = main.uuid.uuid4().hex
            now = main.utc_now()
            main.store.save_job(
                main.ReconstructionJob(
                    job_id=job_id, status=main.JobStatus.QUEUED, poll_url=f"/v1/reconstructions/{job_id}",
                    created_at=now, updated_at=now, kind="reconstruct",
                )
            )
            response = client.get(f"/v1/internal/reconstructions/{job_id}/selections")
            self.assertEqual(response.status_code, 404)

    def test_one_photo_three_typed_names_produce_three_masks_then_three_reconstruct_jobs(self) -> None:
        """The step 27 scenario: several objects from one image, one SAM 3.1
        pass, then one Fast-SAM3D job per selected object."""
        with TestClient(app) as client:
            ctx = self._three_selections(client)
            claim = client.post(
                "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]}
            ).json()
            self.assertEqual(claim["job_id"], ctx["job_id"])

            selection_ids = ["sel-vase", "sel-lamp", "sel-chair"]
            for index, selection_id in enumerate(selection_ids):
                result = client.post(
                    f"/v1/internal/reconstructions/{ctx['job_id']}/selections/{selection_id}/result",
                    data={
                        "worker_id": "gpu-1",
                        "result": json.dumps(
                            {"status": "segmented", "score": 0.9 - index * 0.05, "alternatives": []}
                        ),
                    },
                    files={"mask": ("mask.png", io.BytesIO(_mask_bytes(ctx["width"], ctx["height"])), "image/png")},
                )
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["status"], "segmented")

            job = main.store.get_job(ctx["job_id"])
            self.assertEqual(job.status, "complete")
            self.assertIsNone(job.lease_owner)

            upload = client.get(f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}").json()
            self.assertEqual(
                {item["selection_id"]: item["status"] for item in upload["selections"]},
                {sid: "segmented" for sid in selection_ids},
            )
            for item in upload["selections"]:
                mask = client.get(item["mask_preview_url"])
                self.assertEqual(mask.status_code, 200)

            # Back in mock mode (no real GPU/worker in this test), `generate`
            # dispatches one `reconstruct` job per chosen object.
            generate = client.post(
                f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}/generate",
                json={"selection_ids": selection_ids},
            )
            self.assertEqual(generate.status_code, 202)
            body = generate.json()
            self.assertEqual(len(body["assets"]), 3)
            self.assertEqual(len(body["jobs"]), 3)
            self.assertEqual({j["kind"] for j in body["jobs"]}, {"reconstruct"})

            assets = client.get(f"/v1/projects/{ctx['project_id']}/assets").json()
            self.assertEqual(len(assets), 3)
            for asset in assets:
                self.assertEqual(asset["status"], "ready")

    def test_a_selection_with_no_match_fails_with_a_reason_and_does_not_block_the_others(self) -> None:
        with TestClient(app) as client:
            ctx = self._three_selections(client)
            client.post("/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]})

            failed = client.post(
                f"/v1/internal/reconstructions/{ctx['job_id']}/selections/sel-chair/result",
                data={"worker_id": "gpu-1", "result": json.dumps({"status": "failed", "reason": "nothing found matching that name; try being more specific"})},
            )
            self.assertEqual(failed.status_code, 200)
            self.assertEqual(failed.json()["status"], "failed")
            self.assertIsNotNone(failed.json()["error"])

            # The job is not complete yet -- two selections are still pending.
            self.assertEqual(main.store.get_job(ctx["job_id"]).status, "running")

            for selection_id in ("sel-vase", "sel-lamp"):
                client.post(
                    f"/v1/internal/reconstructions/{ctx['job_id']}/selections/{selection_id}/result",
                    data={"worker_id": "gpu-1", "result": json.dumps({"status": "segmented", "score": 0.8})},
                    files={"mask": ("mask.png", io.BytesIO(_mask_bytes(ctx["width"], ctx["height"])), "image/png")},
                )

            job = main.store.get_job(ctx["job_id"])
            self.assertEqual(job.status, "complete")
            upload = client.get(f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}").json()
            statuses = {item["selection_id"]: item["status"] for item in upload["selections"]}
            self.assertEqual(statuses, {"sel-vase": "segmented", "sel-lamp": "segmented", "sel-chair": "failed"})

    def test_result_from_a_non_owner_worker_is_rejected(self) -> None:
        with TestClient(app) as client:
            ctx = self._three_selections(client)
            client.post("/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]})

            rejected = client.post(
                f"/v1/internal/reconstructions/{ctx['job_id']}/selections/sel-vase/result",
                data={"worker_id": "gpu-2", "result": json.dumps({"status": "segmented", "score": 0.8})},
                files={"mask": ("mask.png", io.BytesIO(_mask_bytes(ctx["width"], ctx["height"])), "image/png")},
            )
            self.assertEqual(rejected.status_code, 401)

    def test_segmented_result_without_a_mask_file_is_422(self) -> None:
        with TestClient(app) as client:
            ctx = self._three_selections(client)
            client.post("/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]})
            response = client.post(
                f"/v1/internal/reconstructions/{ctx['job_id']}/selections/sel-vase/result",
                data={"worker_id": "gpu-1", "result": json.dumps({"status": "segmented", "score": 0.8})},
            )
            self.assertEqual(response.status_code, 422)


class SeveralUploadsInFlightTests(unittest.TestCase):
    def test_two_uploads_segment_jobs_are_claimed_and_completed_independently(self) -> None:
        with TestClient(app) as client:
            _drain_queue(client)
            project_id = client.post("/v1/projects", json={"name": "in-flight", "description": ""}).json()[
                "project_id"
            ]

            uploads = []
            with _AwsLocalMode():
                for index, prompts in enumerate([["mug", "plate"], ["clock"]]):
                    upload = client.post(
                        f"/v1/projects/{project_id}/uploads",
                        files={"image": (f"p{index}.png", io.BytesIO(_png_bytes()), "image/png")},
                    ).json()
                    job_id = client.post(
                        f"/v1/projects/{project_id}/uploads/{upload['upload_id']}/selections",
                        json={
                            "selections": [
                                {"selection_id": f"u{index}-{i}", "prompt": {"text": text}}
                                for i, text in enumerate(prompts)
                            ]
                        },
                    ).json()["job_id"]
                    uploads.append({"upload_id": upload["upload_id"], "job_id": job_id, "prompts": prompts})

            # Both jobs are queued at once, independent of each other.
            for entry in uploads:
                self.assertEqual(main.store.get_job(entry["job_id"]).status, "queued")

            # One dispatcher worker claims and finishes each in turn -- the
            # second claim must not see the first job again while it's held.
            for entry in uploads:
                claim = client.post(
                    "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]}
                ).json()
                self.assertEqual(claim["job_id"], entry["job_id"])
                for selection in main.store.get_job(entry["job_id"]).selection_ids:
                    client.post(
                        f"/v1/internal/reconstructions/{entry['job_id']}/selections/{selection}/result",
                        data={"worker_id": "gpu-1", "result": json.dumps({"status": "segmented", "score": 0.7})},
                        files={"mask": ("mask.png", io.BytesIO(_mask_bytes()), "image/png")},
                    )

            for entry in uploads:
                job = main.store.get_job(entry["job_id"])
                self.assertEqual(job.status, "complete")
                self.assertIsNone(job.lease_owner)

            all_uploads = [
                client.get(f"/v1/projects/{project_id}/uploads/{entry['upload_id']}").json() for entry in uploads
            ]
            for upload, entry in zip(all_uploads, uploads):
                self.assertEqual(len(upload["selections"]), len(entry["prompts"]))
                for selection in upload["selections"]:
                    self.assertEqual(selection["status"], "segmented")


if __name__ == "__main__":
    unittest.main()
