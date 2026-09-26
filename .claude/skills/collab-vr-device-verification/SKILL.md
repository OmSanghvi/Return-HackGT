---
name: collab-vr-device-verification
description: Use for Build Plan step 25 — end-to-end verification on real hardware of the whole Collaborative VR + web accounts track: website account picker, uploads and sketches, two-headset account-switcher live editing, persistence, performance, failure drills, and Unity Cloud quotas. No Clerk sign-up or Quest linking (decision 2026-09-26, see collab-vr-accounts-and-gates). Results go in docs/BUILD_PLAN.md and are confirmed by the user.
---

# End-to-end verification (step 25)

## Gate

`python3 scripts/check_collab_gates.py 25` (needs 20, 23, and 29). BLOCKED means stop.

## Checklist (dev environment, real Quest headsets)

Record every result, with numbers, under Build Plan step 25.

1. **Website:** as `demo-alice` (account picker), creates a project, and
   invites `demo-bob`. `demo-bob` joins through the invite link, picking
   their account. Both upload a photo with memory text, one uploads a
   Notability sketch (flat card), and one sets a room prompt.
2. **Account switcher on the headsets:** each headset's account switcher
   lists both `SKETCHSCAPE_DEMO_USERS`; picking one signs the headset's
   Multiplayer Services session in anonymously and tags it with that
   account, no linking step.
3. **Live room:** both headsets (add a third if available, to prove N > 2)
   join the same room, each moves their own object, and everyone sees every
   edit live.
3a. **Multi-object upload:** one photo with 3 objects → pick 2 → 2 objects
    reconstruct (with GPU approval) and appear in the room. Two people
    uploading at once both succeed. The web app shows one progress view,
    and polling slows down or stops as expected (check the network tab).
3b. **Letters:** A writes a letter to B. C sees a sealed envelope and
    can't open it. B opens it, and A and C see the flap open and the page
    unfold live. After a reload it's still open. The handwriting is
    legible at reading distance, and the frame rate holds with the page
    open.
4. **Ownership:**
   - `demo-bob` can't grab `demo-alice`'s object.
   - A forged `/edits` call using `demo-bob`'s account header for
     `demo-alice`'s object returns 403. Test with curl.
5. **Persistence:** both leave; a new session shows the final positions.
6. **Session survival:** the first headset leaves mid-session; the other
   keeps editing.
7. **NemoClaw (if step 24 is done):** a proposal is approved on the website
   and appears in the running room.
8. **Performance:** frame rate holds the Quest target (72 Hz baseline)
   with the full room and 2+ people. Note the object count and any drops.
9. **Failure drills:**
   - Wi-Fi off during a save → one revision.
   - Backend down → the live room still works and saves retry.
   - Backend rejects a bad/missing account header → a clean "choose an
     account" message on the headset, no crash.
10. **Accounts and quotas:**
    - DA and Vivox usage limits checked in the Unity dashboard.
11. **Secrets:** `python3 scripts/check_collab_gates.py --status` passes on
    the final commit and on the built web bundle (`app/dist`: grep it for
    `sk_` and `SECRET`).

Report the results. Only the user sets `two_headset_verified`.

## Definition of done

`python3 scripts/check_collab_gates.py --done 25` passes.
