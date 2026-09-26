---
name: meta-track-alignment
description: Use whenever doing product, feature, backend, or Unity work on SketchScape / Shared Room in this repository — deciding what to build next, reviewing a proposed feature, writing API/data-model code for the social layer, or judging whether a change belongs in the hackathon MVP. Keeps decisions pointed at Meta's "Bringing People Closer Together with AI" judging criteria and stops scope creep back into the older generic multi-object room-assembly agent framing.
---

# Meta track alignment

This repository's primary competition target is Meta's "Bringing People
Closer Together with AI" challenge, with the product framed as **Shared
Room**: two or more people (no fixed limit; the demo shows two) each
contribute meaningful objects or letters; AI infers a shared theme and
explanation across all the contributions; Unity turns that into
one explorable VR room. `docs/PROJECT_STATUS.md` is the authoritative,
judge-facing description of this track. `AGENT.md`'s "Primary competition
track" section is the short agent-facing summary. `docs/BUILD_PLAN.md` is
the concrete, ordered, step-by-step execution plan — read it before starting
or resuming any implementation work; it names which of the skills below
governs each step. This skill is the standing gate that applies across all
of them, not a replacement for the step-specific skill.

**The skill roster, one per Build Plan step:** `contributor-data-model` (1)
→ `contributor-api-endpoints` (2) → `nemoclaw-agent-setup` (3) →
`nemoclaw-scene-tools` (4) → `nemoclaw-subject-labeling` (4a) →
`connection-compose-endpoint` (5) → `immersive-reveal-staging` (6) →
`nemoclaw-environment-sourcing` (6a) → `sketch-image-gen-backends` (7, parallel) →
`unity-diegetic-attribution` (8) → `meta-hardware-polish` (9) →
`gpu-cloud-activation` (10, parallel) →
`unity-offline-builder-and-rendering` (11, parallel) → `demo-video-prep`
(12). Load the step-specific skill for the actual how-to; use this skill for
the judgment calls that cut across all of them.

## Before starting any task, ask

1. **Which Build Plan step is this, and is its skill loaded?** Check
   `docs/BUILD_PLAN.md`'s status table. If the task doesn't map to a listed
   step, that's a signal it may be scope creep (see item 3) rather than a
   gap in the plan — confirm with the user before inventing new work outside
   the plan.
2. **Is the AI's reasoning going to be perceivable through the scene, or
   just consumed as coordinates?** If a feature makes AI reasoning invisible
   (e.g. baking a theme straight into transforms with nothing perceivable
   from it), it fails the "AI essential and well-integrated" criterion. But
   the fix is never a floating UI text card or HUD panel — the user has
   explicitly rejected that. Push back toward diegetic expression instead:
   lighting mood, a connecting visual motif between objects, spatial audio,
   spoken narration, per-object haptic/sound signatures, or (only as a last
   resort) a physically-modeled in-world text object like an engraved prop.
   See AGENT.md's "The connection must be felt, not read."
3. **Does this expand the MVP into accounts, chat, real-time multiplayer,
   or notifications?** These are explicitly out of scope for the MVP — this
   is sequential co-creation between two or more named contributors, not a social
   network. Flag it rather than building it. The only exception is the
   gated Collaborative VR track (Build Plan steps 13–29): work there is
   allowed, but only after `python3 scripts/check_collab_gates.py <step>`
   says READY, and never at the expense of MVP steps 1–12.
