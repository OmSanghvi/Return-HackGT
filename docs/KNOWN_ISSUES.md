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
| 2.1 | No authentication on any route | The `X-SketchScape-Dev-User` account header, restricted to the two hardcoded accounts in `demo` mode, verified server-side with real membership/ownership enforcement; used by the web app and headsets alike (R13 — no Clerk, no Meta room tokens); fail-fast config | Step 16; `backend-auth-clerk` | Done |
| 2.2 | No base-revision check: stale saves silently erase newer edits | `based_on_revision` = live revision; 409 when stale; clients rebase their own objects | Step 15, `backend-revision-concurrency` | Done |
| 2.3 | DynamoDB `put_item` without condition and a per-process lock: revisions overwrite each other | `attribute_not_exists(sk)` on blueprint and publication appends, with retry | Step 15 | Done |
| N2 | Whole-blob `ProjectRecord` saves let the live room go backwards | Compare-and-set `LIVE` pointer item | Step 15 | Done |
| N3 | An unapproved NemoClaw draft could get published by a room edit | Edits copy the live revision; publish is compare-and-set on `based_on_revision` | Steps 15, 21 | Done (compare-and-set publish, step 15) / Planned (room edits copy live, step 21) |
| 2.4 | One process-wide `current_scene` for all projects | Rooms read per-project live state only; room routes never touch `current_scene` | Steps 15, 21 | Done (per-project LIVE pointer, step 15) / Planned (room routes, step 21) |
| 2.5 | No ownership: "edit only your own object" is unenforced (Netcode check is client-side) | Contributors bound to one of the two hardcoded accounts; ownership derived from contributions; server returns 403 | Steps 17, 21; `room-api-and-ownership` | Done (ownership helper + membership, step 17) / Planned (room `/edits`, step 21) |
| 2.6 | No partial updates; every save is a full blueprint | Debounced save on release; bounded, idempotent `/v1/rooms/*/edits` builds the revision server-side | Steps 21, 23 | Planned |
| 2.7 | No push channel to live rooms | Session owner polls `/v1/rooms/{id}/state?since_revision=` with ETag/304 | Step 23, DATA_ARCHITECTURE polling contract | Planned |
| 2.8 | No author on revisions | `author` on revisions and publications (the hardcoded account id, `nemoclaw:<id>` for services) | Steps 15, 16 | Done |
| N1 | Headsets calling authoring routes breaks Hard Rule 4 | Public room API `/v1/rooms/*`; Hard Rule 4 updated | Step 21, AGENT.md | Done (docs) / Planned (code) |
| N4 | Mock auth could reach the cloud | Backend refuses to start: mock + DynamoDB or non-mock pipeline; clerk without secret or with `*` origins | Step 16 | Done |
| N15 | Reconstruction jobs live in an in-memory dict: lost on restart, polls fail across instances | Durable lease-based jobs in the store | Step 26, `durable-jobs-and-multi-object-upload` | Done |
| N16 | Uploads stored on one API host's disk | S3 `uploads/` in cloud, disk locally | Step 26 | Done |
| N17 | `asset_ids` appended inside the project blob; simultaneous uploads lose assets | Project→asset child items | Step 26 | Done |
| N20 | DynamoDB table has no GSIs or TTL (needed for "my projects", job queue, edit-idempotency expiry) | GSI1, GSI2, TTL via Terraform; the backend refuses to start without them | DATA_ARCHITECTURE.md, step 26 | Planned (needs approval to apply) |
| N27 | The browser shows photos EXIF-rotated but the server's pixels aren't, so object selections would land in the wrong place | Server applies `exif_transpose` on upload; the canvas draws the stored image; coordinates are normalized 0–1 | Step 26, `web-uploads-and-linking` | Done (server EXIF + normalized coords, step 26) / Planned (canvas, step 20) |

