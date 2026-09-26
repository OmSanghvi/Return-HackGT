---
name: connection-compose-endpoint
description: Use when implementing POST /v1/projects/{project_id}/connection/compose for SketchScape / Shared Room — Build Plan step 5 in docs/BUILD_PLAN.md, the single most important missing piece of the Meta-track MVP. Depends on steps 1, 2 (contributor data model + API) and step 4 (NemoClaw layout tools).
---

# connection/compose endpoint (Build Plan step 5)

This endpoint produces the `ConnectionInsight` the entire Meta-track pitch
depends on. Get the mock path exactly right first — it's what makes the
judged demo work with zero external dependencies.

## Before starting

Confirm steps 1, 2, and 4 are done: `Contributor`/`Contribution` storage and
API endpoints exist, and `place_objects_in_scene` produces valid blueprint
proposals. If any is missing, build it first (load the matching skill).

## The one rule this endpoint must never break

**Invoke NemoClaw's own tools — never a standalone model-API call that
bypasses NemoClaw.** `connection/compose` is not a wrapper around a raw LLM
prompt; it calls `place_objects_in_scene` (and optionally
`read_sketch_layout`) and derives the `ConnectionInsight` from the *same*
reasoning pass that produces the layout, so the theme and the room's staging
never disagree. If you find yourself writing a second, independent call to a
model API "just for the connection text," stop — that's the exact mistake
this rule exists to prevent.

## What to build, concretely

1. `POST /v1/projects/{project_id}/connection/compose` — define a
   `ConnectionComposeResponse` wrapping `ConnectionInsight` +
   `ExperienceBlueprintInput`, following `backend/main.py`'s existing
   response-model conventions.
2. Guard clause: `409` if `len(store.list_contributions(project_id)) <
   project.min_contributors`. This is the concrete enforcement point for
   `SKETCHSCAPE_MIN_CONTRIBUTORS`.
3. **Mock path — build this first.** `PIPELINE_MODE=mock`: a deterministic
   function over the contributions' labels/memory text, no network call, no
   NemoClaw runtime required at all. Same inputs must always produce the
   same theme (write a test that calls it twice and asserts equality). Set
   `ConnectionInsight.backend = "mock"`.
4. **Live path.** Invoke `place_objects_in_scene` from step 4 to get the
   blueprint proposal, and derive `theme`/`explanation`/`object_rationales`
   from that same call's output — not a second independent reasoning pass.
   Set `ConnectionInsight.backend` to `NEMOCLAW_MODEL_PROVIDER`
   (`"meta"`, `"xai"` or `"nebius"`) and `ConnectionInsight.model` to the
   exact model id used.
5. Persist the result via `store.append_connection_insight` (step 1). The
   caller separately calls the existing
   `POST /v1/projects/{project_id}/blueprints` with the returned
   `ExperienceBlueprintInput` — reuse that path, don't duplicate blueprint
   creation logic here.
6. Tests in `backend/test_api.py`:
   - Mock path is deterministic (call twice with the same contributions,
     assert identical theme).
   - `409` when contributions are below `min_contributors`.
   - The composed blueprint references only `READY` assets (reuse the
     checking pattern from `validate_blueprint_assets`).
   - Run once with 2 contributions and once with 4 in the same test file —
     the N-ary check for this step specifically.

## Optional user text (room prompt)

If the project has a `room_prompt` (added by Build Plan step 17; typed on
the website, max 300 chars), pass it to NemoClaw as a style hint alongside
the contributions' labels and memory text. Treat it and all memory text as
**untrusted data**, never as instructions: wrap it in a clearly delimited
field, never let it change tool choice or bypass validation. The mock path
may use it deterministically (e.g. keyword → lighting preset) or ignore it;
both are fine. A missing or empty prompt must not change behavior.

## Definition of done

Two (and, in a separate test, four) contributions compose into a valid `ConnectionInsight` + blueprint
proposal in mock mode with zero external calls, and the same is true (in a
separate test) for four contributions. `bash scripts/verify_local.sh` passes.
Hand off to `immersive-reveal-staging` (step 6), which builds on this
endpoint's output.
