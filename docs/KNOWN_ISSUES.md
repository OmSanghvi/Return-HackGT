# Known issues and their fixes

Every issue found while planning the Collaborative VR + web accounts track
(research and code review, 2026-09-25), with the **current** fix and where
it lives. Fixes are gated Build Plan steps (`docs/BUILD_PLAN.md`, steps
13–29). Run `python3 scripts/check_collab_gates.py <step>` before starting
one (AGENT.md Hard Rule 9).

Status meanings:
- **Done (docs):** the fix is already made in the docs/rules.
- **Planned:** the fix is designed in the named step and skill but not
  coded yet.
- **Verify:** only a real device or GPU run can answer it.
- **Accepted:** a known risk the user chose to keep.
- **Superseded:** the issue no longer applies after a later decision.

## Scope and project

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| 1.1 | AGENT.md forbade accounts and real-time multiplayer | Approved as a separate, gated post-MVP track that never delays steps 1–12 | AGENT.md, ARCHITECTURE.md, PROJECT_STATUS.md, TEAM_TASK_SPLIT.md, `meta-track-alignment` | Done (docs) |
| 1.2 | HackGTUnity (6000.2.10f1, XRI 3.0.11, OpenXR 1.15.1) has no Netcode or Multiplayer Services | Port from VR Multiplayer Template 2.1 using its exact package versions | Step 22, `unity-cloud-collaborative-vr` | Planned |
| N26 | AGENT.md said `place_objects_in_scene` "publishes immediately via Unity MCP", contradicting the approval rule | Tool returns a draft proposal; `blueprint.publish` needs a person's approval; `trigger_unity_scene_update` only applies already-published scenes to the Editor | AGENT.md NemoClaw section | Done (docs) |

## Backend and data

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| 2.1 | No authentication on any route | Clerk `session_token` (web, `authorized_parties`) + `m2m_token` (NemoClaw); headsets use backend room tokens from verified Meta proof; fail-fast config | Steps 16, 18; `backend-auth-clerk`, `meta-quest-identity` | Done (web + M2M, step 16) / Planned (Meta room tokens, step 18) |
| 2.2 | No base-revision check: stale saves silently erase newer edits | `based_on_revision` = live revision; 409 when stale; clients rebase their own objects | Step 15, `backend-revision-concurrency` | Planned (can start now) |
| 2.3 | DynamoDB `put_item` without condition and a per-process lock: revisions overwrite each other | `attribute_not_exists(sk)` on blueprint and publication appends, with retry | Step 15 | Planned |
| N2 | Whole-blob `ProjectRecord` saves let the live room go backwards | Compare-and-set `LIVE` pointer item | Step 15 | Planned |
| N3 | An unapproved NemoClaw draft could get published by a room edit | Edits copy the live revision; publish is compare-and-set on `based_on_revision` | Steps 15, 21 | Planned |
| 2.4 | One process-wide `current_scene` for all projects | Rooms read per-project live state only; room routes never touch `current_scene` | Steps 15, 21 | Planned |
| 2.5 | No ownership: "edit only your own object" is unenforced (Netcode check is client-side) | Contributors bound to Clerk users; ownership derived from contributions; server returns 403 | Steps 17, 21; `room-api-and-ownership` | Done (ownership helper + membership, step 17) / Planned (room `/edits`, step 21) |
| 2.6 | No partial updates; every save is a full blueprint | Debounced save on release; bounded, idempotent `/v1/rooms/*/edits` builds the revision server-side | Steps 21, 23 | Planned |
| 2.7 | No push channel to live rooms | Session owner polls `/v1/rooms/{id}/state?since_revision=` with ETag/304 | Step 23, DATA_ARCHITECTURE polling contract | Planned |
| 2.8 | No author on revisions | `author` on revisions and publications (Clerk user, `nemoclaw:<id>`) | Steps 15, 16 | Done |
| N1 | Headsets calling authoring routes breaks Hard Rule 4 | Public room API `/v1/rooms/*`; Hard Rule 4 updated | Step 21, AGENT.md | Done (docs) / Planned (code) |
| N4 | Mock auth could reach the cloud | Backend refuses to start: mock + DynamoDB or non-mock pipeline; clerk without secret or with `*` origins | Step 16 | Done |
| N15 | Reconstruction jobs live in an in-memory dict: lost on restart, polls fail across instances | Durable lease-based jobs in the store | Step 26, `durable-jobs-and-multi-object-upload` | Planned |
| N16 | Uploads stored on one API host's disk | S3 `uploads/` in cloud, disk locally | Step 26 | Planned |
| N17 | `asset_ids` appended inside the project blob; simultaneous uploads lose assets | Project→asset child items | Step 26 | Planned |
| N20 | DynamoDB table has no GSIs or TTL (needed for "my projects", job queue, link-code expiry) | GSI1, GSI2, TTL via Terraform; the backend refuses to start without them | DATA_ARCHITECTURE.md, step 26 | Planned (needs approval to apply) |
| N27 | The browser shows photos EXIF-rotated but the server's pixels aren't, so object selections would land in the wrong place | Server applies `exif_transpose` on upload; the canvas draws the stored image; coordinates are normalized 0–1 | Step 26, `web-uploads-and-linking` | Planned |

