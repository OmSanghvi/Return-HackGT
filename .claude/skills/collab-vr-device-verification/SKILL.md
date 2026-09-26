---
name: collab-vr-device-verification
description: Use for Build Plan step 25 — end-to-end verification on real hardware of the whole Collaborative VR + web accounts track: website sign-up, uploads and sketches, Quest linking, two-headset live editing, persistence, performance, failure drills, Meta test-user/Data Use Checkup status, and quotas. Results go in docs/BUILD_PLAN.md and are confirmed by the user.
---

# End-to-end verification (step 25)

## Gate

`python3 scripts/check_collab_gates.py 25` (needs 20, 23, and 29). BLOCKED means stop.

## Checklist (dev environment, real Quest headsets, Meta test users)

Record every result, with numbers, under Build Plan step 25.

1. **Website:** A signs up with Clerk, creates a project, and invites B. B
   joins through the invite link. Both upload a photo with memory text,
   one uploads a Notability sketch (flat card), and one sets a room prompt.
2. **Linking:** each headset shows a code, and each person links it on the
   Link Quest page. A wrong code shows an error, and the 6th attempt gets
   429.
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
   - B can't grab A's object.
   - A forged `/edits` call with B's room token for A's object returns
     403. Test with curl; never paste tokens into chat or files.
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
   - Meta validation outage → a clean "can't sign in" message, no crash.
   - Unlinked headset → shows a code.
10. **Accounts and quotas:**
    - Meta **Data Use Checkup** status. Until it's approved, only test
      users can sign in; note this for anyone demoing.
    - DA and Vivox usage limits checked in the Unity dashboard.
11. **Secrets:** `python3 scripts/check_collab_gates.py --status` passes on
    the final commit and on the built web bundle (`app/dist`: grep it for
    `sk_` and `SECRET`).

Report the results. Only the user sets `two_headset_verified`.

## Definition of done

`python3 scripts/check_collab_gates.py --done 25` passes.
