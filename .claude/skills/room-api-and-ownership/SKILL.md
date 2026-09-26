---
name: room-api-and-ownership
description: Use for Build Plan step 17 (project membership, invite codes, binding Contributors to one of the two hardcoded accounts, room_prompt, and deriving which objects each person owns) and step 21 (the public room API /v1/rooms/{project_id}/state and /edits that headsets call with the X-SketchScape-Dev-User account header — no room token, no Clerk session; see collab-vr-accounts-and-gates). The room API is the only backend surface a shipped Unity player may use for collaborative edits (AGENT.md Hard Rule 4).
---

# Membership, ownership, and the room API (steps 17 and 21)

## Gate

`python3 scripts/check_collab_gates.py 17` (needs 2, 16) or `21` (needs 15,
17). BLOCKED means stop.

## Step 17: membership and ownership

- `ProjectRecord` gains `invite_code: str` (at least 16 random URL-safe
  characters, from `secrets.token_urlsafe`) and `room_prompt: str | None`
  (max 300).
  - Only members can see the invite code.
  - Add `POST /v1/projects/{id}/invite/rotate` to rotate it.
- `Contributor` gains `clerk_user_id: str | None` (the field name is
  unchanged from the earlier Clerk plan; it now holds one of the two
  hardcoded account ids — see `backend-auth-clerk`). Registering as a
  contributor requires a valid `invite_code` (except the project creator,
  who is registered automatically) and binds the caller's verified
  identity. That identity can be a contributor of a project only once.
- **Membership check** for every project-scoped route outside `mock` mode
  (`demo` or `clerk`):
  - The caller must be a contributor of the project, else 403.
  - `kind="service"` (NemoClaw) may read all projects and draft revisions,
    but never upload as a person or register as a contributor.
- **Ownership** (from ARCHITECTURE.md: each person edits only objects they
  contributed). Derive it; don't store a second copy:
  `object.asset_id` ∈ {`contribution.asset_id` for the caller's
  contributions}. Helper: `owned_object_ids(project_id, clerk_user_id, blueprint)`.
- Objects with no contributor (NemoClaw environment objects) can't be
  edited from headsets.
- `PATCH /v1/projects/{id}` lets contributors set `room_prompt`.
- Tests:
  - A non-member gets 403 on reads and uploads.
  - A bad invite code gets 403.
  - Registering twice is rejected.
  - A 3-contributor project derives ownership correctly.
  - Mock mode keeps working with the dev user.

## Step 21: the room API

Headsets never call authoring routes (Hard Rule 4). They call these with
the same `X-SketchScape-Dev-User` account header every other `demo`-mode
route uses — the headset's account switcher sends it directly (see
`collab-vr-accounts-and-gates`). There is no room token and no Clerk
session in this plan (decision 2026-09-26, `docs/KNOWN_ISSUES.md` R13).
The website and NemoClaw may call `GET /state` too.

### `GET /v1/rooms/{project_id}/state`

- Caller: a member (the account header), or a service.
- Returns:
  - `live_revision` (step 15 LIVE pointer) and the compiled scene.
  - Per object: `id`, `asset_id`, `position`, `rotation`, `scale`,
    `interactions`, `owner_contributor_id`, and `editable_by_me`.
  - Artifact URLs the headset can fetch with the same token.
- 404 if nothing is published.
- **Cheap polling:** `?since_revision=N` plus an `ETag` over (live
  revision, letter-state version). Return `304` when unchanged. Use a
  separate, generous rate-limit bucket for this read. Step 28 adds
  `letters[]` to the response.

### `POST /v1/rooms/{project_id}/edits`

- Caller: a member, via the account header — a person in a headset.
  Services → 403.
- Body:
  ```json
  {"base_revision": 12, "client_edit_id": "uuid",
   "edits": [{"object_id": "lamp_1", "position": [0.4, 0, 1.2], "rotation": [0, 90, 0], "scale": [1, 1, 1]}]}
  ```
- Values are absolute (so retries are harmless), with at most 20 edits
  per call.

Server order:
1. **Idempotency:** if a revision with this `client_edit_id` by this
   author exists, return it with 200.
2. **Ownership:** every object is in `owned_object_ids`, else 403.
3. **Interaction allowlist:** position needs `translate`, rotation needs
   `rotate`, scale needs `scale`, else 422.
4. **Bounds:** position within ±100 per axis, scale 0.05–20 per axis,
   rotation normalized to [0, 360). NaN/Infinity → 422.
5. **Revision check:** `base_revision` must equal the live revision, else
   409 `{"live_revision": X}`.
6. Copy the **live** blueprint (never the latest draft, so an unapproved
   NemoClaw draft can't be published by accident) and apply only these
   transforms. Run `validate_blueprint_assets`. Append the new revision
   with `based_on_revision`, `author`, and `client_edit_id`, using the
   conditional append.
7. `set_live_revision(expected=base_revision, new=R)`. If that returns
   False → 409. Then append the publication record.
8. Return 201 `{"revision": R, "live_revision": R}`.

People only edit their own objects, so a client's rebase after a 409
never overwrites anyone else. Never touch the process-wide `current_scene`
from these routes.

**Rate limit:** more than about 5 edit calls per user per second → 429.
This protects the API from a buggy client and is separate from the
upload-cost decision. Use an in-process limiter for now, and note in the
PR that multiple instances will need a shared one.

### Tests

- Owner edit → 201, and `state` shows it.
- Non-owner → 403.
- A service identity on `/edits` → 403 (headsets only).
- Missing interaction or out-of-bounds values → 422.
- Stale base → 409.
- Duplicate `client_edit_id` → one revision.
- Two users editing different objects from the same base both survive
  after a rebase.
- An unpublished NemoClaw draft stays unpublished.

## Definitions of done

`--done 17` / `--done 21` and `bash scripts/verify_local.sh` pass.
