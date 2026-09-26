---
name: contributor-api-endpoints
description: Use when implementing the REST endpoints for registering contributors and submitting contributions on a SketchScape / Shared Room project — Build Plan step 2 in docs/BUILD_PLAN.md. Depends on step 1 (contributor-data-model) already being in place.
---

# Contributor API endpoints (Build Plan step 2)

Exposes step 1's `Contributor`/`Contribution` models over HTTP. This is thin
plumbing — the interesting design decisions were already made in step 1 and
in `docs/ARCHITECTURE.md`. Do not add any new data-model fields here; if you
find yourself wanting to, that belongs in `contributor-data-model` instead.

## Before starting

Confirm step 1 is actually done: `Contributor`, `Contribution`, and the six
new `AuthoringStore` methods must already exist and be tested. If they don't,
stop and do step 1 first (load `contributor-data-model`).

## What to build, concretely

Match `backend/main.py`'s existing route style exactly — same
`response_model`/`status_code` pattern as `create_project_asset`, same
`HTTPException` usage as `validate_blueprint_assets`.

1. `POST /v1/projects/{project_id}/contributors` — `response_model=Contributor`,
   `status_code=201`. Body: `{display_name: str}`. Generate `contributor_id`
   using whatever id-generation helper `create_project_asset` already uses
   for `asset_id` — don't invent a second id scheme. Append to
   `project.contributor_ids` and call `store.append_contributor`.
2. `GET /v1/projects/{project_id}/contributors` — `response_model=list[Contributor]`,
   thin wrapper over `store.list_contributors`.
3. `POST /v1/projects/{project_id}/contributions` — `response_model=Contribution`,
   `status_code=201`. Body: `{contributor_id, asset_id, source_type,
   memory_text}`. Validate: `contributor_id` exists in this project's
   `contributor_ids`, and `asset_id` belongs to this project with
   `status == AssetStatus.READY` — reuse the validation pattern from
   `validate_blueprint_assets` rather than writing a new one.
4. `GET /v1/projects/{project_id}/contributions` — `response_model=list[Contribution]`.
5. Tests in `backend/test_api.py`, in the style of the existing
   `MultiViewProvenanceTests` class: register **three** contributors (not
   two — this is the N-ary check), submit a contribution from each, assert
   the list endpoints return all of them, and assert submitting a
   contribution against a non-`READY` asset returns a 4xx.

## Definition of done

`bash scripts/verify_local.sh` passes. A project can accumulate contributors
and contributions purely through these endpoints — no test or caller reaches
into `store` directly to set up fixtures where an endpoint call would do.
Hand off to `connection-compose-endpoint` (Build Plan step 5) once step 4
(NemoClaw layout tools) is also ready — compose depends on both.
