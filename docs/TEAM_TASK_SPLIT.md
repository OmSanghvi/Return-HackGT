# Team task split — 4 parallel tracks

This maps `docs/BUILD_PLAN.md`'s MVP steps (1–12, plus 4a and 6a) onto 4 people so each can work
without stepping on the others' files, then merge in a short, predictable
integration pass at the end. `BUILD_PLAN.md` is still the source of truth
for *how* to do each step (skill name, files, concrete steps, definition of
done) — this file is only the *who* and *in what order*, chosen to minimize
file collisions and blocked time.

The Collaborative VR + web accounts track (Build Plan steps 13–29) is
post-MVP and not assigned here. Whoever picks it up runs
`python3 scripts/check_collab_gates.py <step>` first (AGENT.md Hard Rule 9).

Load `meta-track-alignment` (the standing skill) regardless of track — it's
the judgment-call gate for all of them. Each track below names the
step-specific skill(s) to load in addition.

**Before anyone starts:** agree on the `Contributor`/`Contribution`/
`ConnectionInsight` field names and the NemoClaw tool signatures
(`place_objects_in_scene`, `read_sketch_layout`) as a 15-minute whiteboard
pass. Every other track calls these by name; nailing the shape once up
front is what makes the rest of this split actually parallel instead of
sequential-in-disguise.

---

## Track 1 — Social data layer & API (Build Plan steps 1, 2)

**Owns:** `backend/main.py` (new `Contributor`/`Contribution`/
`ConnectionInsight` models, near `ProjectAsset`), `backend/storage.py`
(`AuthoringStore` extensions, both `LocalJsonStore` and `DynamoDbStore`),
`backend/test_storage.py`.

**Skills:** `contributor-data-model`, `contributor-api-endpoints`.

**Why this is the first thing to land:** Tracks 3 and (partly) 2 build
against these models by name. This track should open its PR early and
small — models + storage first, endpoints second — so the field names are
locked before anyone else needs them.

**Definition of done:** `POST /v1/projects/{id}/contributors`,
`POST /v1/projects/{id}/contributions` work end to end against
`SKETCHSCAPE_STORAGE_BACKEND=local`; N-ary from day one (list of
contributions, never a fixed pair); `bash scripts/verify_local.sh` passes.

---

## Track 2 — NemoClaw agent & scene tools (Build Plan steps 3, 4, 4a live path)

**Owns:** NemoClaw agent registration (outside this repo) + Meta's Unity MCP
Extension setup, `config/nemoclaw/sketchscape-tools.json`,
`backend/subject_labeler.py` (mock path already built — this track adds the
live path only).

**Skills:** `nemoclaw-agent-setup`, `nemoclaw-model-providers`,
`nemoclaw-scene-tools`, `nemoclaw-subject-labeling`.

**Independent of Track 1's files** — this is agent runtime + tool
registration, not backend model code. It only needs the *signature* of
`Contributor`/`Contribution` (from the whiteboard pass) to design
`place_objects_in_scene`'s input shape, not the merged code.

**Definition of done:** NemoClaw is a live agent that can call
`place_objects_in_scene`/`read_sketch_layout` against Meta's Unity MCP
Extension; `identify_subject`'s live path runs inside NemoClaw on the
configured vision model (`NEMOCLAW_VISION_MODEL`; Muse Spark on the default
`meta` provider, see `nemoclaw-model-providers`) with the mock path still
the default (`SKETCHSCAPE_SUBJECT_LABELER=mock`).

---

## Track 3 — Compose, immersive staging & Unity attribution (Build Plan steps 5, 6, 8, 9)

**Owns:** `backend/main.py`'s `connection/compose` endpoint (a new section,
appended — do not edit Track 1's model definitions), the Unity project's
immersive-staging and `SceneInteractionController` work, a sidecar
social-manifest schema if Unity needs one.

**Skills:** `connection-compose-endpoint`, `immersive-reveal-staging`,
`unity-diegetic-attribution`, `meta-hardware-polish`.

