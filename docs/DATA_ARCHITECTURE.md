# Data architecture — SketchScape / Shared Room

The single reference for where every piece of data lives: accounts and
identity, projects and contributors, image uploads (photos, Notability
sketches, letters), segmentation masks, worker-produced PLYs, optional user
text, jobs, blueprints and the live room. Written 2026-09-25. Everything
marked **(new)** is planned in `docs/BUILD_PLAN.md` and gated by
`scripts/check_collab_gates.py`. Nothing here is implemented until its step
says so.

## Principles

1. **One DynamoDB table** (`sketchscape-authoring`, `pk`/`sk`, already in
   `infra/aws/main.tf`) plus **one S3 bucket** for bytes. No second table,
   no second database. `LocalJsonStore` and local files mirror the same
   shapes for offline mock mode (Hard Rule 2).
2. **Published blueprint revisions are the source of truth** for what's in
   a room (Hard Rule 6). Everything else is catalog, provenance, or live
   state.
3. **No list-in-a-blob for anything written concurrently.** `ProjectRecord`
   is saved as one JSON document, so appending to its lists from parallel
   requests loses data. With multi-object uploads and several people
   uploading at once, this is the most likely failure. Membership, assets,
   jobs, and letters are **child items**, not lists in the project document.
4. **Every concurrent write is conditional** (`attribute_not_exists`,
   compare-and-set), as set up in step 15.
5. **Store the minimum personal data.** We keep the Clerk user id, a
   display name, and the linked Meta user id. No emails, no passwords, no
   Meta profile data. Clerk holds identity.
6. **Bytes never go in DynamoDB.** Items hold S3 keys; S3 holds images,
   masks and PLYs.

## DynamoDB item catalog

`pk` / `sk` are strings. The `document` attribute holds the model's JSON as
today. Extra top-level attributes exist only where a condition or an index
needs them.

| Entity | pk | sk | Key attributes | Written by |
| --- | --- | --- | --- | --- |
| Project | `PROJECT#<project_id>` | `META` | document (name, description, min/max contributors, `invite_code`, `room_prompt`, created_by) | step 17 |
| Live pointer | `PROJECT#<id>` | `LIVE` | `revision` (number; compare-and-set) | step 15 |
| Contributor | `PROJECT#<id>` | `CONTRIBUTOR#<contributor_id>` | document (display_name, `clerk_user_id`); `gsi1pk=USER#<clerk_user_id>`, `gsi1sk=PROJECT#<id>` | steps 1, 17 |
| Contribution | `PROJECT#<id>` | `CONTRIBUTION#<contribution_id>` | document (contributor_id, asset_id, `source_type` photo\|sketch\|letter, `memory_text`) | steps 1, 20 |
| Project → asset link **(new)** | `PROJECT#<id>` | `ASSET#<asset_id>` | `created_at` (replaces `ProjectRecord.asset_ids` list) | step 26 |
| Asset | `ASSET#<asset_id>` | `META` | document (label, `kind` reconstruction\|sketch_card\|letter, status, views, artifact keys) | existing + 26 |
| Upload **(new)** | `PROJECT#<id>` | `UPLOAD#<upload_id>` | document (source image key after EXIF orientation, width, height, uploader, `selections[]`: `selection_id`, `prompt` {points [[x,y,1\|0]] \| box [x0,y0,x1,y1] \| text}, normalized 0–1, `label`, `memory_text`, `status` pending\|segmented\|failed\|generated, `mask_key`, `preview_key`, `score`, `alternatives[]`, `origin` person\|suggested) | step 26 |
| Job **(new, durable)** | `JOB#<job_id>` | `META` | document + top-level `status`, `lease_owner`, `lease_expires_at`, `attempts`; `gsi1pk=PROJECTJOBS#<project_id>`, `gsi1sk=<created_at>#<job_id>`; `gsi2pk=JOBQ#<status>`, `gsi2sk=<created_at>#<job_id>` | steps 26, 27 |
| Blueprint revision | `PROJECT#<id>` | `BLUEPRINT#<rev padded>` | document (+ `based_on_revision`, `author`, `client_edit_id`) | existing + 15 |
| Publication | `PROJECT#<id>` | `PUBLICATION#<seq padded>` | document (revision, author, published_at) | existing + 15 |
| Connection insight | `PROJECT#<id>` | `INSIGHT#<rev padded>` | document (`backend` mock\|meta\|xai\|nebius, `model`, theme, explanation, rationales) | steps 1, 5 |
| Room edit idempotency | `PROJECT#<id>` | `EDIT#<author>#<client_edit_id>` | `revision`; `ttl` (7 days) | step 21 |
| Letter **(new)** | `PROJECT#<id>` | `LETTER#<letter_id>` | document (author contributor, `recipient_contributor_ids[]`, page image key, texture key, aspect, `note_text`, envelope style) | step 28 |
| Letter opened **(new)** | `PROJECT#<id>` | `LETTEROPEN#<letter_id>#<contributor_id>` | `opened_at` (conditional put; first open wins, repeat is a no-op) | step 28 |
| Meta link | `META#<meta_user_id>` | `LINK` | `clerk_user_id` | step 18 |
| Meta link (reverse, uniqueness) | `USERLINK#<clerk_user_id>` | `META` | `meta_user_id` | step 18 |
| Link code | `LINKCODE#<sha256(code)>` | `META` | `meta_user_id`, `code_id`, `status` pending\|linked; `ttl` (10 min) | step 18 |

