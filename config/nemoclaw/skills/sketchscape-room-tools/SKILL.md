---
name: sketchscape-room-tools
description: Build, read, and edit a SketchScape project's live VR room through the backend - draft a whole room from a project's uploaded 3D scans, read what's in the room now, or move/rotate/scale objects. Use when asked to build/set up/stage a project's room for the team's VR app (by project id), what's in a room, or to change a room's layout. Drafts only; a project member publishes.
---

# SketchScape room tools

These tools are HTTP clients for this project's own backend, run with your
shell/exec tool:

```
python3 {baseDir}/backend/room_tools_cli.py <verb> '<json>'
```

The backend URL and NemoClaw's service token are already configured in
this sandbox. Never print them, and never pass them as arguments. You act
as a service: you may read and draft, but **you can never publish**.
Always return the CLI's real JSON; never invent ids, positions or revision
numbers.

## draft_room: build a project's whole room

Use this when asked to build, set up, or stage the room for a project (the
team's VR app, not the Unity Editor). It lays out every ready 3D scan the
project's contributors uploaded. Pass `connection_insight` when you know
what ties the objects together, because it drives the lighting, the
connecting light path, the narration and the haptics.

```
python3 {baseDir}/backend/room_tools_cli.py draft_room '{
  "project_id": "<project id>",
  "connection_insight": {"theme": "Lazy Sunday at home", "explanation": "Everything from one slow afternoon on the couch."}
}'
```

It drafts a new, unpublished revision based on the live one, which replaces
the live layout once someone publishes it. Every object is grabbable and
keeps its contributor's attribution, and real scans are sized from their
labels.

## get_room_state: what's in the room now

```
python3 {baseDir}/backend/room_tools_cli.py get_room_state '{"project_id": "<project id>"}'
```

Returns `live_revision`, the objects (id, asset, transform, owner) and a
`summary`. A 404 means nothing has been published yet.

## propose_room_edit: move, rotate or scale objects

Call `get_room_state` first to get the current `base_revision`; never
guess it.

```
python3 {baseDir}/backend/room_tools_cli.py propose_room_edit '{
  "project_id": "<project id>",
  "base_revision": 7,
  "edits": [{"object_id": "cat_0", "position": [0.4, 0, 1.2]}]
}'
```

Each edit needs `object_id` plus at least one of `position`, `rotation` or
`scale`.

If the CLI fails with a `live_revision` in its error, the room changed.
Re-read it and redo the edit against the new revision. Never repeat the
same call.

## After drafting, tell the person

Report the drafted revision number and the objects. Say that it is **not
published yet**: a project member publishes it (on the website, or with
`scripts/publish_room.py`), and then `scripts/export_unity_experience.py`
plus Unity's offline builder turn it into the VR scene. Never claim the
room is live.

## Never

- Call a publish endpoint (the backend refuses a service identity anyway).
- Use the Unity MCP tools for a project's live room. They only edit the
  Editor's open scene. That's the separate `sketchscape-unity-room` skill,
  for quick Editor previews.
