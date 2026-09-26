---
name: sketchscape-room-tools
description: Read the live state of a SketchScape Collaborative VR room and propose an edit to it (move/rotate/scale objects) as a draft revision. Use when asked what's in a room right now, or to change a live room's layout. Never publishes -- a person approves the publish on the website.
---

# SketchScape room tools

Two thin HTTP-client tools live at
`/sandbox/sketchscape/backend/room_tools_cli.py`. They call this project's
own backend room API (Build Plan step 24) over HTTPS/HTTP -- never write to
any store directly and never publish a room. Always shell out to the CLI
and return its real JSON output; never fabricate object ids, positions, or
revision numbers.

Requires `SKETCHSCAPE_NEMOCLAW_TOKEN` and `SKETCHSCAPE_API_URL` to be set in
this sandbox's environment (see the runtime credential provider -- never put
either value in a file). Optional: `SKETCHSCAPE_NEMOCLAW_ID` to tag which
NemoClaw instance made a change (shows up as `nemoclaw:<id>` in `author`).

## get_room_state

Call this first, whenever you're asked about a room's current contents or
before proposing any edit. Read-only, no approval needed.

```
python3 /sandbox/sketchscape/backend/room_tools_cli.py get_room_state '{
  "project_id": "<project id>"
}'
```

Returns `live_revision`, the object list (id, asset_id, position/rotation/
scale, who owns each one, whether it is editable by NemoClaw's caller), and
a short `summary` string. Pass `"response_format": "detailed"` for the full
raw room-state JSON instead of the concise summary.

404 means the project has nothing published yet -- there is no live room to
read or edit.

## propose_room_edit

Call this to move, rotate, or scale one or more existing objects in the
room. Always call `get_room_state` first (or use its `live_revision`) to
get the current `base_revision` -- never guess it.

```
python3 /sandbox/sketchscape/backend/room_tools_cli.py propose_room_edit '{
  "project_id": "<project id>",
  "base_revision": 7,
  "edits": [
    {"object_id": "lamp_1", "position": [0.4, 0, 1.2]},
    {"object_id": "sofa_1", "rotation": [0, 90, 0], "scale": [1, 1, 1]}
  ]
}'
```

Each edit needs `object_id` plus at least one of `position`/`rotation`/
`scale` (each a 3-number list; values you omit are left alone). This drafts
a **new, unpublished revision** built from `base_revision` -- it never
touches the live room. The result's `summary` says which revision was
drafted, what changed, and which contributor(s) own the objects moved, so
whoever reviews it on the website's Room page knows what they're approving.

**If the CLI exits non-zero with a `live_revision` field in its error
JSON**, the room changed since you read it (someone else's edit or a
different NemoClaw draft went live). The error already re-read the room for
you (`room_state` in that same JSON) -- call `get_room_state` again if you
need the freshest view, then redo `propose_room_edit` with the new
`base_revision`. Never retry the exact same call; the objects you're
editing may have moved.

## What you must never do with these tools

- Never call a publish endpoint yourself. Publishing a drafted revision
  (`blueprint.publish`, approval-gated) only happens after a person clicks
  Approve on the website's Room page.
- Never write scene state directly (no store access, no Unity MCP Extension
  call for a live room -- that surface only edits the Editor's own open
  scene, never a shipped/live room; see top-tier-nemoclaw-tool-design).

## Reporting results back to the person

Keep it short and concrete, e.g.: "Room revision 8 drafted from live 7:
moved lamp_1 to (0.4, 0, 1.2), rotated sofa_1 90 degrees; sofa_1 is
demo-bob's contribution. Not published -- needs approval on the website."
Never fabricate coordinates or revision numbers -- always read them from the
tool's actual JSON output.
