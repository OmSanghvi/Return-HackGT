---
name: world-scene-authoring
description: Use when building or editing a placeholder world scene for a hub room (the scene a portal opens in the Quest app) through the Unity MCP. Covers the layout JSON at unity/Assets/Worlds/Layouts/{roomId}.json, the prop library in unity/Assets/Worlds/Props, the Return.* MCP tools (ListWorldRooms, ListProps, ApplyWorldLayout, CaptureWorld), coordinate conventions, and the look-and-adjust loop.
---

# World scene authoring (placeholder worlds)

Real reconstructions are not ready, so each Ready room's portal opens a hand-placed
placeholder world. A world is **data**: one layout JSON per room. Never edit the
world scene by hand or with generic GameObject tools; the scene is regenerated
from the layout on every apply and hand edits are lost.

## The loop

1. `Return.ListWorldRooms`: room id, title, place, date, sky, and whether a layout exists.
   Only `phase: Ready` rooms have portals. Read the title/place/date and picture the memory
   (e.g. "The night hike, Blood Mountain, October"). Cheap placeholders, but make the
   arrival view read as that place within one glance.
2. `Return.ListProps` with a filter (`tree`, `chair`, `rock`, `pirate-kit/`, ...): ids and
   real-world size in metres. Filter; the full list is ~620 entries.
3. `Return.ApplyWorldLayout` with `roomId` and the full `layoutJson`. It saves the file and
   rebuilds the scene. Read `warnings` (unknown prop ids, bad colors) and fix them.
4. `Return.CaptureWorld` with `view` = `front`, then `top`, (and `left`/`right`/`back` if the
   world surrounds the viewer). Open the returned PNG and look at it. Check scale against
   the 1.6 m eye height, gaps, floating or buried props, clutter right in the viewer's face.
5. Edit the layout and apply again. Two or three rounds is normal.

If a tool says a scene has unsaved changes, ask the user; do not discard their work.

## Layout format

```json
{
  "roomId": "night-hike",
  "sceneName": "NightHike",
  "sky": true,
  "props": [
    { "prop": "primitive/plane", "name": "Ground", "size": [80, 0, 80], "color": "#2f3b2a", "pos": [0, 0, 0] },
    { "prop": "nature-kit/tree_pineTallA", "pos": [-4, 0, 6], "yaw": 30 },
    { "prop": "nature-kit/tent_detailedOpen", "pos": [2, 0, 5], "yaw": 200, "scale": 0.8 },
    { "prop": "survival-kit/campfire-pit", "name": "Campfire", "pos": [0, 0, 3] }
  ]
}
```

- `sceneName`: PascalCase, unique; becomes `Assets/Scenes/Worlds/{sceneName}.unity`. Applying
  registers it in Build Settings and the hub's `worldMap` automatically.
- `sky`: surround with the room's painted sky dome at runtime. Keep `true`.
- `prop`: an id from `Return.ListProps`, or a built-in `primitive/plane|cube|cylinder|sphere`
  sized by `size` [x, y, z] metres (planes ignore y). Use primitives for ground, water,
  paths, walls, floors, and anything the kits lack.
- `pos` [x, y, z] metres; `y` is where the prop's **lowest point** rests, so 0 = on the floor.
- `yaw` degrees about +Y. Kit models face +Z at yaw 0 (away from the viewer); yaw 180 turns
  a chair or sign toward the viewer. `scale` multiplies the size ListProps reports (default 1).
- `color` `#rrggbb`: the color of a primitive, or replaces every material color on a model
  (only useful for single-material models).
- `name` optional; shows in the hierarchy. Name things the guide bot might point at.

## Space and scale

- Viewer space: the viewer arrives standing at the origin, facing **+Z**, eyes at 1.6 m.
  +X is their right. The whole world is re-anchored under the viewer at runtime.
- Keep 1.5 m clear around the origin. Put the hero object (the thing the memory is about)
  3 to 8 m ahead, supporting props to the sides, big things (trees, cliffs, water) further out.
- Sizes from ListProps are already real-world, but Kenney proportions are stylized:
  flowers and grass come out oversized (use `scale` 0.3 to 0.5), check furniture against
  a 0.45 m seat height.
- Stack flat surfaces at least 5 cm apart (ground at 0, water at 0.05, path at 0.1),
  or they flicker in the headset.
- 20 to 60 props is plenty. Quest is the target: no hundreds of copies.

## Prop library

`unity/Assets/Worlds/Props/{kit}/`: Kenney CC0 kits as GLB.

| kit | good for |
| --- | --- |
| `nature-kit` | trees (incl. `_fall`, `_dark`, palms), rocks, cliffs, flowers, grass, logs, tents, campfires, canoe, bridges, fences, paths |
| `furniture-kit` | indoor rooms: sofas, chairs, tables, beds, lamps, kitchen, rugs, walls, doorways |
| `pirate-kit` | beach and water: palms, sand patches, docks, boats, barrels, crates, flags |
| `survival-kit` | camping: tents, bedrolls, campfire pit, fish, tools, signposts, autumn trees |

To add a kit, drop its GLB/FBX folder under `Props/`, add a `KitScale` entry in
`unity/Assets/Editor/ReturnWorldScenes.cs` if it is not authored in metres (compare a
ListProps size with the real object), and patch `"metallicFactor": 1` to `0` in Kenney
GLBs (they otherwise render as chrome).

## Files

- `unity/Assets/Editor/ReturnWorldScenes.cs`: layout parsing and scene building
  (menu `Tools/Return/Worlds/Build All From Layouts`, or batch
  `-executeMethod ReturnWorldScenes.BuildAllFromLayouts`).
- `unity/Assets/Editor/ReturnWorldMcpTools.cs`: the `Return.*` MCP tools.
- `unity/Assets/Worlds/Layouts/lake-house.json`: worked example.
- Captures land in `unity/Library/WorldCaptures/` (not committed). The painted sky is
  not in captures; it is built when the portal opens.
