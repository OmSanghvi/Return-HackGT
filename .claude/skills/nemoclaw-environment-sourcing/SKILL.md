---
name: nemoclaw-environment-sourcing
description: Use when implementing NemoClaw's find_object_image tool and the flow where NemoClaw adds its own set-dressing objects to the immersive room by finding web images and sending them through SAM 3.1 → Fast-SAM3D — SketchScape / Shared Room Build Plan step 6a in docs/BUILD_PLAN.md. Depends on steps 4 and 10.
---

# NemoClaw environment objects from web images (Build Plan step 6a)

When NemoClaw builds the immersive room on its own, it can add supporting
objects (rug, lamp, shelving that fits the theme). It finds a clean
single-object photo on the web and reconstructs it with the same pipeline as
contributed objects.

## Rules

- **Web images are only for NemoClaw's environment objects.** Never use them
  to replace or split a contributor's upload, and do not generate images for
  this (the user chose web search over generation).
- **Reuse-friendly sources only:** Openverse and Wikimedia Commons. Store
  `source`, `license`, and `attribution` on every resulting asset — nothing
  in a published scene may have unclear rights.
- **Prefer isolated product-style shots** (single object, plain background);
  they reconstruct far better than cluttered photos.
- **Guardrails:** every environment object is a GPU job NemoClaw starts on
  its own. Enforce a per-scene cap (default 6, env configurable) and an
  on/off flag. No live search or GPU job without explicit user approval
  during development (AGENT.md Hard Rule 3).
- **Mock mode** uses a fixed fixture set with license metadata: no web, no
  GPU, deterministic.
- **Contributed objects stay the heroes.** Mark environment objects so
  `stage_immersive_reveal` (step 6) stages them as supporting set dressing.

## Definition of done

See step 6a in `docs/BUILD_PLAN.md`.
