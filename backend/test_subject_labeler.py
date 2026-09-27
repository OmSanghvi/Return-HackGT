"""NemoClaw identify_subject labeling (Build Plan step 4a).

Run with: python -m unittest test_subject_labeler.py
"""

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["PIPELINE_MODE"] = "mock"
os.environ["SKETCHSCAPE_SUBJECT_LABELER"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
import subject_labeler as sl  # noqa: E402

app = main.app
_IMAGE = b"not-a-real-png"


class LabelerBackendTests(unittest.TestCase):
    def test_default_backend_is_mock(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKETCHSCAPE_SUBJECT_LABELER", None)
            self.assertIsInstance(sl.create_subject_labeler(), sl.MockSubjectLabeler)

    def test_unknown_backend_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            sl.create_subject_labeler(backend="gpt")

    def test_mock_labels_descriptive_filenames(self) -> None:
        labeler = sl.MockSubjectLabeler()
        label = labeler.identify_subject(Path("x"), "Wicker_Armchair-2.jpg")
        self.assertEqual(label.label, "wicker armchair 2")
        self.assertEqual(label.backend, "mock")
        self.assertEqual(labeler.identify_subject(Path("x"), "blue-backpack.png").label, "blue backpack")

    def test_mock_returns_none_for_camera_names(self) -> None:
        labeler = sl.MockSubjectLabeler()
        for name in ("IMG_1234.jpg", "PXL_20260924_101500.jpg", "DSC-0042.png", "1234.png", ""):
            self.assertIsNone(labeler.identify_subject(Path("x"), name), name)

    def test_nemoclaw_backend_is_selectable(self) -> None:
        self.assertIsInstance(sl.create_subject_labeler(backend="nemoclaw"), sl.NemoClawSubjectLabeler)


class _FakeNemoClaw:
    """Records the shell commands the live labeler runs; answers the exec call."""

    def __init__(self, exec_stdout: bytes, exec_code: int = 0, fail_on: str = "") -> None:
        self.calls: list[list[str]] = []
        self.stdin: list[bytes] = []
        self.exec_stdout = exec_stdout
        self.exec_code = exec_code
        self.fail_on = fail_on

    def __call__(self, argv, input=None, capture_output=True, check=False):  # noqa: A002
        from subprocess import CompletedProcess

        self.calls.append(argv)
        self.stdin.append(input)
        script = argv[-1]
        if self.fail_on and self.fail_on in script:
            return CompletedProcess(argv, 1, b"", b"boom")
        if " exec -- " in script:
            return CompletedProcess(argv, self.exec_code, self.exec_stdout, b"")
        return CompletedProcess(argv, 0, b"", b"")


class NemoClawLabelerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.photo = Path(self._tmp.name) / "photo.JPG"
        self.photo.write_bytes(b"jpeg-bytes")

    def test_runs_the_skill_inside_the_sandbox_and_returns_all_labels(self) -> None:
        fake = _FakeNemoClaw(b'noise\n{"labels": ["brown tabby cat", "pink blanket"], "backend": "nemoclaw:muse-spark-1.3"}\n')
        labeler = sl.NemoClawSubjectLabeler(sandbox="sketchscape", wsl_distro="Ubuntu", run=fake)
        label = labeler.identify_subject(self.photo, "IMG_1.jpg")
        self.assertEqual(label.label, "brown tabby cat")
        self.assertEqual(label.alternatives, ["pink blanket"])
        self.assertEqual(label.backend, "nemoclaw:muse-spark-1.3")
        stage, upload, run = (call[-1] for call in fake.calls)
        self.assertEqual(fake.calls[0][:4], ["wsl.exe", "-d", "Ubuntu", "--"])
        self.assertEqual(fake.stdin[0], b"jpeg-bytes")
        self.assertIn("timeout 90 nemoclaw sketchscape upload", upload)
        self.assertIn(f"timeout 300 nemoclaw sketchscape exec -- python3 {sl.SKILL_DIR}/backend/nemoclaw_vision.py /tmp/", run)
        self.assertIn(".jpg --max 8 --cleanup", run)
        for script in (stage, upload, run):
            self.assertNotIn("'", script)
            self.assertNotIn('"', script)

    def test_mask_asks_for_the_masked_object_only(self) -> None:
        mask = Path(self._tmp.name) / "mask.png"
        mask.write_bytes(b"png")
        fake = _FakeNemoClaw(b'{"labels": ["white tv remote"], "backend": "nemoclaw:muse-spark-1.3"}')
        labels, _ = sl.NemoClawSubjectLabeler(wsl_distro="", run=fake).labels(self.photo, mask_path=mask, max_labels=1)
        self.assertEqual(labels, ["white tv remote"])
        self.assertEqual(fake.calls[0][:2], ["bash", "-lc"])
        self.assertRegex(fake.calls[-1][-1], r"--mask /tmp/[0-9a-f]{32}\.png --max 1")

    def test_failures_raise_subject_label_error(self) -> None:
        cases = [
            _FakeNemoClaw(b'{"error": "URLError: 502"}'),
            _FakeNemoClaw(b"no json at all", exec_code=124),
            _FakeNemoClaw(b"", fail_on="upload"),
        ]
        for fake in cases:
            with self.assertRaises(sl.SubjectLabelError):
                sl.NemoClawSubjectLabeler(wsl_distro="", run=fake).identify_subject(self.photo, "x.jpg")

    def test_no_labels_means_none(self) -> None:
        fake = _FakeNemoClaw(b'{"labels": [], "backend": "nemoclaw:muse-spark-1.3"}')
        self.assertIsNone(sl.NemoClawSubjectLabeler(wsl_distro="", run=fake).identify_subject(self.photo, "x.jpg"))

    def test_rejects_unsafe_sandbox_names(self) -> None:
        with self.assertRaises(sl.SubjectLabelError):
            sl.NemoClawSubjectLabeler(sandbox="x; rm -rf ~")


class UploadLabelingTests(unittest.TestCase):
    def upload(self, client: TestClient, filename: str, **kwargs):
        response = client.post(
            "/v1/reconstructions",
            files={"image": (filename, io.BytesIO(_IMAGE), "image/png"), **kwargs.pop("files", {})},
            **kwargs,
        )
        self.assertEqual(response.status_code, 202)
        return client.get(f"/v1/reconstructions/{response.json()['job_id']}").json()

    def test_nemoclaw_labels_upload_without_hint(self) -> None:
        with TestClient(app) as client:
            job = self.upload(client, "wicker-armchair.png")
        self.assertEqual(job["subject_hint"], "wicker armchair")
        self.assertEqual(job["subject_hint_source"], "nemoclaw")
        self.assertEqual(job["subject_label_backend"], "mock")

    def test_typed_hint_is_never_overwritten(self) -> None:
        with TestClient(app) as client:
            job = self.upload(client, "wicker-armchair.png", data={"subject_hint": "rattan chair"})
        self.assertEqual(job["subject_hint"], "rattan chair")
        self.assertEqual(job["subject_hint_source"], "user")
        self.assertIsNone(job["subject_label_backend"])

    def test_unlabelable_upload_keeps_empty_hint(self) -> None:
        with TestClient(app) as client:
            job = self.upload(client, "IMG_1234.png")
        self.assertIsNone(job["subject_hint"])
        self.assertIsNone(job["subject_hint_source"])

    def test_uploaded_mask_skips_labeling(self) -> None:
        with TestClient(app) as client, patch.object(
            main.subject_labeler, "identify_subject", side_effect=AssertionError("called")
        ):
            job = self.upload(
                client,
                "wicker-armchair.png",
                files={"mask": ("mask.png", io.BytesIO(_IMAGE), "image/png")},
            )
        self.assertIsNone(job["subject_hint"])

    def test_unavailable_labeler_does_not_fail_upload(self) -> None:
        with TestClient(app) as client, patch.object(
            main, "subject_labeler", sl.NemoClawSubjectLabeler(wsl_distro="", run=_FakeNemoClaw(b"", fail_on="upload"))
        ):
            job = self.upload(client, "wicker-armchair.png")
        self.assertEqual(job["status"], "complete")
        self.assertIsNone(job["subject_hint"])

    def test_project_asset_view_records_label_provenance(self) -> None:
        with TestClient(app) as client:
            project_id = client.post("/v1/projects", json={"name": "Labels"}).json()["project_id"]
            asset = client.post(
                f"/v1/projects/{project_id}/assets",
                files={"image": ("ceramic-mug.png", io.BytesIO(_IMAGE), "image/png")},
            ).json()
            view = client.post(
                f"/v1/projects/{project_id}/assets/{asset['asset_id']}/views",
                files={"image": ("ceramic-mug-side.png", io.BytesIO(_IMAGE), "image/png")},
            ).json()
        self.assertEqual(asset["label"], "ceramic mug")
        self.assertEqual(asset["views"][0]["subject_hint_source"], "nemoclaw")
        self.assertEqual(view["subject_hint"], "ceramic mug side")
        self.assertEqual(view["subject_hint_source"], "nemoclaw")


class DetectObjectsTests(unittest.TestCase):
    def test_every_label_becomes_a_suggestion_deduped_and_capped(self) -> None:
        label = sl.SubjectLabel(
            label="brown tabby cat", backend="nemoclaw:muse-spark-1.3",
            alternatives=["pink blanket", "Brown Tabby Cat", "white tv remote", "red couch"],
        )
        with TestClient(app) as client, patch.object(
            main.subject_labeler, "identify_subject", return_value=label
        ), patch.dict(os.environ, {"SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD": "3"}):
            project_id = client.post("/v1/projects", json={"name": "Detect"}).json()["project_id"]
            upload = client.post(
                f"/v1/projects/{project_id}/uploads",
                files={"image": ("IMG_1.png", io.BytesIO(_png()), "image/png")},
            )
            self.assertIn(upload.status_code, (200, 201), upload.text)
            upload_id = upload.json()["upload_id"]
            detected = client.post(f"/v1/projects/{project_id}/uploads/{upload_id}/detect")
            self.assertEqual(detected.status_code, 202, detected.text)
            job = client.get(f"/v1/reconstructions/{detected.json()['job_id']}").json()
            selections = client.get(f"/v1/projects/{project_id}/uploads/{upload_id}").json()["selections"]
        self.assertEqual([s["label"] for s in selections], ["brown tabby cat", "pink blanket", "white tv remote"])
        self.assertTrue(all(s["origin"] == "suggested" for s in selections))
        self.assertEqual(job["subject_label_backend"], "nemoclaw:muse-spark-1.3")


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 50, 50)).save(buffer, format="PNG")
    return buffer.getvalue()

