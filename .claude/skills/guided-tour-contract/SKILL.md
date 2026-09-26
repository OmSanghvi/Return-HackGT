---
name: guided-tour-contract
description: Use for Build Plan step 30 — the guided tour JSON contract that the in-VR guide bot performs. Covers shared/guided-tour.schema.json, the GuidedTour Pydantic models, validate_guided_tour (every id checked against the blueprint, every fact traced to real contributions, sealed letters never included), TOUR#/TOURLIVE storage in both stores, the draft → activate API (people activate, NemoClaw only drafts), and the deterministic compose_tour_mock author. Load before touching any tour model, route, or store method.
---

# Guided tour contract (step 30)

## Gate

Run `python3 scripts/check_collab_gates.py 30`. It needs steps 5 (mock),
15, and 17. If the result is BLOCKED, stop. The design is in
`docs/BUILD_PLAN.md` under "Guided tour bot track"; the storage layout is
in `docs/DATA_ARCHITECTURE.md` (the `TOUR#`, `TOURLIVE`, `GUIDESESSION#`,
and `GUIDETURN#` rows).

## Why this contract exists

The in-room guide (step 32) may say and do **only** what this JSON
contains. So the JSON has to be closed, and it has to be verifiably true:

- **Closed** means every id the guide can reference is listed here.
- **True** means every fact traces back to something a person wrote or to
  NemoClaw's recorded insight.

The validator is the part that makes "the model follows only the JSON"
enforceable, so treat it as the core of this step.

## Files

- `shared/guided-tour.schema.json` (new, JSON Schema draft 2020-12). Its
  shape is exactly the example in the Build Plan.
- `backend/main.py`:
  - models: `TourFactSource`, `TourFact`, `TourElement`, `TourStop`,
    `TourNarration`, `TourStep`, `TourGuardrails`, `TourPersona`,
    `TourAuthoredBy`, `GuidedTourInput`, `GuidedTour`
  - functions: `validate_guided_tour`, `compose_tour_mock`
  - the routes below
- `backend/storage.py`: `append_tour`, `get_tour`, `list_tours`,
  `get_active_tour_version`, and `set_active_tour_version` on the
  `AuthoringStore` ABC, `LocalJsonStore`, and `DynamoDbStore`.
- `backend/test_guided_tour.py` (new).

## Model details

- Reuse the id pattern `^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$` from
  `BlueprintObject.id`. Don't invent a new one.
- `TourFactSource.kind` is a `Literal` of: `connection_insight`,
  `placement_rationale`, `contribution_memory`, `attribution`,
  `room_prompt`, `letter_envelope`, `authored`.
- `TourElement.kind` is a `Literal` of: `contribution`, `environment`,
  `letter`, `motif`.
- Field bounds:
  - `offset_m`: 3 floats, each in [-5, 5].
  - `min_dwell_s`: 0–30.
  - `persona.name`: ≤ 40 chars.
  - `persona.voice`: `Literal["mms-tts-eng"]` in v1.
  - `persona.style`: `Literal["warm", "playful", "calm"]`.
- `GuidedTour` adds `project_id`, `tour_version`, `status`, `created_at`,
  and `author`, where `author` is the caller identity, like
  `ExperienceBlueprint.author`.

## `validate_guided_tour(project, tour_input) -> None` (raises 422)

Load blueprint `based_on_revision`. Use `compile_social_manifest(blueprint)`
to get object → contributor, and `store.list_contributions`. Then check, in
this order. Each check has its own message, so the NemoClaw retry (step 31)
can act on it:

1. Serialized size ≤ 256 KB, plus the counts: ≤ 30 steps, ≤ 400 facts,
   ≤ 200 elements.
2. Uniqueness of `fact_id`, `element_id`, and `step_id`. Every reference
   resolves: the theme's facts; each element's facts; each step's facts,
   focus, reveal, and stop anchor; narration facts; `next_step_ids`;
   `start_step_id`; `end_step_ids`.
3. Elements:
   - `object_id` exists in the blueprint for `contribution`,
     `environment`, and `letter`.
   - A `contribution` element's `contributor_id` and
     `contributor_display_name` equal the manifest's.
   - A `motif` has `object_id` null and a non-empty `staging_cue_id`.
4. Facts:
   - `contribution_memory`: `ref_id` is a contribution id. The text equals
     that contribution's `memory_text`, or is one of its sentences (split
     on `(?<=[.!?])\s+`), after `.strip()`.
   - `attribution`: the text must contain the contributor's display name
     and the element label.
   - `authored`: `derived_from` is non-empty and resolves, and it passes
     `grounding_violations(text, [derived facts], vocab)`. Put that
     function in `backend/guide_validator.py` now, because step 32 reuses
     it.
   - `letter_envelope`: the text may only contain the tour vocabulary plus
     the words `letter`, `from`, `for`, `to`, `sealed`, `a`, `an`, `the`,
     `is`, `this`, and `and`. A letter's `note_text` is never allowed,
     even as a substring: check every letter in the project.
5. Reveals:
   - `reveal_element_ids` only name `initially_visible: false` elements.
   - Every hidden element is revealed by some step that's reachable from
     the start.
6. Step graph:
   - A BFS from the start reaches every step.
   - Every non-end step has at least one next step.
   - Every end step is reachable.
7. Narration: `narration.fact_ids` ⊆ the step's `fact_ids`, and the
   narration passes `grounding_violations` against those facts.

## `grounding_violations(text, facts, vocab) -> list[str]`

