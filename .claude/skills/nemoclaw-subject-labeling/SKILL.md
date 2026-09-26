---
name: nemoclaw-subject-labeling
description: Use when implementing or changing NemoClaw's identify_subject tool — automatic labeling of the object in a contributor's uploaded photo so it can be passed to SAM 3.1 as subject_hint — for SketchScape / Shared Room, Build Plan step 4a in docs/BUILD_PLAN.md. Mock path has no dependency; the live path depends on step 3 (nemoclaw-agent-setup).
---

# NemoClaw subject labeling (Build Plan step 4a)

Contributors upload a photo without typing a prompt. NemoClaw decides which
object is the subject and hands SAM 3.1 a short noun phrase.

## Rules

- **User-typed `subject_hint` always wins.** Only label when it is empty.
- **Several subjects per upload** (updated 2026-09-25). Return a list of
  noun-phrase labels, most prominent first, capped by
  `SKETCHSCAPE_MAX_OBJECTS_PER_UPLOAD` (default 8). They become SAM 3.1
  multi-concept prompts, and the person picks which found objects to
  reconstruct (Build Plan steps 26–27). The single-object legacy path uses
  the first label.
- **Labels are SAM 3.1 concept prompts:** a noun plus one or two
  distinguishing attributes ("wicker armchair", "blue ceramic mug"). Never a
  relational sentence ("the chair left of the table") — SAM 3.1 does not
  parse those reliably.
- **Keep `mask_review`.** If SAM 3.1 can't find a clear match, the job goes
  to review with NemoClaw's label visible for correction. Do not add any
  fallback that guesses a generic prompt (see the comment in
  `worker/worker_server.py`).
- **Record provenance:** `subject_hint_source` is `"user"` or `"nemoclaw"`,
  and the label's `backend` is `"mock"` or the NemoClaw runtime name.
- **Mock is default** (`SKETCHSCAPE_SUBJECT_LABELER=mock`): deterministic,
  offline, labelled `mock`. Never break it (AGENT.md Hard Rule 2).
- **Live path runs inside NemoClaw** on the configured vision model (`NEMOCLAW_VISION_MODEL`; Muse Spark on the default `meta` provider, see `nemoclaw-model-providers`) — never a
  standalone model API call from `main.py`. Tests mock it; no live call
  without explicit user approval (Hard Rule 3).

## Definition of done

See step 4a in `docs/BUILD_PLAN.md`. Run `bash scripts/verify_local.sh`.
