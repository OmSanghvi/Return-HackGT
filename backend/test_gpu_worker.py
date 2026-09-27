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

def _ready_objects(client: "TestClient", names: list[str]) -> dict:
    """A project with one photo whose objects are segmented and reconstructed
    (mock pipeline): returns ids for the internal pose/scene routes."""
    _drain_queue(client)
    project_id = client.post("/v1/projects", json={"name": "scene", "description": ""}).json()["project_id"]
    upload_id = client.post(
        f"/v1/projects/{project_id}/uploads",
        files={"image": ("room.png", io.BytesIO(_png_bytes()), "image/png")},
    ).json()["upload_id"]
    client.post(
        f"/v1/projects/{project_id}/uploads/{upload_id}/selections",
        json={"selections": [{"selection_id": f"s{i}", "prompt": {"text": n}} for i, n in enumerate(names)]},
    )
    generated = client.post(
        f"/v1/projects/{project_id}/uploads/{upload_id}/generate",
        json={"selection_ids": [f"s{i}" for i in range(len(names))]},
    ).json()
    return {
        "project_id": project_id,
        "upload_id": upload_id,
        "job_ids": [job["job_id"] for job in generated["jobs"]],
        "asset_ids": [asset["asset_id"] for asset in generated["assets"]],
    }


def _pose_v2() -> dict:
    return {
        "version": 2,
        "frame": "opencv",
        "image_size": [40, 30],
        "intrinsics": {"fx": 30.0, "fy": 30.0, "cx": 20.0, "cy": 15.0},
        "gravity_up_cam": [0, -1, 0],
        "object": {"centroid_cam": [0.1, 0.2, 2.0], "yaw_deg": None, "reprojection_iou": 0.81},
        "raw": {"version": 1, "rotation": [1, 0, 0, 0]},
    }


def _post_complete(client: "TestClient", job_id: str, pose: bytes | None, **data):
    files = {
        "ply": ("reconstruction.ply", io.BytesIO(b"ply\nformat binary_little_endian 1.0\nend_header\n"), "application/octet-stream"),
        "mask": ("mask.png", io.BytesIO(_mask_bytes()), "image/png"),
    }
    if pose is not None:
        files["pose"] = ("pose.json", io.BytesIO(pose), "application/json")
    return client.post(
        f"/v1/internal/reconstructions/{job_id}/result",
        data={"result": json.dumps({"status": "complete", "object_label": "cat"}), **data},
        files=files,
    )


class WorkerPoseTests(unittest.TestCase):
    """Contract 1a/2: the result callback accepts `pose` and carries it onto
    the job, the asset and the asset view; bad poses never fail a scan."""

    def test_pose_is_stored_as_a_file_and_inlined_on_job_asset_and_view(self) -> None:
        with TestClient(app) as client:
            ctx = _ready_objects(client, ["cat"])
            job_id, asset_id = ctx["job_ids"][0], ctx["asset_ids"][0]
            response = _post_complete(client, job_id, json.dumps(_pose_v2()).encode())
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            self.assertEqual(job["pose"]["version"], 2)
            self.assertEqual(job["pose_url"], f"/v1/artifacts/{job_id}/pose.json")
            stored = json.loads((main.ARTIFACT_ROOT / job_id / "pose.json").read_text())
            self.assertEqual(stored["object"]["reprojection_iou"], 0.81)
            asset = client.get(f"/v1/projects/{ctx['project_id']}/assets/{asset_id}").json()
            self.assertEqual(asset["pose"]["intrinsics"]["fx"], 30.0)
            self.assertEqual(asset["views"][0]["pose"]["frame"], "opencv")
            self.assertEqual(asset["views"][0]["upload_id"], ctx["upload_id"])
            served = client.get(job["pose_url"])
            self.assertEqual(served.status_code, 200)

    def test_non_finite_numbers_become_null(self) -> None:
        with TestClient(app) as client:
            job_id = _ready_objects(client, ["cat"])["job_ids"][0]
            raw = b'{"version": 2, "object": {"yaw_deg": NaN, "centroid_cam": [1, Infinity, 2]}}'
            job = _post_complete(client, job_id, raw).json()
            self.assertIsNone(job["pose"]["object"]["yaw_deg"])
            self.assertEqual(job["pose"]["object"]["centroid_cam"], [1, None, 2])
            json.loads((main.ARTIFACT_ROOT / job_id / "pose.json").read_text(), parse_constant=self.fail)

    def test_bad_or_oversized_pose_is_ignored_and_the_scan_still_completes(self) -> None:
        with TestClient(app) as client:
            job_id = _ready_objects(client, ["cat"])["job_ids"][0]
            for bad in (b"not json", b"[1, 2]", b'{"no_version": true}', b"{" + b" " * (300 * 1024) + b"}"):
                response = _post_complete(client, job_id, bad)
                self.assertEqual(response.status_code, 200, bad[:20])
                self.assertEqual(response.json()["status"], "complete")
                self.assertIsNone(response.json()["pose"])
                self.assertIsNone(response.json()["pose_url"])

    def test_a_pose_too_big_to_inline_keeps_the_file_and_drops_raw_inline(self) -> None:
        with TestClient(app) as client:
            job_id = _ready_objects(client, ["cat"])["job_ids"][0]
            pose = _pose_v2()
            pose["raw"] = {"points": [0.123456789] * 12000}  # ~150 KB: under the 256 KB cap
            job = _post_complete(client, job_id, json.dumps(pose).encode()).json()
            self.assertNotIn("raw", job["pose"])
            self.assertEqual(job["pose"]["object"]["reprojection_iou"], 0.81)
            stored = json.loads((main.ARTIFACT_ROOT / job_id / "pose.json").read_text())
            self.assertEqual(len(stored["raw"]["points"]), 12000)


