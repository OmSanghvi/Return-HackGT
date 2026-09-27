"""Tests for web_media (Openverse / Poly Haven search + curated offline fallback).

Run with: python -m unittest test_web_media.py

HTTP is mocked; the curated URLs themselves were checked live (HTTP 200/206)
on 2026-09-26 when the catalog was written.
"""

import io
import json
import unittest
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlparse

import web_media as wm


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(routes, seen):
    def urlopen(request, timeout=None):
        url = request.full_url
        seen.append((url, dict(request.header_items())))
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(json.dumps(payload).encode())
        raise urllib.error.URLError("no route")
    return urlopen


_IMAGES = {"results": [
    {"title": "Cozy Living Room", "url": "https://live.staticflickr.com/1/a_b.jpg", "thumbnail": "https://api.openverse.org/t/1",
     "creator": "Prayitno", "license": "by", "license_version": "2.0", "source": "flickr", "width": 1024, "height": 683,
     "foreign_landing_url": "https://flickr.com/1"},
    {"title": "Tiny", "url": "https://x.org/tiny.jpg", "license": "cc0", "width": 200, "height": 100},
    {"title": "Vector", "url": "https://x.org/a.svg", "filetype": "svg", "license": "cc0", "width": 2000, "height": 2000},
    {"title": "Old photo", "url": "https://upload.wikimedia.org/p.png", "creator": "", "license": "pdm", "width": 900, "height": 1200},
]}
_AUDIO = {"results": [
    {"title": "Door slam", "url": "https://cdn.freesound.org/a.mp3", "filetype": "mp3", "duration": 2000, "license": "cc0", "creator": "a"},
    {"title": "Rain drops", "url": "https://cdn.freesound.org/b.mp3", "filetype": "mp3", "duration": 25000, "license": "by", "license_version": "4.0",
     "creator": "b", "source": "freesound", "tags": [{"name": "rain"}]},
    {"title": "Rain ambience loop", "url": "https://cdn.freesound.org/c.mp3", "filetype": "mp3", "duration": 120000, "license": "cc0",
     "creator": "c", "source": "freesound", "tags": [{"name": "ambience"}]},
    {"title": "Weird format", "url": "https://cdn.freesound.org/d.flac", "filetype": "flac", "duration": 60000, "license": "cc0"},
]}
_PH_ASSETS = {
    "cozy_den": {"name": "Cozy Den", "tags": ["couch", "lamp"], "categories": ["indoor", "night"], "download_count": 5,
                 "authors": {"Greg Zaal": "All"}, "description": "A cozy living room at night."},
    "sunny_field": {"name": "Sunny Field", "tags": ["grass"], "categories": ["outdoor"], "download_count": 900, "authors": {"X": "All"}},
}
_PH_FILES = {"hdri": {"2k": {"hdr": {"url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/cozy_den_2k.hdr"}}}}


class SearchTests(unittest.TestCase):
    def run_with(self, routes, fn, *args, **kwargs):
        seen: list = []
        with mock.patch("urllib.request.urlopen", _fake_urlopen(routes, seen)):
            return fn(*args, **kwargs), seen

    def test_search_images_filters_and_attributes(self) -> None:
        out, seen = self.run_with({"https://api.openverse.org/v1/images/": _IMAGES}, wm.search_images, "cozy living room", count=5)
        self.assertEqual(out["source"], "openverse")
        self.assertEqual([r["title"] for r in out["results"]], ["Cozy Living Room", "Old photo"])
        first = out["results"][0]
        self.assertEqual(first["attribution"], "'Cozy Living Room' by Prayitno, CC BY 2.0, via flickr")
        self.assertEqual((first["width"], first["height"]), (1024, 683))
        self.assertEqual(out["results"][1]["attribution"], "'Old photo', Public Domain Mark, via Openverse")
        query = parse_qs(urlparse(seen[0][0]).query)
        self.assertEqual(query["q"], ["cozy living room"])
        self.assertEqual(query["license"], [wm.DEFAULT_LICENSES])
        self.assertIn("SketchScape", seen[0][1].get("User-agent", ""))  # Cloudflare blocks urllib's default UA

    def test_search_sounds_prefers_long_ambience(self) -> None:
        out, _ = self.run_with({"https://api.openverse.org/v1/audio/": _AUDIO}, wm.search_sounds, "rain")
        self.assertEqual([r["title"] for r in out["results"]], ["Rain ambience loop", "Rain drops"])
        self.assertEqual(out["results"][0]["duration_s"], 120.0)
        self.assertEqual(out["results"][1]["attribution"], "'Rain drops' by b, CC BY 4.0, via Freesound")

    def test_search_environment_returns_exact_file_urls(self) -> None:
        out, seen = self.run_with({"https://api.polyhaven.com/assets": _PH_ASSETS, "https://api.polyhaven.com/files/cozy_den": _PH_FILES},
                                  wm.search_environment, "cozy living room", kind="hdri", categories="indoor")
        self.assertEqual(out["source"], "polyhaven")
        self.assertEqual(out["results"][0]["hdri_url"], _PH_FILES["hdri"]["2k"]["hdr"]["url"])
        self.assertIn("Greg Zaal", out["results"][0]["attribution"])
        self.assertEqual(len(out["results"]), 1)  # "sunny field" doesn't match the query
        self.assertIn("categories=indoor", seen[0][0])

    def test_offline_falls_back_to_curated(self) -> None:
        err = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        routes = {"https://api.": err}
        env, _ = self.run_with(routes, wm.search_environment, "night stars", kind="hdri", categories="outdoor")
        self.assertEqual(env["source"], "curated")
        self.assertIn("network unavailable", env["note"])
        self.assertEqual(env["results"][0]["id"], "satara_night")
        tex, _ = self.run_with(routes, wm.search_environment, "oak wood floor", kind="texture")
        self.assertIn(tex["results"][0]["id"], ("laminate_floor_02", "wood_floor"))
        snd, _ = self.run_with(routes, wm.search_sounds, "rain on window")
        self.assertEqual(snd["source"], "curated")
        self.assertEqual(snd["results"][0]["title"], "rain on window")
        img, _ = self.run_with(routes, wm.search_images, "family")
        self.assertEqual(img["results"], [])
        self.assertEqual(img["source"], "offline")

    def test_http_403_is_reported_as_policy(self) -> None:
        err = urllib.error.HTTPError("https://api.openverse.org", 403, "Forbidden", {}, None)
        snd, _ = self.run_with({"https://api.": err}, wm.search_sounds, "birds")
        self.assertIn("sketchscape-web-media", snd["note"])

    def test_bad_input(self) -> None:
        with self.assertRaises(wm.WebMediaError):
            wm.search_images("  ")
        with self.assertRaises(wm.WebMediaError):
            wm.search_environment("x", kind="video")


