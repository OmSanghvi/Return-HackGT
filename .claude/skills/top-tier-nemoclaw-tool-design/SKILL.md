---
name: top-tier-nemoclaw-tool-design
description: Use when designing, implementing, or reviewing ANY NemoClaw tool (standing guidance), and specifically for Build Plan step 24 — NemoClaw room tools (get_room_state, propose_room_edit, publish through the approval-gated path) for the Collaborative VR room. Covers where NemoClaw may act (backend vs the Editor-only Unity MCP Extension), agent-tool design rules, registry conventions, service identity, and approval gating.
---

# Designing top-tier NemoClaw tools

## Gate (step 24 only)

```bash
python3 scripts/check_collab_gates.py 24
```
Needs steps 3 (NemoClaw runtime), 15, 16 and 21. If BLOCKED, stop. The
design rules below apply to every NemoClaw tool at any time.

## Which surface a tool acts on

| Surface | Changes | Use for |
| --- | --- | --- |
| Meta XR Unity MCP Extension | The scene open in the **Unity Editor** (it extends Unity's own MCP package; install Unity MCP first, then `https://github.com/meta-quest/Unity-MCP-Extensions.git`) | Authoring the base scene before a build |
| Backend authoring API | Blueprint revisions, i.e. the durable room | Anything that should reach a **live room** |

A running Quest session never sees Editor changes until someone rebuilds.
A tool that changes a live Shared Room **goes through the backend** (draft
revision, then approval-gated publish). The session owner pulls it in
(step 23). Hard Rule 4 also keeps NemoClaw out of the shipped player.

Verified facts about the MCP Extension: Unity **6000.0.66f2+** (6.1+
recommended; HackGTUnity's 6000.2.10f1 is fine), Meta XR SDK **v78+**,
GitHub-only and "functionality might vary by version", so **pin a commit**.
Documented operations: create/update/delete GameObjects, relative
move/rotate, make grabbable, teleport hotspots. **No read/query operation is
documented.** Get current transforms from `/v1/rooms/{id}/state` or
`compiled-scene`, never by assuming the extension can read.

## Design rules (Anthropic's "writing tools for agents" + MCP guidance)

1. Shape tools around a job (`place_objects_in_scene`), not one endpoint
   each.
2. Accept lists, never fixed pairs; test with 2 and 5 objects in one run.
3. Strict typed inputs matching the backend's Pydantic constraints (ids
   `^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$`, 3-float vectors, interaction
   allowlist). Reject bad input at the tool.
4. Validate before writing (`shared/experience-blueprint.schema.json` or
   `POST /blueprints/validate`).
5. Short, readable results ("revision 14 drafted from live 13; moved lamp_1
   +0.4 m x; not published"). Offer `response_format: concise|detailed`
   for large payloads.
6. Actionable errors ("live revision is now 15; call get_room_state and
   redo the proposal").
7. Pass state explicitly (`project_id`, `base_revision`); no hidden
   "current room" in the runtime.
8. Safe to retry; check `GET /publications` before re-publishing after a
   timeout.
9. Gate costly, irreversible, or user-visible actions behind approval.
10. Test with real agent transcripts too. Keep pure layout logic separate
    so it's unit-testable without an LLM; add one `PIPELINE_MODE=mock`
    end-to-end test.

## Registry and naming

- `config/nemoclaw/sketchscape-tools.json` uses dotted ids and the fields
  `id`, `method`, `path`, `purpose`, `approval_required`, optional
  `approval_reason`, `implementation_status`. It's documentation only.
  Never put credentials in it.
- Callable tool names are `snake_case` (many model APIs reject dots in
  function names). Name the registry id in each tool's description.
- Set `implementation_status` to `implemented` only after the tool has run
  successfully end to end. The gate script reads this.

## Service identity

NemoClaw calls the backend with a **Clerk M2M token**
(`accepts_token` includes `m2m_token`, step 16), giving
`Identity(kind="service")` and `author = nemoclaw:<id>` on revisions. It
never uses a person's Clerk token. The M2M credential lives in NemoClaw's
runtime credential provider, never in this repo.

## Step 24 tools

| Callable | Registry id | Does | Approval |
| --- | --- | --- | --- |
| `get_room_state(project_id)` | `room.state.fetch` | `GET /v1/rooms/{project_id}/state` (service identities may read) → concise summary | No |
| `propose_room_edit(project_id, base_revision, edits[])` | `room.edit.draft` | Copy the live blueprint, apply edits, validate, `POST /v1/projects/{project_id}/blueprints?base_revision=<live>`. Never publishes. | No |
| (existing) | `blueprint.publish` | Publish after a person approves it on the website's Room page (step 19/20 web app). Step 15 compare-and-set returns 409 if the room changed since the draft; then re-propose. | **Yes** |

- `propose_room_edit` may move environment objects and, when the user asked
  for a layout change, contributed objects. It must say which people's
  objects it moves, so the approver knows.
- On 409, re-read with `get_room_state` and re-draft. Never overwrite.

## Approval summary

| Action | Approval |
| --- | --- |
| Read state, validate, draft a revision | No |
| Publish any revision (including into a live room) | **Yes** |
| Anything that starts GPU work | **Yes** |
| Registering MCP targets, installing runtimes | **Yes** |

## Definition of done (step 24)

`python3 scripts/check_collab_gates.py --done 21` and
`bash scripts/verify_local.sh` pass; both tools are registered with the
correct `approval_required` and pass 2-object, 5-object, and mock
end-to-end tests.