4. **Is NemoClaw the thing that owns scene understanding, and is its model
   runtime switchable?** Two separate things get this wrong if conflated:
   - The composition step (`connection/compose`) must invoke **NemoClaw's
     own tools** (`place_objects_in_scene`, `stage_immersive_reveal`, etc.)
     — never a standalone model-API call that bypasses NemoClaw. NemoClaw's
     tools are the scene-authoring mechanism; don't build a parallel one.
   - NemoClaw's *underlying model* defaults to **Muse Spark on the Meta
     Model API** for this track (`NEMOCLAW_MODEL_PROVIDER=meta`). The Grok
     API (`xai`, Resilience Commons framing) and Nebius Token Factory
     (`nebius`, open models including Llama) stay switchable. It's a config
     choice, not a second API path. See `nemoclaw-model-providers`.
   - Separately, the old **sketch → photorealistic image** step (a
     different pipeline stage from NemoClaw's reasoning) is **gone** —
     `POST /v1/sketches`, `backend/image_gen.py`, and its `mock`/`azure`/`hf`
     backends were removed. Hallucinating a fake photorealistic object from
     a line drawing was more trouble than it was worth (a paid backend, a
     network hop, a visibly fake result) next to a direct photo upload,
     which already does the job. **Do not reintroduce `image_gen.py`, an
     `azure`/`hf`/`grok` image-generation backend, `/v1/sketches`, or Meta
     Muse Image (still rejected on cost, moot now anyway).** A Notability
     sketch now takes one of two paths instead — shown directly as a flat
     card, or reconstructed through the existing SAM 3.1 → Fast-SAM3D
     pipeline as a 3D "memory plaque" with the contributor's memory text
     physically part of it, which doubles as a diegetic answer to item 2
     above. See `docs/BUILD_PLAN.md` step 7 and `sketch-image-gen-backends`
     — neither path is built yet. Don't mix any of this up with NemoClaw's
     own model provider (`NEMOCLAW_MODEL_PROVIDER`); that's an independently
     configurable, still-current setting. **Muse Spark (a reasoning model)
     is not "Meta Muse Image"**; only the image-generation backend is
     rejected.
5. **If this touches Unity MCP, is it Meta's official Unity MCP Extension for
   Horizon** (https://developers.meta.com/horizon/documentation/unity/unity-mcp-extension/)
   **— not a generic/third-party Unity MCP server?** This is a hard
   requirement for the Meta track, specified in both AGENT.md and
   PROJECT_STATUS.md, for the same judge-legibility reason as the Llama
   requirement. Check that page's current setup instructions before wiring
   or changing the Unity MCP integration — its install steps and tool
   surface can change.
6. **If this touches how the room is staged/revealed once objects and the
   connection insight exist, is it landing the emotional beat, not just
   placing objects?** AGENT.md's "Immersive scene craft" section names the
   open-source toolkit for this: VR Builder's guided step/transition model
   for reveal sequencing, PrimeTween or TweenPlayables for animation, an
   open-source URP volumetric lighting/fog shader for mood, Unity's own
   VisualEffectGraph-Samples for restrained ambient particles, Google's
   open-source Resonance Audio for spatial sound and spoken narration, and
   Unity's XR Interaction Toolkit haptic API for per-object haptic/sound
   signatures. Treat all of it as an additive layer on top of a working
   plain scene — never let immersive staging become a dependency the core
   connection story can't work without.
7. **If this touches hardware-specific polish** (passthrough closing beat,
   hand-tracking for the bounded edit, Quest-account identity, Mixed Reality
   Capture recording, Llama Guard moderation on memory text) — see AGENT.md's
   "Hardware and production ideas that lean into Meta specifically." These
   are optional, priority-ordered, time-permitting additions, not MVP
   blockers; don't let them delay the core connection flow.
8. **Does mock mode still work end to end?** `PIPELINE_MODE=mock` must
   produce a deterministic `ConnectionInsight` and layout with no GPU, AWS,
   or model credentials, and must always be labelled `mock` in metadata.
   Never let a change silently break this path — it's the judging-safe demo
   path.

## When reviewing or writing code for the social layer

- New records should be `Contributor`, `Contribution`, and
  `ConnectionInsight`, layered on top of the existing project/asset/blueprint
  contracts — not a parallel data model.
- Model these as **lists**, never a fixed pair (`contributor_a`/`contributor_b`
  fields, or code that assumes exactly two contributions). The demo is
  two-person for clarity, but the data model, storage layout (extend
  `DynamoDbStore`'s existing single-table sort-key families —
  `CONTRIBUTOR#<id>`, `CONTRIBUTION#<id>`, `INSIGHT#<revision>` — rather than
  forking a new table), and NemoClaw composition/staging prompts must accept
  N contributions from day one. See `docs/ARCHITECTURE.md`'s "Scaling Shared
  Room from two contributors to N" before writing this layer. Real-time
  multiplayer is still not needed to support N — this stays sequential
  co-creation.
- Reuse existing blueprint validation, immutable revisions, publication, and
  compiled-scene loading. Do not let AI write arbitrary Unity code or bypass
  the blueprint contract.
- Keep social metadata in the authoring blueprint or a versioned sidecar
  manifest; only touch `shared/scene.schema.json` if Unity genuinely needs a
  new runtime field to stage the social context (contributor cues, theme,
  narration audio reference) — this metadata drives diegetic staging, not a
  UI text display, so don't assume it needs a "label" or "caption" field.
- Run `bash scripts/verify_local.sh` after backend changes and confirm it
  passes before reporting done, per AGENT.md's hard rules.

## When something seems off

If a request would pull work toward the secondary Grok/Resilience-Commons
framing, confirm with the user which track is intended before proceeding —
mixing the two pitches in one build or one video reads as unfocused to
judges (this is explicit in PROJECT_STATUS.md's own framing notes).