class _FakeVlmResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class _FakeVlm:
    """Stands in for urllib's urlopen against worker/vlm_server.py."""

    def __init__(self, body: bytes = b"", error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.requests: list = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return _FakeVlmResponse(self.body)


class GpuLabelerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.photo = Path(self.dir.name) / "photo.png"
        self.photo.write_bytes(_png())

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_gpu_backend_is_selectable_and_reads_its_url(self) -> None:
        with patch.dict(os.environ, {"SKETCHSCAPE_VLM_URL": "http://127.0.0.1:9999/"}):
            labeler = sl.create_subject_labeler(backend="gpu")
        self.assertIsInstance(labeler, sl.GpuSubjectLabeler)
        self.assertEqual(labeler.url, "http://127.0.0.1:9999")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SKETCHSCAPE_VLM_URL", None)
            self.assertEqual(sl.GpuSubjectLabeler().url, "http://127.0.0.1:8003")

    def test_detect_request_and_every_object_in_salience_order(self) -> None:
        body = json.dumps({
            "model": "qwen2.5-vl-7b",
            "objects": [
                {"name": "Floor lamp", "box": [1, 2, 3, 4], "salient": False},
                {"name": "tabby cat", "box": [5, 6, 7, 8], "salient": True},
                {"name": "wall", "box": None, "salient": True},
                {"name": "a red sofa", "box": None, "salient": True},
                {"name": "Tabby Cat", "box": [0, 0, 1, 1], "salient": True},
                {"name": 42},
                "junk",
            ],
        }).encode()
        fake = _FakeVlm(body)
        label = sl.GpuSubjectLabeler(url="http://vlm", timeout=5, opener=fake).identify_subject(self.photo, "x.jpg")
        self.assertEqual(label.label, "tabby cat")
        self.assertEqual(label.alternatives, ["red sofa", "floor lamp"])
        self.assertEqual(label.backend, "gpu:qwen2.5-vl-7b")
        self.assertEqual(label.boxes["tabby cat"], [5.0, 6.0, 7.0, 8.0])
        request, timeout = fake.requests[0]
        self.assertEqual(request.full_url, "http://vlm/v1/detect")
        self.assertEqual(timeout, 5)
        sent = json.loads(request.data)
        self.assertGreaterEqual(sent["max_objects"], 8)
        self.assertTrue(sent["image_b64"])

    def test_large_photos_are_downscaled_and_boxes_mapped_back(self) -> None:
        from PIL import Image

        big = Path(self.dir.name) / "big.jpg"
        Image.new("RGB", (2560, 1600), (10, 120, 200)).save(big, format="JPEG")
        body = json.dumps({"objects": [{"name": "sofa", "box": [100, 200, 640, 400], "salient": True}]}).encode()
        fake = _FakeVlm(body)
        label = sl.GpuSubjectLabeler(url="http://vlm", timeout=5, opener=fake).identify_subject(big, "big.jpg")
        sent = json.loads(fake.requests[0][0].data)
        with Image.open(io.BytesIO(base64.b64decode(sent["image_b64"]))) as img:
            self.assertEqual(img.size, (1280, 800))
        self.assertEqual(label.boxes["sofa"], [200.0, 400.0, 1280.0, 800.0])

    def test_numbered_instances_collapse_into_one_name(self) -> None:
        body = json.dumps({"objects": [
            {"name": "wooden chair", "box": [1, 1, 5, 5]},
            {"name": "wooden chair 2", "box": [9, 9, 12, 12]},
            {"name": "Wooden Chair #3"},
            {"name": "rug"},
            {"name": "left striped cat"},
            {"name": "right striped cat"},
        ]}).encode()
        label = sl.GpuSubjectLabeler(url="http://vlm", timeout=5, opener=_FakeVlm(body)).identify_subject(self.photo, "x")
        self.assertEqual([label.label, *label.alternatives], ["wooden chair", "rug", "left striped cat", "right striped cat"])
        self.assertEqual(label.boxes["wooden chair"], [1.0, 1.0, 5.0, 5.0])

    def test_the_cap_keeps_the_largest_salient_objects(self) -> None:
        body = json.dumps({"objects": [
            {"name": "microwave oven", "box": [0, 0, 10, 10], "salient": True},
            {"name": "green sofa", "box": [0, 0, 400, 300], "salient": True},
            {"name": "painting", "box": None, "salient": True},
            {"name": "huge wall shelf", "box": [0, 0, 900, 900], "salient": False},
            {"name": "rug", "box": [0, 0, 300, 100], "salient": True},
        ]}).encode()
        with patch.dict(os.environ, {"SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD": "3"}):
            label = sl.GpuSubjectLabeler(opener=_FakeVlm(body)).identify_subject(self.photo, "x.jpg")
        self.assertEqual([label.label, *label.alternatives], ["green sofa", "rug", "microwave oven"])

    def test_names_are_capped_at_the_per_upload_limit(self) -> None:
        body = json.dumps({"objects": [{"name": f"thing {chr(97 + i)}{chr(97 + i)}"} for i in range(20)]}).encode()
        with patch.dict(os.environ, {"SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD": "5"}):
            label = sl.GpuSubjectLabeler(opener=_FakeVlm(body)).identify_subject(self.photo, "x.jpg")
        self.assertEqual(1 + len(label.alternatives), 5)
        self.assertEqual(label.backend, "gpu")

    def test_failures_raise_subject_label_error_only(self) -> None:
        import urllib.error

        cases = [
            _FakeVlm(error=urllib.error.URLError("connection refused")),
            _FakeVlm(error=TimeoutError("timed out")),
            _FakeVlm(error=urllib.error.HTTPError("http://vlm", 500, "boom", {}, None)),
            _FakeVlm(b"<html>"),
            _FakeVlm(b'{"objects": "nope"}'),
            _FakeVlm(b"[]"),
            _FakeVlm(b"{" + b" " * (1024 * 1024 + 10) + b"}"),
        ]
        for fake in cases:
            with self.assertRaises(sl.SubjectLabelError):
                sl.GpuSubjectLabeler(opener=fake).identify_subject(self.photo, "x.jpg")

    def test_only_background_means_no_label(self) -> None:
        body = json.dumps({"objects": [{"name": "wall"}, {"name": "Floor"}, {"name": " "}]}).encode()
        self.assertIsNone(sl.GpuSubjectLabeler(opener=_FakeVlm(body)).identify_subject(self.photo, "x.jpg"))

    def test_clean_object_names(self) -> None:
        self.assertEqual(
            sl.clean_object_names(["The Cat!", "cat", "an old  armchair", "ceiling", "x", "left cat"], limit=8),
            ["cat", "old armchair", "left cat"],
        )

    def test_a_down_vision_server_never_fails_detect_or_upload(self) -> None:
        import urllib.error

        broken = sl.GpuSubjectLabeler(opener=_FakeVlm(error=urllib.error.URLError("refused")))
        with TestClient(app) as client, patch.object(main, "subject_labeler", broken):
            project_id = client.post("/v1/projects", json={"name": "Down"}).json()["project_id"]
            created = client.post(
                f"/v1/projects/{project_id}/uploads",
                data={"detect": "true"},
                files={"image": ("IMG_1.png", io.BytesIO(_png()), "image/png")},
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["objects_mode"], "nothing_detected")
            self.assertIsNone(created.json()["job_id"])
            detected = client.post(f"/v1/projects/{project_id}/uploads/{created.json()['upload_id']}/detect")
            self.assertEqual(detected.status_code, 202)
            self.assertIsNone(detected.json()["job_id"])

    def test_a_labeler_bug_never_fails_an_upload(self) -> None:
        with TestClient(app) as client, patch.object(
            main.subject_labeler, "identify_subject", side_effect=KeyError("bug")
        ):
            response = client.post(
                "/v1/reconstructions", files={"image": ("sofa.png", io.BytesIO(_IMAGE), "image/png")}
            )
        self.assertEqual(response.status_code, 202)

    def test_gpu_labels_are_recorded_as_gpu_hints(self) -> None:
        label = sl.SubjectLabel(label="tabby cat", backend="gpu:qwen", alternatives=["sofa"])
        with TestClient(app) as client, patch.object(main.subject_labeler, "identify_subject", return_value=label):
            job_id = client.post(
                "/v1/reconstructions", files={"image": ("IMG_2.png", io.BytesIO(_IMAGE), "image/png")}
            ).json()["job_id"]
            job = client.get(f"/v1/reconstructions/{job_id}").json()
        self.assertEqual(job["subject_hint"], "tabby cat")
        self.assertEqual(job["subject_hint_source"], "gpu")
        self.assertEqual(job["subject_label_backend"], "gpu:qwen")


if __name__ == "__main__":
    unittest.main()
