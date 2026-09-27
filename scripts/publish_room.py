#!/usr/bin/env python3
"""Publish a drafted room revision as a project member (the human step).

NemoClaw can only *draft* a room (``draft_room`` / ``propose_room_edit``);
publishing is a person's decision. The web app has no publish button yet, so
this is that button: it publishes as one of the backend's demo accounts
(``SKETCHSCAPE_AUTH_MODE=demo``, header ``X-SketchScape-Dev-User``), which
must be a member of the project.

    python scripts/publish_room.py --project-id <id> [--revision N] [--as demo-alice]
        [--api-url http://<wsl-ip>:8000]

Without --revision it publishes the newest revision. Prints the result, then
the export command that turns the published room into the Unity VR scene.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("scripts", 1)[0] + "backend")
from room_tools import _config_value  # noqa: E402  (same ~/.config/sketchscape/api-url)


def _call(method: str, url: str, user: str) -> tuple[int, object]:
    request = urllib.request.Request(url, method=method, headers={"X-SketchScape-Dev-User": user, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body.decode(errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--revision", type=int)
    parser.add_argument("--as", dest="user", default="demo-alice", help="demo account that is a project member")
    parser.add_argument("--api-url", default=_config_value("api-url") or "http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.api_url.rstrip("/")

    revision = args.revision
    if revision is None:
        status, project = _call("GET", f"{base}/v1/projects/{args.project_id}", args.user)
        if status != 200:
            print(f"Could not read project ({status}): {project}", file=sys.stderr)
            return 1
        revisions = project.get("blueprint_revisions") or []
        if not revisions:
            print("The project has no drafted revisions to publish.", file=sys.stderr)
            return 1
        revision = max(revisions)

    status, result = _call("POST", f"{base}/v1/projects/{args.project_id}/blueprints/{revision}/publish", args.user)
    if status != 200:
        print(f"Publish failed ({status}): {result}", file=sys.stderr)
        return 1
    objects = (result or {}).get("scene", {}).get("objects", [])
    print(f"Published revision {revision} of {args.project_id} as {args.user}: {len(objects)} object(s).")
    print("Next, build it into the team's VR app:")
    print(f"  python scripts/export_unity_experience.py --api-url {base} --project-id {args.project_id} --unity-project unity")
    print("  then in Unity (unity/): Tools > SketchScape > Authoring > Build Offline Experience Scene")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
