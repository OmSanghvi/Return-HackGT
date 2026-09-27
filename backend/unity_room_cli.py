#!/usr/bin/env python3
"""Command-line entry point for unity_room, for agent runtimes with shell
access (the sketchscape-unity-room OpenClaw skill).

Usage:
    python3 unity_room_cli.py compose_room '<json>'     # or '-' to read JSON from stdin
    python3 unity_room_cli.py build_code <room-slug>
    python3 unity_room_cli.py finalize_code <room-slug>
    python3 unity_room_cli.py list_assets all

list_assets prints the real 3D scans (Gaussian splats) available in Unity.
compose_room builds any object whose label matches one of them (for example
"our cat Miso" matches "cat") from that scan instead of a placeholder cube.

compose_room takes {"objects": [{"asset_id", "label"}, ...], "theme"?,
"connection_insight"? {"theme", "explanation"}, "room_name"?,
"sketch_layout_hint"? {"relations": [...]}, "project_id"?}, prints the plan
as compact JSON (summary, room, objects, staging, unity_steps), and saves
the room's build code under $SKETCHSCAPE_ROOM_STATE_DIR (default
/tmp/sketchscape-rooms).

build_code and finalize_code print C# for the Unity_RunCommand steps
between marker lines:

    === BUILD CODE: pass everything between the markers verbatim as Code to unity-mcp__Unity_RunCommand ===
    <C#>
    === END BUILD CODE ===

Outputs stay small on purpose: agent runtimes truncate long tool results.
Non-zero exit + a JSON {"error": ...} on failure.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import scene_tools as st
import unity_room as ur


def _state_dir() -> Path:
    return Path(os.environ.get("SKETCHSCAPE_ROOM_STATE_DIR", "/tmp/sketchscape-rooms"))


def _print_code(label: str, code: str) -> None:
    print(f"=== {label} CODE: pass everything between the markers verbatim as Code to unity-mcp__Unity_RunCommand ===")
    print(code.rstrip())
    print(f"=== END {label} CODE ===")


def _compose(raw: str) -> None:
    payload = json.loads(sys.stdin.read() if raw == "-" else raw)
    hint = payload.get("sketch_layout_hint")
    plan = ur.compose_room(
        payload["objects"],
        theme=payload.get("theme") or (payload.get("connection_insight") or {}).get("theme") or "Shared Room",
        connection_insight=payload.get("connection_insight"),
        sketch_layout_hint=st.LayoutHint(**hint) if hint else None,
        room_name=payload.get("room_name"),
        project_id=payload.get("project_id", "preview"),
    )
    code = plan.pop("build_code")
    state = _state_dir()
    state.mkdir(parents=True, exist_ok=True)
    (state / f"{plan['room']['slug']}.build.cs").write_text(code)
    print(json.dumps(plan, separators=(",", ":")))


def _build_code(slug: str) -> None:
    path = _state_dir() / f"{ur._checked_slug(slug)}.build.cs"
    if not path.is_file():
        raise st.SceneToolError(f"no composed room '{slug}'; run compose_room first (it prints room.slug)")
    _print_code("BUILD", path.read_text())


def _list_assets(_: str) -> None:
    assets = ur.load_catalog()
    print(json.dumps(
        {"real_assets": [{"label": a["label"], "asset_id": a["asset_id"]} for a in assets],
         "note": "Objects whose label contains one of these labels are built from the real 3D scan; others are placeholder cubes."},
        separators=(",", ":"),
    ))


_COMMANDS = {
    "list_assets": _list_assets,
    "compose_room": _compose,
    "build_code": _build_code,
    "finalize_code": lambda slug: _print_code("FINALIZE", ur.room_finalize_command(slug)),
}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _COMMANDS:
        print(
            json.dumps({"error": "usage: unity_room_cli.py compose_room '<json>'|- | build_code <slug> | finalize_code <slug> | list_assets all"}),
            file=sys.stderr,
        )
        return 2
    try:
        _COMMANDS[argv[1]](argv[2])
    except (st.SceneToolError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
