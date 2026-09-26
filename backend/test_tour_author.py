"""NemoClaw's `author_guided_tour` tool (Build Plan step 31).

Run with: python -m unittest test_tour_author.py

No real network call -- urllib.request.urlopen is monkeypatched with a fake
response, matching test_room_tools.py's pattern. `model_call` is a stub
here too: the live model call needs the NemoClaw agent runtime (step 3),
which this repo doesn't have yet.
"""

import io
import json
import unittest
import urllib.error
from unittest import mock

import tour_author as ta


def _fake_urlopen_sequence(responses):
    calls = list(responses)

    def _urlopen(request, timeout=None):  # noqa: ARG001
        status, body = calls.pop(0)
        payload = json.dumps(body).encode("utf-8") if body is not None else b""
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(payload))
        return _FakeResponse(status, payload)

    return _urlopen


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


_COMPILED_SCENE = {"objects": [], "meta": {"social": {}}}
_INSIGHTS = [{"theme": "Two homes, one memory", "explanation": "Both carry warmth."}]
_CONTRIBUTIONS = [{"contributor_id": "c1", "memory_text": "Grandma's teapot."}]
_CONTRIBUTORS = [{"contributor_id": "c1", "display_name": "Alice"}]

_READ_SEQUENCE = [
    (200, _COMPILED_SCENE),
    (200, _INSIGHTS),
    (200, _CONTRIBUTIONS),
    (200, _CONTRIBUTORS),
]


class GatherTourInputsTests(unittest.TestCase):
    def test_gathers_all_four_reads(self) -> None:
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(_READ_SEQUENCE)):
                inputs = ta.gather_tour_inputs("proj-1")
        self.assertEqual(inputs["latest_insight"], _INSIGHTS[-1])
        self.assertEqual(inputs["contributions"], _CONTRIBUTIONS)

    def test_no_insights_raises_before_model_call(self) -> None:
        sequence = [(200, _COMPILED_SCENE), (200, [])]
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
                with self.assertRaises(ta.TourAuthorError):
                    ta.gather_tour_inputs("proj-1")

    def test_missing_token_raises_before_any_network_call(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ta.TourAuthorError):
                ta.gather_tour_inputs("proj-1")


class AuthorGuidedTourTests(unittest.TestCase):
    def test_first_attempt_success(self) -> None:
        sequence = [*_READ_SEQUENCE, (201, {"tour_version": 1, "status": "draft"})]
        model_call = mock.Mock(return_value={"fake": "tour-input"})
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
                result = ta.author_guided_tour("proj-1", model_call=model_call)
        self.assertEqual(result, {"tour_version": 1, "status": "draft"})
        model_call.assert_called_once_with(mock.ANY, None)

    def test_422_then_retry_succeeds_and_feeds_back_rule_message(self) -> None:
        sequence = [
            *_READ_SEQUENCE,
            (422, {"detail": "fact_authored: not allowed"}),
            (201, {"tour_version": 2, "status": "draft"}),
        ]
        model_call = mock.Mock(side_effect=[{"fake": "bad"}, {"fake": "good"}])
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
                result = ta.author_guided_tour("proj-1", model_call=model_call)
        self.assertEqual(result["tour_version"], 2)
        self.assertEqual(model_call.call_args_list[1].args[1], "fact_authored: not allowed")

    def test_exhausted_retries_raises_with_last_validator_message(self) -> None:
        sequence = [
            *_READ_SEQUENCE,
            (422, {"detail": "first failure"}),
            (422, {"detail": "second failure"}),
            (422, {"detail": "third failure"}),
        ]
        model_call = mock.Mock(return_value={"fake": "still-bad"})
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(sequence)):
                with self.assertRaises(ta.TourAuthorError) as ctx:
                    ta.author_guided_tour("proj-1", model_call=model_call)
        self.assertIn("third failure", str(ctx.exception))
        self.assertEqual(model_call.call_count, ta.MAX_RETRIES + 1)

    def test_default_model_call_raises_actionable_error(self) -> None:
        with mock.patch.dict("os.environ", {"SKETCHSCAPE_NEMOCLAW_TOKEN": "t" * 32}, clear=True):
            with mock.patch("urllib.request.urlopen", _fake_urlopen_sequence(list(_READ_SEQUENCE))):
                with self.assertRaises(ta.TourAuthorError):
                    ta.author_guided_tour("proj-1")


if __name__ == "__main__":
    unittest.main()
