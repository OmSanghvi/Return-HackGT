#!/usr/bin/env python3
"""Command-line entry point for the room tools, for agent runtimes with shell
access (the sketchscape-unity-room OpenClaw skill).

Usage (every verb takes exactly one argument; JSON may be '-' for stdin):
    python3 unity_room_cli.py list_scenes all
    python3 unity_room_cli.py list_assets all
    python3 unity_room_cli.py search_images '{"query": "family photos 1990s", "count": 4}'
    python3 unity_room_cli.py search_sounds '{"query": "rain on window"}'
    python3 unity_room_cli.py search_environment '{"kind": "hdri", "query": "cozy living room evening"}'
    python3 unity_room_cli.py compose_room '{"scene_id": "<id>", "room_name": "Lazy Sunday"}'
    python3 unity_room_cli.py build_code <room-slug> [part]
    python3 unity_room_cli.py finalize_code <room-slug>
    python3 unity_room_cli.py status_code <room-slug>

compose_room prints a short summary (room, objects, environment, unity_steps)
and saves the full plan, the room spec and its C# under
$SKETCHSCAPE_ROOM_STATE_DIR (default /tmp/sketchscape-rooms).
finalize_code's RoomKit.Finalize adds the Quest camera rig, interaction rig,
grab on every object, the teleport hotspots, pickups and foveation (no
meta_add_* calls needed); status_code's RoomKit.Status prints one JSON line of
what is already done, so a build can resume instead of starting over.
build_code / finalize_code / status_code print C# for Unity_RunCommand between marker lines:

    === BUILD CODE: pass everything between the markers verbatim as Code to unity-mcp__Unity_RunCommand ===
    <C#>
    === END BUILD CODE ===

A bigger room's build comes in parts (=== BUILD CODE PART k/N ... ===), one
Unity_RunCommand call each, in order: the first parts store slices of the spec
in the Editor's SessionState, the last reassembles them (length + hash checked)
and builds.
`build_code <slug> <k>` prints part k alone.

Outputs stay small on purpose (agent runtimes truncate tool results at 16k).
Non-zero exit + a JSON {"error": ...} on failure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import scene_tools as st
import unity_room as ur
import web_media as wm

MAX_OUTPUT = 12000


def _state_dir() -> Path:
    return Path(os.environ.get("SKETCHSCAPE_ROOM_STATE_DIR", "/tmp/sketchscape-rooms"))


def _json_arg(raw: str) -> dict:
    payload = json.loads(sys.stdin.read() if raw == "-" else raw)
    if not isinstance(payload, dict):
        raise TypeError("expected a JSON object")
    return payload


def _emit(obj: object) -> None:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    if len(text) > MAX_OUTPUT and isinstance(obj, dict) and isinstance(obj.get("results"), list):
        while len(text) > MAX_OUTPUT and obj["results"]:
            obj["results"].pop()
            text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    print(text[:MAX_OUTPUT])


def _print_code(label: str, code: str) -> None:
    print(f"=== {label} CODE: pass everything between the markers verbatim as Code to unity-mcp__Unity_RunCommand ===")
    print(code.rstrip())
    print(f"=== END {label} CODE ===")


def _compact_plan(plan: dict) -> dict:
    """What the agent needs from a composed room, in about 1-2 KB. Every tool result stays in the agent's
    context for the rest of the build, and a 90k-token context made Muse Spark restart a finished build twice."""
    return {
        "summary": plan.get("summary"),
        "room": {"slug": plan["room"]["slug"], "scene_path": plan["room"]["scene_path"]},
        "objects": [f"{o['id']} ({o['label']})" for o in (plan.get("objects") or [])][:16],
        "in_photo_scene": (plan.get("in_photo_scene") or [])[:8],
        "environment": plan.get("environment"),
        "audio": (plan.get("audio") or [])[:4],
        "images": len(plan.get("images") or []),
        "particles": plan.get("particles") or [],
        "shared": bool((plan.get("shared") or {}).get("enabled")),
        "performance": plan.get("performance"),
        "unity_steps": plan.get("unity_steps"),
        "notes": (plan.get("notes") or [])[:3],
    }


def _compose(raw: str) -> None:
    result = ur.compose_room(_json_arg(raw))
    slug = result["plan"]["room"]["slug"]
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{slug}.spec.json").write_text(json.dumps(result["spec"], indent=1, ensure_ascii=False), encoding="utf-8")
    (state / f"{slug}.plan.json").write_text(json.dumps(result["plan"], indent=1, ensure_ascii=False), encoding="utf-8")
    (state / f"{slug}.build.cs").write_text(result["build_code"], encoding="utf-8")
    (state / f"{slug}.finalize.cs").write_text(result["finalize_code"], encoding="utf-8")
    print(json.dumps(_compact_plan(result["plan"]), separators=(",", ":"), ensure_ascii=False)[:MAX_OUTPUT])


def _part_block(parts: list[str], k: int) -> str:
    n = len(parts)
    return (f"=== BUILD CODE PART {k}/{n}: pass everything between the markers verbatim as Code to unity-mcp__Unity_RunCommand ===\n"
            f"{parts[k - 1].rstrip()}\n=== END BUILD CODE PART {k}/{n} ===")


def _build_code(arg: str) -> None:
    """``build_code <slug>`` (all parts that fit in one output) or ``build_code <slug> <k>`` (part k)."""
    words = arg.replace(":", " ").split()
    slug = ur._checked_slug(words[0] if words else "")
    spec_path = _state_dir() / f"{slug}.spec.json"
    if not spec_path.is_file():
        raise st.SceneToolError(f"no composed room '{slug}'; run compose_room first (it prints room.slug)")
    parts = ur.room_build_parts(json.loads(spec_path.read_text(encoding="utf-8")))
    n = len(parts)
    if len(words) > 1:
        k = int(words[1])
        if not 1 <= k <= n:
            raise ValueError(f"room {slug} has build parts 1..{n}")
        if n == 1:
            _print_code("BUILD", parts[0])
        else:
            print(_part_block(parts, k))
        return
    if n == 1:
        _print_code("BUILD", parts[0])
        return
    head = (f"This room's build comes in {n} parts. Make one unity-mcp__Unity_RunCommand call per part, in order "
            f"1..{n}, each with exactly the code between that part's markers (parts 1-{n - 1} store the room spec in "
            f"Unity, part {n} builds the room).")
    blocks = [_part_block(parts, k) for k in range(1, n + 1)]
    text = "\n".join([head] + blocks)
    if len(text) <= MAX_OUTPUT:
        print(text)
    else:  # too long for one tool result: one part at a time
        print(head + f" This output shows part 1; get the others with: build_code {slug} 2 ... build_code {slug} {n}")
        print(blocks[0])


def _finalize_code(slug: str) -> None:
    slug = ur._checked_slug(slug)
    spec_path = _state_dir() / f"{slug}.spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.is_file() else None
    _print_code("FINALIZE", ur.room_finalize_command(slug, spec))


def _status_code(slug: str) -> None:
    _print_code("STATUS", ur.room_status_command(slug))


def _list_assets(_: str) -> None:
    assets = ur.load_catalog()
    _emit({
        "real_assets": [
            {"label": a.get("label"), "asset_id": a.get("asset_id"), "scene_id": a.get("upload_id") or "",
             "posed": bool((a.get("pose") or {}).get("object") or (a.get("pose") or {}).get("rotation"))}
            for a in assets
        ][:80],
        "note": "Objects whose label contains one of these labels are built from the real 3D scan; others are placeholder cubes. Prefer compose_room with a scene_id (list_scenes all).",
    })


def _list_scenes(_: str) -> None:
    doc = ur.load_catalog_doc()
    scenes = ur.list_scenes(doc)
    _emit({
        "scenes": scenes[:30],
        "note": ("compose_room {\"scene_id\": ..., \"room_name\": ...} rebuilds that photo as a room you stand inside, with all its objects."
                 if scenes else "No photo scenes synced yet; compose_room with objects instead (list_assets all)."),
    })


def _search_images(raw: str) -> None:
    p = _json_arg(raw)
    _emit(wm.search_images(p.get("query") or p.get("q") or "", count=p.get("count", 5), license=p.get("license") or wm.DEFAULT_LICENSES,
                           aspect_ratio=p.get("aspect_ratio") or ""))


def _search_sounds(raw: str) -> None:
    p = _json_arg(raw)
    _emit(wm.search_sounds(p.get("query") or p.get("q") or "", count=p.get("count", 4), license=p.get("license") or wm.DEFAULT_LICENSES,
                           prefer_loops=bool(p.get("prefer_loops", True))))


def _search_environment(raw: str) -> None:
    p = _json_arg(raw)
    _emit(wm.search_environment(p.get("query") or p.get("q") or "", kind=p.get("kind") or "hdri", categories=p.get("categories") or "",
                                count=p.get("count", 4), resolution=p.get("resolution") or "2k"))


_COMMANDS = {
    "list_scenes": _list_scenes,
    "list_assets": _list_assets,
    "search_images": _search_images,
    "search_sounds": _search_sounds,
    "search_environment": _search_environment,
    "compose_room": _compose,
    "build_code": _build_code,
    "finalize_code": _finalize_code,
    "status_code": _status_code,
}

_USAGE = ("usage: unity_room_cli.py list_scenes all | list_assets all | search_images '<json>' | search_sounds '<json>' | "
          "search_environment '<json>' | compose_room '<json>'|- | build_code <slug> [part] | finalize_code <slug> | "
          "status_code <slug>")


def main(argv: list[str]) -> int:
    if argv[1:2] == ["build_code"] and len(argv) == 4:  # build_code <slug> <part>
        argv = argv[:2] + [f"{argv[2]} {argv[3]}"]
    if len(argv) != 3 or argv[1] not in _COMMANDS:
        print(json.dumps({"error": _USAGE}))
        return 2
    try:
        _COMMANDS[argv[1]](argv[2])
    except (st.SceneToolError, wm.WebMediaError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
