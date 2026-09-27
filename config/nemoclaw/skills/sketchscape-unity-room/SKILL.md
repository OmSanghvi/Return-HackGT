---
name: sketchscape-unity-room
description: Build an immersive SketchScape Shared Room in the live Unity Editor - the uploaded photo rebuilt as a 3D Gaussian-splat scene you stand inside at real scale, its objects as grabbable 3D scans, an HDRI sky with matching light, web images, ambient sound, particles, staging, and the Meta Quest rig, grab and teleport setup. Use whenever asked to build, create, set up, craft, or stage a room/scene/experience/memory in Unity (or "in VR"/"on Quest").
---

# Build an immersive Shared Room in Unity

Two things work together:

- **The room planner CLI** (run it with your shell/exec tool):
  `python3 {baseDir}/backend/unity_room_cli.py <verb> <arg>`
- **The Unity MCP tools** (`unity-mcp__*`), which act on the Unity Editor.

The planner does all the layout, scale, lighting and audio math and writes
the Unity C# for you. **Never invent coordinates, sizes, URLs or C#.** Use
exactly what the planner printed.

## Procedure: one continuous turn, about 12-30 tool calls

**Don't end your turn or reply to the person until step 8.** A short
progress note is fine, but keep calling tools until the room is finalized.
Never stop to ask permission.

1. **Find the photo.** `list_scenes all` lists photo scenes (`scene_id`, the
   caption, mood, and the objects in each). Pick the one the person is
   talking about (the caption and object names tell you). If there are no
   scenes, run `list_assets all` and use `objects` instead of `scene_id`.

2. **Optional: find media that fits the memory** (1-3 searches, keep it
   quick). Each prints a few results with a ready `url` and `attribution`.
   ```
   python3 {baseDir}/backend/unity_room_cli.py search_images '{"query": "vintage family photos living room", "count": 4}'
   python3 {baseDir}/backend/unity_room_cli.py search_sounds '{"query": "rain on window"}'
   python3 {baseDir}/backend/unity_room_cli.py search_environment '{"kind": "hdri", "query": "cozy living room evening", "categories": "indoor"}'
   ```
   Pick 2-4 images that evoke the memory (never more than 6), at most 1-2
   sounds, and only override the sky if the default wouldn't fit. If a
   search says `"source": "curated"` or `"offline"`, the sandbox has no web
   access right now; that's fine, the room still gets curated media.

3. **Compose.** A bare `{"scene_id", "room_name"}` already gives a complete,
   immersive room: sky, key/fill/rim light matched to the photo, fog,
   particles, floor, ambient sound, teleport points. Add what you found:
   ```
   python3 {baseDir}/backend/unity_room_cli.py compose_room '{
     "scene_id": "<scene_id from list_scenes>",
     "room_name": "Lazy Sunday",
     "connection_insight": {"theme": "Sunday afternoons", "explanation": "Every Sunday the cats claimed the blanket before anyone else could."},
     "images": [{"url": "<url>", "title": "<title>", "attribution": "<attribution>"}],
     "sounds": [{"url": "<url>", "title": "<title>", "attribution": "<attribution>", "kind": "ambient"}]
   }'
   ```
   Options (all optional):
   - `objects`: `[{"label": "grandma's reading lamp", "asset_id"?: "..."}]`
     for extra things (from `list_assets`, or anything else, which becomes
     a placeholder). Things already in the photo are included
     automatically; don't repeat them.
   - `connection_insight`: what ties it together. It sets the mood colour,
     the reveal order, the light-path motif and the spoken narration.
   - `sounds[].kind`: `"ambient"` (fills the room) or `"object"` with
     `"attach_to": "<object label>"` (for example purring on the cat).
   - `images[].placement`: `"left"`, `"right"` or `"behind"`.
   - `environment`: `{"hdri": "<id from search_environment or a mood like 'night stars'>",
     "floor_texture": "<id or words like 'dark wood'>", "wall_texture": "<id or words>"
     (adds walls), "fog": false | 0.03, "shell": true}`.
   - `particles`: `"auto"` (default), `"none"`, or one of `dust`,
     `fireflies`, `snow`, `rain`, `embers`.
   - `player_eye_height`: metres (default 1.6).

   It prints a compact plan. `room.slug` names the room, and `unity_steps`
   is the exact, ordered list of Unity tool calls to make next.

4. **Build.** Run `build_code <room.slug>`. It builds the room in its own
   new scene file, so the team's other scenes are never touched.
   - One `=== BUILD CODE ... ===` block: call `unity-mcp__Unity_RunCommand`
     with `Code` set to everything between the markers, **verbatim** (no
     marker lines, no edits, no reformatting).
   - `=== BUILD CODE PART k/N ... ===` blocks (bigger rooms come in short
     parts): make **one `unity-mcp__Unity_RunCommand` call per part, in order
     1..N**, each with exactly the code between that part's markers. Parts
     1..N-1 answer "stored part k of N"; part N builds the room. If the output
     shows only part 1, get part k with `build_code <room.slug> k`. Never
     merge, shorten or retype parts, and never try to host the spec somewhere
     else: the parts are the way in.
   - "part k ... is missing" or "the room spec parts ... do not match": send
     the named part (or all parts) again, then the last part.
   - "has unsaved changes": stop and tell the person to save or discard
     them in Unity. Don't work around it.
   - "RoomKit is not installed": stop and tell the person to run
     `python scripts/install_hackgt_roomkit.py` on the Unity machine.
   - A compile error: run `build_code` again and retry once, copying exactly.
   - The build report lists anything that failed to download (an image or
     sound URL). That is not fatal; mention it at the end.

5. **Make it a Quest room.** Make every remaining call in
   `plan.unity_steps`, in order, with exactly the listed args:
   `unity-mcp__meta_get_config_information`, `unity-mcp__meta_add_camerarig`,
   `unity-mcp__meta_add_interactionrig`, one `unity-mcp__meta_add_grabbable`
   per object (`NameOrID` = the object id), and one
   `unity-mcp__meta_add_teleport_hotspot` per listed position. If one call
   fails, note it and continue.

6. **Finalize.** Run `finalize_code <room.slug>`, then call
   `unity-mcp__Unity_RunCommand` with its code verbatim. It moves the player
   rig to the spawn point, saves the scene and reports what is **actually**
   in it.

7. **Check (optional).** `unity-mcp__Unity_GetConsoleLogs` for errors.

8. **Report**, from the finalize output rather than the plan. Keep it short:
   the scene path; the photo scene; which objects are separate grabbable 3D
   scans and which are part of the photo; the sky, light and sound; the
   images; the teleport points; the narration line (spoken in the room,
   never shown as a text card); anything that failed. Mention the credits
   are in the room.

## Notes

- To change a room, compose again with the same `room_name` and the full
  new request, then build and finalize again. The build recreates that
  room's scene from scratch.
- Keep people's own words in object labels ("our cat Miso"). A label that
  contains a scanned label ("cat") gets the real scan.
- Unity's MCP capture tools don't draw Gaussian splats, so a screenshot may
  look empty even when the room is fine. Trust the build/finalize reports.
