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
    "objects": _ROOM_STATE["objects"],
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
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(rt.RoomToolError):
                rt.get_room_state("proj-1")


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
