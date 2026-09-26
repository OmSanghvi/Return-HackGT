---
name: web-uploads-and-linking
description: Use for Build Plan step 20 — the web app's content and account screens. Photo upload with reconstruction progress, Notability sketch upload (flat card or 3D memory plaque), optional user text (object label / subject hint, memory text, room prompt), and project invites and contributor joining under the two hardcoded accounts (no Clerk, no Link Quest page — decision 2026-09-26, see collab-vr-accounts-and-gates).
---

# Web uploads, sketches, and optional text (step 20)

## Gate

`python3 scripts/check_collab_gates.py 20` (needs 7, 17, 19, 26). BLOCKED
means stop. The sketch backend (step 7) must really exist; don't build UI
against endpoints that aren't there.

## Joining a project (uses step 17)

- Creating a project makes the creator its first contributor (bound to
  the account chosen in the picker — `collab-vr-accounts-and-gates`).
- The project page shows an **invite link** containing the project's
  `invite_code`. Opening it, with an account chosen, calls the contributor
  registration route with the code. Without a valid code → 403. The display
  name defaults to the account id and can be edited.

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
  2. **Name each object** they want in 3D, next to the returned
     `image_url` preview (the server's EXIF-corrected image): a text field
     per object, e.g. "blue vase" — a SAM 3.1 semantic text prompt that
     finds that kind of object and lets them pick which instance if there
     are several. **Decision (user, 2026-09-26): typed name only** — no
     click-to-select and no drag-a-box; this matches the semantic-only
     segmentation the backend actually runs.

     Each selection gets a chip in a side list. There they can edit the
     name (also the label), add optional **memory text** ("why this
     matters", ≤1000 chars with a counter), or delete it. The chip list
     shows the per-photo cap (default 8, from the server).
  3. **Mask it:** "Find these objects" → `POST .../selections` with all
     chips at once (one SAM 3.1 job per photo). As masks arrive, each
     object is shown outlined in its chip's color with its score.
  4. **Fix or confirm:**
     - A wrong mask can be fixed by typing a more specific or different
       name (`POST .../selections/{selection_id}/refine`, which re-masks
       only that object), or by switching to another found instance.
     - Failed selections show the reason ("nothing found matching that
       name; try being more specific").
  5. **Generate 3D:** "Make 3D" with the checked objects →
     `POST .../uploads/{upload_id}/generate`. One PLY job runs per
     object, and the server creates each contribution with its memory
     text.
  6. **Optional "Suggest objects"** button (auto-detect): NemoClaw proposes
     selections as dashed chips that the person keeps or removes. Nothing
     is generated without a person's choice.

  Accessibility: the name field and chip list are ordinary form controls —
  no canvas, no pointer-only interaction to replicate.
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

## Text safety and limits (all screens)

- Enforce the backend's limits client-side; the backend stays the
  authority.
- Render all user and AI text as plain text.
- **Cost decision (user, 2026-09-25): no per-user upload limits.** Every
  cloud upload can start a GPU job, so this app doesn't throttle. The
  owner watches cost.

## Tests

Vitest + Testing Library:
- The selection form:
  - a name chip sends `{text}`
  - the cap disables adding chips
  - a refine sends only that selection, with its new text
  - "Make 3D" is disabled until at least one object is masked
- File type and size rejection; HEIC handling.
- The PDF → PNG path, with a small fixture PDF.
- Optional fields are omitted when empty.
- The invite flow sends the code.

## Definition of done

`--done 20` and `verify_local.sh` pass. In mock mode:
1. Create a project, invite a second (mock) user, and both upload a photo
   with memory text; each reaches ready.
2. Upload a sketch as a flat card.
3. Save a room prompt.
4. Link a (mock) Quest with a code.