## Uploads, GPU, and SAM 3.1

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| N18 | Worker handles one job and one mask per image (queue size 1, `choose_one`, 429 when busy) | The person types a name for each object on the website → one SAM 3.1 semantic pass per photo → one Fast-SAM3D job per chosen object via a leased dispatcher | Steps 26–27, `gpu-multi-object-worker` | Planned |
| N19 | Hard Rule 5 said "T4 16 GB", but the verified GPU is an L40S (45 GB) and Terraform still defaults to a T4 | Rule rewritten: sequential within a job; `SKETCHSCAPE_GPU_CONCURRENCY` > 1 only after an approved benchmark; T4 stays at 1 | AGENT.md Hard Rule 5, step 27 | Done (docs) |
| N28 | Superseded 2026-09-26: object selection is text-only (semantic predictor only), so there's no interactive predictor to share memory with | — | Step 27 | Superseded |
| — | Fast-SAM3D's joint multi-mask mode is unverified | Baseline is one run per object; joint mode is an optional experiment | Step 27 | Verify |
| N13 | No per-user upload limits: uncapped GPU spend | User decision. The per-photo object cap (default 8) is only a safety bound | Steps 20, 26 | Accepted |
| N11 | Backend accepts JPEG/PNG/WebP only | HEIC converted in the browser or rejected; Notability PDF pages rendered to PNG in the browser | Steps 20, 28 | Planned |
| N12 | User text (labels, memory text, room prompt, letter notes) is untrusted | Plain-text rendering; length limits; delimited data for NemoClaw, never instructions | Steps 5, 20, 28; DATA_ARCHITECTURE | Planned |

## Identity and auth

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| N7 | Superseded by R13: Clerk has no Meta Quest login | — no longer applies, there's no Meta Quest login to have | Steps 14, 18 (retired) | Superseded |
| N8 | Superseded by R13: Meta `GetUserProof` needs the Data Use Checkup | — no longer applies, no `GetUserProof` call in the plan | Step 13 (retired scope) | Superseded |
| N14 | Superseded by R13: link codes could be guessed | — no longer applies, there's no link-code flow | Step 18 (retired) | Superseded |
| N22 | Superseded by R13: polling the link flow wasted Meta server checks | — no longer applies | Step 18 (retired) | Superseded |
| N29 | Superseded by R13: this row created step 30 (a single-headset demo carve-out for the room API and letters) because steps 21/28/29 were gated behind the Clerk/Meta plan (13/14/18) | R13 retired the Clerk/Meta plan outright, so there's no separate "real" path to carve out from — step 30 was merged back into steps 21 and 28, which now depend only on already-done steps | R13; `docs/BUILD_PLAN.md`, `collab-vr-accounts-and-gates` | Superseded |
| N5 | Superseded by R13: NemoClaw needed its own identity via Clerk M2M | A shared bearer token (`SKETCHSCAPE_NEMOCLAW_TOKEN`, R14) instead, matching `SKETCHSCAPE_WORKER_TOKEN`; `author = nemoclaw:<id>` unchanged | R14; Steps 16, 21, 24 | Done (R14, token built) / Planned (room tools, step 24) |
| N9 | Moot after R13: Clerk's Electron support is unofficial | Upload app is a React + Vite web app with an account picker (no Clerk at all now) | Steps 19–20, AGENT.md | Done (docs) |
| N10 | The "Export to Quest" screen ran a local script, which a web app can't do | Screen tells people to open the room in the Quest app; the export script stays a developer tool | AGENT.md | Done (docs) |
| 4.3 | Superseded by R13: dev and prod Clerk/Meta identities would differ | — no longer applies; `SKETCHSCAPE_DEMO_USERS` can differ per env if ever needed, but nothing requires it | Step 13 (retired scope) | Superseded |
| 4.6 | Superseded by R13: long-lived tokens on the headset | — no longer applies; the account header has no expiry to manage | Step 18 (retired) | Superseded |
| 4.1, 4.2, 4.4, 4.5 | Clerk OAuth browser login on the headset (redirect, `aud`, public client, device grant) | Headset uses the Meta account instead | — | Superseded |

## Networking and VR

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| 3.1 | Client-hosted Relay can't migrate the host: the room dies when the host leaves | Distributed Authority sessions (NGO 2.x) | Step 22 | Planned |
| 3.2 | Guides show deprecated Relay/Lobby packages and template 2.0.6 | `com.unity.services.multiplayer` and template 2.1 versions | Step 22 | Planned |
| 3.3 | Two people could start separate sessions for one room | `CreateOrJoinSessionAsync("room-<project_id>")` | Step 22 | Planned |
| 3.4 | Netcode client ↔ UGS player ↔ person mapping | Player property with the hardcoded account id; backend stays the authority | Step 22 | Planned |
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