def _scene_doc(upload_id: str | None = None) -> dict:
    doc = {
        "version": 1,
        "frame": "opencv",
        "image_size": [40, 30],
        "intrinsics": {"fx": 30.0, "fy": 30.0, "cx": 20.0, "cy": 15.0},
        "gravity_up_cam": [0, -1, 0],
        "splat": {"file": "scene.ply", "count": 3, "source": "apple-sharp", "aligned_scale": 1.0},
    }
    if upload_id:
        doc["upload_id"] = upload_id
    return doc


_SCENE_PLY = b"ply\nformat binary_little_endian 1.0\nelement vertex 0\nend_header\n"


def _post_scene(client: "TestClient", job_id: str, doc=None, ply: bytes | None = _SCENE_PLY,
                analysis: bytes | None = None, raw_json: bytes | None = None, **data):
    body = raw_json if raw_json is not None else json.dumps(doc).encode()
    files = {"scene_json": ("scene.json", io.BytesIO(body), "application/json")}
    if ply is not None:
        files["scene_ply"] = ("scene.ply", io.BytesIO(ply), "application/octet-stream")
    if analysis is not None:
        files["analysis_json"] = ("analysis.json", io.BytesIO(analysis), "application/json")
    return client.post(f"/v1/internal/reconstructions/{job_id}/scene", data=data, files=files)


