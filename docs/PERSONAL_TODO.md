# What you personally need to do right now

Last updated: 2026-09-26 (after Build Plan step 16).

This is **only** the human/dashboard/hardware work. Coding steps agents can
run without you are listed at the bottom so you can ignore them.

---

## Do next (blocks the Collaborative VR track)

### 1. Step 13 — account dashboards

Unity Cloud is already linked. The rest is on you (Hard Rule 3: accounts
need your approval / hands).

| # | Task | When done, tell an agent so they can flip |
| --- | --- | --- |
| 1a | **Clerk (dev):** create the app; note the **publishable** key (`pk_…`); put the **secret** key only in backend env (never the repo or chat); make sure `http://localhost:5173` works as a allowed origin; confirm you can create an M2M machine for NemoClaw | gate `clerk_app_ready` |
| 1b | **Meta Horizon:** create the developer app for the Quest build; note **App ID**; put **App Secret** only in backend env + Unity Dashboard; **add every tester as a test user** (required until Data Use Checkup is approved) | gate `meta_app_ready` |
| 1c | **Unity Dashboard → Authentication → ID Providers → Meta Quest (Oculus):** enter that Meta App ID + App Secret | gate `unity_meta_provider_configured` |

Optional but time-sensitive: if anyone outside the team will use Meta user
verification, **submit Meta's Data Use Checkup early**. Until Meta
approves it, only test users work.

Check progress anytime:

```bash
python3 scripts/check_collab_gates.py --done 13
```

### 2. Step 14 — Quest Meta identity spike (real headset)

Only after step 13 gates are confirmed. On a **real Quest** signed in as a
**test user**, you (or someone with the headset) must prove:

1. Entitlement check passes
2. `GetLoggedInUser` returns an ID
3. Two `GetUserProof` nonces obtained
4. `SignInWithOculusAsync` succeeds with one nonce
5. The other nonce validates with `is_valid: true` at
   `graph.oculus.com/user_nonce_validate` (you run this from a shell with
   the App Secret in an env var — never paste the secret into chat)

Then tell an agent so they can set gate `quest_meta_identity_spike_passed`.

Fill results into `docs/BUILD_PLAN.md` step 14 when you have them:
sign-in OK / nonce `is_valid` / test users set up.

---

## Soon, but not blocking coding today

| Task | Why | Notes |
| --- | --- | --- |
| Approve GPU / AWS spend when asked | Hard Rule 3 — agents must not start EC2 or paid runs alone | Step 27 and any re-smoke of the GPU path |
| Set cloud env vars on the EC2 API process | Live DynamoDB/S3 path on the instance | Optional for mock judging; ~5 min; `infra/aws/SMOKE_TEST_GUIDE.md` Step 5 |
| Record demo video + write-up | Judging | Prefer local mock + precomputed assets (`docs/PROJECT_STATUS.md`) |
| Keep secrets out of the repo | Gate script fails `verify_local.sh` on leaks | Clerk `sk_…`, Meta `OC\|…`, any `VITE_*SECRET*` |

Secrets that will eventually live **only** in backend secret storage (not
files, not chat):

- `CLERK_SECRET_KEY`
- `SKETCHSCAPE_META_APP_SECRET`
- `SKETCHSCAPE_ROOM_TOKEN_SECRET` (≥32 random bytes, when step 18 lands)
- Model API keys for NemoClaw (`META_MODEL_API_KEY` / `XAI_API_KEY` / …)

Public values that are fine to share with an agent: Clerk publishable key,
Meta App ID, web origin URLs.

---

## Already done (you can ignore)

- Step 15 — backend revision safety
- Step 16 — backend auth core (Clerk web + M2M, mock mode)
- Step 17 — membership, invites, ownership, `room_prompt`
- Steps 1–2 — contributor data model + API
- Unity Cloud project linked
- Scope for Collaborative VR track approved

---

## Agents can do without you (for now)

These do **not** need your dashboard work first:

| Step | What | Needs |
| --- | --- | --- |
| 26 | Durable jobs, shared uploads, multi-object upload API | 15 (ready) |
| 7 | Notability flat card + memory plaque | — |

Blocked until **you** finish 13 (and for some, 14):

| Step | Waiting on you |
| --- | --- |
| 14 | Step 13 dashboards + a real Quest |
| 18 | Steps 14 + 16 |
| 19 | Steps 13 + 16 (Clerk app for the web shell) |
| 22 | Steps 13 + 14 |
| 25 | Real two-headset + web verification |

Full gate status: `python3 scripts/check_collab_gates.py --status`
