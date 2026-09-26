---
name: backend-revision-concurrency
description: Use for Build Plan step 15 — making blueprint revisions and publication safe under concurrent writers (multiple API instances, multiple headsets, NemoClaw). Adds based_on_revision + 409 on stale writes, conditional DynamoDB writes, and a compare-and-set LIVE pointer for the published revision. Prerequisite for the public room API (step 21) and NemoClaw room tools (step 24).
---

# Backend revision safety (step 15)

## Gate

```bash
python3 scripts/check_collab_gates.py 15
```
If BLOCKED, stop (see `collab-vr-accounts-and-gates`). Done when
`--done 15` and `bash scripts/verify_local.sh` both pass.

## The bugs this step fixes (read in the current code)

1. `create_blueprint` computes `revision = len(revisions) + 1` and accepts any
   blueprint. A writer building on an old revision silently erases newer
   edits.
2. `DynamoDbStore.append_blueprint` and `append_publication` use
   unconditional `put_item`, and `self._lock` only covers one process. Two
   API instances can write the same sort key; the later one overwrites.
3. `ProjectRecord` is stored as one JSON blob and saved whole
   (`save_project`), so `published_revision` inside it is last-write-wins
   and can't be used in a DynamoDB condition. Two racing publishes can move
   the live room **backwards**.
4. A draft that NemoClaw proposed (not yet approved) can be the latest
   revision. Anything that builds on "latest" instead of "published" would
   publish that draft by accident.

## Design

- **Every new revision records what it was built on.** Add to
  `ExperienceBlueprint`: `based_on_revision: int | None = None` and
  `author: str | None = None` (step 16 fills `author`).
- **`POST /v1/projects/{id}/blueprints?base_revision=N`** (optional query
  param, so current callers keep working): if given, it must equal the
  currently **published** revision (0 = nothing published yet), else
  **409** with `{"detail": ..., "published_revision": current}`. The new
  revision stores `based_on_revision=N`. New callers (room API, NemoClaw
  room tools) must always send it.
- **Publish compare-and-set.** `publish_blueprint` publishes revision R only
  if `R.based_on_revision` equals the current published revision. Otherwise
  409 "stale draft, rebase on revision X". Revisions with
  `based_on_revision=None` (legacy/manual authoring) keep today's behavior,
  including deliberate rollback to an older revision.
- **LIVE pointer as the source of which revision is live.**
  - Store method: `set_live_revision(project_id, expected: int | None, new: int) -> bool`
    and `get_live_revision(project_id) -> int | None`.
  - DynamoDB: item `pk=PROJECT#<id>`, `sk=LIVE`, numeric attribute
    `revision`. Update with `put_item(..., ConditionExpression="attribute_not_exists(pk) OR #r = :expected")`
    (use `attribute_not_exists(pk)` only when `expected is None`). Return
    False on `ConditionalCheckFailedException`.
  - LocalJsonStore: same check under `self._lock`, persisted in the JSON
    state (bump `STATE_VERSION` handling if the file format changes; keep
    loading old files).
  - Readers (`compiled-scene`, and step 21's room state) use
    `get_live_revision`. `ProjectRecord.published_revision` stays as a
    cached copy for existing clients but is not trusted for decisions.
- **Conditional appends.**
  - `append_blueprint`: DynamoDB `ConditionExpression="attribute_not_exists(sk)"`;
    LocalJsonStore checks `revision == len(list)+1` under the lock. Both
    raise a `RevisionConflict` exception. `create_blueprint` retries with
    the next number (max 5 tries), then 409.
  - `append_publication`: same conditional put on the next sequence number,
    retry on conflict (publications are append-only, so retrying with the
    next number is always correct).
- Don't write the whole `ProjectRecord` from the room/publish hot path; that
  blob is last-write-wins across instances.

## Tests (backend/test_api.py, backend/test_storage.py)

- Create with `base_revision` equal to published → 201; stale → 409 with
  `published_revision` in the body.
- Two drafts both based on revision 1: publishing the first succeeds, the
  second gets 409.
- Legacy draft (no `base_revision`) still publishes, and rollback to an
  older legacy revision still works.
- LocalJsonStore: `set_live_revision` with a wrong `expected` returns False.
- DynamoDB path: if tests use moto (check how existing DynamoDB tests run),
  assert a duplicate `append_blueprint` raises `RevisionConflict`. If there
  is no moto setup, unit-test the condition logic with a stubbed table and
  say so in the PR.
- Existing tests must keep passing (mock path unchanged, Hard Rule 2).

## Definition of done

`python3 scripts/check_collab_gates.py --done 15` and
`bash scripts/verify_local.sh` pass. Update the test count in AGENT.md
(Hard Rule 8, the "fully built" table, and "How to validate") and in
`docs/PROJECT_STATUS.md`.
