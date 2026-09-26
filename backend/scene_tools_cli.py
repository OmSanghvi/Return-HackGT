#!/usr/bin/env python3
"""Command-line entry point exposing the scene_tools functions as CLI verbs,
so an agent runtime with shell access (e.g. an OpenClaw skill) can call
place_objects_in_scene / read_sketch_layout / stage_immersive_reveal without
needing a Python import in-process.

Usage:
    python3 scene_tools_cli.py place_objects_in_scene '<json>'
    python3 scene_tools_cli.py read_sketch_layout '<json>'
    python3 scene_tools_cli.py stage_immersive_reveal '<json>'

Each verb reads one JSON argument (or "-" to read JSON from stdin) and
prints one JSON result to stdout. Non-zero exit + a JSON {"error": ...} on
failure.
"""

from __future__ import annotations

import json
import sys

import scene_tools as st


def _read_arg(raw: str) -> dict:
    if raw == "-":
        raw = sys.stdin.read()
    return json.loads(raw)


def _cmd_place_objects_in_scene(payload: dict) -> dict:
    hint = payload.get("sketch_layout_hint")
    layout_hint = st.LayoutHint(**hint) if hint else None
    return st.place_objects_in_scene(
        payload["objects"],
        sketch_layout_hint=layout_hint,
        project_id=payload.get("project_id", "preview"),
        theme=payload.get("theme", "Shared Room"),
    )


def _cmd_read_sketch_layout(payload: dict) -> dict:
    hint = st.read_sketch_layout(payload.get("sketch_image"), backend=payload.get("backend"))
    return {"relations": hint.relations, "backend": hint.backend}


def _cmd_stage_immersive_reveal(payload: dict) -> dict:
    return st.stage_immersive_reveal(payload["connection_insight"], payload["objects"])


_COMMANDS = {
    "place_objects_in_scene": _cmd_place_objects_in_scene,
    "read_sketch_layout": _cmd_read_sketch_layout,
    "stage_immersive_reveal": _cmd_stage_immersive_reveal,
}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _COMMANDS:
        print(
            json.dumps({"error": f"usage: scene_tools_cli.py <{'|'.join(_COMMANDS)}> '<json>'"}),
            file=sys.stderr,
        )
        return 2
    command, raw_arg = argv[1], argv[2]
    try:
        payload = _read_arg(raw_arg)
        result = _COMMANDS[command](payload)
    except (st.SceneToolError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
