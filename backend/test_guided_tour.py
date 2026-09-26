"""Guided tour contract tests (Build Plan step 30).

Run with `python -m unittest test_guided_tour.py`. Per this task's
instructions these were written but deliberately **not executed** here --
they'll be run on another machine.
"""

import importlib.util
import io
import os
import tempfile
import unittest

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from guided_tour import GuidedTour  # noqa: E402
from guide_validator import grounding_violations  # noqa: E402

app = main.app

_HAS_BOTO3 = importlib.util.find_spec("boto3") is not None
_HAS_MOTO = importlib.util.find_spec("moto") is not None
_HAS_AWS_MOCKS = _HAS_BOTO3 and _HAS_MOTO

if _HAS_AWS_MOCKS:
    from moto import mock_aws  # noqa: E402

    import storage  # noqa: E402
    from test_storage import _TEST_REGION, _create_moto_authoring_table  # noqa: E402


class _TourFixtureMixin:
    """Builds a published, 3-contributor room with a ConnectionInsight --
    the minimum a tour can be composed against. Never exactly two
    contributors (AGENT.md's N-contributor rule)."""

    def _make_project(self, client, name: str = "Tour room") -> str:
        return client.post("/v1/projects", json={"name": name, "description": ""}).json()["project_id"]

    def _contribute(
        self, client, project_id: str, name: str, hint: str, memory: str, source_type: str = "photo"
    ) -> dict:
        contributor = client.post(
            f"/v1/projects/{project_id}/contributors", json={"display_name": name}
        ).json()
        r = client.post(
            f"/v1/projects/{project_id}/assets",
            data={"subject_hint": hint},
            files={"image": (f"{hint}.png", io.BytesIO(b"PNG-DATA"), "image/png")},
        )
        asset = client.get(f"/v1/projects/{project_id}/assets/{r.json()['asset_id']}").json()
        r = client.post(
            f"/v1/projects/{project_id}/contributions",
            json={
                "contributor_id": contributor["contributor_id"],
                "asset_id": asset["asset_id"],
                "source_type": source_type,
                "memory_text": memory,
            },
        )
        return r.json()

    def _build_and_publish_room(self, client, contributions: list[dict]) -> tuple[str, dict]:
        composed = client.post(f"/v1/projects/{self.project_id}/connection/compose").json()
        revision = client.post(
            f"/v1/projects/{self.project_id}/blueprints", json=composed["blueprint"]
        ).json()["revision"]
        published = client.post(f"/v1/projects/{self.project_id}/blueprints/{revision}/publish")
        assert published.status_code == 200, published.text
        return revision, composed["insight"]

    def _setup_three_contributor_room(self, client) -> None:
        self.project_id = self._make_project(client)
        self.contributions = [
            self._contribute(client, self.project_id, "Alice", "mug", "My grandma's tea every morning."),
            self._contribute(client, self.project_id, "Bo", "guitar", "The first song I ever learned."),
            self._contribute(client, self.project_id, "Cass", "kite", "We flew this every windy afternoon."),
        ]
        self.revision, self.insight = self._build_and_publish_room(client, self.contributions)


