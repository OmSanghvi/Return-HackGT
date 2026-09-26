---
name: demo-video-prep
description: Use when preparing, scripting, reviewing, or recording the SketchScape / Shared Room demo video or write-up, or when editing features.txt or the demo-plan sections of docs/PROJECT_STATUS.md. Keeps the recording plan honest about mock-vs-live status and makes sure every feature the video claims is actually true in the build being recorded, for both the Meta track and the Immersive AR/VR track.
---

# Demo video prep

This repository is submitting one working prototype to two hackathon tracks
— Meta ("Bringing People Closer Together with AI") and Immersive AR/VR —
from a single recorded demo. `features.txt` at the repo root is the feature
checklist for both track cuts; `docs/PROJECT_STATUS.md` has the full Meta
demo plan and write-up structure; `docs/BUILD_PLAN.md` step 12 is this
skill's entry in the overall build plan and lists which earlier steps this
depends on. Read all three before drafting or revising a script.

## Before drafting or revising the script

1. **One recording, two framings — never two different demos.** The video
   itself doesn't change between tracks; only which write-up leads with
   which beats. Don't let a request to "emphasize AR/VR more" turn into
   scripting a second, separate video.
2. **Every claimed feature must be true in the build you're about to
   record.** Walk `features.txt` line by line against the actual running
   app before finalizing a script — do not narrate a feature that exists
   only as a plan in PROJECT_STATUS.md's "what needs to be built" section.
3. **Mock vs. live must be stated, not implied.** If recording in
   `PIPELINE_MODE=mock` (the judging-safe default), the script and write-up
   must say so plainly and note that the real GPU pipeline was verified
   separately — this is framed as a strength in PROJECT_STATUS.md, not
   something to hide.
4. **The AI's reasoning must be perceivable, but never as on-screen text.**
   The single highest-leverage beat for the Meta track is the moment the
   `ConnectionInsight` (shared theme + explanation) lands — through mood
   lighting, a connecting motif, and spoken narration (see
   `immersive-reveal-staging`), not a text card. The script should linger on
   that moment, not rush past it to get to the Quest headset shot — but
   "linger" means hold the shot of the staged scene, never cut to a caption.
5. **The Quest headset must be shown on a real head.** This is called out
   explicitly in PROJECT_STATUS.md as the strongest "why Meta" beat and
   doubles as the strongest AR/VR-track technical beat — do not cut it for
   time.

## When writing the two write-ups

- **Meta write-up** answers: who it's for, how it strengthens connection,
  why AI (specifically NemoClaw's tool-driven scene authoring, running on
  Llama by default) is essential, and what's live vs. mocked. Use the exact
  structure already in `docs/PROJECT_STATUS.md`'s "Write-up" section — don't
  invent a new one.
- **AR/VR write-up** leads with the reconstruction pipeline and real-time
  splat rendering (SAM 3.1 → Fast-SAM3D → Gaussian-splat → UnitySplats →
  Quest), citing the verified end-to-end numbers (70s total, 814k-vertex,
  53 MB splat, NVIDIA L40S) from `features.txt` / PROJECT_STATUS.md rather
  than restating the connection-story framing as the lead.

## Final check before calling the video "done"

- No placeholder primitives are visible anywhere in the recorded room (a
  failed reconstruction must be skipped, never shown as a cube/capsule).
- No on-screen or narrated claim implies a live model ran if the recording
  used mock mode.
- The video runs 2–3 minutes, matching the beat timing in
  `docs/PROJECT_STATUS.md`'s demo plan.
