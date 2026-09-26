---
name: unity-cloud-collaborative-vr
description: Use for Build Plan step 22 — adding live networking to HackGTUnity so one person's grab/move/rotate/scale shows on every other Quest in real time. Meta account sign-in (Platform SDK + SignInWithOculusAsync), Unity Multiplayer Services sessions with Distributed Authority, Netcode for GameObjects 2.x, XR Interaction Toolkit, and Unity's VR Multiplayer Template 2.1.
---

# Collaborative VR networking in HackGTUnity (step 22)

Verified against Unity and Meta docs, Sept 2026.

## Gate

`python3 scripts/check_collab_gates.py 22` (needs 13 and 14). BLOCKED means
stop. Networking without proven Meta sign-in means rewriting the
connection flow later.

## Starting point (checked)

- `HackGTUnity`: Unity **6000.2.10f1**, XRI 3.0.11, XR Management 4.5.1,
  OpenXR 1.15.1.
- Linked to a Unity Cloud project.
- **No Netcode and no Multiplayer Services yet.**

## Decisions

- **Sign-in:** Meta account on the headset. Initialize the Meta Platform
  SDK, run the entitlement check, then `GetLoggedInUser()` and
  `GetUserProof()`, then
  `AuthenticationService.Instance.SignInWithOculusAsync(nonce, userId)`.
  Fetch a **separate** nonce for the backend room token (step 18); each
  nonce works once. Never call `SignInAnonymouslyAsync` except in the
  offline fallback.
- **Distributed Authority (DA), not client-hosted Relay.** Unity doesn't
  support host migration for Netcode for GameObjects in client-hosted
  Relay sessions, so the room would close whenever the host left. DA keeps
  the session up and migrates the session-owner role. It needs NGO **2.x**.
- **VR Multiplayer Template 2.1** (`com.unity.template.vr-multiplayer`,
  Unity 6+, Quest 2/3/Pro, DA by default) is the reference. It includes
  `XRI Network Game Manager`, `XRI Network Player Avatar`,
  `Network Grab Interactable`, `Client Network Transform`,
  `Network Billboard`, and Vivox.
- Create a scratch project from the template **outside the repo**, port
  its networking prefabs and scripts into `HackGTUnity`, and use the same
  package versions as the scratch project's `Packages/manifest.json`.
  Template 2.0.6 is older (NGO 1.8, Lobby/Relay, no DA); don't copy from it.
- The standalone Relay and Lobby packages are deprecated in Unity 6. Use
  `com.unity.services.multiplayer`.

## Build

1. Install `com.unity.services.multiplayer` and
   `com.unity.netcode.gameobjects` 2.x. Keep XRI/OpenXR as they are unless
   the template needs newer; if so, upgrade in its own commit and re-test
   the existing scene first.
2. Sign in: Meta → UGS (above), and Meta → backend room token
   (`POST /v1/auth/meta/session`).
   - On 409 `link_required`: call `/v1/auth/meta/link-code` and show the
     code and website URL as in-world text. Poll
     `GET /v1/auth/meta/link-code/{code_id}/status` every 5 s (no nonce).
     On `linked`, call `/session` once with a fresh nonce.
3. One live session per Shared Room:
   ```csharp
   // Any number of people: size the session from the project, never a hard-coded 2.
   var options = new SessionOptions { MaxPlayers = project.MaxContributors }.WithDistributedAuthorityNetwork();
   var session = await MultiplayerService.Instance.CreateOrJoinSessionAsync($"room-{projectId}", options);
   ```
   Check the SDK reference for your installed version's session id limits.
4. Each client sets a player property with its Clerk user id (the room
   token's `sub`) on join. That maps Netcode clients to contributors.
5. Build the room from `GET /v1/rooms/{project_id}/state` (step 21), with
   `Authorization: Bearer <room token>`. Each object becomes a networked
   object with an owner-authoritative transform and
   `Network Grab Interactable`. Fetch artifacts with the same token.
6. **Ownership guard:** set objects to `OwnershipStatus.RequestRequired`.
   In `OnOwnershipRequested`, allow only when `editable_by_me` for the
   requester. This is a client-side UX guard; the backend (step 21) is the
   real enforcement.
7. Quest build settings:
   - IL2CPP + ARM64 and Vulkan.
   - OpenXR with the Meta Quest feature group (not the legacy Oculus
     plugin).
   - Internet Access = Require.
   - Meta App ID set in the Platform settings.
8. **Offline fallback:** if sign-in or the session fails, the room still
   loads read-only (single user), with a clear in-world offline state. No
   crash and no placeholder primitives (Hard Rule 7).
9. **Editor/mock:** in the Editor, a mock identity replaces the Meta
   calls, and the backend runs in `mock` auth mode.

## Verify on device (record in Build Plan step 25)

- Frame rate and latency with 2+ headsets (no official numbers exist).
- Avatar and hand sync: study the template's `XRI Network Player Avatar`.
- DA and Vivox quotas and pricing for this Unity Cloud project.

## Definition of done

`--done 22` passes. Two test users on two headsets join the same room; a
grab on one moves the object on the other; the session survives the first
client leaving; an unlinked headset shows a link code.

## Sources

- https://docs.unity3d.com/Packages/com.unity.template.vr-multiplayer@2.1/manual/index.html
- https://docs.unity.com/en-us/mps-sdk/session-host-migration
- https://docs.unity.com/en-us/mps-sdk/create-session
- https://docs.unity3d.com/Packages/com.unity.netcode.gameobjects@2.11/manual/components/core/networkobject-ownership.html
- https://docs.unity3d.com/Packages/com.unity.services.authentication@3.2/api/Unity.Services.Authentication.IAuthenticationService.SignInWithOculusAsync.html
- https://developers.meta.com/horizon/documentation/unity/ps-ownership/