## Uploads, GPU, and SAM 3.1

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| N18 | Worker handles one job and one mask per image (queue size 1, `choose_one`, 429 when busy) | The person selects objects on the website (click, box, or name) → one SAM 3.1 pass (interactive for points/boxes, semantic for names) → one Fast-SAM3D job per chosen object via a leased dispatcher | Steps 26–27, `gpu-multi-object-worker` | Planned |
| N19 | Hard Rule 5 said "T4 16 GB", but the verified GPU is an L40S (45 GB) and Terraform still defaults to a T4 | Rule rewritten: sequential within a job; `SKETCHSCAPE_GPU_CONCURRENCY` > 1 only after an approved benchmark; T4 stays at 1 | AGENT.md Hard Rule 5, step 27 | Done (docs) |
| N28 | Unknown whether SAM 3's interactive and semantic predictors can share one loaded model (VRAM) | Measure; lazy-load the interactive predictor if needed; record in step 27 | Step 27 | Verify |
| — | Fast-SAM3D's joint multi-mask mode is unverified | Baseline is one run per object; joint mode is an optional experiment | Step 27 | Verify |
| N13 | No per-user upload limits: uncapped GPU spend | User decision. The per-photo object cap (default 8) is only a safety bound | Steps 20, 26 | Accepted |
| N11 | Backend accepts JPEG/PNG/WebP only | HEIC converted in the browser or rejected; Notability PDF pages rendered to PNG in the browser | Steps 20, 28 | Planned |
| N12 | User text (labels, memory text, room prompt, letter notes) is untrusted | Plain-text rendering; length limits; delimited data for NemoClaw, never instructions | Steps 5, 20, 28; DATA_ARCHITECTURE | Planned |

## Identity and auth

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| N7 | Clerk has no Meta Quest login | Meta user proof on the headset → backend room token; one-time link code entered on the website | Steps 14, 18, 20 | Planned |
| N8 | Meta `GetUserProof` needs the Data Use Checkup; until approved only test users work | Register test users now; submit the DUC early if outsiders will use it | Steps 13, 25 | Verify |
| N14 | Link codes could be guessed | Hashed, single-use, 10-minute expiry, 5 attempts per user per 10 minutes | Step 18 | Planned |
| N22 | Polling the link flow with a Meta nonce each time wastes Meta server checks | Nonce-free `GET /v1/auth/meta/link-code/{code_id}/status` | Step 18 | Planned |
| N5 | NemoClaw needed its own identity | Clerk M2M token, `author = nemoclaw:<id>` | Steps 16, 24 | Done (identity, step 16) / Planned (room tools, step 24) |
| N9 | Clerk's Electron support is unofficial | Upload app is a React + Vite web app with `@clerk/react` | Steps 19–20, AGENT.md | Done (docs) |
| N10 | The "Export to Quest" screen ran a local script, which a web app can't do | Screen tells people to open the room in the Quest app; the export script stays a developer tool | AGENT.md | Done (docs) |
| 4.3 | Dev and prod identities differ | Separate dev/prod Clerk instances and Meta apps in the config matrix | Step 13, `collab-vr-accounts-and-gates` | Planned |
| 4.6 | Long-lived tokens on the headset | 1-hour backend room tokens, memory-only, refreshed via a fresh Meta proof | Steps 18, 23 | Planned |
| 4.1, 4.2, 4.4, 4.5 | Clerk OAuth browser login on the headset (redirect, `aud`, public client, device grant) | Headset uses the Meta account instead | — | Superseded |

