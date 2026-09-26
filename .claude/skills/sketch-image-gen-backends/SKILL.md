---
name: sketch-image-gen-backends
description: Use when implementing the Notability sketch direct-display path (flat textured quad) or the SAM3D memory-plaque path (a Notability page reconstructed in 3D with the contributor's memory text physically embedded) for SketchScape — Build Plan step 7 in docs/BUILD_PLAN.md. The old sketch → image-generation → reconstruction pipeline (`POST /v1/sketches`, `backend/image_gen.py`, azure/hf/grok image backends) has been removed; do not resurrect it. No dependency on the social-layer steps; can be built any time.
---

# Notability sketch: direct display + SAM3D memory plaque (Build Plan step 7)

## The old pipeline is gone — do not rebuild it

This step used to be "add a `grok` backend to `backend/image_gen.py`,
azure/hf already cover the Meta track." That whole premise is retired.
`POST /v1/sketches`, `backend/image_gen.py` (`mock`/`azure`/`hf` backends),
and `backend/test_image_gen.py` were deleted. Turning a hand sketch into a
fabricated "photorealistic" object via DALL-E/SDXL added a paid backend, a
network hop, and a visibly fake result — for a case a direct photo upload to
the existing `POST /v1/reconstructions` already handles better. If someone
has a real object, they photograph it; Notability sketches get a path that
uses them for what they actually are instead.

**Do not reintroduce `image_gen.py`, an `azure`/`hf`/`grok` image-generation
backend, or `/v1/sketches`.** If any reference to Meta Muse Image, Azure
DALL-E, or HF SDXL image-gen turns up anywhere in the repo, it's stale —
remove it. (This is unrelated to `NEMOCLAW_MODEL_BACKEND=llama|grok`, which
picks NemoClaw's own *reasoning* model and is untouched by this step.)

## What to build, concretely

Two paths, per `docs/BUILD_PLAN.md` step 7:

### Path 1 — Direct display (flat quad)

The default, always-available path. A Notability export is stored and
placed into the room as a textured plane/card — no SAM 3.1, no
Fast-SAM3D, no GPU, no paid API.

1. Add an endpoint (e.g. `POST /v1/projects/{project_id}/sketch-assets`)
   that stores the sketch image and registers it as a catalog asset with a
   source type that marks it as a flat card, not a reconstructed mesh —
   reuse the existing asset/catalog contract (`ProjectAsset`, `AssetView`);
   don't fork a parallel one.
2. Make `place_objects_in_scene` (step 4 / `nemoclaw-scene-tools`) treat
   this asset type as a billboard/card placement (position + rotation +
   scale) instead of a 3D object placement.
3. This path must work end to end in `PIPELINE_MODE=mock` with no GPU and
   no credentials, same as every other mock-mode path.

### Path 2 — SAM3D memory plaque

The better use of Notability: reconstruct the **actual page** — sketch plus
the contributor's memory note — through the existing SAM 3.1 → Fast-SAM3D
pipeline like any other photo, so the memory text is physically part of the
resulting 3D object's geometry/texture. This is the concrete mechanism for
AGENT.md's "the connection must be felt, not read" rule and Step 8's need
for an in-world text object instead of a floating UI panel
(`unity-diegetic-attribution` should prefer this over inventing its own
text-rendering path).

1. Upload the Notability page image to the existing
   `POST /v1/reconstructions` unchanged — no new reconstruction code. The
   "object" is the page/plaque itself.
2. Let NemoClaw's staging (`stage_immersive_reveal`, step 6) place the
   resulting plaque mesh near its contributor's other object, per step 8's
   attribution manifest.
3. Before committing to this as more than opt-in: verify Fast-SAM3D
   actually reconstructs a flat page with legible text well. The GPU
   pipeline was verified end-to-end on object geometry (a real photo,
   814,432-vertex splat), not specifically on a flat textured plane with
   text — check the output before treating Path 2 as reliable. If text
   doesn't survive reconstruction legibly, fall back to Path 1 for that
   contribution rather than shipping an illegible plaque.

## Definition of done

A contributor can submit a Notability sketch and see it in the room either
as a flat card (Path 1, always works, no GPU/cost) or as a reconstructed 3D
plaque with legible embedded text (Path 2, GPU-dependent — verified per
point 3 above). `bash scripts/verify_local.sh` passes. No `image_gen.py`, no
`azure`/`hf`/`grok` image-generation backend, no `/v1/sketches` endpoint
exists anywhere in the repo.