class CuratedTests(unittest.TestCase):
    def test_catalog_is_complete_and_well_formed(self) -> None:
        for h in wm.CURATED_HDRIS:
            self.assertTrue(h["url_2k"].startswith("https://dl.polyhaven.org/") and h["url_2k"].endswith("_2k.hdr"))
            self.assertIn(h["setting"], ("indoor", "outdoor"))
            self.assertIn("CC0", h["attribution"])
        self.assertGreaterEqual(len([h for h in wm.CURATED_HDRIS if h["setting"] == "indoor"]), 8)
        self.assertGreaterEqual(len([h for h in wm.CURATED_HDRIS if h["setting"] == "outdoor"]), 8)
        kinds = {t["kind"] for t in wm.CURATED_TEXTURES}
        self.assertEqual(kinds, {"floor", "wall", "ground"})
        ids = {s["id"] for s in wm.CURATED_SOUNDS}
        for needed in ("room_tone", "rain_window", "fireplace", "birds_morning", "city_evening", "ocean_waves"):
            self.assertIn(needed, ids)
        for s in wm.CURATED_SOUNDS:
            self.assertTrue(s["url"].startswith("https://cdn.freesound.org/previews/") and s["url"].endswith(".mp3"))
            self.assertTrue(s["license"].startswith("CC"))

    def test_pick_hdri(self) -> None:
        self.assertEqual(wm.pick_hdri("indoor", "evening", "cozy, quiet", ["living room"])["id"], "fireplace")
        self.assertEqual(wm.pick_hdri("indoor", "morning", "bright airy")["id"], "lebombo")
        self.assertEqual(wm.pick_hdri("outdoor", "night", "magical")["id"], "satara_night")
        self.assertEqual(wm.pick_hdri("outdoor", "day", "sunny", ["beach"])["id"], "spiaggia_di_mondello")
        self.assertEqual(wm.pick_hdri("", "", "", ["park", "autumn"])["setting"], "outdoor")
        self.assertEqual(wm.pick_hdri()["setting"], "indoor")

    def test_pick_texture_and_sounds(self) -> None:
        self.assertEqual(wm.pick_texture("floor", "light oak wood")["id"], "laminate_floor_02")
        self.assertEqual(wm.pick_texture("floor", "grass lawn", setting="outdoor")["id"], "leafy_grass")
        self.assertEqual(wm.pick_texture("floor", "")["kind"], "floor")
        self.assertIsNone(wm.pick_texture("wall", "velvet"))
        self.assertEqual(wm.pick_texture("wall", "exposed red brick")["id"], "red_brick_03")
        self.assertEqual([s["id"] for s in wm.pick_sounds(["rain on window"])], ["room_tone", "rain_window"])
        self.assertEqual(wm.pick_sounds([], setting="outdoor", time_of_day="night")[0]["id"], "night_crickets")
        self.assertEqual(wm.object_sound("our cat Miso")["id"], "cat_purring")
        self.assertIsNone(wm.object_sound("guitar"))


if __name__ == "__main__":
    unittest.main()
