---
name: meta-quest-identity
description: Use for Build Plan step 14 (on-device spike proving Meta account identity on Quest - entitlement check, GetLoggedInUser, GetUserProof, SignInWithOculusAsync, server nonce validation) and step 18 (backend Meta identity exchange, backend room tokens, and linking a Quest's Meta account to a Clerk user with a code entered on the website).
---

# Meta account on the Quest, linked to Clerk (steps 14 and 18)

## Gate

`python3 scripts/check_collab_gates.py 14` (or `18`). BLOCKED means stop.

## Verified facts (2026-09-25)

- Meta Platform SDK: `Users.GetLoggedInUser()` returns the user's Meta ID;
  `Users.GetUserProof()` returns a **single-use** nonce.
- Server check: `POST https://graph.oculus.com/user_nonce_validate` with
  `access_token=OC|<APP_ID>|<APP_SECRET>`, `nonce`, `user_id` →
  `{"is_valid": true}`. The nonce is invalid after one check.
- `GetUserProof` requires Meta's **Data Use Checkup**. Until it's
  approved, only **test users** work. Community reports show
  `is_valid:false` when the app or user isn't set up on a release channel,
  so use test users on a release channel from day one.
- Unity Authentication has a built-in Meta Quest provider:
  `AuthenticationService.Instance.SignInWithOculusAsync(nonce, userId)`,
  configured with the Meta App ID and App Secret in the Unity dashboard.
- Meta IDs from `GetLoggedInUser` are app-scoped. If the team ever ships a
  second app, Meta provides an org-scoped ID lookup; not needed now.
- Meta does not give you the user's email, hence the explicit linking step.

## Step 14: on-device spike (a test scene in HackGTUnity)

1. Import the Meta Platform SDK (Meta XR SDK v78+ is already required for
   the MCP extension) and set the App ID (Meta > Platform > Edit Settings).
2. On start: initialize the platform, then run the **entitlement check**
   (required for Store apps). If it fails, quit gracefully.
3. `GetLoggedInUser()` → `userId`.
4. `GetUserProof()` **twice** → `nonceA`, `nonceB` (each works once).
5. `await UnityServices.InitializeAsync();`
   `await AuthenticationService.Instance.SignInWithOculusAsync(nonceA, userId);`
6. Log `nonceB` and `userId` in the development build only. The user runs
   the `curl` validation from their own shell with the secret in an env
   var. **Never** put the secret in a file, the Unity project, or chat.
7. Report results. Only the user sets `quest_meta_identity_spike_passed`.

## Step 18: backend exchange and linking (`backend/meta_identity.py`)

Environment (see the config matrix in `collab-vr-accounts-and-gates`):
`SKETCHSCAPE_META_APP_ID`, `SKETCHSCAPE_META_APP_SECRET`,
`SKETCHSCAPE_ROOM_TOKEN_SECRET`. If any is missing in `clerk` mode, the
Meta routes are disabled and the app **fails to start** when
`SKETCHSCAPE_META_ENABLED=true`. In `mock` mode, `validate_nonce` accepts
`mock-nonce` for any user id and makes no network call (Hard Rule 2).

### Store

Add to `AuthoringStore` (both backends):
- `META#<meta_user_id>` → `{clerk_user_id, linked_at}`. **Unique both
  ways**: a Meta ID links to one Clerk user, and a Clerk user to one Meta
  ID. Use conditional writes in DynamoDB (`attribute_not_exists`) and
  re-linking needs an explicit unlink first.
- `LINKCODE#<sha256(code)>` → `{meta_user_id, expires_at}` with DynamoDB
  TTL, deleted on use.

### Routes

1. `POST /v1/auth/meta/session` (headset) with body
   `{meta_user_id, nonce}`.
   - Validate the nonce with Meta (timeout 5 s; on Meta outage return 503,
     never allow sign-in).
   - Linked → return a **room token**: HS256 JWT signed with
     `SKETCHSCAPE_ROOM_TOKEN_SECRET`, `iss="sketchscape-api"`,
     `aud="sketchscape-room"`, `sub=<clerk_user_id>`, `meta=<meta_user_id>`,
     `exp` = 1 hour. Use PyJWT (add to requirements, pinned).
   - Not linked → 409 `{"link_required": true}`.
2. `POST /v1/auth/meta/link-code` (headset) with body
   `{meta_user_id, nonce}` (a fresh nonce).
   - Validate the nonce, then issue an **8-character code** from an
     unambiguous alphabet (no 0/O/1/I), valid 10 minutes, single use.
   - Store only its hash. Return the code, an opaque `code_id`, and the
     website URL to show in the headset.
   - **Polling:** `GET /v1/auth/meta/link-code/{code_id}/status` →
     `{status: "pending" | "linked" | "expired"}`. It needs no Meta nonce,
     which avoids a Meta server check on every poll. The headset polls
     every 5 s for up to 10 min, then on `linked` makes one
     `POST /v1/auth/meta/session` with a fresh nonce. The `code_id` only
     reveals status, never a token.
3. `POST /v1/auth/meta/link` (website, Clerk session) with body `{code}`.
   - Look up the hash; if expired or used → 400. Link the Meta ID to the
     caller's Clerk user.
   - Limit to 5 attempts per Clerk user per 10 minutes (429), to stop
     guessing.
4. `DELETE /v1/auth/meta/link` (website, Clerk session) unlinks the
   caller's Quest.
5. `GET /v1/auth/meta/link` (website) returns whether a Quest is linked.

`backend/auth.py` (step 16) gains a third verifier. A bearer token with
`aud=sketchscape-room` verified by the room secret gives
`Identity(kind="user", user_id=<clerk_user_id>, via="meta")`. It's
accepted only on `/v1/rooms/*`, artifact reads needed by the headset, and
`GET` project/room reads, never on website-only routes like linking.

Optional: mirror the link into Clerk `private_metadata.meta_user_id` via
the Clerk Backend API so the Clerk dashboard shows it. The backend store
stays the source of truth.

### Tests (`backend/test_meta_identity.py`, Meta HTTP stubbed)

- Valid nonce + linked → token with the right `sub`/`aud`/`exp`.
- Invalid nonce → 401. Meta timeout → 503.
- Unlinked → 409 `link_required`.
- The full link flow works. An expired code, a reused code, and the 6th
  attempt (429) all fail.
- A Meta ID can't be linked to two Clerk users.
- A room token is rejected on `/v1/auth/meta/link`, and a tampered token
  is rejected.
- Boot fails when Meta is enabled without its secrets.

## Definitions of done

- 14: the user confirms the device spike, and `--done 14` passes.
- 18: `--done 18` and `bash scripts/verify_local.sh` pass.

## Sources

- https://developers.meta.com/horizon/documentation/unity/ps-ownership/
- https://developers.meta.com/horizon/resources/publish-data-use/
- https://docs.unity3d.com/Packages/com.unity.services.authentication@3.2/api/Unity.Services.Authentication.IAuthenticationService.SignInWithOculusAsync.html
- https://communityforums.atmeta.com/discussions/dev-unity/s2s-getuserproof-is-validfalse-understanding-platform-sdk-integration-and-releas/987062
