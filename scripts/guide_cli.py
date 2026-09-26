#!/usr/bin/env python3
"""Headset-free terminal client for the guide runtime (Build Plan step 32).

Plays a tour against a running backend without a Unity build: create a
session, then drive it with single-letter commands. Uses `urllib.request`
only (matching `backend/room_tools.py`'s HTTP-client style, no `requests`
dependency).

Usage:
    python3 scripts/guide_cli.py --project p_123 [--api http://127.0.0.1:8000]
        [--account demo-alice] [--live]

Commands (read from stdin, one per line):
    n            next
    r            repeat
    m            more
    a <id>       ask about element <id>
    l <id>       linger on element <id>
    q <text...>  ask a free-text question
    e            end
    quit / q!    exit the CLI (not to be confused with `q <text>`, which
                 needs at least one space-separated word after `q`)

Each turn prints the step, the lines with their fact ids, and
`source`/`validation`/`latency_ms`. `--live` is only a reminder: this CLI
never holds a model key itself -- the backend process must already be
running with a live `SKETCHSCAPE_GUIDE_MODEL_PROVIDER` configured.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT = "demo-alice"
TIMEOUT_S = 20.0


def _request(method: str, url: str, account: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-SketchScape-Dev-User": account},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        payload = error.read().decode("utf-8", errors="replace")
        print(f"HTTP {error.code}: {payload}", file=sys.stderr)
        raise


def _print_turn(turn: dict) -> None:
    print(f"[{turn.get('step_id', '')}] source={turn.get('source')} "
          f"backend={turn.get('backend')} model={turn.get('model')} "
          f"latency_ms={turn.get('latency_ms')} end={turn.get('end')}")
    for line in turn.get("lines", []):
        print(f"  say: {line['text']}  (facts: {line['fact_ids']})")
    validation = turn.get("validation", {})
    if validation.get("repairs"):
        print(f"  repairs: {validation['repairs']}")
    move_to = turn.get("move_to", {})
    if move_to.get("anchor_element_id"):
        print(f"  move_to: {move_to['anchor_element_id']} offset={move_to.get('offset_m')}")
    if turn.get("highlight_element_ids"):
        print(f"  highlight: {turn['highlight_element_ids']}")
    if turn.get("reveal_element_ids"):
        print(f"  reveal: {turn['reveal_element_ids']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--project", required=True)
    parser.add_argument("--account", default=DEFAULT_ACCOUNT)
    parser.add_argument("--live", action="store_true", help="Reminder only -- see module docstring.")
    args = parser.parse_args(argv[1:])

    if args.live:
        print(
            "--live: this CLI never holds a model key. Make sure the backend process is "
            "already running with SKETCHSCAPE_GUIDE_MODEL_PROVIDER set to a live provider.",
            file=sys.stderr,
        )

    base = args.api.rstrip("/")
    session = _request(
        "POST", f"{base}/v1/rooms/{args.project}/guide/sessions", args.account
    )
    session_id = session["session_id"]
    turn_seq = 1
    print(f"session {session_id}, tour_version {session['tour_version']}")
    _print_turn(session["turn"])

    def send(event: dict, client_turn_id: str) -> None:
        nonlocal turn_seq
        body = {"client_turn_id": client_turn_id, "turn_seq": turn_seq, "event": event}
        turn = _request(
            "POST",
            f"{base}/v1/rooms/{args.project}/guide/sessions/{session_id}/turns",
            args.account,
            body,
        )
        _print_turn(turn)
        turn_seq += 1

    print("commands: n=next r=repeat m=more a <id>=ask_about l <id>=linger q <text>=question e=end quit=exit")
    counter = 0
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        if line in ("quit", "q!"):
            break
        counter += 1
        client_turn_id = f"cli-{counter}"
        command, _, rest = line.partition(" ")
        rest = rest.strip()
        if command == "n":
            send({"type": "next"}, client_turn_id)
        elif command == "r":
            send({"type": "repeat"}, client_turn_id)
        elif command == "m":
            send({"type": "more"}, client_turn_id)
        elif command == "a" and rest:
            send({"type": "ask_about", "element_id": rest}, client_turn_id)
        elif command == "l" and rest:
            send({"type": "linger", "element_id": rest}, client_turn_id)
        elif command == "q" and rest:
            send({"type": "question", "text": rest}, client_turn_id)
        elif command == "e":
            send({"type": "end"}, client_turn_id)
            break
        else:
            print(f"unrecognized command: {line!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
