---
name: letters-vr-envelope
description: Use for Build Plan step 29 — the letter experience in the Quest room. A sealed envelope prop, recipient-only opening, a networked open animation everyone sees (flap opens, page slides out and unfolds), a textured 3D paper page that stays legible at reading distance, haptics and paper sound, late-joiner and persisted state, and Quest texture and performance limits.
---

# Letters in VR: envelope and 3D page (step 29)

## Gate

`python3 scripts/check_collab_gates.py 29` (needs 22 and 28). BLOCKED means
stop.

## Assets

- **Envelope model:** model it in Blender. A body plus a flap with a hinge
  bone (or a flap blendshape), and a paper insert slot. Aim for ≤2k
  triangles. Export FBX or glTF into `HackGTUnity`.
  - If you use a downloaded model instead, it must be CC0/CC-BY with the
    license and attribution recorded (the project's clear-rights rule).
  - One material with a paper texture; envelope styles swap tint and seal
    decals.
- **Paper page:** a procedural mesh in Unity, not a model file:
  - A subdivided quad sized to the letter's `aspect_ratio` (for example
    0.21 m wide, height from the aspect), about 24×32 segments, so it can
    bend.
  - Two horizontal fold lines (tri-fold). Unfold by rotating vertex rows
    around the fold lines (a small script or a vertex shader driven by one
    `unfold` 0→1 parameter).
  - The texture is the letter's `texture_url` from room state, loaded at
    runtime (`UnityWebRequestTexture`) with mipmaps and anisotropic
    filtering, so handwriting stays readable.
  - A thin back face with a plain paper color.

## Interaction and networking

- **States:** `Sealed → Opening → Open`, held in a `NetworkVariable` on the
  letter's `NetworkObject`, plus `openedAt` (network time) so every client
  plays the same animation in sync.
- **Sealed:**
  - The envelope rests where the blueprint placed it.
  - A diegetic label on the envelope (printed on the paper, not a floating
    UI panel) says who it's for, from recipient display names.
  - A recipient sees a soft glow on the seal.
- **Opening (recipient only):**
  1. The recipient grabs the envelope (`Network Grab Interactable`) and
     pulls the flap, or pinches the seal with hand tracking.
  2. The client checks `editable`/recipient status from room state, then
     calls `POST /v1/rooms/{id}/letters/{letter_id}/open` with the room
     token.
  3. **Only on 200** does it request the state change `Sealed → Opening`
     through the object's authority (in DA, the recipient takes ownership
     for the animation).
  4. Everyone plays the animation. At the end, the state is `Open`.
- A non-recipient who tries to open it gets gentle feedback (a small
  shake, a paper-rustle sound, and haptic), and nothing is sent to the
  backend.
- **Animation**, about 2.5 s total, using the tween library chosen in Build
  Plan step 6 (PrimeTween or TweenPlayables). Don't add a third library.
  1. Flap hinge 0° → 170° over 0.6 s (ease out).
  2. The page slides out of the envelope over 0.8 s.
  3. The page unfolds over 1.0 s.
  4. The page settles facing the recipient, about 0.45–0.6 m from the eyes
     and slightly below eye level, then can be grabbed and read freely.

  Add paper sound (spatial, with Resonance Audio if step 6 adopts it) and a
  light haptic impulse on each step (XRI `SendHapticImpulse`).
- **Late joiners and new sessions:** a letter already opened (from room
  state) spawns directly in `Open`, with the page out and unfolded, and
  doesn't animate.
- **Persistence:** the backend `LETTEROPEN` item is the truth. The network
  variable is only for live display. If the backend call fails, the
  envelope stays sealed and shows "try again".

## Quest limits

- The texture is 2048 px on the long edge (from step 28): about 16 MB of
  GPU memory each when uncompressed. Load the page texture **only when the
  letter is opened, or when the viewer is the author or a recipient**, and
  unload it for far-away letters if the room holds many.
- Keep the frame rate at the target with the letter open. Record the
  numbers in step 25.
- The offline experience builder (step 11) must handle `source: "letter"`.
  In offline mode, sealed letters show as sealed envelopes with no network
  calls.

## Tests

- EditMode tests: the unfold math (vertex positions at 0, 0.5, 1) and the
  state machine (a non-recipient can't move it out of Sealed; late join
  goes straight to Open).
- Manual checks with the XR Device Simulator and then on a headset: the
  recipient opens it, a second headset sees the animation in sync, a
  non-recipient is refused, and handwriting is readable at reading
  distance.
- **Single-headset account-switcher check:** with only one headset, use
  the account switcher (`collab-vr-accounts-and-gates`) — as
  `demo-alice`, send a letter to `demo-bob`; switch to `demo-bob` and
  confirm the sealed envelope shows and opens for him; switch back to
  `demo-alice` and confirm she still sees it as sent/opened. These are the
  same room-state/open calls either account makes
  (`room-api-and-ownership`), just switching which account's header is
  sent.

## Definition of done

`--done 29` passes, and it's verified on two headsets in step 25:
- the recipient opens the letter
- the other person sees it open live
- a reload shows it opened
- the handwriting is legible
- the frame rate holds
