---
name: sketchscape-scene-tools
description: Turn a list of SketchScape contributed objects into an immersive Unity room layout (placement, depth, relative scale) and choreograph the emotional reveal when a connection between contributors' objects is shared. Use when asked to place/arrange objects in a scene, lay out a room, or stage a reveal/connection moment.
---

# SketchScape scene tools

Three deterministic, offline reasoning tools live at
`/sandbox/sketchscape/backend/scene_tools_cli.py`. They are the actual
composition mechanism (Build Plan steps 4 and 6 of this project) -- never
bypass them by inventing your own coordinates or guessing a layout by hand.
Always shell out to the CLI and return its real JSON output.

## place_objects_in_scene

Call this whenever you're given a list of contributed objects (each with an
`asset_id` and a `label`) and asked to arrange them in a room/scene. It
reasons about realistic interior-design layout: an arc facing the room's
entry point, varied depth per object for an immersive (non-flat) feel, and
label-driven relative scale (a "reading lamp" comes out much smaller than a
"family sofa"). It returns a schema-valid blueprint proposal -- it never
publishes anything.

```
python3 /sandbox/sketchscape/backend/scene_tools_cli.py place_objects_in_scene '{
  "objects": [
    {"asset_id": "a1", "label": "reading lamp"},
    {"asset_id": "a2", "label": "family sofa"}
  ],
  "theme": "Two homes, one memory",
  "project_id": "<project id if known, else omit>"
}'
```

Always pass a **list** -- 1, 2, 5, or any N objects, never a hard-coded
pair. Optionally include `"sketch_layout_hint": {"relations": ["lamp left_of chair"]}`
if a Notability sketch suggested spatial relationships (left_of, right_of,
behind, in_front_of are understood; anything else is safely ignored).

## read_sketch_layout

Optional pre-step: extracts rough spatial relationships from a sketch image
into the `sketch_layout_hint` shape above. Currently mock-only (returns no
relations) until the live vision path is wired up -- do not treat its
absence as a failure; `place_objects_in_scene` works fine without a hint.

```
python3 /sandbox/sketchscape/backend/scene_tools_cli.py read_sketch_layout '{}'
```

## stage_immersive_reveal

Call this after you have a `ConnectionInsight` (theme + explanation) and
the placed objects from `place_objects_in_scene`. It choreographs the
moment the contributions are experienced together: reveal order, a
lighting/mood preset keyed to the theme, a connecting light-path motif
between the objects, spoken narration text (the connection must be
*felt*, never put in a floating UI text card), and a distinct haptic
signature per object.

```
python3 /sandbox/sketchscape/backend/scene_tools_cli.py stage_immersive_reveal '{
  "connection_insight": {"theme": "Two homes, one memory", "explanation": "Both objects carry the warmth of a childhood living room."},
  "objects": [ /* the "objects" array returned by place_objects_in_scene */ ]
}'
```

## Reporting results back to the person

Keep your summary short and concrete, e.g.: "Placed 2 objects (revision
preview): reading lamp at (-1.4, 0.2, 1.8) scaled down, family sofa at
(1.6, 0.5, 2.1) scaled up to anchor the room; not published." Never
fabricate coordinates -- always read them from the tool's actual JSON
output.
