"""Tests for nemoclaw_vision (identify_subject's live path, run inside the
NemoClaw sandbox). No network: the model call is a stub.

Run with: python -m unittest test_nemoclaw_vision.py
"""

import json
import tempfile
import unittest
from pathlib import Path

import nemoclaw_vision as nv


class CleanLabelTests(unittest.TestCase):
    def test_keeps_sam_friendly_noun_phrases(self) -> None:
        self.assertEqual(nv.clean_label("  The Brown Tabby Cat. "), "brown tabby cat")
        self.assertEqual(nv.clean_label("white tv remote"), "white tv remote")

    def test_rejects_relational_generic_long_or_non_text(self) -> None:
        for bad in ("remote next to the cat", "the chair left of the table", "object", "Thing",
                    "a very large old wooden antique dining table", "42", "", None, 7):
            self.assertIsNone(nv.clean_label(bad), bad)


class ParseLabelsTests(unittest.TestCase):
    def test_parses_fenced_json_dedupes_and_caps(self) -> None:
        text = 'Sure!\n```json\n{"labels": ["pink blanket", "Pink blanket", "cat next to remote", "tomato", "mug"]}\n```'
        self.assertEqual(nv.parse_labels(text, 2), ["pink blanket", "tomato"])

    def test_garbage_gives_no_labels(self) -> None:
        for text in (None, "", "no json here", '{"labels": "cat"}', "{not json}"):
            self.assertEqual(nv.parse_labels(text, 8), [])


class IdentifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.photo = Path(self._tmp.name) / "photo.jpg"
        self.photo.write_bytes(b"\xff\xd8jpeg")
        self.mask = Path(self._tmp.name) / "mask.png"
        self.mask.write_bytes(b"\x89PNG")

    def _stub(self, content: str, seen: list):
        def post(url, body, timeout):
            seen.append((url, body))
            return {"choices": [{"message": {"content": content}}]}
        return post

    def test_photo_request_goes_to_nemoclaw_managed_inference(self) -> None:
        seen: list = []
        labels = nv.identify(str(self.photo), max_labels=3, post=self._stub('{"labels": ["cat", "blanket"]}', seen))
        self.assertEqual(labels, ["cat", "blanket"])
        url, body = seen[0]
        self.assertEqual(url, "https://inference.local/v1/chat/completions")
        self.assertEqual(body["model"], "muse-spark-1.3")
        self.assertGreaterEqual(body["max_tokens"], 4000)  # Muse Spark reasons first
        images = [part for part in body["messages"][0]["content"] if part["type"] == "image_url"]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertNotIn("authorization", json.dumps(body).lower())  # NemoClaw injects credentials

    def test_mask_sends_both_images_and_returns_one_label(self) -> None:
        seen: list = []
        labels = nv.identify(
            str(self.photo), mask_path=str(self.mask),
            post=self._stub('{"labels": ["gray striped cat", "extra"]}', seen),
        )
        self.assertEqual(labels, ["gray striped cat"])
        parts = seen[0][1]["messages"][0]["content"]
        self.assertEqual([p["type"] for p in parts], ["text", "image_url", "image_url"])
        self.assertTrue(parts[2]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_cli_prints_json_and_cleans_up(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        out = io.StringIO()
        with patch.object(nv, "_post", lambda url, body, timeout: {"choices": [{"message": {"content": '{"labels": ["tomato"]}'}}]}):
            with contextlib.redirect_stdout(out):
                code = nv.main([str(self.photo), "--cleanup"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"labels": ["tomato"], "backend": "nemoclaw:muse-spark-1.3"})
        self.assertFalse(self.photo.exists())


if __name__ == "__main__":
    unittest.main()
