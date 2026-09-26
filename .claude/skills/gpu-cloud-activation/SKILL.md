---
name: gpu-cloud-activation
description: Use when running the GPU end-to-end verification (SAM 3.1 + Fast-SAM3D on EC2) and activating DynamoDB/S3 cloud backends for SketchScape — Build Plan step 10 in docs/BUILD_PLAN.md, AGENT.md items 2-3. Involves real AWS spend and GPU instance lifecycle — every irreversible action here requires explicit user approval first.
---

# GPU + cloud activation (Build Plan step 10)

This step has no dependency on the social-layer work (steps 1–9) and can run
in parallel. It also costs real money and touches live AWS infrastructure —
treat every step below as requiring explicit user approval before executing,
per `AGENT.md`'s hard rules and `.agents/skills/sketchscape-infrastructure/SKILL.md`.

## Do not skip the safety boundary

- Never run `terraform apply`, start the EC2 instance, run a GPU job, or set
  live cloud env vars on the running API process without the user explicitly
  approving that specific action first.
- Read `infra/aws/SMOKE_TEST_GUIDE.md` fully before starting — it is the
  authoritative, already-written runbook. This skill only tells you when to
  reach for it, not how to replace it.
- Stop the EC2 instance immediately after any bounded smoke test, even a
  successful one.

## Current status

The GPU half is already done: SAM 3.1 → Fast-SAM3D was verified end-to-end
on an NVIDIA L40S (g6e.xlarge, us-east-2) — 70 s total, a 53 MB PLY (see
`docs/PROJECT_STATUS.md`). Unless something changed on the instance, start
at concrete step 2. Re-run step 1 only with explicit approval.

## Concrete steps

1. **GPU end-to-end verification** (`AGENT.md` item 2): start the stopped EC2
   instance → confirm SSM access and `nvidia-smi` → publish the bootstrap
   bundle → bootstrap with an explicitly user-supplied `HF_TOKEN` (unset
   immediately after) → run the SAM 3.1 smoke test → run the Fast-SAM3D
   smoke test → confirm the full API callback path works → **stop the
   instance**. Follow `infra/aws/SMOKE_TEST_GUIDE.md` step by step; don't
   improvise a shorter path.
2. **Cloud backend activation** (`AGENT.md` item 3): once verification
   passes, set `SKETCHSCAPE_STORAGE_BACKEND=dynamodb`,
   `SKETCHSCAPE_DYNAMODB_TABLE`, `SKETCHSCAPE_ARTIFACTS_BACKEND=s3`,
   `SKETCHSCAPE_ARTIFACTS_BUCKET` on the running API process — this is Step
   5 of `infra/aws/SMOKE_TEST_GUIDE.md`. This does not require a new
   Terraform apply if the table/bucket already exist (per `AGENT.md`'s
   "What is fully built" table, they're already provisioned and
   live-verified).
3. If step 1 (Contributor/Contribution storage) has landed by the time this
   runs, verify the new `CONTRIBUTOR#`/`CONTRIBUTION#`/`INSIGHT#` sort-key
   families round-trip against the *real* DynamoDB table, not just
   `moto`/local tests — this is the one thing local `verify_local.sh` cannot
   confirm.

## Definition of done

Matches `infra/aws/SMOKE_TEST_GUIDE.md`'s own success criteria exactly. The
instance is stopped when this step ends, regardless of outcome.