class WorkerSceneRouteTests(unittest.TestCase):
    """Contract 2: GET/POST /v1/internal/reconstructions/{job_id}/scene."""

    def test_capture_round_trip_records_scene_key_on_upload_and_every_view(self) -> None:
        with TestClient(app) as client:
            ctx = _ready_objects(client, ["cat", "blanket"])
            upload_id, job_id = ctx["upload_id"], ctx["job_ids"][0]

            before = client.get(f"/v1/internal/reconstructions/{job_id}/scene")
            self.assertEqual(before.status_code, 200)
            self.assertEqual(before.json()["upload_id"], upload_id)
            self.assertFalse(before.json()["exists"])
            self.assertTrue(before.json()["image_key"].startswith(f"uploads/{ctx['project_id']}/{upload_id}/"))

            analysis = json.dumps({"room_type": "living room", "caption": "Two cats."}).encode()
            stored = _post_scene(client, job_id, _scene_doc(upload_id), analysis=analysis)
            self.assertEqual(stored.status_code, 200, stored.text)
            key = f"artifacts/scenes/{upload_id}/scene.json"
            self.assertEqual(stored.json()["scene_key"], key)
            self.assertEqual(stored.json()["scene_ply_key"], f"artifacts/scenes/{upload_id}/scene.ply")
            self.assertEqual(stored.json()["analysis_key"], f"artifacts/scenes/{upload_id}/analysis.json")
            self.assertEqual(stored.json()["assets_updated"], 2)
            scene_dir = main.ARTIFACT_ROOT / "scenes" / upload_id
            self.assertEqual(json.loads((scene_dir / "scene.json").read_text())["version"], 1)
            self.assertEqual((scene_dir / "scene.ply").read_bytes(), _SCENE_PLY)
            self.assertTrue((scene_dir / "analysis.json").is_file())

            after = client.get(f"/v1/internal/reconstructions/{ctx['job_ids'][1]}/scene").json()
            self.assertTrue(after["exists"])
            self.assertEqual(after["scene_key"], key)

            upload = client.get(f"/v1/projects/{ctx['project_id']}/uploads/{upload_id}").json()
            self.assertEqual(upload["scene_key"], key)
            assets = client.get(f"/v1/projects/{ctx['project_id']}/assets").json()
            self.assertEqual({view["scene_key"] for asset in assets for view in asset["views"]}, {key})
            for asset_id in ctx["asset_ids"]:  # persisted, not only filled at read time
                self.assertEqual(main.store.get_asset(asset_id).views[0].scene_key, key)

            served = client.get(f"/v1/projects/{ctx['project_id']}/uploads/{upload_id}/scene/scene.json")
            self.assertEqual(served.status_code, 200)
            self.assertEqual(served.json()["splat"]["count"], 3)
            self.assertEqual(
                client.get(f"/v1/projects/{ctx['project_id']}/uploads/{upload_id}/scene/secret.txt").status_code, 404
            )

            # Idempotent overwrite, now without a splat: the old one is kept.
            again = _post_scene(client, job_id, _scene_doc(), ply=None)
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["scene_ply_key"], f"artifacts/scenes/{upload_id}/scene.ply")

    def test_objects_generated_after_the_capture_get_the_scene_key(self) -> None:
        with TestClient(app) as client:
            ctx = _ready_objects(client, ["cat"])
            _post_scene(client, ctx["job_ids"][0], _scene_doc())
            client.post(
                f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}/selections",
                json={"selections": [{"selection_id": "late", "prompt": {"text": "lamp"}}]},
            )
            late = client.post(
                f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}/generate",
                json={"selection_ids": ["late"]},
            ).json()
            asset = main.store.get_asset(late["assets"][0]["asset_id"])
            self.assertEqual(asset.views[0].scene_key, f"artifacts/scenes/{ctx['upload_id']}/scene.json")

    def test_scene_routes_require_the_worker_token(self) -> None:
        with TestClient(app) as client:
            job_id = _ready_objects(client, ["cat"])["job_ids"][0]
            previous = os.environ.get("SKETCHSCAPE_WORKER_TOKEN")
            os.environ["SKETCHSCAPE_WORKER_TOKEN"] = "right-token"
            try:
                self.assertEqual(client.get(f"/v1/internal/reconstructions/{job_id}/scene").status_code, 401)
                self.assertEqual(_post_scene(client, job_id, _scene_doc(), worker_token="wrong").status_code, 401)
                ok = client.get(
                    f"/v1/internal/reconstructions/{job_id}/scene",
                    headers={"X-SketchScape-Worker-Token": "right-token"},
                )
                self.assertEqual(ok.status_code, 200)
                self.assertEqual(_post_scene(client, job_id, _scene_doc(), worker_token="right-token").status_code, 200)
            finally:
                if previous is None:
                    os.environ.pop("SKETCHSCAPE_WORKER_TOKEN", None)
                else:
                    os.environ["SKETCHSCAPE_WORKER_TOKEN"] = previous

    def test_a_job_leased_to_another_worker_is_refused(self) -> None:
        with TestClient(app) as client:
            job_id = _ready_objects(client, ["cat"])["job_ids"][0]
            job = main.store.get_job(job_id)
            job.lease_owner = "gpu-1"
            main.store.save_job(job)
            self.assertEqual(_post_scene(client, job_id, _scene_doc(), worker_id="gpu-2").status_code, 401)
            self.assertEqual(_post_scene(client, job_id, _scene_doc(), worker_id="gpu-1").status_code, 200)

    def test_invalid_scene_uploads_are_rejected(self) -> None:
        with TestClient(app) as client:
            ctx = _ready_objects(client, ["cat"])
            job_id = ctx["job_ids"][0]
            cases = {
                "not json": (b"{nope", _SCENE_PLY, None),
                "non-finite": (b'{"version": 1, "depth_range_m": [0.5, NaN]}', _SCENE_PLY, None),
                "array": (b"[1]", _SCENE_PLY, None),
                "no version": (b'{"frame": "opencv"}', _SCENE_PLY, None),
                "other upload": (json.dumps(_scene_doc("someone-else")).encode(), _SCENE_PLY, None),
                "not a ply": (json.dumps(_scene_doc()).encode(), b"GIF89a....", None),
                "bad analysis": (json.dumps(_scene_doc()).encode(), _SCENE_PLY, b"[]"),
            }
            for name, (raw, ply, analysis) in cases.items():
                response = _post_scene(client, job_id, raw_json=raw, ply=ply, analysis=analysis)
                self.assertEqual(response.status_code, 422, name)
            too_big = b'{"version": 1, "pad": "' + b"x" * (2 * 1024 * 1024) + b'"}'
            self.assertEqual(_post_scene(client, job_id, raw_json=too_big).status_code, 413)
            big_analysis = b'{"pad": "' + b"x" * (256 * 1024) + b'"}'
            self.assertEqual(
                _post_scene(client, job_id, _scene_doc(), analysis=big_analysis).status_code, 413
            )
            from unittest.mock import patch

            with patch.object(main, "MAX_SCENE_PLY_BYTES", 64):
                oversized = _SCENE_PLY + b"\0" * 100
                self.assertEqual(_post_scene(client, job_id, _scene_doc(), ply=oversized).status_code, 413)
            # Nothing was stored by the rejected attempts.
            self.assertFalse(client.get(f"/v1/internal/reconstructions/{job_id}/scene").json()["exists"])
            upload = client.get(f"/v1/projects/{ctx['project_id']}/uploads/{ctx['upload_id']}").json()
            self.assertIsNone(upload["scene_key"])

    def test_a_scene_stored_straight_into_storage_shows_on_the_assets(self) -> None:
        import asyncio

        with TestClient(app) as client:
            ctx = _ready_objects(client, ["cat"])
            upload_id = ctx["upload_id"]
            assets = client.get(f"/v1/projects/{ctx['project_id']}/assets").json()
            self.assertIsNone(assets[0]["views"][0]["scene_key"])
            # worker/backfill_scenes.py writes the files without the callback.
            asyncio.run(main.artifact_store.put(
                f"scenes/{upload_id}", "scene.json",
                main._bytes_upload_file(json.dumps(_scene_doc(upload_id)).encode(), "scene.json"),
                size_limit=1 << 20,
            ))
            assets = client.get(f"/v1/projects/{ctx['project_id']}/assets").json()
            self.assertEqual(assets[0]["views"][0]["scene_key"], f"artifacts/scenes/{upload_id}/scene.json")
            self.assertEqual(assets[0]["views"][0]["upload_id"], upload_id)
            one = client.get(f"/v1/projects/{ctx['project_id']}/assets/{assets[0]['asset_id']}").json()
            self.assertEqual(one["views"][0]["scene_key"], f"artifacts/scenes/{upload_id}/scene.json")

    def test_standalone_job_uses_its_own_id_as_the_scene_id(self) -> None:
        with TestClient(app) as client:
            job_id = client.post(
                "/v1/reconstructions",
                data={"subject_hint": "mug"},
                files={"image": ("mug.png", io.BytesIO(_png_bytes()), "image/png")},
            ).json()["job_id"]
            info = client.get(f"/v1/internal/reconstructions/{job_id}/scene").json()
            self.assertEqual(info["upload_id"], job_id)
            stored = _post_scene(client, job_id, _scene_doc())
            self.assertEqual(stored.status_code, 200, stored.text)
            self.assertTrue((main.ARTIFACT_ROOT / "scenes" / job_id / "scene.json").is_file())

    def test_unknown_job_is_404(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/v1/internal/reconstructions/nope/scene").status_code, 404)
            self.assertEqual(_post_scene(client, "nope", _scene_doc()).status_code, 404)


class AutoGenerateAfterSegmentationTests(unittest.TestCase):
    """An upload that asked for its objects (`detect`/`objects`) gets its
    reconstruct jobs queued by the backend once the GPU segment pass ends."""

    def test_detected_objects_are_segmented_then_queued_for_reconstruction(self) -> None:
        from unittest.mock import patch

        import subject_labeler as sl

        label = sl.SubjectLabel(
            label="sofa", backend="gpu:test-vlm", alternatives=["floor lamp", "Sofa", "rug"],
            # 40x30 photo: the lamp's box is clamped, the rug's is degenerate.
            boxes={"sofa": [1, 2, 30, 20], "floor lamp": [-4, 0, 99, 25], "rug": [5, 5, 5.5, 9]},
        )
        with TestClient(app) as client, patch.object(main.subject_labeler, "identify_subject", return_value=label):
            _drain_queue(client)
            project_id = client.post("/v1/projects", json={"name": "auto", "description": ""}).json()["project_id"]
            with _AwsLocalMode():
                created = client.post(
                    f"/v1/projects/{project_id}/uploads",
                    data={"detect": "true"},
                    files={"image": ("room.png", io.BytesIO(_png_bytes()), "image/png")},
                )
                self.assertEqual(created.status_code, 201, created.text)
                body = created.json()
                self.assertEqual(body["objects_mode"], "detected")
                self.assertEqual([s["label"] for s in body["selections"]], ["sofa", "floor lamp", "rug"])
                segment_job = main.store.get_job(body["job_id"])
                self.assertEqual(segment_job.kind, "segment")
                self.assertTrue(segment_job.auto_generate)
                self.assertEqual(segment_job.subject_label_backend, "gpu:test-vlm")

                claim = client.post(
                    "/v1/internal/jobs/claim", json={"worker_id": "gpu-1", "kinds": ["segment"]}
                ).json()
                self.assertEqual(claim["job_id"], body["job_id"])
                # The segmenter gets each object's box to pick that instance.
                task = client.get(f"/v1/internal/reconstructions/{body['job_id']}/selections").json()
                self.assertEqual(
                    [s["box"] for s in task["selections"]], [[1.0, 2.0, 30.0, 20.0], [0.0, 0.0, 40.0, 25.0], None]
                )
                for index, selection in enumerate(body["selections"]):
                    status = "failed" if index == 2 else "segmented"
                    client.post(
                        f"/v1/internal/reconstructions/{body['job_id']}/selections/{selection['selection_id']}/result",
                        data={"worker_id": "gpu-1", "result": json.dumps({"status": status, "score": 0.8, "reason": "none"})},
                        files={"mask": ("mask.png", io.BytesIO(_mask_bytes()), "image/png")},
                    )
                # Two reconstruct jobs are queued for the dispatcher; the failed rug is not.
                jobs = [job for job in main.store.list_project_jobs(project_id) if job.kind == "reconstruct"]
                self.assertEqual(len(jobs), 2)
                self.assertEqual({job.status for job in jobs}, {"queued"})
                self.assertEqual({job.subject_hint for job in jobs}, {"sofa", "floor lamp"})
                upload = client.get(f"/v1/projects/{project_id}/uploads/{body['upload_id']}").json()
                self.assertEqual(
                    sorted(s["status"] for s in upload["selections"]), ["failed", "generated", "generated"]
                )
                # A late /generate for the same objects is refused, not doubled.
                again = client.post(
                    f"/v1/projects/{project_id}/uploads/{body['upload_id']}/generate",
                    json={"selection_ids": [body["selections"][0]["selection_id"]]},
                )
                self.assertEqual(again.status_code, 409)
            _drain_queue(client)


if __name__ == "__main__":
    unittest.main()