It's deterministic and shared with step 32:

- The allowed set is lower-cased word tokens (`[A-Za-z0-9']+`) from the
  facts' text, plus `vocab`. `vocab` holds contributor display names,
  element labels, the theme title, and the persona name, split into
  tokens.
- A token in `text` is a violation when it's any of these, and its lower
  case isn't in the allowed set:
  - a capitalized word that isn't the first word of a sentence
  - any token containing a digit
  - any token inside `"…"` or `“…”`
- Return the list of violating tokens; empty means grounded.

This deliberately doesn't try to judge paraphrase quality. It only
guarantees that no new name, number, or quote appears. Common lowercase
prose is allowed, so the model can still sound natural.

## Storage

- Local: add `tours` and `tour_live` to the JSON store. Use the same
  locking as blueprints.
- DynamoDB:
  - `put_item` for `TOUR#%06d` with `ConditionExpression=
    "attribute_not_exists(pk)"`.
  - The `TOURLIVE` compare-and-set is an `update_item` with a condition
    `attribute_not_exists(pk) OR tour_version = :expected`, copied from
    `set_live_revision`.
  - On activate, rewrite the previously active `TOUR#` document's `status`
    to `retired`, and the new one to `active`. Use `TransactWriteItems`
    with the pointer update, so the three writes succeed together.
- Next version = `max(existing) + 1`, allocated under the conditional put.
  On a conflict, retry once.

## Routes

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| POST | `/v1/projects/{project_id}/tours/compose` | `require_project_draft` | `SKETCHSCAPE_TOUR_AUTHOR=mock` → `compose_tour_mock` → validate → store draft → 201 `GuidedTour`. `nemoclaw` → 501 until step 31. 409 if there's no LIVE revision or no `ConnectionInsight`. |
| POST | `/v1/projects/{project_id}/tours` | `require_project_draft` (service identity allowed once R14 lands) | Body `GuidedTourInput`, validated, stored as a draft → 201 |
| GET | `/v1/projects/{project_id}/tours` | `require_project_read` | A summary list: version, status, based_on_revision, authored_by, created_at |
| GET | `/v1/projects/{project_id}/tours/{tour_version}` | `require_project_read` | The full tour |
| POST | `/v1/projects/{project_id}/tours/{tour_version}/activate` | person only (`require_user`) + project write | Body `{expected_active_version: int\|null}` → compare-and-set → 200. 403 for a service identity, 409 on a stale expected version. Re-validate against the **current LIVE** blueprint first, and return 409 with `stale_element_ids` if more than half the steps would be skipped. |

## `compose_tour_mock` (deterministic, no network)

Inputs: the LIVE blueprint, the latest `ConnectionInsight`, the
contributions, the contributors, and the social manifest.

1. Facts:
   - `f_theme` = `"The room's theme is {theme}."`
   - `f_explanation` = the insight explanation, as a `connection_insight`
     source.
   - Per contribution: `f_<obj>_owner` = `"{name} brought the {label}."`
     (`attribution`).
   - Per contribution: `f_<obj>_memory` = each sentence of `memory_text`
     (`contribution_memory`), if the memory text is non-empty.
   - Per contribution: `f_<obj>_why` = the placement rationale
     (`placement_rationale`).
2. Steps:
   - `s_welcome`: theme and explanation facts. Anchored on the first
     contribution object.
   - One step `s_<obj>` per contribution, in blueprint order: owner,
     memory, and why facts. Narration = `"{owner fact} {first memory
     sentence}"`.
   - `s_together`: focuses every contribution and reveals every hidden
     element. Its narration is the theme fact.
3. Environment objects (`contribution_id is None`) become `environment`
   elements with an owner-free fact only if they have a label.
4. Letters become `letter` elements with `f_<obj>_letter` =
   `"This is a sealed letter from {author} for {recipients}."`.
5. `persona` = `{"name": "Lumen", "voice": "mms-tts-eng", "style":
   "warm"}`.
6. `off_topic_reply` = `"I can only tell you about this room and what
   everyone brought to it."`
7. `authored_by` = `{backend: "mock", model: "mock-tour-v1", tool:
   "compose_tour_mock", prompt_version: null}`.

Run `validate_guided_tour` on the mock output inside compose. A mock tour
that fails validation is a bug, and the error should say so.

## Tests (`backend/test_guided_tour.py`)

Use 3 contributors by default, plus one 4-contributor test. Never exactly
two (AGENT.md N-contributor rule).

- Compose is deterministic: the same inputs twice give byte-identical JSON,
  excluding `created_at` and `tour_version`.
- Compose → activate → `GET` shows active; the previous version shows
  retired.
- One 422 test per validator rule listed above, each asserting its
  message.
- Activate: service identity → 403. A stale `expected_active_version` →
  409.
- A letter with `note_text` "meet me at the lake" → no fact contains
  "lake".
- `DynamoDbStore` round-trips a tour and the compare-and-set against the
  in-memory fake table that `backend/test_storage.py` already uses (no
  moto, no AWS).
- The schema-parity test: a set of fixtures accepted and rejected
  identically by the JSON Schema and by `GuidedTourInput`. Add
  `jsonschema>=4,<5` to `backend/requirements-dev.txt`; it's not there
  today.

## Definition of done

`python3 scripts/check_collab_gates.py --done 30` and
`bash scripts/verify_local.sh` pass. In mock mode, with zero external
calls, a 3-contributor project goes compose → activate, and
`GET /tours/{v}` returns a valid active tour.
