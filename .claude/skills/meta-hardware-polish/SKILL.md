---
name: meta-hardware-polish
description: Use when implementing the optional Meta-specific hardware polish for SketchScape / Shared Room — passthrough closing beat, hand tracking for the bounded edit, Quest-account contributor identity, and Llama Guard moderation on memory text. Build Plan step 9 in docs/BUILD_PLAN.md. Depends on step 8. None of these block the core demo if skipped.
---

# Meta hardware polish (Build Plan step 9)

Small, priority-ordered additions that read as deliberate "why Meta" choices.
Every item here is optional and independently toggleable — build in order,
stop wherever time runs out, and never let one of these block the core
connection flow.

## Before starting

Confirm step 8 (diegetic attribution + bounded edit) is done — several of
these items extend it rather than standing alone.

## Build in this priority order

0. **Use Meta XR Building Blocks first.** With the Meta XR Core SDK
   installed, **Meta > Tools > Building Blocks** in the Unity menu gives you
   drag-and-drop, pre-wired Passthrough and Hand Tracking blocks — try this
   before hand-assembling either feature from raw SDK components.
1. **Passthrough closing beat.** [Meta XR SDK Passthrough API](https://developers.meta.com/horizon/documentation/unity/unity-passthrough/)
   (`OVRManager` → Quest Features → Passthrough Support) — the virtual room
   fading into the contributor's real physical space at the end of the
   experience. Purely additive visual beat; verify it doesn't interfere with
   the core scene load.
2. **Hand tracking for the bounded edit.** [Meta XR Interaction SDK](https://developers.meta.com/horizon/documentation/unity/unity-handtracking-overview/),
   pinch-to-grab via its built-in grab/poke gestures (don't build custom
   hand-pose detection), as an **alternate** input path alongside the
   existing controller-based bounded edit from step 8 — not a replacement.
   If hand tracking isn't tracking reliably in testing, the controller path
   must still work.
3. **Contributor identity from the logged-in Quest account.** Meta Platform
   SDK — concretely:
   ```csharp
   Oculus.Platform.Users.GetLoggedInUser().OnComplete(msg => {
       if (!msg.IsError) {
           string displayName = msg.GetUser().DisplayName;
           // pre-fill or replace the typed display_name
       }
   });
   ```
   Use the result to pre-fill or replace the `display_name` field in
   `POST /v1/projects/{project_id}/contributors` (step 2). The typed-name
   path must remain the fallback if the Platform SDK call errors or isn't
   available (e.g. desktop simulator testing).
4. **Llama Guard moderation.** In `POST /v1/projects/{project_id}/contributions`
   (step 2), pass `memory_text` through [Llama Guard](https://github.com/meta-llama/PurpleLlama)
   (Meta's open-source PurpleLlama project; Llama Guard 3 ships 1B and 8B
   variants) before persisting. Decide and document the exact rejection
   contract before wiring it in — either a `4xx` with a reason, or a stored
   moderation flag on the `Contribution` record — don't leave this ambiguous
   in the implementation.
5. Mixed Reality Capture recording is **not** a build step — it's a
   recording-time choice made in `demo-video-prep` (step 12). Don't build
   anything here for it beyond ensuring the scene renders correctly under
   Quest's MRC compositing (no UI overlays that MRC can't composite
   correctly, for instance).

## Definition of done

Each item built is independently toggleable and none blocks the core
connection flow if absent or disabled — verify this explicitly by running
through the full flow with each item turned off, one at a time. Hand off to
`demo-video-prep` (step 12) once whichever subset of these landed.