## Feasibility review (2026-09-26)

A read-only review of the backend, the GPU pipeline, and the plans
(steps 13–30) against the code. `bash scripts/verify_local.sh` passed with
152 tests (2 skipped). Doc fixes below are already applied; code issues
are open.

| # | Issue | Fix | Where | Status |
| --- | --- | --- | --- | --- |
| R1 | The demo account switcher was unbuildable before step 13 under the project's own gates (see N29) | New step 30 carve-out, gate entry and manual gate; step 21/29 done-checks tightened; Hard Rule 4 exception written. **Superseded by R13**: step 30 was later merged back into steps 21/22/28 when the whole Clerk/Meta plan was retired | BUILD_PLAN, `check_collab_gates.py`, `gates.json`, AGENT.md, skills | Superseded by R13 |
| R2 | CORS allows only `GET`/`POST`, but the API has `PATCH /v1/projects/{id}` (step 17) and `DELETE .../selections/{id}` (step 26); a browser on another origin (the step 19–20 web app) fails preflight. `TestClient` doesn't do preflight, so tests miss it | Add `PATCH` and `DELETE` to `allow_methods`, plus a browser-preflight test | `backend/main.py:563` | Open (code) — fix before step 19 |
| R3 | Test count "106" was stale in AGENT.md, backend/README.md, PROJECT_STATUS.md | Updated to 152 | those files | Done (docs) |
| R4 | Step 15 and 26 rows here still said "Planned" | Statuses updated (2.2, 2.3, N2, N3, 2.4, N15, N16, N17, N27) | this file | Done (docs) |
| R5 | `backend/worker_contract.json` described `input_job_id` and `*_path` string fields; the real callback is a `result` JSON (`status`, `object_label`, `error`) plus multipart `ply`/`mask`/`preview` files | Schema rewritten to match `WorkerResult` and the route | `backend/worker_contract.json` | Done (docs) |
| R6 | PIPELINE_PLAN.md, AGENT.md, and DATA_ARCHITECTURE.md still described in-memory jobs / missing GSIs | Durable jobs are done; GSIs and TTL are written in Terraform but not applied; the worker is still push-based (nothing calls `/v1/internal/jobs/claim`) | those files | Done (docs) |
| R7 | Docs said the worker returns 429 on a second job; with `Queue(maxsize=1)` one job runs, one waits, and the **third** gets 429 | Docs corrected; step 27's dispatcher replaces this model anyway | `worker/README.md`, `gpu-multi-object-worker` | Done (docs) |
| R8 | Superseded 2026-09-26: object selection is text-only now (decision: typed name only, no click/box), matching the semantic-only path `segment_sam31_local.py`/`bootstrap_sam31_local.sh` already have — there's no interactive predictor left to verify | — | Step 27 | Superseded |
| R9 | `--done 30` checked that `test_demo_room.py` exists but not what it covers, so the "demo header never works in `clerk` mode" property relied on that test file's content | Moot: step 30 was merged into steps 21/28 (R13), which have their own test requirements in `room-api-and-ownership`/`letters-backend-and-web` | `collab-vr-accounts-and-gates` | Superseded by R13 |
| R10 | Clerk M2M tokens are billed per create/verify since March 2026 | Negligible at demo volume; note when step 24 goes live | Step 24 | Accepted |
| R11 | Hackathon timeline: steps 13, 14, 18 needed dashboard work or on-device testing that wasn't scheduled | **Superseded by R13**: 13/14/18's Clerk/Meta scope is retired, so 19–29 no longer wait on it — only step 22 still needs a linked Unity Cloud project, and steps 3/27 still need their own manual gates | BUILD_PLAN | Superseded by R13 |
| R12 | Decision (user, 2026-09-26): object selection is **text-only** — a person types a name for each object; there is no click-to-include/exclude and no drag-a-box. Simpler UI, and it matches the only segmentation code this repo has ever run (`SAM3SemanticPredictor`, text prompts) | `SelectionPrompt`/`RefineSelectionRequest` now hold just `text`; `render_mock_mask`/`validate_selection_prompt` simplified to match; mock mask is always a centered ellipse | `backend/main.py`, `backend/upload_pipeline.py`, `backend/test_jobs.py`; steps 20, 26, 27 and their skills; N18, N28 (superseded), R8 (superseded) | Done |
| R13 | Decision (user, 2026-09-26): the two hardcoded `demo` accounts are the **real, permanent identity model** for the Collaborative VR track, not a temporary stand-in for Clerk/Meta account setup. Clerk sign-in, Meta account linking, and room tokens are off the plan | Steps 13/14/18's Clerk/Meta scope retired (13 keeps only its scope-approval gate); 19's web app uses an account picker, not `@clerk/react`; 21's room API and 22's Unity session use the hardcoded-account header/player-property instead of room tokens; step 22's Unity sign-in is anonymous (`SignInAnonymouslyAsync`) rather than forbidden-outside-offline-fallback; the earlier step 30 carve-out is retired — its content is just steps 21/28/22 now, since there's no separate "real" path to carve out from | `docs/BUILD_PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DATA_ARCHITECTURE.md`, `collab-vr-accounts-and-gates`, `meta-quest-identity`, `unity-cloud-collaborative-vr`, `web-app-foundation`, `web-uploads-and-linking`, `room-api-and-ownership`, `letters-backend-and-web`, `letters-vr-envelope`, `vr-edit-cloud-backprop-sync`, `backend-auth-clerk`, `top-tier-nemoclaw-tool-design`, `scripts/check_collab_gates.py`, `config/collab-vr/gates.json`, AGENT.md | Done (docs + gates) |
| R14 | R13's removal of Clerk leaves NemoClaw (step 24) with no service identity: `kind="service"` in `backend/auth.py` is only ever produced by a Clerk M2M token today | Added a shared bearer token, `SKETCHSCAPE_NEMOCLAW_TOKEN` (≥32 chars, checked with `secrets.compare_digest`, fail-fast at startup if shorter), matching the existing `SKETCHSCAPE_WORKER_TOKEN` pattern. Checked before the `SKETCHSCAPE_AUTH_MODE` dispatch in `require_identity`, giving `Identity(kind="service", via="nemoclaw", user_id="nemoclaw:<id>")`. NemoClaw can read `GET /v1/rooms/{id}/state`, a project's asset list, and artifact bytes (`GET /v1/artifacts/{job_id}/{filename}`) with this token, and can draft a blueprint revision, but `require_project_write` still 403s it on `POST /v1/rooms/{id}/edits` and on publish — no direct write to LIVE | Built alongside step 21 (not a separate step-16 follow-up); `backend/auth.py`, `backend/main.py`, `backend/test_auth.py`, `backend/test_api.py` | Done (code); NemoClaw itself (step 3) still hasn't started, so nothing calls this token in production yet |
| R15 | `SKETCHSCAPE_AUTH_MODE=clerk` and its code in `backend/auth.py` are no longer part of the plan (R13) but are left in place, tested, and still scanned for leaked Clerk keys | Nothing to fix — a deliberate choice, not an oversight. Don't build new work against `clerk` mode, and don't delete it either | `backend/auth.py`, `backend/test_auth.py`, `backend-auth-clerk` | Accepted |

## Suggested order

(Revised by R13 — steps 14 and 18 are retired, and step 13 now needs only
your scope approval, already given.)

1. **Steps 1–2, 15, 16, 17, 26** are done (contributors, backend revision
   safety, auth, membership/ownership, durable jobs).
2. **Steps 19–20:** the website (account picker, selection canvas,
   uploads).
3. **Step 21:** the room API + the account switcher's backend half.
4. **Step 22:** Unity networking (anonymous sign-in + account switcher,
   Distributed Authority). Needs a linked Unity Cloud project only.
5. **Step 27:** GPU, with approval.
6. **Step 23:** live room backprop.
7. **Steps 28–29:** letters.
8. **Step 24:** NemoClaw room tools (R14's `SKETCHSCAPE_NEMOCLAW_TOKEN` is
   already built; step 24 still waits on step 3, NemoClaw's own runtime).
9. **Step 25:** verification on real devices.
