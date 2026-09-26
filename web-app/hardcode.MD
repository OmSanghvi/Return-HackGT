# Hardcoded features (demo build)

What the web app fakes on purpose so the demo can't break, what is still real, and what's left to hardcode.
Rule from `features.txt`: fake the plumbing, never lie about it. If a judge asks, "mock mode" is the answer.

Status: **done** = already hardcoded in `src/`, **todo** = should be hardcoded, not yet.

## 0. Real mode (Build Plan steps 19-20)

Everything below this section (1-9) describes **mock mode**: the live demo at
returnweb-hazel.vercel.app, unchanged, used whenever `VITE_SKETCHSCAPE_API_URL`
is unset at build time. Setting it switches the whole site into **real mode**
instead -- see `src/config.ts`, which is the single switch (`REAL_MODE`) that
`App.tsx` branches on before any mock code runs.

- **done** Account picker (`src/real/RealShell.tsx`) replaces the fake
  sign-in: a header control between the two hardcoded accounts
  (`VITE_SKETCHSCAPE_ACCOUNTS`, defaulting to `demo-alice,demo-bob` to match
  the backend's `SKETCHSCAPE_DEMO_USERS` default). Every API call sends
  `X-SketchScape-Dev-User: <chosen account>` (`src/api/client.ts`).
- **done** Typed API client (`src/api/client.ts`, `src/api/types.ts`): every
  project/contributor/upload/selection/generate/jobs call the backend
  actually exposes, JSON error mapping (401/403/409/413/415), and
  `XMLHttpRequest`-based upload progress.
- **done** Real project create/join (`src/real/RealProjectsPage.tsx`), photo
  upload with per-object typed names (text-only SAM 3.1 prompts, no
  click/drag selection -- matches the backend's semantic-only segmentation),
  refine/delete a selection, "Make 3D" generate, and a shared batch
  job-polling loop with ETag/If-None-Match and the documented backoff
  (2s/5s/10s + jitter, paused while the tab is hidden, `Retry-After`
  honored) -- `src/real/RealProjectPage.tsx`, `src/api/polling.ts`.
- **done** Generated objects and a Notability flat-card sketch upload are
  shown once ready (`src/real/RealProjectPage.tsx`'s asset gallery).
- **todo** Notability sketches: only the flat-card path is wired (PNG/JPEG
  upload straight to `/sketch-assets`); no PDF-page-to-PNG conversion in the
  browser yet, and no 3D memory-plaque option from the web UI.
- **todo** Letters (step 28) -- not built here on purpose, per
  `web-uploads-and-linking`.
- **known gap (not fixed here, see AGENT.md Hard Rule 9 / task notes):** the
  backend's CORS middleware hard-codes `allow_methods=["GET", "POST"]` in
  every auth mode (`backend/main.py`, where `app.add_middleware(CORSMiddleware,
  ...)` is configured) -- it never varies with `SKETCHSCAPE_AUTH_MODE`. A
  browser preflight for `PATCH /v1/projects/{id}` (room prompt) or
  `DELETE .../selections/{id}` (remove a chip) gets back
  `Access-Control-Allow-Methods: GET, POST` and blocks the real request, when
  the web app and backend are on different origins (exactly the local-dev
  setup: Vite on :5173, backend on :8000). Confirmed with
  `curl -X OPTIONS .../v1/projects/x -H "Access-Control-Request-Method: PATCH"`
  -> `400 Disallowed CORS method`. It does **not** affect the production path
  through `vercel.json`'s `/api/*` rewrite (same-origin from the browser's
  perspective, so no preflight is sent at all), and it was left alone here
  because another agent is editing `backend/main.py` -- the fix is adding
  `"PATCH"` and `"DELETE"` to that `allow_methods` list.
- Local dev: run the backend with `SKETCHSCAPE_AUTH_MODE=demo`,
  `SKETCHSCAPE_WEB_ORIGINS=http://localhost:5173`, `PIPELINE_MODE=mock`, then
  `VITE_SKETCHSCAPE_API_URL=http://localhost:8000 npm run dev` (or put that
  line in `web-app/.env.development`, which is git-ignored). See the repo's
  top-level report for exact commands.

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
