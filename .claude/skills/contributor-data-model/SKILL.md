---
name: contributor-data-model
description: Use when implementing the Contributor, Contribution, and ConnectionInsight data models and their storage backing for SketchScape / Shared Room — Build Plan step 1 in docs/BUILD_PLAN.md. Covers backend/main.py model definitions and backend/storage.py's AuthoringStore extension (LocalJsonStore + DynamoDbStore).
---

# Contributor data model (Build Plan step 1)

This is the foundation every other social-layer step depends on. Read
`docs/BUILD_PLAN.md`'s "Step 1" section first — it has the exact field lists
and method names to add. This skill is the execution guide for that step;
don't re-derive the design, it's already decided.

## Non-negotiable constraints

- **Model everything as lists, never a pair.** No `contributor_a_id` /
  `contributor_b_id` fields, no code that assumes `len(contributions) == 2`
  anywhere. The MVP demo uses two contributors, but the data model must not
  encode that. See `docs/ARCHITECTURE.md`'s "Scaling Shared Room from two
  contributors to N."
- **Extend the existing single-table DynamoDB design — do not create a new
  table.** `DynamoDbStore` already has a generic `_query_children(project_id,
  sk_prefix)` helper; reuse it with `sk_prefix="CONTRIBUTOR"`,
  `"CONTRIBUTION"`, and `"INSIGHT"`. Read `backend/storage.py`'s existing
  `list_blueprints`/`append_blueprint` implementation before writing the new
  methods — copy that pattern exactly, including the zero-padded
  `_seq_key` for `ConnectionInsight` (it's revisioned like a blueprint;
  contributors/contributions are not revisioned, so they don't need
  `_seq_key`, just a stable id in the sort key).
- **Mirror `LocalJsonStore` and `DynamoDbStore` exactly.** Every other entity
  in this store is implemented identically in both backends so mock mode and
  cloud mode are structurally identical. Do not let one backend get ahead of
  the other.
- **Read env-configured defaults, don't hard-code them.** `min_contributors`
  and `max_contributors` on `ProjectRecord` default from
  `SKETCHSCAPE_MIN_CONTRIBUTORS` (default `2`) and
  `SKETCHSCAPE_MAX_CONTRIBUTORS` (default `6`) at project-creation time.

## What to build, concretely

1. `backend/main.py`: add `Contributor`, `Contribution` (with
   `ContributionSourceType`), and `ConnectionInsight` (with a
   per-object `placement_rationale` list and `backend: Literal["mock",
   "llama", "grok"]`) as `BaseModel` subclasses. Match the field style of
   `ProjectAsset`/`AssetView` exactly — read those two classes first.
2. Extend `ProjectRecord` with `contributor_ids`, `contribution_ids`,
   `min_contributors`, `max_contributors`.
3. Add six abstract methods to `AuthoringStore`: `list_contributors`,
   `append_contributor`, `list_contributions`, `append_contribution`,
   `list_connection_insights`, `append_connection_insight`.
4. Implement all six in `LocalJsonStore` (JSON-file, atomic write, same
   pattern as existing entities) and `DynamoDbStore` (single-table, reusing
   `_query_children`).
5. Write `backend/test_storage.py` tests: round-trip through both backends,
   and **explicitly test a project with 3+ contributors**, not just 2 — this
   is the concrete proof the model isn't secretly pair-shaped.

## Definition of done

`bash scripts/verify_local.sh` passes. Grep your diff for `contributor_a`,
`contributor_b`, or any literal `== 2` / `len(...) == 2` gating contributor
count — none should exist outside of the `min_contributors` default value
itself. Hand off to `contributor-api-endpoints` (Build Plan step 2) next.
