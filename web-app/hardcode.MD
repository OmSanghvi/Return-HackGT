# Hardcoded features (demo build)

What the web app fakes on purpose so the demo can't break, what is still real, and what's left to hardcode.
Rule from `features.txt`: fake the plumbing, never lie about it. If a judge asks, "mock mode" is the answer.

Status: **done** = already hardcoded in `src/`, **todo** = should be hardcoded, not yet.

## 1. Landing page
- **done** All copy, imagery and the VR chapter are static. No live stats, no counters.
- **done** Theme is always dusk. No clock, no toggle, no day mode.

## 2. Login
- **done** Local sign-in only (`src/auth.tsx`, `src/screens/SignIn.tsx`): email and password are prefilled, any input signs in.
- **done** The current user is always `ME` (`Dylan Houle`, `dylan@return.world`, `src/data/store.ts`).

## 3. Dashboard
- **done** Four seeded rooms, one per card state (`seed()` in `store.ts`):
  - `The lake house`: ready (3 people, Lake Norman, July 14, 2019)
  - `Grandma's porch`: collecting, you're done, waiting on Sam
  - `Last day of summer`: building at 35%
  - `Ava's graduation`: invite from Ava Lin, you haven't joined
- **done** Rooms live in `localStorage` (`return-demo-v1`), no backend.
- **done** Rename, leave, remove, manage people are local-only.
- **done** `/?reset` restores the seeded rooms and signs out.

## 4. Create room + invite
- **done** Invite search runs over a fixed people list (`KNOWN_PEOPLE`: Mom, Sam Park, Samira Ali, Ava Lin, Jordan Reyes). No real user lookup.
- **done** Invites are never emailed. "Sent 2 minutes ago" and Resend only update a timestamp.
- **done** Room backdrop scene is picked round-robin, not from the photos.
- **done** Field lives on the Add photos screen once at least one photo is in, owner only, parsed locally, stored, not sent anywhere.

## 5. Upload photos + note
- **real** File picking, preview, remove, the note field and validation. Judges will click these.
- **done** Photos are downscaled to data URLs and kept in the browser. No upload to S3 or the API.
- **done** Fake 900 ms "Adding" beat before moving on, so it feels like an upload.
- **done** Max 12 photos, note max 1000 chars.

## 6. Waiting for others
- **done** Nobody arrives on a timer; `.` brings the next person in and animates their row; "Start without X" (owner only) jumps to building.
- **done** Their photo counts (3 to 7) and notes are canned (`NOTES` in `store.ts`: the dock, the screen door, the fireflies).
- **done** "We'll email you when it's ready" is copy only. No email.

## 7. Building
- **done** Progress is a 7 s animation that runs while the page is open, not a reconstruction job; the fog clears as it fills; keep the optional pipeline-names todo.

## 8. Ready
- **done** Portal shows the room's cover photo or its painted scene with a depth map. It is not the real splat.
- **done** Headset steps are two ("Open return on your Quest", "Sign in with this same account").
- **done** "Built from N photos by M people" is summed from member counts.
- **todo** Map the seeded `lake-house` room (and any room created during the demo) to one precomputed, known-good scene in Unity, so the room you open on the Quest is always the same beautiful one. `NEXT_STEPS.md` step 2.
- **todo** Hardcode one AI connection theme per seeded room for the headset (e.g. lake house: "the place everyone came back to"). It lives in the VR scene as lighting, motif and narration, never as a text card on the web or in VR (`features.txt` feature 2).

## 9. Numbers and claims to hardcode in copy / narration
- 70 s total on an NVIDIA L40S (42 s segment + 28 s reconstruct), 814k vertices, 53 MB splat. Real, verified numbers: fine to cite.
- Pipeline name: SAM 3.1 -> Fast-SAM3D -> Gaussian splat -> UnitySplats -> Quest.
- Model powering NemoClaw in the recording: "mock". Don't imply a live model ran.

## Do NOT hardcode
- The upload form's validation and error messages.
- Anything that shows a placeholder cube in VR for a failed reconstruction. Skip the object instead.
- A claim that the build or AI ran live when it was mock.
