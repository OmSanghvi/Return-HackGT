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

    def test_nemoclaw_backend_needs_runtime(self) -> None:
        with self.assertRaises(sl.SubjectLabelError):
            sl.create_subject_labeler(backend="nemoclaw").identify_subject(Path("x"), "mug.png")


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
            main, "subject_labeler", sl.NemoClawSubjectLabeler()
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


if __name__ == "__main__":
    unittest.main()