class ComposeTourMockTests(_TourFixtureMixin, unittest.TestCase):
    def test_compose_is_deterministic_for_three_contributors(self) -> None:
        with TestClient(app) as client:
            self._setup_three_contributor_room(client)
            first = client.post(f"/v1/projects/{self.project_id}/tours/compose")
            self.assertEqual(first.status_code, 201, first.text)
            second = client.post(f"/v1/projects/{self.project_id}/tours/compose")
            self.assertEqual(second.status_code, 201, second.text)
            f, s = first.json(), second.json()
            for key in ("facts", "elements", "steps", "theme", "persona", "guardrails", "authored_by"):
                self.assertEqual(f[key], s[key], key)
            self.assertEqual(f["tour_version"], 1)
            self.assertEqual(s["tour_version"], 2)

    def test_compose_is_deterministic_for_four_contributors(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            self.project_id = pid
            contributions = [
                self._contribute(client, pid, "Alice", "shell", "Found on the beach the summer we met."),
                self._contribute(client, pid, "Bo", "paddle", "Our first boat on the lake."),
                self._contribute(client, pid, "Cass", "lamp", ""),
                self._contribute(client, pid, "Dev", "towel", "Swimming lessons with my brother."),
            ]
            self._build_and_publish_room(client, contributions)
            first = client.post(f"/v1/projects/{pid}/tours/compose")
            second = client.post(f"/v1/projects/{pid}/tours/compose")
            self.assertEqual(first.status_code, 201, first.text)
            self.assertEqual(first.json()["facts"], second.json()["facts"])

    def test_compose_activate_get_shows_active_and_retires_previous(self) -> None:
        with TestClient(app) as client:
            self._setup_three_contributor_room(client)
            v1 = client.post(f"/v1/projects/{self.project_id}/tours/compose").json()
            v2 = client.post(f"/v1/projects/{self.project_id}/tours/compose").json()

            activate_v1 = client.post(
                f"/v1/projects/{self.project_id}/tours/{v1['tour_version']}/activate",
                json={"expected_active_version": None},
            )
            self.assertEqual(activate_v1.status_code, 200, activate_v1.text)
            self.assertEqual(activate_v1.json()["status"], "active")

            activate_v2 = client.post(
                f"/v1/projects/{self.project_id}/tours/{v2['tour_version']}/activate",
                json={"expected_active_version": v1["tour_version"]},
            )
            self.assertEqual(activate_v2.status_code, 200, activate_v2.text)

            got_v1 = client.get(f"/v1/projects/{self.project_id}/tours/{v1['tour_version']}").json()
            got_v2 = client.get(f"/v1/projects/{self.project_id}/tours/{v2['tour_version']}").json()
            self.assertEqual(got_v1["status"], "retired")
            self.assertEqual(got_v2["status"], "active")

    def test_activate_rejects_service_identity(self) -> None:
        with TestClient(app) as client:
            self._setup_three_contributor_room(client)
            v1 = client.post(f"/v1/projects/{self.project_id}/tours/compose").json()
            os.environ["SKETCHSCAPE_NEMOCLAW_TOKEN"] = "a" * 40
            try:
                r = client.post(
                    f"/v1/projects/{self.project_id}/tours/{v1['tour_version']}/activate",
                    json={"expected_active_version": None},
                    headers={"Authorization": "Bearer " + "a" * 40},
                )
                self.assertEqual(r.status_code, 403)
            finally:
                del os.environ["SKETCHSCAPE_NEMOCLAW_TOKEN"]

    def test_activate_stale_expected_version_is_409(self) -> None:
        with TestClient(app) as client:
            self._setup_three_contributor_room(client)
            v1 = client.post(f"/v1/projects/{self.project_id}/tours/compose").json()
            r = client.post(
                f"/v1/projects/{self.project_id}/tours/{v1['tour_version']}/activate",
                json={"expected_active_version": 999},
            )
            self.assertEqual(r.status_code, 409)

    def test_letter_note_text_never_appears_in_a_fact(self) -> None:
        with TestClient(app) as client:
            self.project_id = self._make_project(client)
            contributions = [
                self._contribute(client, self.project_id, "Alice", "mug", "My grandma's tea every morning."),
                self._contribute(client, self.project_id, "Bo", "guitar", "The first song I ever learned."),
                self._contribute(
                    client, self.project_id, "Cass", "envelope", "meet me at the lake", source_type="letter"
                ),
            ]
            self._build_and_publish_room(client, contributions)
            tour = client.post(f"/v1/projects/{self.project_id}/tours/compose")
            self.assertEqual(tour.status_code, 201, tour.text)
            for fact in tour.json()["facts"]:
                self.assertNotIn("lake", fact["text"].lower())
                self.assertNotIn("meet", fact["text"].lower())


class ValidateGuidedTourRuleTests(_TourFixtureMixin, unittest.TestCase):
    """One 422 per validator rule, each mutating a known-good composed tour."""

    def setUp(self) -> None:
        self.client_cm = TestClient(app)
        self.client = self.client_cm.__enter__()
        self._setup_three_contributor_room(self.client)
        self.good_tour = self.client.post(f"/v1/projects/{self.project_id}/tours/compose").json()

    def tearDown(self) -> None:
        self.client_cm.__exit__(None, None, None)

    def _post(self, tour_input: dict):
        return self.client.post(f"/v1/projects/{self.project_id}/tours", json=tour_input)

    def _tour_input(self) -> dict:
        # Strip GuidedTour-only fields to get back a GuidedTourInput payload.
        keys = (
            "schema_version", "based_on_revision", "persona", "theme", "facts",
            "elements", "steps", "start_step_id", "end_step_ids", "guardrails", "authored_by",
        )
        return {key: self.good_tour[key] for key in keys}

    def test_unknown_object_is_422(self) -> None:
        payload = self._tour_input()
        payload["elements"][0]["object_id"] = "not-a-real-object"
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("element_object", r.json()["detail"])

    def test_wrong_contributor_is_422(self) -> None:
        payload = self._tour_input()
        for element in payload["elements"]:
            if element["kind"] == "contribution":
                element["contributor_display_name"] = "Somebody Else"
                break
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("element_contributor", r.json()["detail"])

    def test_memory_text_not_verbatim_is_422(self) -> None:
        payload = self._tour_input()
        for fact in payload["facts"]:
            if fact["source"]["kind"] == "contribution_memory":
                fact["text"] = "This is not what they wrote."
                break
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("fact_contribution_memory", r.json()["detail"])

    def test_authored_fact_without_derived_from_is_422(self) -> None:
        payload = self._tour_input()
        payload["facts"].append(
            {
                "fact_id": "f_bad_authored",
                "text": "Something connective.",
                "source": {"kind": "authored", "ref_id": None},
                "derived_from": [],
            }
        )
        payload["theme"]["fact_ids"].append("f_bad_authored")
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("fact_authored", r.json()["detail"])

    def test_authored_fact_that_adds_a_name_is_422(self) -> None:
        payload = self._tour_input()
        theme_fact_id = payload["theme"]["fact_ids"][0]
        payload["facts"].append(
            {
                "fact_id": "f_bad_name",
                "text": "Percival visited the room.",
                "source": {"kind": "authored", "ref_id": None},
                "derived_from": [theme_fact_id],
            }
        )
        payload["theme"]["fact_ids"].append("f_bad_name")
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("fact_authored", r.json()["detail"])

    def test_letter_note_text_as_fact_is_422(self) -> None:
        payload = self._tour_input()
        payload["facts"].append(
            {
                "fact_id": "f_bad_letter",
                "text": "This is a sealed letter with a secret message inside it.",
                "source": {"kind": "letter_envelope", "ref_id": None},
                "derived_from": [],
            }
        )
        payload["theme"]["fact_ids"].append("f_bad_letter")
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("fact_letter_envelope", r.json()["detail"])

    def test_unreachable_step_is_422(self) -> None:
        payload = self._tour_input()
        anchor = payload["steps"][0]["stop"]["anchor_element_id"]
        payload["steps"].append(
            {
                "step_id": "s_orphan",
                "title": "Orphan",
                "stop": {"anchor_element_id": anchor, "offset_m": [0.0, 0.0, 0.0]},
                "focus_element_ids": [],
                "reveal_element_ids": [],
                "fact_ids": [],
                "narration": {"text": "Unreachable.", "fact_ids": []},
                "next_step_ids": [],
                "min_dwell_s": 3,
            }
        )
        payload["end_step_ids"].append("s_orphan")
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("step_graph_unreachable", r.json()["detail"])

    def test_hidden_element_never_revealed_is_422(self) -> None:
        payload = self._tour_input()
        anchor = payload["steps"][0]["stop"]["anchor_element_id"]
        payload["elements"].append(
            {
                "element_id": "el_hidden",
                "kind": "motif",
                "object_id": None,
                "contributor_id": None,
                "contributor_display_name": None,
                "label": "",
                "fact_ids": [],
                "staging_cue_id": "cue_1",
                "initially_visible": False,
            }
        )
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("reveal_unreachable", r.json()["detail"])

    def test_over_256kb_is_422(self) -> None:
        """Neither facts (<=400) nor elements (<=200) alone can cross 256 KB at
        their per-field max length, so this pads both close to their count
        caps to cross the byte limit while staying inside both -- the size
        check runs before any reference is resolved, so the padding ids
        don't need to point at anything real."""
        payload = self._tour_input()
        theme_fact_id = payload["theme"]["fact_ids"][0]
        for i in range(min(395, 400 - len(payload["facts"]))):
            payload["facts"].append(
                {
                    "fact_id": f"f_pad_{i}",
                    "text": "x" * 500,
                    "source": {"kind": "authored", "ref_id": None},
                    "derived_from": [theme_fact_id],
                }
            )
        for i in range(min(195, 200 - len(payload["elements"]))):
            payload["elements"].append(
                {
                    "element_id": f"e_pad_{i}",
                    "kind": "environment",
                    "object_id": f"obj_pad_{i}",
                    "contributor_id": None,
                    "contributor_display_name": None,
                    "label": "x" * 200,
                    "fact_ids": [],
                    "staging_cue_id": None,
                    "initially_visible": True,
                }
            )
        r = self._post(payload)
        self.assertEqual(r.status_code, 422)
        self.assertIn("size", r.json()["detail"])


class GroundingViolationsTests(unittest.TestCase):
    def test_grounded_text_has_no_violations(self) -> None:
        self.assertEqual(
            grounding_violations("Maya brought the teapot.", ["Maya brought the teapot."], ["Maya", "teapot"]),
            [],
        )

    def test_new_name_is_a_violation(self) -> None:
        violations = grounding_violations("Percival visited.", ["Maya brought the teapot."], ["Maya"])
        self.assertIn("Percival", violations)

    def test_digit_is_a_violation(self) -> None:
        violations = grounding_violations("It happened in 1994.", ["A fact."], [])
        self.assertIn("1994", violations)

    def test_quoted_span_is_a_violation(self) -> None:
        violations = grounding_violations('She said "hello there".', ["A fact."], [])
        self.assertTrue(any(token.lower() in {"hello", "there"} for token in violations))

    def test_sentence_start_capitalization_is_not_a_violation(self) -> None:
        self.assertEqual(grounding_violations("Welcome. It is warm.", ["A fact."], []), [])


@unittest.skipUnless(_HAS_AWS_MOCKS, "needs both boto3 and moto for a mocked DynamoDB table.")
class DynamoDbTourStorageTests(unittest.TestCase):
    """Round-trips a tour, and its compare-and-set activation, against a
    moto-mocked table -- the same fake the rest of test_storage.py uses."""

    def setUp(self) -> None:
        self._mock = mock_aws()
        self._mock.start()
        _create_moto_authoring_table()
        self.store = storage.DynamoDbStore("sketchscape-authoring-test", region_name=_TEST_REGION)
        self.store.load()

    def tearDown(self) -> None:
        self._mock.stop()

    def _tour(self, project_id: str, version: int) -> GuidedTour:
        return GuidedTour(
            schema_version=1,
            project_id=project_id,
            tour_version=version,
            based_on_revision=1,
            status="draft",
            created_at=main.utc_now(),
            author=None,
            persona={"name": "Lumen", "voice": "mms-tts-eng", "style": "warm"},
            theme={"title": "Home", "fact_ids": ["f_theme"]},
            facts=[
                {
                    "fact_id": "f_theme",
                    "text": "The room's theme is Home.",
                    "source": {"kind": "connection_insight", "ref_id": "insight:1"},
                    "derived_from": [],
                }
            ],
            elements=[],
            steps=[
                {
                    "step_id": "s_welcome",
                    "title": "Welcome",
                    "stop": {"anchor_element_id": "obj_1", "offset_m": [0.0, 0.0, 0.0]},
                    "focus_element_ids": [],
                    "reveal_element_ids": [],
                    "fact_ids": ["f_theme"],
                    "narration": {"text": "Welcome home.", "fact_ids": ["f_theme"]},
                    "next_step_ids": [],
                    "min_dwell_s": 3,
                }
            ],
            start_step_id="s_welcome",
            end_step_ids=["s_welcome"],
            guardrails={"off_topic_reply": "Ask about the room.", "max_lines_per_turn": 3},
            authored_by={"backend": "mock", "model": "mock-tour-v1", "tool": "compose_tour_mock", "prompt_version": None},
        )

    def test_round_trip_and_activation(self) -> None:
        pid = "p_tour_dynamo"
        tour_v1 = self._tour(pid, 1)
        self.store.append_tour(tour_v1)
        tour_v2 = self._tour(pid, 2)
        self.store.append_tour(tour_v2)

        self.assertEqual(len(self.store.list_tours(pid)), 2)
        self.assertEqual(self.store.get_tour(pid, 1).tour_version, 1)
        self.assertIsNone(self.store.get_active_tour_version(pid))

        activated = self.store.activate_tour(pid, None, 1)
        self.assertIsNotNone(activated)
        self.assertEqual(activated.status, "active")
        self.assertEqual(self.store.get_active_tour_version(pid), 1)

        activated_v2 = self.store.activate_tour(pid, 1, 2)
        self.assertEqual(activated_v2.status, "active")
        self.assertEqual(self.store.get_tour(pid, 1).status, "retired")

        # Stale expected version loses the race.
        self.assertIsNone(self.store.activate_tour(pid, 1, 1))


class SchemaParityTests(_TourFixtureMixin, unittest.TestCase):
    """shared/guided-tour.schema.json accepts a real composed tour, and
    rejects the same broken fixture GuidedTourInput rejects."""

    def test_composed_tour_matches_schema(self) -> None:
        import json
        from pathlib import Path

        import jsonschema

        schema = json.loads(
            (Path(__file__).resolve().parent.parent / "shared" / "guided-tour.schema.json").read_text()
        )
        with TestClient(app) as client:
            self._setup_three_contributor_room(client)
            tour = client.post(f"/v1/projects/{self.project_id}/tours/compose").json()
            jsonschema.validate(tour, schema)

            broken = dict(tour)
            broken["status"] = "not-a-real-status"
            with self.assertRaises(jsonschema.ValidationError):
                jsonschema.validate(broken, schema)


if __name__ == "__main__":
    unittest.main()
