---
name: unity-diegetic-attribution
description: Use when implementing contributor attribution and per-contributor bounded scene edits inside the Unity project for SketchScape / Shared Room — Build Plan step 8 in docs/BUILD_PLAN.md. Depends on steps 5 and 6. Covers the sidecar social manifest and extending SceneInteractionController.
---

# Unity diegetic attribution (Build Plan step 8)

Makes the AI's output and each contributor's ownership perceivable in Unity
without a UI text panel, and restricts each contributor's bounded edit to
their own object(s) — generalized to N contributors.

## Before starting

Confirm steps 5 (`connection/compose`) and 6 (`stage_immersive_reveal`) are
done — this step wires their output into the actual Unity scene.

## Constraints carried over from earlier decisions

- **No UI text panel, no HUD, no floating caption.** Attribution is a
  marker, a material tint, or a spoken introduction — never a name-tag UI
  element. This is the same "felt, not read" rule from step 6, applied to
  attribution specifically.
- **Generalize to N objects/contributors**, not a hard-coded pair — test
  with 3 contributors, not 2.
- **Keep the blueprint the source of truth.** Social metadata belongs in the
  authoring blueprint or a versioned sidecar manifest, not
  `shared/scene.schema.json`, unless Unity genuinely needs a new runtime
  field to stage it (per `AGENT.md`'s existing rule) — don't reach for a
  schema change as the first option.

## What to build, concretely

1. Define the sidecar manifest: per object, `contributor_id`,
   `contributor_display_name`, and a reference into the `StagingPlan` (step
   6) for that object's attribution cue. Write it as a small JSON schema
   next to `shared/scene.schema.json` if nothing suitable exists yet — check
   first before assuming you need a new file.
2. Compile this manifest alongside the compiled scene inside the *existing*
   `compile_blueprint` function in `backend/main.py` — do not invent a
   second, parallel compile step or a separate endpoint for it.
3. In the Unity project (`../HackGTUnity`), extend
   `SceneInteractionController`'s existing bounded-action registry (see
   `docs/INTEGRATION_GUIDE.md` §3, "Named interactives and safe actions") so
   a session tied to a given contributor can only submit `scale_by` /
   `translate_by` / `rotate_by` for object ids the manifest attributes to
   that contributor. This is the N-safe version of "one bounded edit per
   contributor" — reuse the existing `POST /v1/scene/actions` policy
   enforcement on the backend side; don't duplicate the allowlist logic in
   Unity.
4. Wire attribution cues (marker/material/spoken intro) and the staging plan
   from step 6 into the scene via the *existing* offline experience builder
   (`SketchScapeOfflineExperienceBuilder`) — do not create a second builder
   path for the social layer.

## Definition of done

A 3-contributor mock composition, once compiled, shows each object correctly
attributed in the desktop simulator (no headset required for this check),
and an attempted edit against an object a given contributor didn't
contribute is rejected by the existing backend policy. Hand off to
`meta-hardware-polish` (step 9) for the optional hardware-specific layer on
top of this.
