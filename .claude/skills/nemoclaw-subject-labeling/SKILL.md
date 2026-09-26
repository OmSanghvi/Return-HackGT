---
name: nemoclaw-subject-labeling
description: Use when implementing or changing NemoClaw's identify_subject tool — automatic labeling of the object in a contributor's uploaded photo so it can be passed to SAM 3.1 as subject_hint — for SketchScape / Shared Room, Build Plan step 4a in docs/BUILD_PLAN.md. Mock path has no dependency; the live path depends on step 3 (nemoclaw-agent-setup).
---

# NemoClaw subject labeling (Build Plan step 4a)

Contributors upload a photo without typing a prompt. NemoClaw decides which
object is the subject and hands SAM 3.1 a short noun phrase.

## Rules

- **User-typed `subject_hint` always wins.** Only label when it is empty.
- **One subject per upload** (the most prominent). Keep internal output a
  list so a capped "all objects" mode is a flag later, not a rewrite.
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
- **Live path runs inside NemoClaw** on its Llama vision runtime — never a
  standalone model API call from `main.py`. Tests mock it; no live call
  without explicit user approval (Hard Rule 3).

## Definition of done

See step 4a in `docs/BUILD_PLAN.md`. Run `bash scripts/verify_local.sh`.
