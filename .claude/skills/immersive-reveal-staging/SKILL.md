---
name: immersive-reveal-staging
description: Use when implementing NemoClaw's stage_immersive_reveal tool and integrating the open-source immersive scene-craft toolkit (VR Builder, PrimeTween/TweenPlayables, URP volumetric lighting, VisualEffectGraph, Resonance Audio, XRI haptics) for SketchScape / Shared Room — Build Plan step 6 in docs/BUILD_PLAN.md. Depends on steps 4 and 5.
---

# Immersive reveal staging (Build Plan step 6)

This is the tool and toolkit that make the connection *felt*, not read — the
concrete implementation of AGENT.md's "The connection must be felt, not
read" rule and its "Immersive scene craft" section. Read both before
starting; this skill is the execution checklist, not the design rationale.

## Before starting

Confirm steps 4 (`place_objects_in_scene`) and 5 (`connection/compose`) are
done — this tool consumes their output (`ConnectionInsight` + placed
`BlueprintObject`s).

## The rule this step exists to enforce

**No floating UI text card or HUD panel for the theme/explanation, ever.**
Express it through lighting, a connecting visual motif, spatial audio,
spoken narration, and per-object haptic/sound signatures. If a design
sketch or a partial implementation puts `ConnectionInsight.explanation` in a
2D text element anywhere in the scene, that's wrong — push back per
`meta-track-alignment`'s check item 2.

## Part A — the tool (backend/agent side)

1. `stage_immersive_reveal(connection_insight: ConnectionInsight, objects:
   list[BlueprintObject]) -> StagingPlan` — define `StagingPlan` as plain
   data (no Unity-specific types): reveal order across however many objects
   exist, a lighting/mood preset keyed to the theme, a connecting-motif spec
   (e.g. a light-path curve between object positions), a narration reference
   (TTS text or an audio asset id), and per-object haptic/sound signature
   ids.
2. Must accept the same N-length object list as `place_objects_in_scene` —
   test with 2 and separately with 5 objects.

## Part B — the toolkit (Unity side, `../HackGTUnity`)

Pick and integrate one implementation per bullet — don't half-integrate two
alternatives for the same job:

1. **Guided sequencing** — [VR Builder](https://github.com/MindPort-GmbH/VR-Builder)'s
   step/transition model (or a minimal subset of it) drives the reveal order
   from `StagingPlan`.
2. **Animation** — [PrimeTween](https://github.com/KyryloKuzyk/PrimeTween) or
   [TweenPlayables](https://github.com/AnnulusGames/TweenPlayables). Pick
   one; record the choice in `docs/INTEGRATION_GUIDE.md`.
3. **Mood lighting** — [CristianQiu/Unity-URP-Volumetric-Light](https://github.com/CristianQiu/Unity-URP-Volumetric-Light)
   or [ramalingamthangamani/URP-Volumetric-Fog](https://github.com/ramalingamthangamani/URP-Volumetric-Fog),
   parameterized by `StagingPlan`'s lighting preset.
4. **Atmosphere** — Unity's own [VisualEffectGraph-Samples](https://github.com/Unity-Technologies/VisualEffectGraph-Samples),
   restrained ambient particles only.
5. **Spatial audio + narration** — [Resonance Audio](https://github.com/resonance-audio/resonance-audio)
   for 3D sound, plus a recorded voice (safest for the demo) or synthesized
   speech reading `ConnectionInsight.explanation` — this audio *is* the
   primary channel replacing on-screen text, not just atmosphere. If
   synthesizing, Meta's own open-source [MMS TTS](https://github.com/facebookresearch/fairseq/tree/main/examples/mms)
   is on-brand for this track (note its CC-BY-NC 4.0 license — fine for a
   hackathon demo, flag if this ever ships commercially); any TTS engine
   works, the requirement is spoken narration, not a specific model.
6. **Per-object haptics/sound** — Unity XR Interaction Toolkit's
   `SendHapticImpulse` driven by `StagingPlan`'s per-object signature ids,
   paired with each object's animation sound cue, so a contributor
   recognizes their object by feel as well as sight.

## Graceful degradation check

With none of Part B installed, the room must still load and read correctly
— plain lighting, no sound, but structurally correct. This can't be caught
by `verify_local.sh`; do it as an explicit manual pass before calling this
step done.

## Definition of done

A recorded run-through shows the full reveal choreography for a 2-object
mock composition, and a second run with Part B fully stubbed out still shows
a correct, if plain, room. Hand off to `unity-diegetic-attribution` (step 8)
for the attribution layer that sits alongside this staging.
