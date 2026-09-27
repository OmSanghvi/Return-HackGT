"""NemoClaw room tools (Build Plan step 24).

Run with: python -m unittest test_room_tools.py

Per the user's explicit instruction this file is written but NOT run as
part of building this step (built ahead of the step 3 gate, untested,
2026-09-26). No real network call -- urllib.request.urlopen is monkeypatched
with a fake response, matching this repo's mock-first philosophy.
"""

import json
import unittest
from unittest import mock

import room_tools as rt


def _fake_urlopen_sequence(responses):
    """responses: list of (status, body_dict_or_none). Returns a context-
    manager-compatible fake, one entry consumed per call, in order."""

    calls = list(responses)

    def _urlopen(request, timeout=None):  # noqa: ARG001
        status, body = calls.pop(0)
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        if status >= 400:
            raise _http_error(request.full_url, status, payload)
        return _FakeResponse(status, payload)

    return _urlopen


def _http_error(url, status, payload):
    import io
    import urllib.error

    return urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(payload))


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_ROOM_STATE = {
    "project_id": "proj-1",
    "live_revision": 7,
    "objects": [
        {
            "id": "lamp_1",
            "asset_id": "a1",
            "position": [0.0, 0.2, 1.0],
            "rotation": [0.0, 0.0, 0.0],
            "scale": [1.0, 1.0, 1.0],
            "interactions": ["translate", "rotate"],
            "owner_contributor_id": "demo-alice",
            "editable_by_me": False,
        }
    ],
    "artifact_urls": {},
    "experience": {"mode": "ar_vr", "theme": "Shared Room", "units": "meters"},
    "environment": {"lighting_preset": "neutral", "skybox": None, "floor": True, "ambient_audio": None},
    "navigation": {"vr": "teleport", "ar": "surface-placement"},
}

_BLUEPRINT = {
    "project_id": "proj-1",
    "revision": 7,
    "created_at": "2026-01-01T00:00:00+00:00",
    "experience": _ROOM_STATE["experience"],
    "environment": _ROOM_STATE["environment"],
    # Blueprint objects (shared/experience-blueprint.schema.json) never carry
    # room-state-view-only fields like owner_contributor_id/editable_by_me
    # (those are added by RoomObjectView in main.py's /rooms/{id}/state
    # route) -- reusing _ROOM_STATE["objects"] here would make this fixture
    # schema-invalid in a way the real blueprint GET response never is.
    "objects": [
        {k: v for k, v in obj.items() if k not in ("owner_contributor_id", "editable_by_me")}
        for obj in _ROOM_STATE["objects"]
    ],
    "portals": [],
    "navigation": _ROOM_STATE["navigation"],
    "based_on_revision": 6,
    "author": "demo-alice",
    "client_edit_id": None,
}


