#!/usr/bin/env python3
"""Command-line entry point exposing room_tools functions as CLI verbs, so an
agent runtime with shell access (e.g. an OpenClaw skill) can call
get_room_state / propose_room_edit without needing a Python import in-process.
Matches scene_tools_cli.py's pattern.

Usage:
    python3 room_tools_cli.py get_room_state '<json>'
    python3 room_tools_cli.py propose_room_edit '<json>'
    python3 room_tools_cli.py draft_room '{"project_id": "...", "connection_insight"?: {...}, "theme"?: "..."}'

Each verb reads one JSON argument (or "-" to read JSON from stdin) and
prints one JSON result to stdout. Non-zero exit + a JSON {"error": ...} on
failure. Credentials (SKETCHSCAPE_NEMOCLAW_TOKEN, SKETCHSCAPE_API_URL,
SKETCHSCAPE_NEMOCLAW_ID) come from the environment -- never pass them as
CLI arguments.
"""

from __future__ import annotations

import json
import sys

import room_tools as rt


def _read_arg(raw: str) -> dict:
    if raw == "-":
        raw = sys.stdin.read()
    return json.loads(raw)


def _cmd_get_room_state(payload: dict) -> dict:
    return rt.get_room_state(
        payload["project_id"],
        response_format=payload.get("response_format", "concise"),
    )


def _cmd_propose_room_edit(payload: dict) -> dict:
    return rt.propose_room_edit(
        payload["project_id"],
        payload["base_revision"],
        payload["edits"],
    )


def _cmd_draft_room(payload: dict) -> dict:
    return rt.draft_room(
        payload["project_id"],
        connection_insight=payload.get("connection_insight"),
        theme=payload.get("theme"),
        player_eye_height=payload.get("player_eye_height"),
    )


_COMMANDS = {
    "get_room_state": _cmd_get_room_state,
    "propose_room_edit": _cmd_propose_room_edit,
    "draft_room": _cmd_draft_room,
}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _COMMANDS:
        print(
            json.dumps({"error": f"usage: room_tools_cli.py <{'|'.join(_COMMANDS)}> '<json>'"}),
            file=sys.stderr,
        )
        return 2
    command, raw_arg = argv[1], argv[2]
    try:
        payload = _read_arg(raw_arg)
        result = _COMMANDS[command](payload)
    except rt.StaleRevisionError as exc:
        print(json.dumps({"error": str(exc), "live_revision": exc.live_revision, "room_state": exc.room_state}))
        return 1
    except (rt.RoomToolError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
