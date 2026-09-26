# Next steps

The short version. The full, ordered plan with a skill per step is
`docs/BUILD_PLAN.md`; status is in `docs/PROJECT_STATUS.md`.

## Already done

- Job-based FastAPI API: upload, polling, artifact serving, scene JSON, safe
  scene edits, projects and multi-view assets, versioned blueprints and
  publication.
- Mock mode that works fully offline with no GPU or credentials.
- Local JSON, DynamoDB, and S3 backends (the cloud ones live-verified).
- The GPU pipeline, verified end-to-end on an L40S: 70 s per object.
- `identify_subject` mock labeler for uploads with no typed subject.

## MVP next (Build Plan steps 1–12)

1. **Steps 1–2:** `Contributor` / `Contribution` / `ConnectionInsight`
   models and endpoints, as lists of any length.
2. **Step 5:** `connection/compose`, mock path first. This is the most
   important missing piece.
3. **Step 8:** attribution in Unity without UI text panels.
4. **Step 11:** remove the offline builder's placeholder primitives and
   render a real PLY.
5. **Step 12:** record the demo in mock mode.

Steps 3–4 and 6 (NemoClaw runtime, layout tools, immersive staging) make
the story strong. Steps 7, 9, and 10 are optional polish. If time runs
short, follow the "If time runs out" order at the end of the Build Plan.

## Collaborative VR + web accounts (steps 13–29)

Post-MVP and gated; never take time from steps 1–12 for it. Step 15
(revision safety) can start now, and step 13 needs account setup from you.
The suggested order is at the end of `docs/KNOWN_ISSUES.md`.

## Rules that stay in force

- Never start EC2, run a GPU job, `terraform apply`, or install NemoClaw
  without explicit approval.
- Failed objects are left out of the room, never replaced with
  placeholders.
- Mock output is always labelled `mock` and never presented as a model
  result.
