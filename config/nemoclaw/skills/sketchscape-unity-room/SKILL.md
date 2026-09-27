---
name: sketchscape-unity-room
description: Build an immersive SketchScape Shared Room in the live Unity Editor - the uploaded photo rebuilt as a 3D Gaussian-splat scene you stand inside at real scale, its objects as grabbable 3D scans, an HDRI sky with matching light, web images, ambient sound, particles, staging, and a Quest-ready rig with grab, teleport and pickups. Use whenever asked to build, create, set up, craft, or stage a room/scene/experience/memory in Unity (or "in VR"/"on Quest").
---

# Build an immersive Shared Room in Unity

Two things work together:

- **The room planner CLI**, run with the exec tool:
  `python3 {baseDir}/backend/unity_room_cli.py <verb> <arg>`
- **Unity's Run Command tool**, which runs the C# the planner prints.

The planner does all the layout, scale, lighting, audio and Quest setup math
and writes the Unity C# for you. **Never invent coordinates, sizes, URLs or
C#.** Use exactly what the planner printed.

## Calling tools (no searching needed)

Call tools directly with `tool_call`. Don't use `tool_search` or
`tool_describe`: every result stays in your context, and a build that fills
its context loses track of what it already did.

| What | `tool_call` id | `args` |
|---|---|---|
| Run a planner command | `openclaw:core:exec` | `{"command": "python3 {baseDir}/backend/unity_room_cli.py <verb> <arg>", "timeout": 120}` |
| Run C# in Unity | `mcp:bundle-mcp:unity-mcp__Unity_RunCommand` | `{"Title": "<short title>", "Code": "<the C# between the markers>"}` |
| Unity console (only if something failed) | `mcp:bundle-mcp:unity-mcp__Unity_GetConsoleLogs` | `{"logTypes": "error", "maxEntries": 10}` |

Don't call `meta_add_*` tools: the finalize step does all of that in one call.

## Procedure: one continuous turn, about 10-14 tool calls

**Don't end your turn or reply to the person until step 7.** A short
progress note is fine, but keep calling tools until the room is finalized.
Never stop to ask permission. `<slug>` is the room name with every character
other than `A-Z a-z 0-9 _ -` turned into `_` (for example
`Cabin living room` -> `Cabin_living_room`).

