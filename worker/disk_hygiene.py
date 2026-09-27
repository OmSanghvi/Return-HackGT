"""Disk hygiene for the GPU host (docs/WEB_TO_QUEST_PIPELINE.md section 7).

The GPU host's root disk is small next to its model weights, and three
things used to grow on it forever:

* ``worker_server.py``'s per-job work dirs (``SKETCHSCAPE_WORK_DIR``, e.g.
  ``/opt/sketchscape/data/jobs/<job_id>`` and ``.../scenes/<upload_id>``),
* the GPU dispatcher's per-segment-job dirs (``SKETCHSCAPE_DISPATCHER_WORK_DIR``),
* ``scene_capture.py``'s geometry cache (``SKETCHSCAPE_SCENE_CACHE/<sha>/``).

Everything here is plain stdlib (no numpy/torch) so every service's venv can
import it and the CPU-only unit tests (``test_disk_hygiene.py``) cover it.
Every function is best-effort: a cleanup problem is logged and swallowed,
never raised into the job that triggered it.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Iterable

log = logging.getLogger("disk_hygiene")


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def dir_size_bytes(path: Path) -> int:
    """Total size of the regular files under ``path`` (symlinks not followed)."""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def _latest_mtime(path: Path) -> float:
    """Newest mtime of ``path`` itself or anything directly inside it.

    A job dir's own mtime only changes when entries are added/removed at its
    top level, so a long job that only rewrites ``output/...`` would look old
    by its own mtime; checking one level down keeps a live dir "young".
    """
    try:
        newest = path.stat().st_mtime
    except OSError:
        return 0.0
    try:
        for child in path.iterdir():
            try:
                newest = max(newest, child.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return newest


def remove_tree(path: Path) -> int:
    """Remove ``path`` (dir or file); return the bytes freed, 0 on failure."""
    path = Path(path)
    try:
        if path.is_symlink() or path.is_file():
            size = path.lstat().st_size
            path.unlink()
            return size
        if not path.is_dir():
            return 0
        size = dir_size_bytes(path)
        shutil.rmtree(path, ignore_errors=True)
        return size if not path.exists() else 0
    except OSError as exc:
        log.warning("Could not remove %s: %s", path, exc)
        return 0


def sweep_old_dirs(
    roots: Iterable[Path],
    max_age_seconds: float,
    *,
    keep_names: Iterable[str] = (),
    nested: Iterable[str] = (),
    now: float | None = None,
) -> dict[str, float]:
    """Remove the direct child dirs of each root that are older than
    ``max_age_seconds`` (by the newest mtime of the dir and its entries).

    ``keep_names`` are never removed (e.g. ``"scenes"``); a name listed in
    ``nested`` is itself kept but its own children are swept the same way
    (``worker_server.py``'s ``WORK_DIR/scenes/<upload_id>``). Returns
    ``{"removed": count, "freed_bytes": bytes}``.
    """
    now = time.time() if now is None else now
    keep = set(keep_names) | set(nested)
    nested_names = set(nested)
    removed = 0
    freed = 0
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in nested_names and child.is_dir() and not child.is_symlink():
                inner = sweep_old_dirs([child], max_age_seconds, now=now)
                removed += int(inner["removed"])
                freed += int(inner["freed_bytes"])
                continue
            if child.name in keep or child.is_symlink() or not child.is_dir():
                continue
            if now - _latest_mtime(child) < max_age_seconds:
                continue
            size = remove_tree(child)
            if not child.exists():
                removed += 1
                freed += size
    if removed:
        log.info("Swept %d stale dir(s), freed %.1f MB", removed, freed / 2**20)
    return {"removed": removed, "freed_bytes": freed}


def evict_lru(
    cache_dir: Path,
    max_bytes: float,
    *,
    in_use: Iterable[str] = (),
) -> dict[str, float]:
    """Keep ``cache_dir``'s entries (direct child dirs) under ``max_bytes``,
    evicting the least recently used first (by dir mtime -- callers touch an
    entry on every hit). Entries named in ``in_use`` are never evicted, and
    their size still counts toward the cap. Returns ``{"removed": count,
    "freed_bytes": bytes, "kept_bytes": bytes}``.
    """
    cache_dir = Path(cache_dir)
    protected = set(in_use)
    if not cache_dir.is_dir():
        return {"removed": 0, "freed_bytes": 0, "kept_bytes": 0}
    entries: list[tuple[float, int, Path]] = []
    for child in cache_dir.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        entries.append((mtime, dir_size_bytes(child), child))
    total = sum(size for _mtime, size, _path in entries)
    removed = 0
    freed = 0
    # Oldest first; stop as soon as the cache fits.
    for _mtime, size, path in sorted(entries, key=lambda item: item[0]):
        if total <= max_bytes:
            break
        if path.name in protected:
            continue
        freed_now = remove_tree(path)
        if not path.exists():
            removed += 1
            freed += freed_now
            total -= size
    if removed:
        log.info("Evicted %d cache entr%s from %s, freed %.1f MB (now %.1f MB)",
                 removed, "y" if removed == 1 else "ies", cache_dir, freed / 2**20, total / 2**20)
    return {"removed": removed, "freed_bytes": freed, "kept_bytes": total}


def touch(path: Path) -> None:
    """Mark a cache entry as just used (LRU); never raises."""
    try:
        os.utime(path)
    except OSError:
        pass