**This is the integration-heavy track** — steps 5 and 6 formally depend on
Tracks 1 and 2. In practice: start scaffolding `connection/compose` against
the whiteboarded model/tool shapes and a hand-written mock response
immediately; swap in real calls to Track 1's store and Track 2's NemoClaw
tools once those PRs land. Steps 8 and 9 can't produce a real attributed
scene until 5 and 6 work, but the `SceneInteractionController` bounded-edit
registry and the hardware-polish building blocks (Passthrough, hand
tracking) can be built and tested against a hand-built fixture scene in
parallel, then pointed at the real compiled scene at integration time.

**Definition of done:** a mock `connection/compose` call produces a staged,
attributed two-contributor room in Unity with a bounded edit per
contributor; matches AGENT.md's "the connection must be felt, not read"
rule (no floating UI text panel).

---

## Track 4 — Independent infra & isolated features (Build Plan steps 7, 10, 11, 6a)

**Owns:** the new Notability sketch endpoint(s) (flat-card + SAM3D
memory-plaque paths — entirely new code, doesn't touch anything Track 1 or
3 own), `infra/aws/` (GPU verification, cloud backend activation), the
Unity offline experience builder (placeholder-primitive fallback removal,
real-PLY splat rendering), and — once Track 2's step 4 and this track's own
step 10 are both done — `find_object_image` environment sourcing.

**Skills:** `sketch-image-gen-backends`, `gpu-cloud-activation`,
`unity-offline-builder-and-rendering`, `nemoclaw-environment-sourcing`.

**Genuinely independent** — `docs/BUILD_PLAN.md` already calls these three
steps out as having no dependency on the social layer. This track can start
immediately and merge whenever ready; it touches no file any other track
touches. **`gpu-cloud-activation` involves real AWS spend and GPU instance
lifecycle** — every irreversible action there needs explicit sign-off from
the person actually holding the AWS account, not just "the team."

**Definition of done:** a Notability sketch shows up in the room as a flat
card or SAM3D plaque; the GPU worker is verified end-to-end and cloud
backends (DynamoDB/S3) are activated on the EC2 API (the GPU pipeline itself
is already verified on an L40S); Unity renders a real Fast-SAM3D `.ply`
splat with no placeholder-primitive fallback.

---

## Where files actually overlap (and how to avoid conflicts)

The only shared file is `backend/main.py`, touched by Track 1 (new models +
two new endpoints near `ProjectAsset`) and Track 3 (one new endpoint,
`connection/compose`, added later in the file). Both additions are
append-only — new classes/routes, not edits to existing code — so:

- Track 1 merges first, in a small PR (models + storage before endpoints).
- Track 3 rebases onto Track 1's merge before opening its own PR, and adds
  its endpoint in its own clearly-separated section rather than interleaving
  with Track 1's code.
- Nobody edits another track's models/endpoints directly — if a shape needs
  to change, that's a message to the owning track, not a drive-by edit.

Every other file (`storage.py`, `subject_labeler.py`,
`sketchscape-tools.json`, `infra/aws/*`, the Unity offline builder, the new
sketch endpoints) has exactly one owning track.

---

## Integration phase (after all 4 land) — Build Plan step 12

Once Tracks 1–4 are merged:

1. Run `bash scripts/verify_local.sh` on the merged `main` — must pass
   before anything else.
2. Swap Track 3's mock `connection/compose` inputs for Track 1's real store
   and Track 2's real NemoClaw tool calls; confirm the live path still
   produces a sensible, attributed room.
3. Point the Unity offline builder (Track 4) at a real compiled scene from
   the merged backend and confirm Track 3's attribution/bounded-edit work
   renders correctly against real geometry, not the fixture scene.
4. Whoever is recording records the demo (`demo-video-prep` skill) —
   `PIPELINE_MODE=mock` end to end is the judging-safe path; the live GPU
   and cloud paths (Track 4) are confirmed working separately, not depended
   on at recording time.