0. **Status first (always, also after any summary or hiccup).**
   `status_code <slug>`, then run its code in Unity. It prints one JSON line:
   `built`, `grabbable`, `teleports`, `camera_rig`, `pickups`,
   `quest_performance`, `finalized`, splat counts...
   - `finalized: true` -> skip to step 7 (report).
   - `built: true` but not finalized -> skip to step 5.
   - `open: false` with `scene_exists: true` (the room was built but its scene
     isn't the open one, so the other values are `null`) -> skip to step 5;
     finalize opens the room's scene itself.
   - `scene_exists: false` -> start at step 1. **Never rebuild a room that
     is already built.**
   - `"error"` in the JSON, or a build/finalize saying another open scene has
     unsaved changes -> stop and tell the person (don't discard their work).
     If you notice you are repeating steps you already did, stop, run
     `status_code <slug>` and continue from what it says.

1. **Find the photo.** If the request already names the scene (for example
   "scene 3ae525c1"), skip this step and give that id to `compose_room` (the
   8-character prefix works). Otherwise `list_scenes all` lists photo scenes
   (`scene_id`, the caption, mood, and the objects in each); pick the one the
   person is talking about. If there are no scenes, run `list_assets all` and
   use `objects` instead of `scene_id`.

2. **Optional: media** (0-2 searches, keep it quick). Each prints a few
   results with a ready `url` and `attribution`:
   ```
   python3 {baseDir}/backend/unity_room_cli.py search_images '{"query": "vintage family photos living room", "count": 4}'
   python3 {baseDir}/backend/unity_room_cli.py search_sounds '{"query": "rain on window"}'
   python3 {baseDir}/backend/unity_room_cli.py search_environment '{"kind": "hdri", "query": "cozy living room evening", "categories": "indoor"}'
   ```
   At most 4 images and 1-2 sounds. If a search says `"source": "curated"`
   or `"offline"`, that's fine: the room still gets curated media.

3. **Compose.** A bare `{"scene_id", "room_name"}` already gives a complete
   room: sky, key/fill/rim light matched to the photo, fog, particles, floor,
   ambient sound, teleport points, the shared layer and the Quest setup.
   ```
   python3 {baseDir}/backend/unity_room_cli.py compose_room '{
     "scene_id": "<scene_id from list_scenes>",
     "room_name": "Lazy Sunday",
     "connection_insight": {"theme": "Sunday afternoons", "explanation": "Every Sunday the cats claimed the blanket before anyone else could."},
     "images": [{"url": "<url>", "title": "<title>", "attribution": "<attribution>"}],
     "sounds": [{"url": "<url>", "title": "<title>", "attribution": "<attribution>", "kind": "ambient"}]
   }'
   ```
   Optional keys: `objects` (`[{"label": "grandma's reading lamp", "asset_id"?: "..."}]`
   for extra things; things in the photo are included automatically),
   `connection_insight` (mood colour, reveal order, narration),
   `sounds[].kind` `"ambient"` or `"object"` with `"attach_to": "<label>"`,
   `images[].placement` `"left"|"right"|"behind"`,
   `environment` (`{"hdri": ..., "floor_texture": ..., "wall_texture": ..., "fog": false|0.03, "shell": true}`),
   `particles` (`"auto"`, `"none"`, `dust`, `fireflies`, `snow`, `rain`, `embers`),
   `player_eye_height` (default 1.6).
   It prints a short summary: `room.slug`, the objects, and `unity_steps`
   (build parts, then finalize, then status).

4. **Build.** Run `build_code <slug>` once and copy each part straight from
   its output into a Run Command call. Don't redirect it to a file, split it
   with a script or read it back: that costs extra calls and context.
   One Run Command call per block:
   - One `=== BUILD CODE ... ===` block: pass everything between the markers
     as `Code`, **verbatim** (no marker lines, no edits, no reformatting).
   - `=== BUILD CODE PART k/N ... ===` blocks: **one call per part, in order
     1..N**, each with exactly that part's code. Parts 1..N-1 answer "stored
     part k of N"; part N builds the room (it can take a minute or two). If
     the output shows only part 1, get part k with `build_code <slug> k`.
     Never merge, shorten or retype parts.
   - "part k ... is missing" / "the room spec parts ... do not match": send
     the named part (or all parts) again, then the last part.
   - A compile error (usually a character changed while copying): run
     `build_code <slug>` again and resend, once.
   - A timeout or "Unity not detected": Unity is still importing/building.
     Wait about 30 s (`sleep 30` with exec; never sleep longer), then run
     step 0 (status) - don't resend the build blindly.
   - "has unsaved changes" (any open scene): stop and tell the person to save
     or discard them in Unity. RoomKit refuses rather than lose their work.
   - "RoomKit is not installed" or "older than 1.0.16": stop and tell the
     person to run `python scripts/install_hackgt_roomkit.py` on the Unity
     machine.
   - Failed downloads (an image or sound URL) are not fatal; mention them.

5. **Finalize.** `finalize_code <slug>`, then run its code. In one call
   RoomKit adds the Meta Quest camera rig and interaction rig, near and
   distance grab on every separate object, the teleport hotspots, desktop
   pickups and foveated rendering, keeps Android free of MSAA, moves the rig to the spawn point,
   saves the scene, and reports what is **actually** there. Running it twice
   is safe (it only adds what's missing).

6. **Confirm.** `status_code <slug>` once more; check `finalized: true`,
   `grabbable` and `distance_grabbable` = the object count, `teleports` > 0, `quest_lod_renderers` >
   0 and `full_res_renderers` = 0 when the scans have Quest copies.

7. **Report**, from the finalize/status output rather than the plan. Short:
   the scene path; the photo scene; which objects are separate grabbable
   scans and which stay in the photo; sky, light and sound; images; teleport
   points; how people interact (below); the narration line (spoken in the
   room, never shown as a text card); anything that failed. Credits are in
   the room.

## What the room gives people (say this in the report, don't rebuild it)

- **In the headset (Meta Quest):** move with the thumbstick (smooth
  locomotion and smooth turning) or teleport to the hotspots; grab any
  separate object with a hand or controller, up close or from a distance
  (distance grab pulls it to your hand); poke or ray the shared layer's
  buttons (Account 1 / Account 2 badges, envelopes). A head-collision guard
  gently pushes you back out if you lean into a wall or an object.
- **In the Unity Editor without a headset:** hold the right mouse button to
  look, WASD to move, Q/E down/up, Shift faster; hold left-click on an
  object to carry it, scroll to turn it; let go and it glides back to its
  place (`DesktopCameraLook`, `DesktopPickup`, `SketchScapePickup`).
- Carrying never changes the room: objects return to their place. Layout
  changes go through a new compose/build.
- **Shared layer** (rooms from a project's photos): Account 1 / Account 2
  switcher, each person's upload notes on cards beside their objects,
  sealed letters only the recipient can open, contributor tags. It reads
  live data when online and a snapshot offline. Don't build it yourself.

## Quest performance rules (why the room is built this way)

On 2026-09-27 a room with 3.37 million Gaussian splats (a 976k-splat teddy
bear) ran at **5 FPS on a Quest 2**: jittery, laggy, and nearby objects
flickered as the headset re-projected stale frames. So every room now:

- uses the sync's **Quest-sized copies** (`<file>_quest.ply`: at most 120k
  splats for the photo scene and 25k per object, about 300k in total; check
  `splats_total` in status);
- runs Android at a quality level **without MSAA** and turns on **foveated
  rendering** on the rig (`QuestPerformance`).

Keep it that way: never swap a room back to full-resolution splats, never
add big splat assets beyond the photo's objects, keep images ≤ 4, sounds ≤ 2
added by you, particles modest. If status shows `full_res_renderers` > 0,
say so in the report (the scans need a re-sync to get Quest copies).

## Notes

- To change a room, compose again with the same `room_name` and the full new
  request, then build, finalize and confirm. The build recreates that room's
  scene from scratch; other scenes are never touched.
- Keep people's own words in object labels ("our cat Miso"). A label that
  contains a scanned label ("cat") gets the real scan.
- Capture tools and the Scene view may not show splats right after a build
  (the splat renderer refreshes on Play or scene reload). Trust status and
  the reports; don't rebuild because a picture looks empty.
