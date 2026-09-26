#!/usr/bin/env python3
"""Command-line entry point exposing `tour_author.author_guided_tour` as a
CLI verb, so an agent runtime with shell access (e.g. an OpenClaw skill) can
call it without needing a Python import in-process. Mirrors
`scene_tools_cli.py`'s shape.

Usage:
    python3 tour_author_cli.py author_guided_tour '<json>'

The JSON argument (or "-" to read JSON from stdin) is
`{"project_id": "..."}`. Prints one JSON result to stdout:
`{"tour_version": ..., "status": "draft"}`. Non-zero exit + a JSON
`{"error": ...}` on failure.

This CLI never supplies its own `model_call` -- it calls
`author_guided_tour` with the default, which raises clearly until the
NemoClaw agent runtime (Build Plan step 3) exists to drive it. A live
NemoClaw session imports `tour_author` directly and passes its own
`model_call` instead of shelling out to this script.
"""

from __future__ import annotations

import json
import sys

import tour_author as ta


def _read_arg(raw: str) -> dict:
    if raw == "-":
        raw = sys.stdin.read()
    return json.loads(raw)


def _cmd_author_guided_tour(payload: dict) -> dict:
    return ta.author_guided_tour(payload["project_id"])


_COMMANDS = {
    "author_guided_tour": _cmd_author_guided_tour,
}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in _COMMANDS:
        print(
            json.dumps({"error": f"usage: tour_author_cli.py <{'|'.join(_COMMANDS)}> '<json>'"}),
            file=sys.stderr,
        )
        return 2
    command, raw_arg = argv[1], argv[2]
    try:
        payload = _read_arg(raw_arg)
        result = _COMMANDS[command](payload)
    except (ta.TourAuthorError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
