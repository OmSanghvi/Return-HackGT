---
name: web-uploads-and-linking
description: Use for Build Plan step 20 — the web app's content and account screens. Photo upload with reconstruction progress, Notability sketch upload (flat card or 3D memory plaque), optional user text (object label / subject hint, memory text, room prompt), project invites and contributor joining, and the Link Quest page that links a headset's Meta account to the Clerk user.
---

# Web uploads, sketches, optional text, and Quest linking (step 20)

## Gate

`python3 scripts/check_collab_gates.py 20` (needs 7, 17, 18, 19, 26). BLOCKED
means stop. The sketch backend (step 7) and Meta linking (step 18) must
really exist; don't build UI against endpoints that aren't there.

## Joining a project (uses step 17)

- Creating a project makes the creator its first contributor (bound to
  their Clerk user).
- The project page shows an **invite link** containing the project's
  `invite_code`. A signed-in person opening it calls the contributor
  registration route with the code. Without a valid code → 403. The display
  name defaults to the Clerk user's name and can be edited.

## Photo upload

- Accept JPEG, PNG, and WebP only (the backend allowlist), max 16 MB.
  - iPhone **HEIC**: convert in the browser before upload, or reject with
    "Export as JPEG". Don't send HEIC.
  - Downscale very large images client-side (for example to 4096 px on the
    long edge) to stay under the limit.
- **Several objects per photo, several photos at once. The person
  chooses the objects** (step 26 API):
  1. **Upload:** drop one or more photos. Each goes to
     `POST /v1/projects/{id}/uploads` in parallel with its own progress bar
     (XHR upload progress). No GPU work starts yet.
  2. **Select objects on a canvas** drawn over the returned `image_url`
     (the server's EXIF-corrected image, so clicks line up). For each
     object the person wants in 3D, they use one of three tools:
     - **Click** on the object (an include point). Shift-click or the
       "exclude" tool marks parts that aren't the object, for example a
       table under a vase.
     - **Drag a box** around the object.
     - **Type its name** ("blue vase"), which finds that kind of object
       and lets them pick which instance if there are several.

     Each selection gets a colored chip in a side list. There they can
     rename it (the label), add optional **memory text** ("why this
     matters", ≤1000 chars with a counter), or delete it. The chip list
     shows the per-photo cap (default 8, from the server). Coordinates are
     sent normalized 0–1, so screen size doesn't matter.
  3. **Mask it:** "Find these objects" → `POST .../selections` with all
     chips at once (one SAM 3.1 job per photo). As masks arrive, each
     object is shown outlined in its chip's color with its score.
  4. **Fix or confirm:**
     - A wrong mask can be fixed with more include/exclude clicks or a new
       box (`POST .../selections/{selection_id}/refine`, which re-masks
       only that object). For a typed name, the person can switch to
       another found instance.
     - Failed selections show the reason ("nothing found at that point;
       try a box").
  5. **Generate 3D:** "Make 3D" with the checked objects →
     `POST .../uploads/{upload_id}/generate`. One PLY job runs per
     object, and the server creates each contribution with its memory
     text.
  6. **Optional "Suggest objects"** button (auto-detect): NemoClaw proposes
     selections as dashed chips that the person keeps or removes. Nothing
     is generated without a person's choice.

  Accessibility: every canvas action also has a keyboard or list
  equivalent (select a chip, nudge its box with arrow keys, type a name).
  The canvas works with touch (tap = include point, long-press = exclude).
- **One polling loop for everything** (`docs/DATA_ARCHITECTURE.md`,
  polling contract):
  - `GET /v1/projects/{id}/jobs?active=1` with `If-None-Match`.
  - 2 s for the first 20 s, then 5 s, then 10 s after 2 min; ±20% jitter.
  - Pause while `document.hidden`; honor `Retry-After`.
  - Stop when no jobs are active.
  - Never one polling loop per object.
  - Show a status per object: selected / masking / masked / needs a fix /
    generating 3D / ready / failed.
  - On "needs a fix", keep the photo open in the canvas so the person can
    refine that one object.
- Uploads start right away with no per-user limit (user decision). The
  per-photo object cap comes from the server (default 8).
- More angles of the same object: the existing add-view route (see
  `docs/INTEGRATION_GUIDE.md`); same file rules.

## Notability sketches (uses step 7)

- **Export format:** Notability exports are commonly PDF. Check the
  current Notability export options before building.
  - If users export PDF, render the chosen page to PNG in the browser
    (pdf.js) and upload the PNG. The backend accepts images only.
  - An image export uploads as is.
- The person picks one:
  - **Flat card** (default, no GPU): the step 7 flat-quad sketch asset
    route.
  - **3D memory plaque**: the page goes through reconstruction like a
    photo (GPU). Warn that handwriting may not stay legible (step 7
    verifies this). Offer flat card as the fallback.
- The optional memory text works the same as for photos.

## Letters

The "Write a letter" form (recipients, page upload, optional note) belongs
to step 28 (`letters-backend-and-web`). Don't build it here.

## Optional room prompt

- A project-level **"Describe the room you want"** field (optional, max
  300 chars), saved on the project (step 17 adds `room_prompt` to the
  project, editable by contributors).
- `connection/compose` (step 5) reads it as a hint. It's **untrusted
  data**: NemoClaw must treat it as a description, never as instructions.
  Every resulting layout still passes schema and bounds validation. If
  step 9's Llama Guard exists, it screens this text too.
- If step 5 isn't built yet, the field is still saved and shown; the
  button that composes the room stays hidden.

## Link Quest page (uses step 18)

- Shows the status from `GET /v1/auth/meta/link`: linked / not linked.
- Code entry: 8 characters, case-insensitive, spaces ignored →
  `POST /v1/auth/meta/link`. Show clear errors for expired, used, or
  too-many-attempts (429, retry after 10 min).
- Unlink button → `DELETE /v1/auth/meta/link`, with a confirmation.
- Instructions: "Open SketchScape on your Quest, it shows a code, enter it
  here." The headset polls the code's status without a nonce (step 18), so
  it moves on by itself within about 5 s of linking.

## Text safety and limits (all screens)

- Enforce the backend's limits client-side; the backend stays the
  authority.
- Render all user and AI text as plain text.
- **Cost decision (user, 2026-09-25): no per-user upload limits.** Every
  cloud upload can start a GPU job, so this app doesn't throttle. The
  owner watches cost.

## Tests

Vitest + Testing Library:
- The selection canvas:
  - point, box, and text chips send normalized coordinates, verified
    against a known image size
  - shift-click sends label 0
  - the cap disables adding chips
  - a refine sends only that selection
  - "Make 3D" is disabled until at least one object is masked
- File type and size rejection; HEIC handling.
- The PDF → PNG path, with a small fixture PDF.
- Optional fields are omitted when empty.
- Link-code input normalization and error states.
- The invite flow sends the code.

## Definition of done

`--done 20` and `verify_local.sh` pass. In mock mode:
1. Create a project, invite a second (mock) user, and both upload a photo
   with memory text; each reaches ready.
2. Upload a sketch as a flat card.
3. Save a room prompt.
4. Link a (mock) Quest with a code.
