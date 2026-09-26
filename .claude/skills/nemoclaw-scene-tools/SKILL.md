---
name: nemoclaw-scene-tools
description: Use when implementing NemoClaw's place_objects_in_scene and read_sketch_layout tools for SketchScape / Shared Room — Build Plan step 4 in docs/BUILD_PLAN.md. Depends on step 3 (nemoclaw-agent-setup) already having a working agent runtime.
---

# NemoClaw layout tools (Build Plan step 4)

These are the tools that turn a catalog of contributed objects into a room
layout. They are the scene-understanding mechanism for this product —
`connection/compose` (step 5) will call into these, not a separate model API.

## Before starting

Confirm `nemoclaw-agent-setup` (step 3) is actually done — a working agent
runtime registered against the Unity MCP Extension for Horizon. If not, stop
and do that first.

## Non-negotiable constraint

**Both tools must accept a list of objects, never a hard-coded pair.** Test
each with 2 objects and separately with 5 in the same test run. This is the
concrete, tool-signature-level enforcement of
`docs/ARCHITECTURE.md`'s N-contributor section — if the function signature
takes `object_a` and `object_b` instead of `objects: list[...]`, it's wrong.

## What to build, concretely

1. **`place_objects_in_scene(objects: list[{asset_id, label}], sketch_layout_hint:
   LayoutHint | None) -> ExperienceBlueprintInput`** — reasons about
   realistic room layout (interior-design logic) for however many objects
   are passed, assigns `position`/`rotation`/`scale`/`interactions` per
   `BlueprintObject` (see `backend/main.py`'s existing `BlueprintObject`
   model for the exact shape and field constraints — id/asset_id patterns,
   `min_length`/`max_length` on `position`/`rotation`/`scale`), and returns a
   blueprint input. **Do not auto-publish** — publication stays a separate,
   explicit step (`POST /v1/projects/{id}/blueprints/{revision}/publish`)
   per the existing contract; this tool only proposes.
2. **`read_sketch_layout(sketch_image) -> LayoutHint`** — optional. Extracts
   rough spatial relationships from a Notability sketch ("lamp is left of
   chair, window is behind") into a small structured hint. NemoClaw may
   ignore it and reason purely from labels; don't make it a hard dependency
   of `place_objects_in_scene`.
3. Validate every `ExperienceBlueprintInput` your tool produces against
   `shared/experience-blueprint.schema.json` before returning it — this
   schema is the authoring contract and objects here are already
   array-shaped with no length limit, so nothing there needs to change.
4. Where possible, separate pure-reasoning/geometry logic (testable without
   a live LLM call) from the actual model invocation, and unit-test the
   former directly. Add one integration smoke test that runs
   `place_objects_in_scene` end-to-end against `PIPELINE_MODE=mock` fixtures.

## Definition of done

A 2-object input and a 5-object input, run in the same test session, both
produce a schema-valid `ExperienceBlueprintInput`. Hand off to
`connection-compose-endpoint` (step 5), which will call this tool from the
live (non-mock) path of `POST /v1/projects/{id}/connection/compose`.
