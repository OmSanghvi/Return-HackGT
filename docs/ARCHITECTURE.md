# Architecture

For the concrete, ordered, step-by-step plan that builds everything
described in this document — exact files, functions, and the
`.claude/skills/<name>` skill governing each step — see `docs/BUILD_PLAN.md`.
This document explains the design; the build plan executes it.

## Boundary diagram

```text
                Unity desktop / future AR
                           |
        public REST: image upload, poll, scene JSON, edit
                           v
                     FastAPI backend
              / mock worker        \
             v                      v
      placeholder scene       one local GPU worker
                                      |
                         private loopback endpoints
                                      v
                  SAM 3.1 text-prompt segmentation
                                      |
                         aligned white-on-black mask
                                      v
                         staged Fast-SAM3D
                                      |
                         Gaussian-splat .ply artifact
```

## Non-negotiable ownership

- **Unity** renders, shows progress, invokes the portal, and applies validated
  scene JSON. It has no Hugging Face, AWS, or worker credential.
- **Backend** validates uploads, owns job status and scene JSON, and exposes
  only public-safe artifact URLs.
- **Worker** is the only component allowed to load models and receive the
  `SKETCHSCAPE_WORKER_TOKEN`.
- **Terraform** creates a private bundle bucket, narrowly-scoped instance role,
  SSM access, and a single GPU host. It does not contain Hugging Face tokens.

## API lifecycle

1. Unity posts `image`, optional aligned `mask`, and a short `subject_hint` to
   `POST /v1/reconstructions`.
2. The API replies `202` with a `job_id` and a relative `poll_url`.
3. Unity polls `GET /v1/reconstructions/{job_id}` every 1–2 seconds.
4. `complete` includes `scene`; Unity swaps its placeholder scene through the
   portal. `mask_review` keeps the existing showcase scene and asks for a
   better image or mask. `failed` shows an actionable error.
5. The worker alone uses private `/v1/internal/...` endpoints to fetch inputs
   and post results.

## Real-artifact constraint

SAM 3D produces a Gaussian-splat `.ply`, not a conventional `.glb`. The
repository supports the job and artifact lifecycle, but a Unity Gaussian-splat
renderer package must be selected before claiming real PLY rendering. The
portal demo must therefore include semantic-prefab fallback and pre-rendered
assets.

---

## Scaling Shared Room from two contributors to N

The Meta-track MVP (`docs/PROJECT_STATUS.md`) demos exactly two contributors
because that's the clearest, most judgeable story in a 2–3 minute video. None
of the underlying contracts should hard-code "two," so a family or friend
group can grow a room later without a rewrite. This section is the reference
for building the social layer N-ary from the start — `docs/BUILD_PLAN.md`
steps 1–2 (`contributor-data-model`, `contributor-api-endpoints` skills) are
where this reference actually gets implemented.

### Data model — no pair-specific fields

`Contributor` and `Contribution` are already naturally list-shaped: a
project has a list of contributors, each with a list of contributions. Do
not add fields like `contributor_a_id` / `contributor_b_id` anywhere — always
model this as `contributors: list[Contributor]` and
`contributions: list[Contribution]` scoped by `project_id`. Add:

- `Project.min_contributors` (default `2`) and `Project.max_contributors`
  (default unset/unbounded, or a small cap like `6` for the hackathon build
  to keep NemoClaw's layout reasoning and the room's readability bounded).
- A room only becomes eligible for `connection/compose` once
  `len(contributions) >= min_contributors`; composing again after a new
  contribution arrives (the "revisit and add to the room later" arc) should
  be a first-class re-compose call, not a special case.

### Database — extend the existing single-table design, don't fork it

`backend/storage.py`'s `DynamoDbStore` already uses one DynamoDB table with a
`PROJECT#<project_id>` partition key and typed sort keys (`META`,
`BLUEPRINT#<rev>`, `PUBLICATION#<seq>`) so everything for one project is
queryable together. Extend the same pattern instead of introducing a second
table:

