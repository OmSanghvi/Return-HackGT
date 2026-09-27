"""Unit tests for `disk_hygiene.py` (docs/WEB_TO_QUEST_PIPELINE.md 7) and the
scene-cache eviction wiring in `scene_capture.py`. Stdlib + numpy only.

Run with `python -m unittest test_disk_hygiene` from this directory.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disk_hygiene as dh  # noqa: E402


def _make_entry(root: Path, name: str, size: int, age_s: float, now: float) -> Path:
    entry = root / name
    (entry / "output").mkdir(parents=True, exist_ok=True)
    (entry / "output" / "blob.bin").write_bytes(b"x" * size)
    stamp = now - age_s
    for path in (entry / "output" / "blob.bin", entry / "output", entry):
        os.utime(path, (stamp, stamp))
    return entry


class SweepOldDirsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.now = time.time()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_removes_only_dirs_older_than_the_cutoff(self) -> None:
        old = _make_entry(self.root, "old-job", 1000, 5 * 3600, self.now)
        young = _make_entry(self.root, "young-job", 1000, 600, self.now)
        stray_file = self.root / "note.txt"
        stray_file.write_text("keep")
        os.utime(stray_file, (self.now - 10 * 3600,) * 2)

        result = dh.sweep_old_dirs([self.root], 3 * 3600, now=self.now)

        self.assertFalse(old.exists())
        self.assertTrue(young.exists())
        self.assertTrue(stray_file.exists())  # only dirs are swept
        self.assertEqual(result["removed"], 1)
        self.assertGreaterEqual(result["freed_bytes"], 1000)

    def test_nested_dir_is_kept_but_its_old_children_are_swept(self) -> None:
        scenes = self.root / "scenes"
        old_scene = _make_entry(scenes, "upload-a", 10, 5 * 3600, self.now)
        new_scene = _make_entry(scenes, "upload-b", 10, 60, self.now)
        os.utime(scenes, (self.now - 9 * 3600,) * 2)

        dh.sweep_old_dirs([self.root], 3 * 3600, nested=["scenes"], now=self.now)

        self.assertTrue(scenes.is_dir())
        self.assertFalse(old_scene.exists())
        self.assertTrue(new_scene.exists())

    def test_a_dir_with_a_recently_touched_entry_counts_as_young(self) -> None:
        job = _make_entry(self.root, "long-job", 10, 5 * 3600, self.now)
        os.utime(job / "output", (self.now - 30, self.now - 30))
        dh.sweep_old_dirs([self.root], 3 * 3600, now=self.now)
        self.assertTrue(job.exists())

    def test_missing_roots_are_ignored(self) -> None:
        self.assertEqual(dh.sweep_old_dirs([self.root / "nope"], 1)["removed"], 0)


class EvictLruTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)
        self.now = time.time()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_evicts_least_recently_used_first_until_under_the_cap(self) -> None:
        oldest = _make_entry(self.cache, "sha-oldest", 400, 300, self.now)
        middle = _make_entry(self.cache, "sha-middle", 400, 200, self.now)
        newest = _make_entry(self.cache, "sha-newest", 400, 100, self.now)

        result = dh.evict_lru(self.cache, 900)

        self.assertFalse(oldest.exists())
        self.assertTrue(middle.exists())
        self.assertTrue(newest.exists())
        self.assertEqual(result["removed"], 1)
        self.assertLessEqual(result["kept_bytes"], 900)

    def test_never_evicts_an_entry_in_use(self) -> None:
        oldest = _make_entry(self.cache, "sha-oldest", 400, 300, self.now)
        middle = _make_entry(self.cache, "sha-middle", 400, 200, self.now)
        newest = _make_entry(self.cache, "sha-newest", 400, 100, self.now)

        dh.evict_lru(self.cache, 500, in_use={"sha-oldest"})

        self.assertTrue(oldest.exists())  # in use: kept even though oldest
        self.assertFalse(middle.exists())
        self.assertFalse(newest.exists())  # still over the cap after `middle`

    def test_touch_makes_an_entry_most_recently_used(self) -> None:
        first = _make_entry(self.cache, "sha-a", 400, 300, self.now)
        second = _make_entry(self.cache, "sha-b", 400, 200, self.now)
        dh.touch(first)  # a cache hit on `first`
        dh.evict_lru(self.cache, 500)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_under_the_cap_nothing_happens(self) -> None:
        entry = _make_entry(self.cache, "sha-a", 100, 300, self.now)
        self.assertEqual(dh.evict_lru(self.cache, 10_000)["removed"], 0)
        self.assertTrue(entry.exists())


class SceneCaptureCacheWiringTests(unittest.TestCase):
    def test_cache_entry_in_use_pins_the_entry_during_eviction(self) -> None:
        import scene_capture as sc

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            cache.mkdir()
            image = Path(tmp) / "photo.jpg"
            image.write_bytes(b"not-really-a-jpeg")
            sha = sc.sha256_file(image)
            now = time.time()
            pinned = _make_entry(cache, sha, 400, 500, now)  # the oldest entry
            other = _make_entry(cache, "f" * 64, 400, 100, now)
            saved = (sc.CACHE_DIR, sc.CACHE_MAX_GB)
            sc.CACHE_DIR, sc.CACHE_MAX_GB = cache, 500 / 2**30
            try:
                with sc.cache_entry_in_use(image):
                    sc.evict_scene_cache()
                    self.assertTrue(pinned.exists())  # in use: never evicted
                    self.assertFalse(other.exists())
                # Released: now the cap applies to it too (on exit).
                self.assertTrue(pinned.exists())  # 400 B alone fits the 500 B cap
            finally:
                sc.CACHE_DIR, sc.CACHE_MAX_GB = saved


if __name__ == "__main__":
    unittest.main()