Writes that must succeed together use `TransactWriteItems` with conditions.
Examples: both Meta link items; a contributor plus its membership index;
an asset plus its project link.

### Indexes and table settings (Terraform change, needs approval)

The table has **no GSIs today**. Add them in `infra/aws/main.tf` (never
`terraform apply` without explicit approval, Hard Rule 3):

- **GSI1** (`gsi1pk`, `gsi1sk`), overloaded:
  - `USER#<clerk_user_id>` → the person's projects (the "My projects" page).
  - `PROJECTJOBS#<project_id>` → the project's jobs, newest first (used for
    batch polling).
- **GSI2** (`gsi2pk`, `gsi2sk`): `JOBQ#queued` → the oldest queued job
  first (the GPU dispatcher's claim query).
- **TTL** on attribute `ttl` (link codes, edit idempotency records).
- Keep point-in-time recovery, SSE, and the existing `DeleteTable` deny
  policy.

The local store implements the same access patterns with in-memory indexes
rebuilt at load.

## S3 layout (one bucket: `SKETCHSCAPE_ARTIFACTS_BUCKET`)

| Prefix | Contents | Written by | Read by |
| --- | --- | --- | --- |
| `uploads/<project_id>/<upload_id>/source.<jpg\|png\|webp>` | Original photo or sketch page (≤16 MB, JPEG/PNG/WebP) | API on upload | Worker via internal route; the uploader |
| `uploads/<project_id>/<upload_id>/selections/<selection_id>-mask.png` and `-preview.png` (+ `-alt<n>` for text alternatives) | SAM 3.1 mask per selected object | Worker (step 27) | Web (selection canvas), worker (Fast-SAM3D input) |
| `artifacts/<job_id>/object.ply`, `mask.png`, `mask-preview.png` | Worker-produced Gaussian splat + final mask (existing layout) | Worker via internal route | Headset/Unity, web thumbnails |
| `letters/<project_id>/<letter_id>/page.png` | Original letter page | API (step 28) | Author and recipients (sealed); all members once opened |
| `letters/<project_id>/<letter_id>/texture-2048.png` | Page downscaled to 2048 px on the long edge for Quest memory | API (Pillow) | Headset |

- **Uploads go to S3 in cloud mode (new, step 26).** Today uploads are
  saved on the API host's disk (`UPLOAD_ROOT`), so with more than one API
  instance the worker can fetch an input from an instance that doesn't
  have it. Local mode keeps the disk layout.
- **No public objects.** Block public access, SSE on. Reads go through the
  API: the existing `/v1/artifacts/...` redirects to a presigned GET that
  expires in 5 minutes, after the membership (and letter-seal) check.
- **PLYs come only from the worker** (decision 2026-09-25: users don't
  upload PLYs). A PLY is about 50 MB, which is why it streams to S3 through
  the existing multipart path, never buffered in memory.
- Lifecycle (optional, post-demo): expire `uploads/` selection masks that were
  never selected after 30 days.

## Object selection flow (website → SAM 3.1 → PLY)

```
upload photo (stored, EXIF-corrected; no GPU)
  → person marks each wanted object on the canvas: click (include/exclude),
    box, or typed name; adds optional label + memory text per object
  → POST .../selections → one segment job (SAM 3.1 set_image once)
  → masks shown per object → refine any one (more points / new box)
  → POST .../generate with the chosen selections
  → one reconstruct job (Fast-SAM3D) per object → PLY → asset + contribution
```

Auto-detect (NemoClaw labels as text prompts) only creates *suggested*
selections. Nothing generates without a person's choice.

## Optional user text (context for NemoClaw)

| Field | Where | Limit | Used for |
| --- | --- | --- | --- |
| Selection `label` / `subject_hint`; text-prompt `text` | Upload selection, per object | 100 chars (existing) | The object's name in the room; a SAM 3.1 text prompt when the person types a name; NemoClaw labels the object if it's blank (step 4a) |
| `memory_text` | Contribution | 1000 chars | Why the object matters; compose theme, staging, narration |
| `room_prompt` | Project | 300 chars | Overall room style hint for `connection/compose` |
| `note_text` | Letter | 2000 chars | Optional typed transcription: narration and accessibility, extra context for composing the room |
| `display_name` | Contributor | 80 chars | Attribution in the room |

All of it is **untrusted input**:
- Stored as given, length-checked on the server.
- Rendered as plain text in the web app.
- Passed to NemoClaw inside clearly delimited data fields, never as
  instructions.
- Screened by Llama Guard if step 9 is built.
- Never put into prompts that decide tool calls without schema validation
  of the result.

## Accounts and auth data

- **Clerk**: users, sessions, and M2M machines live in Clerk. We store only
  `clerk_user_id` (on Contributor items and GSI1) and the author strings on
  revisions.
- **Demo mode (added 2026-09-26):** with `SKETCHSCAPE_AUTH_MODE=demo`, the
  same `clerk_user_id` field and GSI1 key just hold one of the two hardcoded
  demo account ids (`SKETCHSCAPE_DEMO_USERS`) instead of a real Clerk `sub`.
  No schema change; see `backend/auth.py` and `docs/BUILD_PLAN.md`'s "Demo
  auth mode" note.
- **Meta**: `META#<id>` / `USERLINK#<id>` link items, plus short-lived
  hashed link codes.
- **Secrets are never stored in the table** (`CLERK_SECRET_KEY`, Meta app
  secret, room-token secret, model provider keys). They live in backend or
  NemoClaw secret storage, per the config matrix in
  `collab-vr-accounts-and-gates`.

## Job lifecycle (durable, step 26)

```
queued ──claim(lease)──▶ running ──callback──▶ complete
   ▲                        │  └──────────────▶ needs_review (segmentation unclear)
   └──── lease expired ─────┘                ─▶ failed (after max attempts)
```

- Job kinds:
  - `segment` runs SAM 3.1 once per image over the selections the person
    made on the website: points/box use the interactive predictor (one
    mask each), and text uses the semantic predictor (best instance plus
    alternatives). A refine re-runs one selection.
  - `reconstruct` runs Fast-SAM3D once per selection the person chose to
    generate.
- **Claim:** a conditional update `status=queued → running` that sets
  `lease_owner` and `lease_expires_at` (default 15 min). The dispatcher
  renews the lease while working. An expired lease goes back to `queued`,
  with `attempts` incremented. After `SKETCHSCAPE_JOB_MAX_ATTEMPTS`
  (default 2) the job is `failed`.
- **Callbacks** from the worker are accepted only from the current lease
  owner (conditional on `lease_owner`). A late callback from an expired
  lease is ignored.
- The job state lives in the store, so **any API instance can answer a
  poll**. The in-memory `jobs` dict in `main.py` is removed.

## Polling contract (all clients)

Polling is the baseline; there's no push channel. Every polling endpoint is
read-only, cheap (store reads only, never starts work), and returns an
`ETag`. Clients send `If-None-Match` and get `304` when nothing changed.
Polling endpoints have their own rate-limit bucket (about 5 requests per
second per identity), separate from write limits. On `429` or `503`,
clients honor `Retry-After`.

| Client | Endpoint | Cadence | Stop when |
| --- | --- | --- | --- |
| Web: selections, masks, and reconstructions | `GET /v1/projects/{id}/jobs?active=1` (one call covers every object in flight) | 2 s for the first 20 s, then 5 s, then 10 s after 2 min; ±20% jitter; paused while the tab is hidden | No active jobs remain |
| Web: a single legacy job | `GET /v1/reconstructions/{job_id}` | Same curve | Terminal status |
| Headset: session owner | `GET /v1/rooms/{id}/state?since_revision=N` (304 if the live revision and letter states are unchanged) | 3 s | Session ends |
| Headset: waiting for Quest link | `GET /v1/auth/meta/link-code/{code_id}/status` (no Meta nonce needed) | 5 s, max 10 min, then show a new code | `linked` → one `POST /v1/auth/meta/session` |
| NemoClaw | `GET /v1/rooms/{id}/state`, jobs endpoint | On demand only, never in a loop | — |

Server-sent events or WebSockets can replace polling later without changing
these resources.