```
PK = "PROJECT#<project_id>"
  SK = "META"                        -> project record (incl. min/max contributors)
  SK = "CONTRIBUTOR#<contributor_id>" -> one contributor (display name, joined_at)
  SK = "CONTRIBUTION#<contribution_id>" -> one contribution (contributor_id, asset_id, memory text)
  SK = "INSIGHT#<0-padded revision>"  -> one ConnectionInsight (theme, explanation, per-object rationale)
  SK = "BLUEPRINT#<0-padded revision>"
  SK = "PUBLICATION#<0-padded seq>"
```

A `Query` with `begins_with(SK, "CONTRIBUTOR#")` or `"CONTRIBUTION#"` returns
all of them for a project regardless of how many there are — this is what
makes N contributors free at the storage layer. Apply the identical shape to
`LocalJsonStore` (a `contributors` and `contributions` list per project
record) so mock mode and cloud mode stay structurally identical, which is the
existing rule for every other entity in this store.

### Config

Add these alongside the existing `SKETCHSCAPE_*` variables (see AGENT.md's
"Key environment variables"):

```bash
SKETCHSCAPE_MIN_CONTRIBUTORS=2   # a room can't compose a connection below this
SKETCHSCAPE_MAX_CONTRIBUTORS=6   # keep NemoClaw's layout + demo readability bounded
```

`config/nemoclaw/sketchscape-tools.json` and
`config/unity/sketchscape-scene.profile.json` have no hard-coded "two"
assumption today — no schema change is required there. Keep it that way: any
new tool entry or profile field must describe behavior in terms of "each
contribution" / "each object," never "the first/second contributor."

### NemoClaw and the blueprint/scene contract

- `shared/experience-blueprint.schema.json`'s `objects` field is already an
  array with no length limit — N objects need no schema change.
- `place_objects_in_scene` and `stage_immersive_reveal` (see AGENT.md) need
  to reason about a *set* of objects and contributors, not a pair: shared
  theme inference becomes a clustering problem (which objects support the
  same sub-theme, which one is an outlier that still deserves a place),
  layout becomes group-arrangement rather than two-point placement, and the
  reveal sequence becomes an ordered walk through however many contributions
  exist. Prompt/response contracts for the composition step should always
  accept a list of contributions, never assume exactly two.
- Contributor attribution stays in the authoring blueprint's sidecar social
  manifest, not `shared/scene.schema.json`, exactly as already specified for
  the two-contributor MVP — this doesn't change with N.
- One bounded scene edit per contributor still applies per-object: each
  contributor can only edit the object(s) they contributed, regardless of
  how many other contributors are in the room.

### Unity Cloud / real-time presence — explicitly out of MVP scope, but plan for it

The MVP stays **sequential co-creation**: contributors add their object at
different times, nobody needs to be online simultaneously, and there is no
netcode anywhere in the shipped build. This scales to N contributors with
zero networking work, which is why it's the right MVP shape. Do not add
real-time multiplayer to hit the N-contributor request — it's explicitly
out of scope per the existing hard rule against accounts, chat, real-time
multiplayer, and notifications.

If a *future* "everyone views the finished room together, live" mode is ever
built, evaluate these paths and pick the one that best fits the track:

- **Meta's own Platform SDK — Shared Spatial Anchors / colocation**
  (Quest-native shared-anchor APIs for co-located or remote presence in the
  same virtual space). Prefer this for the Meta track specifically, for the
  same judge-legibility reason `AGENT.md` already gives for the Llama model
  and the Unity MCP Extension: using Meta's own platform capability instead
  of a generic third-party service is a deliberate, on-brand choice for this
  challenge. Check Meta's current Horizon OS developer documentation for the
  exact API surface before implementing — do not guess method names.
- **Unity Cloud / Unity Gaming Services** (Unity Authentication, Lobby,
  Relay, and Netcode for GameObjects) if the experience ever needs to run on
  non-Quest / cross-platform clients, or if Meta's colocation APIs don't fit
  the deployment target. This is the generic, engine-native path and is
  reasonable to reach for outside the Meta-track submission, but it adds
  real infrastructure (a Unity Cloud project, authentication, a relay
  service) that the current backend does not have, and it does not carry
  the same "why Meta" story.

Either path is additive on top of the existing published-blueprint/
compiled-scene contract — the compiled scene stays the single source of
truth for what's *in* the room; a real-time layer would only add who else is
looking at it and when, never bypass blueprint validation or publication.