## Networking and VR

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| 3.1 | Client-hosted Relay can't migrate the host: the room dies when the host leaves | Distributed Authority sessions (NGO 2.x) | Step 22 | Planned |
| 3.2 | Guides show deprecated Relay/Lobby packages and template 2.0.6 | `com.unity.services.multiplayer` and template 2.1 versions | Step 22 | Planned |
| 3.3 | Two people could start separate sessions for one room | `CreateOrJoinSessionAsync("room-<project_id>")` | Step 22 | Planned |
| 3.4 | Netcode client ↔ UGS player ↔ person mapping | Player property with the Clerk user id; backend stays the authority | Step 22 | Planned |
| N23 | `MaxPlayers = 8` was hard-coded | From the project's `max_contributors`; lists everywhere, never two | Step 22, AGENT.md | Done (docs) |
| N24 | A sealed letter's page could leak before it's opened | Page URL only for author and recipients until opened | Step 28 | Planned |
| 6.1 | Quest build settings | IL2CPP + ARM64, Vulkan, OpenXR Meta feature group, Internet = Require | Step 22 | Planned |
| 3.5, 6.2, 6.3 | DA quotas, Quest performance budgets, avatar/hand sync undocumented | Measure on two or more headsets; study template avatar prefabs | Step 25 | Verify |

## NemoClaw

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| 5.1 | The Unity MCP Extension documents no read or query operations | Read scene state from the backend (`compiled-scene`, room state); step 3 checks what Unity's base MCP exposes | `top-tier-nemoclaw-tool-design`, `nemoclaw-agent-setup` | Done (docs) |
| 5.2 | The MCP Extension edits the Editor, not live headsets | Live changes only via backend draft + approved publish | Step 24 | Done (docs) |
| 5.3 | MCP Extension is GitHub-only and "may vary by version" | Pin a commit or tag in `Packages/manifest.json` | Step 3, `nemoclaw-agent-setup` | Done (docs) |
| 5.4 | Dotted registry ids aren't valid tool names | snake_case callables mapped to registry ids | `top-tier-nemoclaw-tool-design` | Done (docs) |
| 5.5 | Approval differs between people and NemoClaw | Headset transform edits auto-save; NemoClaw publishes always need approval | Steps 23–24 | Done (docs) |
| N25 | `NEMOCLAW_MODEL_BACKEND=llama\|grok` was out of date | `NEMOCLAW_MODEL_PROVIDER=meta\|xai\|nebius` (Muse Spark / Grok / Nebius Token Factory), one OpenAI-compatible adapter | Step 3, `nemoclaw-model-providers` | Done (docs) |
| N21 | A skill told agents to delete any "Meta Muse" reference, which would remove the Muse Spark config | Only "Muse Image" image generation is rejected | `sketch-image-gen-backends`, `meta-track-alignment` | Done (docs) |
| — | Meta Model API is a US-only public preview | Grok or Nebius are switchable by env var | `nemoclaw-model-providers` | Accepted |

## Secrets and DevOps

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| N6 | Secrets could leak into the repo, the web bundle, or Unity | Gate script scans for Clerk/Meta/xAI keys, secret env assignments, and `VITE_*SECRET*`; `verify_local.sh` fails on a hit | `scripts/check_collab_gates.py` | Done (tested) |
| — | Agents could start a step before its prerequisites exist | `check_collab_gates.py` BLOCKED/READY, manual gates only the user confirms | AGENT.md Hard Rule 9 | Done |

## Suggested order

1. **Step 15** (backend revision safety) can start now; **step 26**
   follows it.
2. **Step 13** needs you:
   - Clerk app
   - Meta app with test users
   - Meta provider configured in Unity
3. **Step 14:** the Meta identity spike on a real Quest.
4. **Steps 1–2 → 16–18:** contributors, auth, linking.
5. **Steps 19–20:** the website (selection canvas, uploads, linking).
6. **Step 27:** GPU, with approval.
7. **Steps 21–23:** live room.
8. **Steps 28–29:** letters.
9. **Step 24:** NemoClaw room tools.
10. **Step 25:** verification on real devices.
