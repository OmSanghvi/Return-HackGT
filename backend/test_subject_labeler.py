"""NemoClaw identify_subject labeling (Build Plan step 4a).

Run with: python -m unittest test_subject_labeler.py
"""

import io
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


if __name__ == "__main__":
    unittest.main()
