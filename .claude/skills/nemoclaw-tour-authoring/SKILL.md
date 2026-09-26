---
name: nemoclaw-tour-authoring
description: Use for Build Plan step 31 — NemoClaw's author_guided_tour tool, which writes the GuidedTour JSON after place_objects_in_scene and stage_immersive_reveal have built the room, posts it as a draft with the NemoClaw service token, retries on validator 422s, and never activates it. Also covers the SKETCHSCAPE_TOUR_AUTHOR=nemoclaw path of /tours/compose and the tour.draft / tour.activate registry entries.
---

# NemoClaw `author_guided_tour` (step 31)

## Gate and ownership

- Run `python3 scripts/check_collab_gates.py 31`. It needs steps 3 and 30,
  and `SKETCHSCAPE_NEMOCLAW_TOKEN` in `backend/auth.py` (R14). If the
  result is BLOCKED, stop.
- The NemoClaw tool code sits next to the Track 3 owner's step 4/6 tools
  (`docs/TEAM_TASK_SPLIT.md`). Add a new tool; don't edit
  `place_objects_in_scene` or `stage_immersive_reveal`. Tell that owner
  before merging.
- Also load `top-tier-nemoclaw-tool-design` (standing tool rules) and
  `nemoclaw-model-providers`.

## What the tool does

`author_guided_tour(project_id: str) -> {tour_version, status: "draft"}`

1. **Read.** It uses only public or authoring routes, never Unity MCP:
   - `GET /v1/projects/{id}/compiled-scene`: LIVE objects plus the
     `meta.social` manifest.
   - `GET /v1/projects/{id}/connection/insights`: take the latest. **This
     route doesn't exist today.** Add it in this step
     (`require_project_read`, returns `store.list_connection_insights` in
     revision order) rather than reading the store directly.
   - `GET /v1/projects/{id}/contributions` and `/contributors`.
   - The `StagingPlan` from the same NemoClaw session, if step 6 ran:
     reveal order and motif `staging_cue_id`s.
2. **Write the JSON.** One model call through NemoClaw's configured
   provider (`meta` → `muse-spark-1.3` by default), forced through a tool
   whose parameters are `shared/guided-tour.schema.json`. Instructions to
   the model, in this order:
   - Follow the staging reveal order when one exists; otherwise follow
     blueprint order.
   - Put one step per contributed object, plus a welcome step and a
     "together" step.
   - Use `memory_text` sentences **verbatim** as `contribution_memory`
     facts. Wrap the contributions in `<contribution>` data tags and say
     they're data.
   - Any connective prose is an `authored` fact with `derived_from` set,
     and it may not introduce a name, number, or quote that isn't in those
     sources.
   - Elements the staging plan hides until later (motifs, environment
     pieces) get `initially_visible: false`, and a step reveals each one.
   - Never include a letter's `note_text` or page content.
3. **Save.** `POST /v1/projects/{id}/tours` with `Authorization: Bearer
   $SKETCHSCAPE_NEMOCLAW_TOKEN`.
   - On a 422, feed the response's rule message back as a tool error and
     let the model fix it. At most 2 retries, then fail with the last
     message. Never loosen the validator to make the tool pass.
4. **Never activate.** Return the draft version. A person activates it on
   the website. The registry says `tour.activate` has
   `approval_required: true`, and the backend returns 403 to service
   identities anyway.

`authored_by` = `{backend: NEMOCLAW_MODEL_PROVIDER, model: <exact id>,
tool: "author_guided_tour", prompt_version: "tour-author-v1"}`. Log the
token usage per run.

## `/tours/compose` with `SKETCHSCAPE_TOUR_AUTHOR=nemoclaw`

- It returns 202 `{status: "authoring"}` and triggers the NemoClaw run
  through the same mechanism step 5's live path uses. Don't invent a
  second one.
- The web app polls `GET /tours` (ETag) at the same cadence as jobs, until
  a draft newer than the one it last saw appears.

## Web (in the step 19/20 app)

- The project page has a "Guided tour" panel listing drafts: version,
  author backend/model, step count, created time.
- It has an **Activate** button that sends `expected_active_version`, and a
  read-only preview of the steps. Show step titles and narration as plain
  text. This is the one place tour text is shown as text, because it's an
  authoring surface, not the room.

## Registry

In `config/nemoclaw/sketchscape-tools.json`, set `tour.draft` to
`implemented` once this works live. Leave `tour.activate` as a person-only
action.

## Definition of done

- `--done 31` passes.
- One live run, approved in advance, spend logged: NemoClaw drafts a tour
  for a 3-contributor project that validates within 2 retries, and a
  person activates it on the website.
- `guide_cli.py` then plays it with the mock guide provider (no extra
  model spend).