class GetRoomStateTests(unittest.TestCase):
    def test_concise_summary_reports_owner_and_editability(self) -> None:
        with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence([(200, _ROOM_STATE)])):
            result = rt.get_room_state("proj-1", token="t" * 32)
        self.assertEqual(result["live_revision"], 7)
        self.assertIn("demo-alice", result["summary"])
        self.assertIn("read-only to me", result["summary"])

    def test_404_raises_actionable_error(self) -> None:
        with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence([(404, None)])):
            with self.assertRaises(rt.RoomToolError):
                rt.get_room_state("proj-1", token="t" * 32)

    def test_missing_token_raises_before_any_network_call(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(rt, "CONFIG_DIR", _empty_dir(self)):
            with self.assertRaises(rt.RoomToolError):
                rt.get_room_state("proj-1")

    def test_token_and_url_fall_back_to_the_sandbox_config_dir(self) -> None:
        import pathlib

        config = _empty_dir(self)
        (pathlib.Path(config) / "nemoclaw-token").write_text("s" * 32 + "\n")
        (pathlib.Path(config) / "api-url").write_text("http://backend.local:8000\n")
        seen = []

        def urlopen(request, timeout=None):  # noqa: ARG001
            seen.append((request.full_url, request.get_header("Authorization")))
            return _FakeResponse(200, json.dumps(_ROOM_STATE).encode())

        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(rt, "CONFIG_DIR", config), \
                mock.patch("urllib.request.urlopen", urlopen):
            rt.get_room_state("proj-1")
        self.assertEqual(seen, [("http://backend.local:8000/v1/rooms/proj-1/state", "Bearer " + "s" * 32)])


def _empty_dir(test: unittest.TestCase):
    import pathlib
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    return pathlib.Path(tmp.name)


_ASSETS = [
    {"asset_id": "cat1", "label": "cat", "status": "ready", "kind": "reconstruction",
     "artifact_url": "/v1/artifacts/j1/reconstruction.ply"},
    {"asset_id": "blanket1", "label": "pink blanket", "status": "ready", "kind": "reconstruction",
     "artifact_url": "/v1/artifacts/j2/reconstruction.ply"},
    {"asset_id": "late1", "label": "mug", "status": "processing", "kind": "reconstruction", "artifact_url": None},
]
_CONTRIBUTIONS = [{"contribution_id": "c-cat", "asset_id": "cat1"}]


class DraftRoomTests(unittest.TestCase):
    def _run(self, responses, **kwargs):
        posted = []
        fake = _fake_urlopen_sequence(responses)

        def urlopen(request, timeout=None):
            if request.get_method() == "POST":
                posted.append((request.full_url, json.loads(request.data)))
            return fake(request, timeout)

        with mock.patch("urllib.request.urlopen", urlopen):
            result = rt.draft_room("proj-1", token="t" * 32, **kwargs)
        return result, posted

    def test_drafts_ready_assets_as_a_staged_grabbable_room_from_nothing_published(self) -> None:
        result, posted = self._run(
            [(200, _ASSETS), (200, _CONTRIBUTIONS), (404, None), (201, {"revision": 1})],
            connection_insight={"theme": "Lazy Sunday at home", "explanation": "One slow afternoon."},
        )
        url, body = posted[0]
        self.assertTrue(url.endswith("/v1/projects/proj-1/blueprints?base_revision=0"))
        self.assertEqual([o["asset_id"] for o in body["objects"]], ["cat1", "blanket1"])  # not the processing one
        cat, blanket = body["objects"]
        self.assertEqual(cat["contribution_id"], "c-cat")
        self.assertIsNone(blanket["contribution_id"])
        self.assertIn("grab", cat["interactions"])
        self.assertEqual(cat["scale"], [0.5, 0.5, 0.5])  # uniform: a cat's largest side
        self.assertEqual(blanket["scale"], [1.4, 1.4, 1.4])
        self.assertEqual(cat["position"][1], 0.0)
        self.assertEqual(body["staging"]["lighting_preset"], "warm-amber")
        self.assertEqual(body["environment"]["lighting_preset"], "warm-amber")
        self.assertEqual(body["navigation"]["vr"], "teleport")
        self.assertFalse(result["published"])
        self.assertIn("revision 1 drafted", result["summary"])

    def test_bases_the_draft_on_the_live_revision(self) -> None:
        _, posted = self._run([(200, _ASSETS), (200, []), (200, _ROOM_STATE), (201, {"revision": 8})])
        self.assertTrue(posted[0][0].endswith("?base_revision=7"))
        self.assertNotIn("staging", posted[0][1])

    def test_no_ready_assets_is_actionable(self) -> None:
        with self.assertRaises(rt.RoomToolError):
            self._run([(200, [_ASSETS[2]])])

    def test_stale_revision_on_409(self) -> None:
        with self.assertRaises(rt.StaleRevisionError):
            self._run([(200, _ASSETS), (200, []), (404, None), (409, {"published_revision": 3})])


class ProposeRoomEditTests(unittest.TestCase):
    def test_successful_draft_reports_change_and_owner(self) -> None:
        create_response = {"revision": 8, "live_revision": 7}
        sequence = [
            (200, _BLUEPRINT),  # GET base_revision blueprint
            (200, _ROOM_STATE),  # get_room_state (ownership lookup)
            (201, create_response),  # POST draft
        ]
        with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
            result = rt.propose_room_edit(
                "proj-1", 7, [{"object_id": "lamp_1", "position": [1.0, 0.2, 2.0]}], token="t" * 32
            )
        self.assertEqual(result["revision"], 8)
        self.assertFalse(result["published"])
        self.assertIn("demo-alice", result["owners"])

    def test_unknown_object_id_raises_before_any_write(self) -> None:
        with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence([(200, _BLUEPRINT)])):
            with self.assertRaises(rt.RoomToolError):
                rt.propose_room_edit(
                    "proj-1", 7, [{"object_id": "nope", "position": [0, 0, 0]}], token="t" * 32
                )

    def test_stale_revision_raises_with_fresh_room_state(self) -> None:
        sequence = [
            (200, _BLUEPRINT),  # GET base_revision blueprint
            (200, _ROOM_STATE),  # ownership lookup
            (409, {"detail": "stale", "published_revision": 9}),  # POST draft -> 409
            (200, {**_ROOM_STATE, "live_revision": 9}),  # re-read after 409
        ]
        with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
            with self.assertRaises(rt.StaleRevisionError) as ctx:
                rt.propose_room_edit(
                    "proj-1", 7, [{"object_id": "lamp_1", "position": [1.0, 0.2, 2.0]}], token="t" * 32
                )
        self.assertEqual(ctx.exception.live_revision, 9)

    def test_no_edits_raises(self) -> None:
        with self.assertRaises(rt.RoomToolError):
            rt.propose_room_edit("proj-1", 7, [], token="t" * 32)


if __name__ == "__main__":
    unittest.main()
