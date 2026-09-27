# Web → Quest pipeline — contract (2026-09-27)

Two people (the two hardcoded accounts) share a project on the web app, upload
photos with personal notes, and write each other sealed letters. The GPU host
reconstructs everything. One of them presses **Build room in VR**. A runner on
the Unity machine has NemoClaw (Muse Spark) build the immersive room in
HackGTUnity through Unity MCP. In the room, an **Account 1 / Account 2**
switcher shows each person's notes and the letters they may open. (An Android
APK was planned and then dropped by the user; see §6.)

This file is the binding contract between the parts built on 2026-09-27. The
photo → room part it builds on is `docs/IMMERSIVE_SCENE_PIPELINE.md`. Change an
interface here only together with every consumer.

Scope decided by the user on 2026-09-27: the Quest app is the HackGTUnity room
(not the team's `unity/` hub); one headset, with an in-world account switcher
(multi-headset networking, Build Plan step 22, is out of scope); rooms reach
the Quest as an APK. The in-world guide agent is out of scope. The user also
said this work may contradict `AGENT.md` (its step gates and hard rules don't
bind it). Kept anyway: no secrets in files, commits, command arguments, chat or
logs; the web app's mock mode keeps working; tests stay green.

## 0. Hosts, identities, addresses

- **API**: EC2 `i-05f7fe9fc8d8da00a`, Elastic IP `http://100.63.32.83:8000`.
  HTTPS through the web app's proxy: `https://returnweb-hazel.vercel.app/api/<path>`
  (`web-app/vercel.json` rewrite). Unity and the Quest default to the HTTPS
  base (Android blocks cleartext HTTP); both bases must work.
- **Accounts**: `demo-alice` = "Account 1", `demo-bob` = "Account 2", sent as
  `X-SketchScape-Dev-User` (backend `SKETCHSCAPE_AUTH_MODE=demo`).
- **Runner identity**: `Authorization: Bearer <SKETCHSCAPE_NEMOCLAW_TOKEN>`
  (`backend/auth.py`, kind `"service"`). On the Unity machine the token lives
  in `%USERPROFILE%\.config\sketchscape\room-runner-token` (one line, created by
  the backend work, user-only). Never print, log or commit it.
- **Unity Editor lock**: `%LOCALAPPDATA%\SketchScape\unity-editor.lock`, JSON
  `{"owner": "...", "since": "<ISO time>"}`. Whoever drives the open HackGTUnity
  Editor (the runner during a NemoClaw build, an agent testing in the Editor)
  creates it first and deletes it when done. A lock older than 60 min is stale
  and may be removed.

## 1. Room builds (backend)

A room build is a request to turn a project's photos into a VR room.

`RoomBuild` = `{"build_id", "project_id", "requested_by", "prompt", "scene_id",
"status", "message", "slug", "scene_path", "apk_path", "runner_id",
"created_at", "updated_at"}` (strings; `""` when unknown).

Status: `requested` → `claimed` → `syncing` → `building` → `packaging` →
`ready` | `failed`. At most one non-terminal build per project (409 otherwise).
A claimed build whose runner stops reporting for 30 min goes back to
`requested`.

Member routes (demo account header; project membership enforced):
- `POST /v1/projects/{project_id}/room-builds` body `{"prompt"?: str (≤ 1000),
  "scene_id"?: upload_id}` → 201 `RoomBuild`. Default `scene_id` = the
  project's newest upload that has a stored scene (`scene_key`); 409 if none.
- `GET /v1/projects/{project_id}/room-builds` → `[RoomBuild]`, newest first (≤ 20).
- `GET /v1/projects/{project_id}/room-builds/{build_id}` → `RoomBuild`.

- `POST /v1/projects/{project_id}/room-builds/{build_id}/cancel` → the build
  ends `failed` with "Cancelled by <account>".
- 409: no stored scene, or a build is already active (the message names it);
  422: unknown `scene_id` or a prompt over 1000 chars.

Runner routes (service token):
- `POST /v1/internal/room-builds/claim` body `{"runner_id"}` → 200 `RoomBuild`
  (the oldest `requested`, now `claimed`) or 204 when none.
- `POST /v1/internal/room-builds/{build_id}/status` body `{"runner_id",
  "status", "message"?, "slug"?, "scene_path"?, "apk_path"?}` → 200 `RoomBuild`
  (409 if another runner holds it; terminal states are final).
- Forward jumps are allowed; re-posting the same status is a heartbeat (the
  runner sends one every 4 min with a progress `message`); an identical
  terminal report is a no-op 200. A dry run (`--no-agent`) ends `ready` with an
  empty `scene_path` and a message starting "Dry run": offer a room only when
  `scene_path` is set.

Personal notes: an upload carries an optional `note` (multipart form field on
`POST /v1/projects/{p}/uploads`; editable by its uploader with
`PATCH /v1/projects/{p}/uploads/{u}` `{"note"}`).

### 1b. The headset's view: `GET /v1/rooms/{project_id}/shared`

One call gives a headset (or the runner's snapshot) everything the shared layer
shows, **as seen by the account in `X-SketchScape-Dev-User`**. It needs no
published blueprint. Shape (JsonUtility-friendly: no nulls, no dicts, no nested
arrays; `""` / `false` / `[]` when empty):

```json
{"project_id": "...", "title": "...", "viewer": "demo-alice", "viewer_label": "Account 1",
 "accounts": [{"id": "demo-alice", "label": "Account 1", "display_name": "...", "color": "#e8a33d"},
              {"id": "demo-bob", "label": "Account 2", "display_name": "...", "color": "#4aa3df"}],
 "notes": [{"note_id": "...", "author": "demo-bob", "text": "...", "upload_id": "...",
            "asset_ids": ["..."], "created_at": "..."}],
 "letters": [{"letter_id": "...", "author": "demo-alice", "recipients": ["demo-bob"], "title": "...",
              "sealed": true, "can_open": false, "opened": false,
              "body": "", "texture_url": ""}],
 "objects": [{"asset_id": "...", "label": "...", "contributor": "demo-bob", "editable_by_me": false}],
 "latest_build": {"build_id": "", "status": "", "slug": "", "scene_path": "", "apk_path": ""}}
```

- `notes` = the personal text each person attached to their uploads/contributions.
- `letters`: `body` and `texture_url` (`/v1/projects/{p}/letters/{id}/texture`)
  are filled only when the viewer may read the letter (author, or a recipient
  who opened it). A recipient opens with the existing
  `POST /v1/rooms/{p}/letters/{id}/open`. Everyone sees that a letter exists and
  who it is for.

## 2. Runner (`scripts/room_build_runner.py`, Unity machine)

Loop: claim → `syncing`: `python scripts/sync_s3_assets_to_unity.py
--project-id <p>`, then write the shared snapshot (§4) → `building`: take the
Editor lock, redeploy the sandbox skills (`bash scripts/nemoclaw-deploy-skills.sh`
in WSL), run the agent (`nemoclaw sketchscape agent --agent main --session-id
room-build-<build_id> -m "<prompt>"`; the prompt names the scene id, the room
name and the person's prompt), confirm the scene file exists, release the lock
→ `ready` with `slug` and `scene_path` (`apk_path` stays `""`: no Android APK,
user decision 2026-09-27; the `packaging` status is unused); any failure →
`failed` with a short `message`. One build at a time; `--once` runs a single
claim; logs to `%LOCALAPPDATA%\SketchScape\room-runner.log`.

## 3. Room spec `shared` block (compose_room → RoomKit)

Added to the room spec (`docs/IMMERSIVE_SCENE_PIPELINE.md` §5) when the scene
belongs to a project. JsonUtility-safe (no nulls, nested arrays or dicts):

```json
"shared": {"enabled": true, "project_id": "...",
           "api_base": "https://returnweb-hazel.vercel.app/api",
           "accounts": ["demo-alice", "demo-bob"], "labels": ["Account 1", "Account 2"],
           "default_account": "demo-alice", "snapshot_resource": "SharedSnapshots/<project_id>"}
```

`{"enabled": false, ...}` (all strings empty, arrays empty) when there is no project.

## 4. Shared snapshot (offline copy in the APK)

The runner writes it into HackGTUnity after syncing and before the agent builds:
`Assets/SketchScape/Resources/SharedSnapshots/<project_id>.json`, plus each
readable letter page as `Assets/SketchScape/Resources/SharedSnapshots/<project_id>/<letter_id>.png`.
Because it sits under `Resources/`, the player loads it on the device with
`Resources.Load` (`"SharedSnapshots/<project_id>"`); `Assets/` paths don't exist
there. The Quest uses it when the API is unreachable. It holds, per account,
**exactly the `/v1/rooms/{p}/shared` response for that account** (never a
letter body the account couldn't read):

```json
{"version": 1, "project_id": "...", "fetched_at": "<ISO>",
 "views": [{"account": "demo-alice", "shared": { ...GET /v1/rooms/{p}/shared as demo-alice... }},
           {"account": "demo-bob",   "shared": { ...as demo-bob... }}]}
```

## 5. VR shared layer (HackGTUnity, RoomKit)

RoomKit builds a `SharedRoom` rig when `shared.enabled`:
- **Account switcher**: a world-space "Account 1 / Account 2" control near the
  spawn point, usable with hands (poke) and controllers (ray). The choice
  persists (PlayerPrefs) and drives every request header.
- **Personal notes**: each contributor's upload note, shown diegetically (a card
  or sheet of paper) next to their reconstructed objects, or on a notes board by
  the spawn when the object isn't separate. It carries the author's label and a
  colour per account.
- **Data**: `GET /v1/rooms/{p}/shared` (§1b) as the current account; the
  snapshot (§4) when offline.
- **Letters**: sealed envelopes for the letters in the view. Only a recipient
  can open one (`POST /v1/rooms/{p}/letters/{id}/open`, then re-read the view);
  it unfolds into a textured paper page (`texture_url`, else the `body` text).
  Switching accounts updates which envelopes can be opened.
- **Attribution**: a small diegetic tag per object with its contributor.
- Live data first, snapshot (§4) when offline. No floating 2D UI panels.
- `RoomKit.Build` refreshes the AssetDatabase first, so freshly synced scans import.

## 6. Quest APK — dropped

The user decided on 2026-09-27: no Android APK. Rooms stay in the HackGTUnity
Editor (built by NemoClaw through Unity MCP); `apk_path` is always `""`. The
shared layer must still run on Quest hardware (hands and controllers, no Editor
APIs in runtime code), since the room can be viewed on a headset without an APK.

## 7. GPU pipeline hardening

- The dispatcher never claims a job while the worker or SAM 3.1 isn't ready, and
  releases a claimed job at once if handing it over fails:
  `POST /v1/internal/jobs/{job_id}/release` (form `worker_id`, `worker_token`,
  `reason`) → `{"released": bool}`; only the lease owner of a running job can
  release it, and `attempts` is not incremented. The claim route also sweeps
  expired job leases (at most once a minute, `SKETCHSCAPE_LEASE_SWEEP_SECONDS`),
  so a job leased by a dispatcher that died is found again.
- Segmentation uses each selection's VLM box to pick the SAM 3.1 instance.
- The host keeps its disk healthy: old job folders and stale scene-cache
  entries are cleaned.

## 8. Running it

- Runner (Unity machine, Editor open): `.\scripts\Start-SketchScape.ps1 -Runner`,
  or `python -u scripts\room_build_runner.py` (flags: `--once`, `--no-agent`,
  `--skip-deploy`, `--api`, `--lock-wait-minutes`, `--agent-timeout`; logs in
  `%LOCALAPPDATA%\SketchScape\room-runner.log` and `room-builds\<id>\`).
- HackGTUnity has Player → Run In Background on, so Play mode keeps running when
  the Editor window isn't focused.
