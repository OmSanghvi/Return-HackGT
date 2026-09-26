#!/usr/bin/env python3
"""Command-line entry point for blueprint_to_unity.blueprint_to_unity_command,
mirroring scene_tools_cli.py's shape so an agent runtime with shell access
can generate the Unity_RunCommand C# script for the Unity write path
without needing a Python import in-process.

Usage:
    python3 blueprint_to_unity_cli.py '<blueprint-json>'
    python3 blueprint_to_unity_cli.py -   # read JSON from stdin

Prints the generated C# source to stdout, ready to paste into the
Unity_RunCommand MCP tool. Non-zero exit + a JSON {"error": ...} on stderr
on failure.
"""

from __future__ import annotations

import json
import sys

from blueprint_to_unity import blueprint_to_unity_command
from scene_tools import SceneToolError


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            json.dumps({"error": "usage: blueprint_to_unity_cli.py '<blueprint-json>'|-"}),
            file=sys.stderr,
        )
        return 2
    raw = argv[1]
    if raw == "-":
        raw = sys.stdin.read()
    try:
        blueprint = json.loads(raw)
        code = blueprint_to_unity_command(blueprint)
    except (SceneToolError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
