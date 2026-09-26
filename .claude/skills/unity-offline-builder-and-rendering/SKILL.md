---
name: unity-offline-builder-and-rendering
description: Use when fixing SketchScapeOfflineExperienceBuilder to remove placeholder-primitive fallback and verifying real Gaussian-splat PLY rendering on Quest for SketchScape — Build Plan step 11 in docs/BUILD_PLAN.md, AGENT.md items 5-7. No dependency on the social-layer steps; can run in parallel.
---

# Unity offline builder + real-PLY rendering (Build Plan step 11)

Baseline VR quality work that every other Unity-side step (6 and 8) builds
on top of. Do this before layering immersive staging or diegetic attribution
on a room that still shows placeholder primitives.

## Hard rule this step enforces

**Failed objects are omitted from the VR room — no placeholder primitives,
ever.** If an object's reconstruction fails, skip it entirely; the
experience still launches with whatever succeeded. Never show a cube,
capsule, or coloured shape standing in for a failed object — this is one of
`AGENT.md`'s hard rules, not a style preference.

## Concrete steps

1. **Fix `SketchScapeOfflineExperienceBuilder`** (in `../HackGTUnity`): if a
   `.ply` exists for an object, create a `GsplatRenderer` for it; if no
   `.ply` exists, skip the object entirely — remove whatever fallback
   primitive code currently exists. The scene must still build and launch
   regardless of how many objects were skipped.
2. **Load one real Fast-SAM3D `.ply`** produced by the verified pipeline
   (see `gpu-cloud-activation`, step 10, for how to get one) into Unity with
   UnitySplats. Confirm it actually renders — this has reportedly never been
   done with a *real* PLY inside the social Shared Room flow specifically,
   per `docs/PROJECT_STATUS.md`'s "partially built" table. If UnitySplats
   hits a blocker, [aras-p/UnityGaussianSplatting](https://github.com/aras-p/UnityGaussianSplatting)
   is the other well-known Unity splat renderer and reportedly runs on
   Quest 3/Quest Pro — but treat it only as a fallback reference for
   comparison, not a fresh primary dependency: its author flagged no
   significant further development since December 2023.
3. Check splat count against Quest 3 limits and confirm acceptable
   framerate. Profile on-device if a headset is available; note explicitly
   in your report if this was only checked in the desktop simulator.
4. **Baseline VR room environment**, once splat rendering is confirmed:
   walls, floor, ceiling, window lighting (handcrafted or procedural),
   ambient lighting approximating the source photos' lighting, walkable area
   with colliders on all objects (no walking through things), and
   teleport/smooth locomotion via the already-imported XRI rig. This is the
   plain, un-staged room that `immersive-reveal-staging` (step 6) later
   layers mood lighting and effects on top of — build it correctly and
   plainly first; don't jump straight to the staged version.

## Definition of done

Matches the acceptance checks already listed in `AGENT.md` items 5–7: no
placeholder primitives anywhere, one real `.ply` confirmed rendering with
acceptable framerate, and a walkable baseline room with colliders and
locomotion. Hand off to `immersive-reveal-staging` (step 6) and
`unity-diegetic-attribution` (step 8), which both assume this baseline room
already exists and is correct.
