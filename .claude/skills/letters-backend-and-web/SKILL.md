---
name: letters-backend-and-web
description: Use for Build Plan step 28 — Notability letters. A contributor uploads a letter page (image, or a PDF page rendered to PNG in the browser), addresses it to one or more contributors, optionally adds typed note text, and the backend stores it as a letter asset that Unity renders as a textured 3D paper page inside an envelope. Covers the letter data model, the sealed/opened state, recipient-only opening via the room API, access control on the page image, the scene schema extension, and the web form.
---

# Letters: backend, room API, and web form (step 28)

## Gate

`python3 scripts/check_collab_gates.py 28` (needs 17, 19, 21, 26). BLOCKED
means stop. See `docs/DATA_ARCHITECTURE.md` for the items and S3 keys.

## Decisions (user, 2026-09-25)

- A letter becomes a **textured 3D paper mesh** built in Unity from the
  uploaded page at full resolution. Handwriting stays legible, and there's
  no GPU job. It is **not** a SAM3D reconstruction. (Build Plan step 7's
  SAM3D "memory plaque" remains optional for non-letter pages.)
- The letter arrives **inside an envelope**, and only its **addressed
  recipients** can open it. Everyone in the room sees it open live, and the
  opened state is saved.

## Data

- `ProjectAsset.kind = "letter"`.
- `LETTER#<letter_id>` item under the project:
  - `author_contributor_id`
  - `recipient_contributor_ids` (1..N, each a contributor of this project;
    may include several people; the author can't be the only recipient)
  - `page_key`, `texture_key`, `aspect_ratio`
  - `note_text` (optional, ≤2000 chars)
  - `envelope_style` (enum, default `classic`)
- Opened state: `LETTEROPEN#<letter_id>#<contributor_id>` items, written
  with a conditional put (a repeat open is a no-op). A letter is "open" once
  any recipient has opened it.
- A `Contribution` with `source_type="letter"` links the letter to its
  author, so attribution works like any other object.

## Routes

1. `POST /v1/projects/{id}/letters` (Clerk session, contributor), multipart:
   - `page` (JPEG/PNG/WebP ≤16 MB)
   - `recipient_contributor_ids` (repeated)
   - `note_text?`, `envelope_style?`, `memory_text?`

   Server:
   - Validate the recipients.
   - Store `page.png` and generate `texture-2048.png` (Pillow; 2048 px on
     the long edge, keeping the aspect ratio).
   - Create the asset (`status=ready` immediately, no GPU), the letter, and
     the contribution.

   Returns 201.
2. `GET /v1/projects/{id}/letters` returns the letter list with a `sealed`
   or `opened` status. Page URLs are included only where the caller may see
   them (below).
3. `POST /v1/rooms/{id}/letters/{letter_id}/open` (**room token only**):
   - The caller's contributor id must be a recipient, else 403.
   - Conditional put of `LETTEROPEN`.
   - Returns 200 `{opened: true, opened_by, opened_at}`. Idempotent.
4. `GET /v1/rooms/{id}/state` (step 21) gains
   `letters: [{letter_id, object_id, recipients, opened, texture_url?}]`.
   The `since_revision` 304 check also covers letter states, so a new open
   shows up in the session owner's poll.
5. **Access to the page image:**
   - Sealed: only the author and the recipients get a presigned URL.
   - Opened: every member gets one, because everyone watched it open.
   - Non-recipients never receive the URL of a sealed letter, so the
     content can't leak before it's opened.

## Scene and blueprint

- Blueprint objects reference the letter asset like any asset.
  NemoClaw's `place_objects_in_scene` treats `kind=letter` as a small prop
  (on a table or surface near the author's other objects, envelope facing
  the room). It still accepts lists, never pairs.
- `shared/scene.schema.json`: add `"letter"` to the `source` enum and an
  optional `letter` object `{letter_id, recipient_contributor_ids, aspect_ratio, envelope_style}`.
  Unity genuinely needs these runtime fields, which is the bar AGENT.md
  sets for changing this schema.
  - The texture URL is **not** in the compiled scene, because it depends on
    who's asking. Unity gets it from room state.
  - Update `compile_blueprint` and its tests.

## Web form (in `app/`)

- "Write a letter" on the project page:
  - Upload the page. Notability PDF exports are rendered to PNG in the
    browser (pdf.js, with a page picker); images upload as they are; HEIC
    is converted or rejected.
  - Choose recipients (multi-select of the other contributors, at least
    one).
  - Optional typed note and envelope style.
  - Preview the page before sending.
- The letters list shows sealed or opened per letter. The author sees
  their own letter's content; others see "Sealed letter for <names>".

## Tests

- Recipient validation:
  - a recipient who isn't a contributor → 422
  - the author as the only recipient → 422
- Open:
  - a non-recipient → 403
  - a recipient → 200
  - a second open → still 200, and no duplicate item is written
- A sealed page URL is hidden from non-recipients and shown after opening.
- Room state includes letters, and the 304 flips after an open.
- The scene schema validates a letter object, and `compile_blueprint`
  emits it.
- Web (Vitest):
  - the recipient picker requires at least one
  - the PDF → PNG render with a fixture
  - error states

## Definition of done

`--done 28` and `verify_local.sh` pass. In mock mode:
1. A writes a letter to B and C.
2. B opens it through the room route.
3. The state shows it opened.
4. D (not a recipient) couldn't see the page before the open and can after.
