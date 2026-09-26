---
name: unity-cloud-collaborative-vr
description: Use for Build Plan step 22 — adding live networking to HackGTUnity so one person's grab/move/rotate/scale shows on every other Quest in real time. Anonymous Unity sign-in plus an in-headset account switcher between the two hardcoded accounts (decision 2026-09-26 — no Meta account sign-in, no room token; see collab-vr-accounts-and-gates), Unity Multiplayer Services sessions with Distributed Authority, Netcode for GameObjects 2.x, XR Interaction Toolkit, and Unity's VR Multiplayer Template 2.1.
---

# Collaborative VR networking in HackGTUnity (step 22)

Verified against Unity docs, Sept 2026. Meta-specific sign-in was verified
2026-09-25 but is no longer part of this plan (see Decisions below).

## Gate

`python3 scripts/check_collab_gates.py 22`. BLOCKED means stop. The only
prerequisite is a linked Unity Cloud project (checked automatically by
this step) — no Clerk or Meta account setup is needed any more (decision
2026-09-26, `docs/KNOWN_ISSUES.md` R13).

## Starting point (checked)

- `HackGTUnity`: Unity **6000.2.10f1**, XRI 3.0.11, XR Management 4.5.1,
  OpenXR 1.15.1.
- Linked to a Unity Cloud project.
- **No Netcode and no Multiplayer Services yet.**

## Decisions

- **Sign-in: anonymous.** `AuthenticationService.Instance.SignInAnonymouslyAsync()`
  after `UnityServices.InitializeAsync()`. Distributed Authority and NGO
  2.x don't care which identity provider signed the player in — they need
  *a* signed-in UGS player, and anonymous sign-in provides one with no
  Meta account, no nonce, and no backend exchange. (Superseded: the
  earlier plan required Meta Platform SDK `GetUserProof()` +
  `SignInWithOculusAsync` + a backend room token; see
  `meta-quest-identity`, kept for reference only.)
- **Account switcher, not per-person login.** Right after sign-in, show an
  in-headset panel listing the accounts from `SKETCHSCAPE_DEMO_USERS`
  (read from a public config ScriptableObject — never hard-code
  "Account 1"/"Account 2" as specific ids). Picking one sets:
  - a UGS **player property** with the chosen account id (so Netcode
    clients map to contributors), and
  - the `X-SketchScape-Dev-User` header on every backend HTTP call for
    the rest of the session (room state, edits, artifact fetches).
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
2. Sign in anonymously to UGS, then show the account switcher. On a
   choice, set the player property and the HTTP header (above).
3. One live session per Shared Room:
   ```csharp
   // Any number of people: size the session from the project, never a hard-coded 2.
   var options = new SessionOptions { MaxPlayers = project.MaxContributors }.WithDistributedAuthorityNetwork();
   var session = await MultiplayerService.Instance.CreateOrJoinSessionAsync($"room-{projectId}", options);
   ```
   Check the SDK reference for your installed version's session id limits.
4. Build the room from `GET /v1/rooms/{project_id}/state` (step 21), with
   the `X-SketchScape-Dev-User` header. Each object becomes a networked
   object with an owner-authoritative transform and
   `Network Grab Interactable`. Fetch artifacts with the same header.
5. **Ownership guard:** set objects to `OwnershipStatus.RequestRequired`.
   In `OnOwnershipRequested`, allow only when `editable_by_me` for the
   requester. This is a client-side UX guard; the backend (step 21) is the
   real enforcement.
6. Quest build settings:
   - IL2CPP + ARM64 and Vulkan.
   - OpenXR with the Meta Quest feature group (not the legacy Oculus
     plugin) — this is about the headset hardware, not accounts.
   - Internet Access = Require.
7. **Offline fallback:** if the session fails to form, the room still
   loads read-only (single user), with a clear in-world offline state. No
   crash and no placeholder primitives (Hard Rule 7). (Anonymous sign-in
   itself still needs network access to reach UGS, so a fully offline
   editor/dev path goes through the mock identity in point 8 instead.)
8. **Editor/mock:** in the Editor, a mock identity replaces the sign-in
   and switcher, and the backend runs in `mock` auth mode.

## Verify on device (record in Build Plan step 25)

- Frame rate and latency with 2+ headsets (no official numbers exist).
- Avatar and hand sync: study the template's `XRI Network Player Avatar`.
- DA and Vivox quotas and pricing for this Unity Cloud project.

## Definition of done

`--done 22` passes, and the user confirms `account_switcher_verified`
(`config/collab-vr/gates.json`) on a real headset: the switcher lists both
`SKETCHSCAPE_DEMO_USERS`, joining under each shows only that account's
`editable_by_me` objects as grabbable, and a grab on one client moves the
object on the other.

## Sources

- https://docs.unity3d.com/Packages/com.unity.template.vr-multiplayer@2.1/manual/index.html
- https://docs.unity.com/en-us/mps-sdk/session-host-migration
- https://docs.unity.com/en-us/mps-sdk/create-session
- https://docs.unity3d.com/Packages/com.unity.netcode.gameobjects@2.11/manual/components/core/networkobject-ownership.html
- Unity Authentication's `SignInAnonymouslyAsync` is documented on the
  `Unity.Services.Authentication.IAuthenticationService` API reference
  (same package as the old `SignInWithOculusAsync` link below, different
  method) — verify the exact URL for your installed package version
  rather than trusting a pasted link here.
- https://docs.unity3d.com/Packages/com.unity.services.authentication@3.2/api/Unity.Services.Authentication.IAuthenticationService.SignInWithOculusAsync.html
  (superseded — kept only because it's the same API reference page family
  as the anonymous method above)
