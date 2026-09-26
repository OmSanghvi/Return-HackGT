---
name: vr-edit-cloud-backprop-sync
description: Use for Build Plan step 23 — "backprop" in HackGTUnity. After a live edit settles on one headset, save it through POST /v1/rooms/{project_id}/edits with the headset's room token, and have the session owner pull in revisions published from outside the session (web approvals of NemoClaw proposals, other clients). Live replication itself is step 22.
---

# VR edit → cloud backprop (step 23)

## Gate

`python3 scripts/check_collab_gates.py 23` (needs 21 and 22). BLOCKED means stop.

## Two layers

| Layer | Job | How | When |
| --- | --- | --- | --- |
| Live (step 22) | Others see the edit now | Distributed Authority, owner-authoritative transform, `Network Grab Interactable` | Every tick while held |
| Durable (this step) | Room survives everyone leaving | `POST /v1/rooms/{project_id}/edits` | Once, after the edit settles |

**Never call the backend per frame while an object is held.**

## Room token lifecycle

- Get a token from `POST /v1/auth/meta/session` with a fresh
  `GetUserProof` nonce. It lasts 1 hour.
- Refresh it about 5 minutes before expiry the same way, with a new nonce
  each time.
- On any 401, refresh once and retry. If that fails, go to the signed-out
  / relink state.
- Keep the token in memory only. Never log it, write it to disk, or put it
  in `PlayerPrefs`.

## Upstream: saving a settled edit

1. **Trigger:** the grab is released, then debounce 1.5 s per object.
   Another nudge inside the window resets the timer.
2. **Who saves:** the person who made the edit, with their own room token.
   The backend needs that identity to enforce ownership, so this isn't
   done by the session owner.
3. Request fields:
   - `base_revision` = last known live revision.
   - `client_edit_id` = a new UUID per save. **Reuse it on network
     retries.**
   - Absolute `position`/`rotation`/`scale` for the edited objects only.
4. Responses:
   - 201 → store the new `live_revision`.
   - 409 → `GET /state`, re-apply only your own objects' current
     transforms, and retry (max 3). Then show an unobtrusive "not saved"
     and try again on the next release.
   - 401 → refresh the token once.
   - 403/422 → don't retry. Snap the object back to its last saved
     transform and log it. The ownership guard or allowlist should have
     prevented it.
   - Network error → retry with the same `client_edit_id`, with backoff.
     The server de-duplicates it.
5. Clamp locally before sending (position ±100, scale 0.05–20).

## Downstream: outside changes reaching a running room

Outside changes include NemoClaw proposals approved on the website and
edits from other sessions.

- Only the **session owner** polls
  `GET /v1/rooms/{project_id}/state?since_revision=<live>` every 3 s with
  `If-None-Match`. A `304` means nothing changed: no body, no work. The
  role migrates with DA ownership. On `429`/`503`, honor `Retry-After`.
  The contract is in `docs/DATA_ARCHITECTURE.md`.
- The state also covers **letter open states** (step 28). A letter opened
  from another session plays its open animation (step 29).
- If `live_revision` is newer and this session didn't write it, apply the
  changed transforms. **Skip objects someone is holding.** Spawn or
  despawn objects that were added or removed; failed reconstructions are
  simply absent (Hard Rule 7).
- New sessions always build from `/state`.

## Why not Unity Cloud Save

Its shared custom-ID items are server-write-only, so it would need extra
server code and create a second source of truth. Hard Rule 6 keeps
published blueprint revisions as the truth.

## Approval boundary

- A person's own transform edits from the headset publish automatically:
  they're cheap, owner-checked, and every earlier revision stays
  restorable.
- NemoClaw publishes always need a person's approval on the website
  (`blueprint.publish`, `approval_required: true`).
- New objects and GPU work never come from this path.

## Definition of done

`--done 23` passes, and:
1. A moves an object; B sees it live; after both leave, a new session
   shows A's final position.
2. A and B move their own objects in the same second; both survive.
3. Wi-Fi off mid-save, then on → exactly one revision.
4. The room token refreshes without interrupting the session.
5. A NemoClaw proposal approved on the website appears in the running
   room within about 5 s.
