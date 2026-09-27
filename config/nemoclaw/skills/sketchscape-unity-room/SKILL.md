---
name: sketchscape-unity-room
description: Build a SketchScape Shared Room in the live Unity Editor from contributed objects - layout, mood lighting, connecting light-path motif, Meta Quest camera rig, interaction rig, grabbable objects and teleport hotspots. Use whenever asked to build, create, set up, craft, or stage a room/scene/experience in Unity (or "in VR"/"on Quest") from a list of objects or memories.
---

# Build a Shared Room in Unity

You build the room with two things together:

- **The room planner CLI** (run it with your shell/exec tool):
  `python3 {baseDir}/backend/unity_room_cli.py`
- **The Unity MCP tools** (`unity-mcp__*`), which act on the Unity Editor.

The planner does the layout, scale, depth and staging math and writes the
Unity C# for you. **Never invent coordinates, sizes, or C#.** Always use what
the planner printed.

## Real 3D scans

Some contributed objects already have a real 3D scan (a Gaussian splat
reconstructed from the contributor's photo) imported into Unity. To see
which labels have one, run:

```
python3 {baseDir}/backend/unity_room_cli.py list_assets all
```

`compose_room` automatically uses the real scan for any object whose label
contains a scanned label ("our cat Miso" uses the "cat" scan), and a
placeholder cube for the rest. Keep the person's own words in each `label`,
and make sure it includes the scanned label when that's the object they
mean. Each plan object's `visual` field says which one it got.

## Procedure (do every step, in order, without stopping to ask)

This is one continuous job with about 10–20 tool calls. **Don't end your
turn or reply to the person until step 5.** A short progress note is fine,
but keep calling tools in the same turn until the room is finalized.

1. **Plan.** Run `compose_room` with the objects the person gave you. Each
   object needs an `asset_id` (letters, digits, `_ . -`; make one from the
   label if none was given, like `lamp1`) and a `label` (what it is, in
   the person's words). Include `connection_insight` when you know what
   ties the objects together, since it drives the lighting and motif. Use a
   short `room_name`.

   ```
   python3 {baseDir}/backend/unity_room_cli.py compose_room '{
     "objects": [
       {"asset_id": "lamp1", "label": "grandma'"'"'s reading lamp"},
       {"asset_id": "guitar1", "label": "dad'"'"'s guitar"}
     ],
     "connection_insight": {"theme": "Evenings at home", "explanation": "Both lived in the corner where the family gathered after dinner."},
     "room_name": "Evenings at Home"
   }'
   ```

   It prints the plan as one line of JSON. `room.slug` names the room, and
   `unity_steps` is the exact, ordered list of Unity tool calls to make
   next.

2. **Build.** Run:
   ```
   python3 {baseDir}/backend/unity_room_cli.py build_code <room.slug>
   ```
   Then call `unity-mcp__Unity_RunCommand` with `Code` set to everything
   between the `=== BUILD CODE ... ===` and `=== END BUILD CODE ===`
   marker lines, **verbatim**. Don't include the marker lines, and don't
   edit, shorten or reformat the code. This creates the room in its own
   new scene file, so the team's other scenes are never touched.
   - If the result says a scene "has unsaved changes", stop and tell the
     person to save or discard them in Unity. Don't work around it.
   - If it fails to compile, run `build_code` again and retry once,
     copying the code exactly.

3. **Make it a Quest room.** Make every remaining call in
   `plan.unity_steps` with exactly the listed args:
   - `unity-mcp__meta_get_config_information`
   - `unity-mcp__meta_add_camerarig`
   - `unity-mcp__meta_add_interactionrig`
   - one `unity-mcp__meta_add_grabbable` per object (`NameOrID` = object
     id)
   - one `unity-mcp__meta_add_teleport_hotspot` per listed position

   If one call fails, note it and continue with the rest.

4. **Finalize and check.** Run:
   ```
   python3 {baseDir}/backend/unity_room_cli.py finalize_code <room.slug from the plan>
   ```
   Then call `unity-mcp__Unity_RunCommand` with `Code` = everything between
   its FINALIZE CODE markers, verbatim. This saves the scene and reports
   what is **actually** in it: the camera rig, the teleport hotspot count,
   and each object with its grab components.

5. **Report**, using the finalize output rather than the plan. Keep it
   short: the scene path, how many objects are grabbable, the camera rig,
   the hotspot count, the lighting mood, the reveal order, and the
   narration line (spoken in the room, never shown as a text card). Also
   report anything that failed. Say which objects are real 3D scans and
   which are still placeholder cubes (from each plan object's `visual`).
   An object with no scan becomes a cube.

## Other useful Unity tools

- `unity-mcp__Unity_GetConsoleLogs`: check for errors after building.
- `unity-mcp__Unity_SceneView_CaptureMultiAngleSceneView`: look at the room.
- `unity-mcp__meta_get_interactors_state`: inspect the interaction rig.

To change an existing room (add or remove objects, change the mood), run
the whole procedure again with the full new object list and the same
`room_name`. The build step recreates that room's scene from scratch.
