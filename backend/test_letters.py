"""Letters: sealed/opened access, recipient-only open, scene emission.

Build Plan step 28 (letters-backend-and-web). Written but NOT run per the
task instructions -- run with `python -m unittest test_letters.py`.
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

import jsonschema  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

app = main.app
SCENE_SCHEMA = json.loads(
    (Path(__file__).resolve().parent.parent / "shared" / "scene.schema.json").read_text("utf-8")
)

A_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as"
    b"\x00\x00\x00\nIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _tiny_png_file(name: str = "page.png"):
    return (name, io.BytesIO(A_PNG), "image/png")


class LettersTestCase(unittest.TestCase):
    """Shared fixture: a project with an author + two recipients."""

    def setUp(self) -> None:
        main.current_scene = main.placeholder_scene()
        self.client = TestClient(app)
        self.client.__enter__()
        project = self.client.post(
            "/v1/projects",
            json={"name": "Letters room"},
            headers={"X-SketchScape-Dev-User": "author-dev"},
        ).json()
        self.project_id = project["project_id"]
        contributors = self.client.get(f"/v1/projects/{self.project_id}/contributors").json()
        self.author_id = contributors[0]["contributor_id"]
        self.recipient1_id = self.client.post(
            f"/v1/projects/{self.project_id}/contributors",
            json={"display_name": "Recipient One"},
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        ).json()["contributor_id"]
        self.recipient2_id = self.client.post(
            f"/v1/projects/{self.project_id}/contributors",
            json={"display_name": "Recipient Two"},
            headers={"X-SketchScape-Dev-User": "recipient2-dev"},
        ).json()["contributor_id"]

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def _create_letter(self, recipient_ids, **extra):
        data = {
            "author_contributor_id": self.author_id,
            "recipient_contributor_ids": recipient_ids,
            **extra,
        }
        return self.client.post(
            f"/v1/projects/{self.project_id}/letters",
            data=data,
            files={"page": _tiny_png_file()},
        )


class LetterValidationTests(LettersTestCase):
    def test_unknown_recipient_is_rejected(self) -> None:
        response = self._create_letter(["not-a-contributor"])
        self.assertEqual(response.status_code, 422)

    def test_author_as_only_recipient_is_rejected(self) -> None:
        response = self._create_letter([self.author_id])
        self.assertEqual(response.status_code, 422)

    def test_valid_letter_is_created_and_ready(self) -> None:
        response = self._create_letter([self.recipient1_id, self.recipient2_id], note_text="Hi")
        self.assertEqual(response.status_code, 201)
        letter = response.json()
        self.assertEqual(letter["note_text"], "Hi")
        self.assertEqual(letter["envelope_style"], "classic")
        asset = self.client.get(f"/v1/projects/{self.project_id}/assets/{letter['asset_id']}").json()
        self.assertEqual(asset["status"], "ready")
        self.assertEqual(asset["kind"], "letter")


class LetterOpenTests(LettersTestCase):
    def setUp(self) -> None:
        super().setUp()
        # Addressed to recipient1 only, so recipient2 is a genuine
        # non-recipient for the sealed-access checks below.
        self.letter_id = self._create_letter([self.recipient1_id]).json()["letter_id"]

    def test_non_recipient_cannot_open(self) -> None:
        response = self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{self.letter_id}/open",
            headers={"X-SketchScape-Dev-User": "author-dev"},
        )
        self.assertEqual(response.status_code, 403)

    def test_recipient_can_open(self) -> None:
        response = self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{self.letter_id}/open",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["opened"])
        self.assertEqual(body["opened_by"], self.recipient1_id)

    def test_second_open_is_idempotent(self) -> None:
        first = self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{self.letter_id}/open",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        ).json()
        second = self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{self.letter_id}/open",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["opened_by"], first["opened_by"])
        letters = self.client.get(f"/v1/projects/{self.project_id}/letters").json()
        self.assertEqual(letters[0]["opened_by"], [self.recipient1_id])

    def test_sealed_page_hidden_then_shown_after_open(self) -> None:
        # recipient2 was never addressed on this letter -- sealed, hidden.
        sealed_view = self.client.get(
            f"/v1/projects/{self.project_id}/letters",
            headers={"X-SketchScape-Dev-User": "recipient2-dev"},
        ).json()[0]
        self.assertTrue(sealed_view["sealed"])
        self.assertIsNone(sealed_view["image_url"])
        self.assertIsNone(sealed_view["note_text"])

        texture_before_non_recipient = self.client.get(
            f"/v1/projects/{self.project_id}/letters/{self.letter_id}/texture",
            headers={"X-SketchScape-Dev-User": "recipient2-dev"},
        )
        self.assertEqual(texture_before_non_recipient.status_code, 403)

        texture_before_recipient = self.client.get(
            f"/v1/projects/{self.project_id}/letters/{self.letter_id}/texture",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        )
        self.assertEqual(texture_before_recipient.status_code, 200)

        # recipient1 opens; now everyone (including recipient2) can see it.
        self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{self.letter_id}/open",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        )
        after_open = self.client.get(
            f"/v1/projects/{self.project_id}/letters/{self.letter_id}/texture",
            headers={"X-SketchScape-Dev-User": "recipient2-dev"},
        )
        self.assertEqual(after_open.status_code, 200)


class RoomStateLetterTests(LettersTestCase):
    def test_room_state_includes_letters_and_etag_flips_after_open(self) -> None:
        letter = self._create_letter([self.recipient1_id]).json()
        blueprint = {
            "experience": {"mode": "vr", "theme": "letters"},
            "objects": [
                {
                    "id": "letter_obj",
                    "asset_id": letter["asset_id"],
                    "position": [0, 0, 1],
                    "scale": [1, 1, 1],
                    "interactions": ["inspect"],
                }
            ],
        }
        created = self.client.post(f"/v1/projects/{self.project_id}/blueprints", json=blueprint)
        self.assertEqual(created.status_code, 201)
        published = self.client.post(f"/v1/projects/{self.project_id}/blueprints/1/publish")
        self.assertEqual(published.status_code, 200)

        scene_object = published.json()["scene"]["objects"][0]
        self.assertEqual(scene_object["source"], "letter")
        self.assertIsNone(scene_object["asset_url"])
        self.assertEqual(scene_object["letter"]["letter_id"], letter["letter_id"])
        jsonschema.validate(published.json()["scene"], SCENE_SCHEMA)

        state = self.client.get(f"/v1/rooms/{self.project_id}/state").json()
        self.assertEqual(len(state["letters"]), 1)
        self.assertFalse(state["letters"][0]["opened"])
        etag = self.client.get(f"/v1/rooms/{self.project_id}/state").headers["etag"]

        not_modified = self.client.get(
            f"/v1/rooms/{self.project_id}/state", headers={"If-None-Match": etag}
        )
        self.assertEqual(not_modified.status_code, 304)

        self.client.post(
            f"/v1/rooms/{self.project_id}/letters/{letter['letter_id']}/open",
            headers={"X-SketchScape-Dev-User": "recipient1-dev"},
        )

        # The old ETag must no longer 304 -- letters_version changed.
        stale = self.client.get(
            f"/v1/rooms/{self.project_id}/state", headers={"If-None-Match": etag}
        )
        self.assertEqual(stale.status_code, 200)
        self.assertTrue(stale.json()["letters"][0]["opened"])


if __name__ == "__main__":
    unittest.main()
